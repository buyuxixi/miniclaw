"""Known integration repair: finite host checks consume user commands on abstention."""
import argparse
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'hermes-agent')]
import scripts.run_laya_round5_replacement as experiment
from scripts.evaluate_native_fastpath import NativePolicy

class DelegatingNativePolicy(experiment.OperationalNativePolicy):
    def guard(self,task,name,args):
        if name=='miniclaw_edit_image':
            # Existing host guard requires literal affirmative rotate/flip grammar,
            # exact parameters, actual selected ID, and resolved user answers.
            # Classifier abstention cannot veto that already explicit permission.
            return NativePolicy.guard(self,task,name,args)
        return super().guard(task,name,args)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args()
    with patch.object(experiment,'OperationalNativePolicy',DelegatingNativePolicy):experiment.run_native(a.out.resolve())
