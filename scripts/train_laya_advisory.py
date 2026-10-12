"""Bounded local supervised experiment with the installed, pinned Laya trainer."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_TF='0',
                  HF_HOME='D:/model/laya-runtime/cache/huggingface')

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--train', action='store_true')
    p.add_argument('--epochs', type=int, default=3)
    p.add_argument('--base', type=Path, default=Path('D:/model/laya-multilingual'))
    p.add_argument('--encoder-lr', type=float, default=2.5e-5)
    p.add_argument('--head-lr', type=float, default=1e-4)
    p.add_argument('--label-smoothing', type=float, default=0.)
    p.add_argument('--contract', choices=('business-eight','formal-seven'), default='business-eight')
    args = p.parse_args()
    import torch
    import laya.train as training
    base = args.base.resolve()
    if not base.is_relative_to(Path('D:/model').resolve()) or not 1<=args.epochs<=8:
        raise ValueError('Base must be local; epochs must be 1..8')
    if not 0<args.encoder_lr<=1e-3 or not 0<args.head_lr<=1e-3:
        raise ValueError('Learning rate exceeds bounded experiment range')
    manifest = json.loads((args.data / 'manifest.json').read_text(encoding='utf-8'))
    for split in ('train', 'dev', 'calibration', 'test'):
        if sha(args.data / (split + '.jsonl')) != manifest['outputs'][split]['sha256']:
            raise ValueError('Dataset changed since audit')
    config = training.TrainConfig(epochs=args.epochs, micro_batch=2, grad_accum=4,
                                  encoder_lr=args.encoder_lr, head_lr=args.head_lr, min_lr=1e-6,
                                  weight_decay=.01, grad_clip=1., loss='soft-ce',
                                  freeze_encoder=False, amp=False, gradient_checkpointing=True,
                                  shuffle_options=('choice',), max_len=1024, head_max_len=384,
                                  calib_max=0, calib_frac=0, eval_data=str(args.data / 'dev.jsonl'),
                                  seed=20261011, log_every=100,label_smoothing=args.label_smoothing)
    config.validate()
    stats = training.dry_run(str(args.data / 'train.jsonl'), str(base), config)
    if any(stats['skipped'].values()) or any(stats.get('eval_skipped', {}).values()):
        raise ValueError('Dry run skipped data')
    report = dict(status='dry_run', config=asdict(config), data=stats,
                  dataset_manifest=manifest, versions={n: importlib.metadata.version(n) for n in ('laya', 'torch', 'transformers')},
                  source_sha256=sha(Path(__file__)), production_service_changed=False,
                  supervised_groups=['intent','target','reference_role','scope','conflict','answer_relation','fact_review'] if args.contract=='formal-seven' else ['intent', 'clarification', 'six independent binary business categories'],
                  hyperparameter_reason='Initial round uses installed Laya LR defaults. Continued training uses smaller LR and optional smoothing to reduce overfitting after observing dev failures. FP32 avoids prior mixed-precision instability; small batches/checkpointing bound 16GB VRAM. Fixed epochs are a bounded experiment, not an optimized choice.',
                  calibration='No item-level automatic split; separate family-level calibration file used by evaluator.')
    write(args.data / 'dry-run.json', report)
    if not args.train:
        print(json.dumps({'status':'dry_run_passed', 'items':stats}, ensure_ascii=False))
        return
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is required')
    output = args.out.resolve()
    if (not output.is_relative_to(Path('D:/model').resolve()) or output == Path('D:/model').resolve()
            or output == base.resolve() or output.is_relative_to(base.resolve()) or output.exists()):
        raise ValueError('Output must be a new checkpoint under D:/model')
    output.mkdir(parents=True)
    report.update(status='running', base=str(base), base_sha256=sha(base / 'model.safetensors'),
                  gpu=torch.cuda.get_device_name(0))
    write(output / 'run-summary.json', report)
    original = training.calibration_records
    def serial_records(*a, **kw):
        kw['batch_size'] = 1
        return original(*a, **kw)
    training.calibration_records = serial_records
    from torch.optim.optimizer import register_optimizer_step_post_hook
    updates = [0]
    def count(*unused): updates[0] += 1
    hook = register_optimizer_step_post_hook(count)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    try:
        result = training.finetune(str(args.data / 'train.jsonl'), str(base), str(output), config, device='cuda')
        report['result'] = result
        report['actual_updates'] = updates[0]
        if updates[0] != stats['optimizer_updates']:
            raise RuntimeError('Incomplete optimizer update budget')
        # Reuse the earlier numeric tensor audit, not serialized-byte changes alone.
        source = Path('D:/model/laya-runtime/finetune/run_training.py')
        spec = importlib.util.spec_from_file_location('pilot_parameter_audit', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report['parameter_audit'] = module.parameter_changes(str(base / 'model.safetensors'), str(output / 'model.safetensors'))
        report['output_sha256'] = sha(output / 'model.safetensors')
        report['base_unchanged'] = sha(base / 'model.safetensors') == report['base_sha256']
        if not report['base_unchanged']:
            raise RuntimeError('Base checkpoint changed')
        report['status'] = 'completed'
    except BaseException as error:
        report.update(status='failed', error=dict(type=type(error).__name__, message=str(error)))
        raise
    finally:
        hook.remove()
        training.calibration_records = original
        report.update(elapsed_seconds=round(time.perf_counter()-start, 2),
                      cuda_peak_allocated_mib=round(torch.cuda.max_memory_allocated()/1048576, 1),
                      cuda_peak_reserved_mib=round(torch.cuda.max_memory_reserved()/1048576, 1))
        write(output / 'run-summary.json', report)
    print(json.dumps({k:report[k] for k in ('status', 'actual_updates', 'elapsed_seconds', 'cuda_peak_allocated_mib')}, ensure_ascii=False))

if __name__ == '__main__': main()
