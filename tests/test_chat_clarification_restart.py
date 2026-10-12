"""Hard-exit a disposable process at the two SQLite commit boundaries."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'hermes-agent')]
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications

SCRIPT = '''
import os,sys,json
from pathlib import Path
root=Path(sys.argv[1]);home=Path(sys.argv[2]);stage=sys.argv[3]
sys.path[:0]=[str(root),str(root/'hermes-agent')]
os.environ['HERMES_HOME']=str(home)
from miniclaw_web.store import Store
from miniclaw_web.clarifications import Clarifications
from hermes_state import SessionDB
service=Clarifications(Store(home));db=SessionDB(db_path=home/'state.db')
db.create_session('chat','cli')
task=service.start('chat','save proposal')
question=service.prepare(task['id'],[{'question':'Which color?','choices':['red','blue']}],'tool','ask')
db.append_message('chat','user',content='save proposal')
db.append_message('chat','assistant',content='',tool_calls=[{'id':'ask','type':'function','function':{'name':'clarify','arguments':'{}'}}])
if stage!='unpaired':
 db.append_message('chat','tool',content='{"status":"awaiting_input"}',tool_call_id='ask')
 db.append_message('chat','assistant',content='Waiting',display_metadata={'clarification_id':question,'task_id':task['id']})
if stage in ('pending','answered','claimed','accepted'):
 service.seal(task['id'],'chat',4)
if stage in ('answered','claimed','accepted'):
 item=service.request(question)
 service.answer(['chat'],question,item['version'],{'q1':'red'},'submission')
if stage in ('claimed','accepted'):service.claim('submission')
if stage=='accepted':db.append_message('chat','user',content='real answer red',display_metadata={'resume_job_id':'submission','task_id':task['id']})
(home/'identity.json').write_text(json.dumps({'task':task['id'],'question':question}))
os._exit(23)
'''


@pytest.mark.parametrize('stage', ['unpaired','prepared','pending','answered','claimed','accepted'])
def test_process_crash_does_not_fabricate_answers_or_repeat_accepted_turn(tmp_path, stage):
    home = tmp_path/'home'
    result = subprocess.run([sys.executable,'-c',SCRIPT,str(ROOT),str(home),stage],capture_output=True,timeout=20)
    assert result.returncode == 23, result.stderr.decode(errors='replace')[-1500:]
    identity = json.loads((home/'identity.json').read_text())
    service = Clarifications(Store(home))
    from hermes_state import SessionDB
    with SessionDB(db_path=home/'state.db',read_only=True) as db:
        service.recover(db.get_messages)
    task = service.task(identity['task'])
    item = service.request(identity['question'])
    if stage in ('unpaired','accepted'):
        assert task['status'] == 'reconciling' and not service.jobs()
    elif stage in ('prepared','pending'):
        assert task['status'] == 'awaiting_input' and item['status'] == 'pending'
        assert not service.jobs() and 'answers' not in item
    else:
        assert item['status'] == 'answered' and task['status'] == 'resume_queued'
        assert service.claim('submission') is True
        assert service.claim('submission') is False
