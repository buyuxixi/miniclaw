import copy
import json
import tempfile
import unittest
from pathlib import Path
from miniclaw_web.canvas import Canvas
from miniclaw_web.store import Store
from miniclaw_web.studio import Studio
from miniclaw_web.studio_video import StudioVideo
from miniclaw_web.generation_audit import entry,project_ledger,usage_fields
from tests.test_canvas import Held
from tests.test_studio_projects_video import PLAN

class GenerationAuditTests(unittest.TestCase):
    def test_unknown_models_and_submission_do_not_become_zero_cost_or_current_model(self):
        for job in ({'id':'old','state':'succeeded'}, {'id':'uncertain','state':'unknown','model':'qwen-image-edit-max'}):
            row=entry(job,'image');self.assertIsNone(row['estimate_cny']);self.assertIsNone(row['actual_cny'])
        self.assertIsNone(entry({'id':'old','state':'succeeded'},'image')['model'])
        self.assertEqual(usage_fields({'image_count':1,'key':'secret','total_tokens':-1,'output_tokens':True}),{'image_count':1})

    def test_new_model_prices_and_resolution_are_used_without_inventing_missing_data(self):
        self.assertEqual(entry({'id':'qwen','state':'succeeded','model':'qwen-image-2.0-pro'},'image')['estimate_cny'],.5)
        self.assertEqual(entry({'id':'mini','state':'succeeded','model':'image-01','provider':'minimax'},'image')['estimate_cny'],.025)
        h3={'id':'h3','state':'succeeded','model':'MiniMax-H3','provider':'minimax','generation_duration':5,'duration':5,'resolution':'768P'}
        self.assertEqual(entry(h3,'video')['estimate_cny'],2.5)
        self.assertEqual(entry({**h3,'mode':'reference','reference_count':7},'video')['estimate_cny'],2.9)
        self.assertIsNone(entry({**h3,'resolution':None},'video')['estimate_cny'])
        self.assertIsNone(entry({**h3,'state':'unknown'},'video')['estimate_cny'])
        self.assertEqual(entry({**h3,'model':'MiniMax-H3-Max','mode':'reference','reference_count':4},'video')['estimate_cny'],3.5)

    def test_ledger_deduplicates_link_aliases_and_counts_unadopted_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);canvas=Canvas(store,executor=Held());studio=Studio(store,canvas,Path(__file__).resolve().parents[1]);studio.message_reader=lambda *_:PLAN
            record=studio.create_project({'request_id':'audit-fixture','name':'Audit','session_id':'live','message':1,'facts':''},'owner')
            workspace=record['id'];state=copy.deepcopy(record['state']);state['assets']=[{'id':'product','name':'首帧素材','file':'source.png'}]
            studio.workspaces.save(workspace,{'request_id':'save-audit','revision':1,'state':state})
            studio._video=StudioVideo(studio,studio.root,executor=Held())
            image_project=canvas.create()['id']
            with store.connect() as db:
                for obj in ('product',state['shots'][0]['id']):
                    db.execute('INSERT INTO video_precision_links VALUES (?,?,?)',(workspace,obj,json.dumps({'project':image_project})))
                for identifier,model in [('image-one','qwen-image-edit-max'),('legacy',None)]:
                    db.execute('INSERT INTO canvas_jobs VALUES (?,?,?)',(identifier,image_project,json.dumps({'id':identifier,'state':'succeeded','model':model,'created':1})))
                db.execute('INSERT INTO studio_video_jobs VALUES (?,?,?)',('video-one',workspace,json.dumps({'id':'video-one','workspace':workspace,'shot':'removed-shot','basis':'old','name':'未采用候选','state':'succeeded','model':'wan2.2-i2v-flash','duration':5,'created_at':2})))
            ledger=project_ledger(studio,workspace)
            self.assertEqual(len(ledger['entries']),3);self.assertEqual(ledger['estimate_cny'],1.5);self.assertEqual(ledger['unestimated_count'],1)
            self.assertFalse(ledger['entries'][0]['adopted']);self.assertIsNone(ledger['actual_cny'])
            self.assertEqual(ledger['entries'][1]['name'],'首帧素材');self.assertEqual(len(ledger['entries'][1]['objects']),2)

if __name__=='__main__':unittest.main()
