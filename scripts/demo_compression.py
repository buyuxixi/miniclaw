"""Offline teaching fixture: real Hermes compressor, explicitly stubbed summary LLM."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ['HERMES_HOME'] = str(ROOT / '.hermes')
sys.path.insert(0, str(ROOT / 'hermes-agent'))
from agent.context_compressor import ContextCompressor, is_compaction_summary_message
from agent.model_metadata import estimate_messages_tokens_rough

messages = [{'role': 'user', 'content': '教学任务：整理虚构保温杯资料，缺少证据的内容不能编造。'}]
for index in range(24):
    messages.extend([
        {'role': 'assistant', 'content': f'第{index + 1}轮资料整理。' + '容量400ml，米白色，面向通勤；保温性能缺少实测数据。' * 40},
        {'role': 'user', 'content': f'第{index + 1}轮检查：保留缺少保温实测证据的约束。'},
    ])
messages.append({'role': 'assistant', 'content': '已确认约束；下一步准备验证清单。'})
with patch('agent.context_compressor.get_model_context_length', return_value=1_000_000):
    compressor = ContextCompressor(model='offline-teaching-fixture', quiet_mode=True,
                                   protect_first_n=2, protect_last_n=4)
    compressor.tail_token_budget = 500
    _ = compressor.context_length
before_tokens = estimate_messages_tokens_rough(messages)
with patch.object(compressor, '_generate_summary', return_value=(
    '教学固定摘要（非模型生成）：目标是整理虚构保温杯资料。已知容量400ml、米白色、通勤场景。'
    '不得编造保温时长；缺少实测证据。未完成任务：准备验证清单。')) as summary:
    after = compressor.compress(messages, current_tokens=before_tokens, force=True)
report = {
    'kind': 'offline_fixture_real_compressor_stubbed_summary',
    'model_called': False, 'database_changed': False, 'summary_quality_verified': False,
    'context_window': compressor.context_length,
    'fixture_overrides': {'protect_first_n': 2, 'protect_last_n': 4, 'tail_token_budget': 500},
    'before_messages': len(messages), 'after_messages': len(after),
    'before_estimated_tokens': before_tokens, 'after_estimated_tokens': estimate_messages_tokens_rough(after),
    'summary_stub_calls': summary.call_count,
    'before': messages, 'after': after,
}
assert summary.call_count > 0 and len(after) < len(messages)
assert any(is_compaction_summary_message(message) for message in after)
out = ROOT / '.codex/verification/compression-demo.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k not in ('before', 'after')}, ensure_ascii=False))
print(f'Saved: {out}')
