"""Actual HTTP repair diagnostic; original failed run is retained unchanged."""
import argparse
import shutil
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import scripts.run_laya_round5_replacement as experiment
from scripts.run_laya_round5_delegated import DelegatingNativePolicy

def run(out):
    isolated=out/'http-native-repair-input'
    if isolated.exists():raise ValueError('repair_run_exists_no_replay')
    (isolated/'round05').mkdir(parents=True)
    for name in ('summary.json','consumption-gates.json','scores.jsonl'):
        shutil.copyfile(out/'round05'/name,isolated/'round05'/name)
    for name in ('native-cases.json','requests.json','jev.jsonl'):shutil.copyfile(out/name,isolated/name)
    with patch.object(experiment,'OperationalNativePolicy',DelegatingNativePolicy):experiment.run_native(isolated,http=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);run(p.parse_args().out.resolve())
