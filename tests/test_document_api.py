"""Real upload/parse/RPC/plugin seams, with model dispatch kept offline."""
import base64
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'hermes-agent')]

from miniclaw_web import canvas_tools, document_tools, images, overlay
from miniclaw_web.runtime import install
from tui_gateway import server
from tui_gateway.contracts import registry as contracts

QUERY, ANALYZE = 'miniclaw_document_query', 'miniclaw_document_analyze'


class OfflineModel:
    def __init__(self):
        self.requests = []
        self.timeout = False

    def __call__(self, messages):
        self.requests.append(messages)
        if self.timeout:
            raise TimeoutError('offline fixture missing receipt')
        payload = json.loads(messages[-1]['content'])
        if payload['data'] and 'id' in payload['data'][0]:
            return json.dumps({'items': [{'id': item['id'], 'value': 'accepted'} for item in payload['data']]})
        return json.dumps({'summary': 'All units merged from offline evidence'})


@pytest.fixture
def host(tmp_path, monkeypatch):
    home = tmp_path / '.hermes'
    home.mkdir()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    (home / 'config.yaml').write_text(
        'platform_toolsets:\n  cli: [miniclaw-documents]\n'
        'memory:\n  memory_enabled: false\n  user_profile_enabled: false\n'
        'plugins:\n  entries:\n    miniclaw-files:\n      settings:\n        workspace: ' + str(workspace) + '\n', encoding='utf-8')
    # install uses process-global bridge services; restore an earlier test app's
    # bridges when this independent host has finished.
    for module, attribute in ((images, '_service'), (canvas_tools, '_service'), (overlay, '_store'),
                              (document_tools, '_documents'), (document_tools, '_analysis')):
        monkeypatch.setattr(module, attribute, getattr(module, attribute))
    monkeypatch.setattr(server, '_sessions', {})
    monkeypatch.setattr(server, '_hermes_home', home)
    monkeypatch.setattr(server, '_db', None)
    monkeypatch.setattr(server, '_db_error', None)
    with patch.dict(server._methods), patch.dict(contracts.METHODS):
        app = FastAPI()
        install(app, tmp_path)
        app.state.miniclaw_analysis.autostart = False
        model = OfflineModel()
        app.state.miniclaw_analysis.call = model
        with TestClient(app) as client:
            session = dict(session_key='document-owner', running=False, profile_home=str(home),
                           agent=SimpleNamespace(session_id='document-owner', tools=[{'function': {'name': QUERY}}, {'function': {'name': ANALYZE}}]))
            server._sessions['document-live'] = session
            yield SimpleNamespace(app=app, client=client, session=session, owner='document-owner', home=home,
                                  documents=app.state.miniclaw_documents, analysis=app.state.miniclaw_analysis, model=model)
        # These executors have no submitted tasks in this fixture.
        images._service.executor.shutdown()
        if hasattr(canvas_tools._service, 'canvas'):
            canvas_tools._service.canvas.executor.shutdown()
        from hermes_state_registry import close_all_under
        close_all_under(home)


def upload(host, name='facts.csv', raw=b'name,amount\na,0.1\nb,0.2\n', owner=None, request=None):
    owner = owner or host.owner
    initialized = host.client.post('/api/miniclaw/uploads', json=dict(
        owner=owner, name=name, size=len(raw), request_id=request or hashlib.sha256(name.encode() + raw).hexdigest()))
    assert initialized.status_code == 200, initialized.text
    transfer = initialized.json()
    for number, offset in enumerate(range(0, len(raw), transfer['part_size'])):
        part = raw[offset:offset + transfer['part_size']]
        response = host.client.put('/api/miniclaw/uploads/' + transfer['id'] + '/parts/' + str(number),
                                   params={'owner': owner}, content=part,
                                   headers={'x-part-sha256': hashlib.sha256(part).hexdigest()})
        assert response.status_code == 200, response.text
    completed = host.client.post('/api/miniclaw/uploads/' + transfer['id'] + '/complete', json={'owner': owner})
    assert completed.status_code == 200, completed.text
    item = completed.json()
    result = host.documents.wait(item['id'], owner, 10)
    assert result['parse_status'] in ('ready', 'partial'), result
    return item


def submit(host, attachments, text='Analyze the supplied documents'):
    return server._methods['miniclaw.turn.submit']('document-turn', dict(
        session_id='document-live', text=text, attachments=attachments))


def test_real_upload_parse_status_download_and_local_query_paths(host):
    item = upload(host)
    identifier = item['id']
    status = host.client.get('/api/miniclaw/documents/' + identifier, params={'owner': host.owner})
    assert status.status_code == 200 and status.json()['parse_status'] == 'ready'
    assert status.json()['rows'] == 2 and status.json()['coverage']['complete']
    downloaded = host.client.get('/api/miniclaw/attachments/' + identifier, params={'owner': host.owner})
    assert downloaded.content == b'name,amount\na,0.1\nb,0.2\n'
    assert 'attachment' in downloaded.headers['content-disposition']
    search = host.client.post('/api/miniclaw/documents/query', json=dict(
        owner=host.owner, action='search', attachment_id=identifier, query='0.2'))
    assert search.status_code == 200
    assert search.json()['retrieval_only'] and search.json()['items'][0]['source']['row_number'] == 2
    read = host.client.post('/api/miniclaw/documents/query', json=dict(
        owner=host.owner, action='read', attachment_id=identifier, offset=1, limit=1))
    assert read.status_code == 200 and read.json()['items'][0]['ordinal'] == 1
    calculated = host.client.post('/api/miniclaw/documents/query', json=dict(
        owner=host.owner, action='calculate', attachment_id=identifier, operation='sum', column='amount'))
    assert calculated.status_code == 200 and calculated.json()['groups'][0]['value'] == '0.3'
    assert calculated.json()['examined_rows'] == 2 and calculated.json()['complete']
    assert not host.model.requests


def test_first_upload_persists_empty_native_session_and_survives_cold_resume(host, monkeypatch):
    # Keep only agent construction offline. Session creation, first-upload
    # persistence, native SQLite reads and the cold resume handler are real.
    scheduled = []
    monkeypatch.setattr(server, '_schedule_agent_build', scheduled.append)
    monkeypatch.setattr(server, '_schedule_session_cap_enforcement', lambda: None)
    monkeypatch.setattr(server, '_make_agent', lambda *_args, **_kwargs: pytest.fail('online agent must not build'))
    created = server._methods['session.create']('new-upload-session', {'source': 'desktop', 'cwd': str(host.home.parent)})
    assert 'error' not in created, created
    minted = created['result']
    owner, runtime_id = minted['stored_session_id'], minted['session_id']
    assert minted['message_count'] == 0 and minted['messages'] == []
    assert server._sessions[runtime_id]['agent'] is None
    db = server._get_db()
    assert Path(db.db_path).resolve() == (host.home / 'state.db').resolve()
    assert db.get_session(owner) is None  # Empty session.create remains a draft.

    item = upload(host, name='before-first-prompt.csv', owner=owner)
    row = db.get_session(owner)
    assert row is not None and row['source'] == 'desktop'
    assert db.get_messages(owner) == []
    assert server._sessions[runtime_id]['history'] == []

    # A process restart loses live runtimes and reopens the native database.
    # Restoring the owner must depend on the durable row, not a warm fallback.
    server._sessions.clear()
    db.close()
    server._db = None
    resumed = server._methods['session.resume']('resume-upload-session', {'session_id': owner, 'source': 'desktop'})
    assert 'error' not in resumed, resumed
    restored = resumed['result']
    assert restored['session_key'] == owner and restored['resumed'] == owner
    assert restored['session_id'] != runtime_id
    assert restored['message_count'] == 0 and restored['messages'] == []
    assert server._sessions[restored['session_id']]['session_key'] == owner
    assert server._sessions[restored['session_id']]['agent'] is None
    assert server._get_db().get_messages(owner) == []
    status = host.client.get('/api/miniclaw/documents/' + item['id'], params={'owner': owner})
    assert status.status_code == 200 and status.json()['parse_status'] == 'ready'
    original = host.client.get('/api/miniclaw/attachments/' + item['id'], params={'owner': owner})
    assert original.content == b'name,amount\na,0.1\nb,0.2\n'
    assert scheduled == [runtime_id, restored['session_id']]
    assert not host.model.requests


@pytest.mark.parametrize('extension', ['csv', 'xlsx'])
def test_status_poll_omits_wide_schema_but_keeps_sources_and_inspect_pages_exact_names(host, extension):
    columns = ['精确列名' * 25 + '_' + str(index) for index in range(120)]
    if extension == 'csv':
        # Seven malformed-width rows produce seven real source warnings.
        raw = (','.join(columns) + '\n' + (','.join(['value'] * 119) + '\n') * 7).encode()
        table, warning_code = 'csv', 'csv_column_mismatch'
    else:
        from openpyxl import Workbook
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('Wide schema')
        sheet.append(columns)
        for _ in range(7):
            sheet.append(['value'] + ['=1+1'] * 119)
        output = io.BytesIO()
        workbook.save(output)
        raw, table, warning_code = output.getvalue(), sheet.title, 'excel_formula_cache_missing'
    identifier = upload(host, name='wide-schema.' + extension, raw=raw)['id']
    assert host.documents.status(identifier, host.owner)['metadata']['tables'][0]['columns'] == columns

    response = host.client.get('/api/miniclaw/documents/' + identifier, params={'owner': host.owner})
    assert response.status_code == 200
    status = response.json()
    assert status['parse_status'] == 'partial' and status['rows'] == 7
    assert set(status['metadata']) <= {'content_scope', 'scope_notes', 'ocr_supported'}
    assert 'tables' not in status['metadata'] and 'columns' not in status['metadata']
    assert columns[0] not in response.text and columns[-1] not in response.text
    assert len(response.content) < 5000
    assert len(status['warnings']) == 5 and status['coverage']['warning_count'] == 7
    assert not status['coverage']['complete']
    warning = status['warnings'][0]
    assert warning['code'] == warning_code and warning['source']['table'] == table
    if extension == 'csv':
        assert warning['source']['line_start'] == 2 and warning['source']['line_end'] == 2
    else:
        assert warning['source']['sheet'] == table and warning['source']['row_number'] == 2

    retrieved, offset = [], 0
    while offset < len(columns):
        inspected = host.client.post('/api/miniclaw/documents/query', json=dict(
            owner=host.owner, action='inspect', attachment_id=identifier, table=table, offset=offset, limit=20))
        assert inspected.status_code == 200, inspected.text
        result = inspected.json()
        page = result['metadata']['tables'][0]
        assert page['name'] == table and page['column_count'] == len(columns)
        assert page['columns'] == columns[offset:offset + len(page['columns'])]
        assert page['next_column_offset'] > offset
        assert page['has_more_columns'] == (page['next_column_offset'] < len(columns))
        assert len(json.dumps({'metadata': result['metadata'], 'warnings': result['warnings']}, ensure_ascii=False).encode()) <= 8000
        retrieved.extend(page['columns'])
        offset = page['next_column_offset']
    assert retrieved == columns
    assert not host.model.requests


def test_ten_attachments_submit_metadata_and_neutralized_markers_without_full_bodies(host):
    attachments = []
    private_body = 'UNIQUE_FULL_ATTACHMENT_CONTENT-' + 'x' * 2000
    for number in range(10):
        raw = ('amount,@file:secret.txt\n' + str(number) + ',' + private_body + '\n').encode()
        name = 'facts-0 @diff.csv' if number == 0 else 'facts-' + str(number) + '.csv'
        attachments.append(upload(host, name=name, raw=raw)['id'])
    seen = {}
    def accepted(rid, params):
        seen.update(params)
        return server._ok(rid, {'status': 'streaming', 'user_row_id': 99101})
    with patch.dict(server._methods, {'prompt.submit': accepted}):
        result = submit(host, attachments)
    assert 'error' not in result, result
    assert all(identifier in seen['text'] for identifier in attachments)
    assert private_body not in seen['text'] and '@file:secret.txt' not in seen['text']
    assert '＠diff.csv' in seen['text'] and '@diff.csv' not in seen['text']
    assert 'media\\objects' not in seen['text'] and str(host.documents.store.home) not in seen['text']
    from agent.context_references import parse_context_references
    assert parse_context_references(seen['text']) == []
    turns = host.client.get('/api/miniclaw/turns', params={'owner': host.owner}).json()
    assert len(turns['99101']['attachments']) == 10
    assert turns['99101']['text'] == 'Analyze the supplied documents'
    assert not host.model.requests


def test_missing_tools_refuses_send_and_retains_owned_attachment_draft(host):
    item = upload(host)
    host.session['agent'].tools = []
    with patch.dict(server._methods, {'prompt.submit': lambda *_: pytest.fail('must reject before native submit')}):
        result = submit(host, [item['id']])
    assert result['error']['code'] == 4200
    assert '草稿已保留' in result['error']['message']
    assert host.client.get('/api/miniclaw/attachments/' + item['id'], params={'owner': host.owner}).status_code == 200
    assert host.client.get('/api/miniclaw/turns', params={'owner': host.owner}).json() == {}


def test_ten_small_texts_above_inline_budget_require_document_tools(host):
    attachments = [upload(host, 'text-' + str(number) + '.txt', b'ordinary short line\n' * 1050)['id'] for number in range(10)]
    assert all(host.documents.store.get('attachments', item, host.owner)['kind'] == 'text' for item in attachments)
    host.session['agent'].tools = []
    with patch.dict(server._methods, {'prompt.submit': lambda *_: pytest.fail('tool capability required')}):
        result = submit(host, attachments)
    assert result['error']['code'] == 4200 and '资料附件工具' in result['error']['message']
    assert all(host.documents.status(item, host.owner)['parse_status'] == 'ready' for item in attachments)


def test_legacy_small_utf8_text_keeps_inline_flow_without_document_tools(host):
    raw = 'ordinary legacy content @file:secret.txt'.encode()
    response = host.client.post('/api/miniclaw/attachments', json=dict(
        owner=host.owner, name='legacy.txt', data=base64.b64encode(raw).decode()))
    assert response.status_code == 200
    host.session['agent'].tools = []
    seen = {}
    def accepted(rid, params):
        seen.update(params)
        return server._ok(rid, {'status': 'streaming', 'user_row_id': 99102})
    with patch.dict(server._methods, {'prompt.submit': accepted}):
        result = submit(host, [response.json()['id']])
    assert 'error' not in result
    assert 'ordinary legacy content' in seen['text'] and '＠file:secret.txt' in seen['text']
    assert not host.model.requests


@pytest.mark.parametrize('endpoint, payload', [
    ('query', {'action': 'inspect', 'attachment_id': 'missing'}),
    ('analysis', {'action': 'start', 'attachments': ['missing'], 'mode': 'scan', 'question': 'scan', 'request_id': 'bad-owner-request'}),
    ('query', {'owner': None, 'action': 'analysis_status', 'job_id': 'missing'}),
    ('analysis', {'owner': [], 'action': 'cancel', 'job_id': 'missing'}),
    ('query', {'owner': 'owner/invalid', 'action': 'inspect', 'attachment_id': 'missing'}),
])
def test_invalid_and_missing_owner_returns_client_error_without_500(host, endpoint, payload):
    result = host.client.post('/api/miniclaw/documents/' + endpoint, json=payload)
    assert result.status_code == 400, result.text


def test_document_and_job_access_reject_foreign_owner_at_actual_routes(host):
    item = upload(host)
    identifier = item['id']
    for method, route, kwargs in [
        ('get', '/documents/' + identifier, {'params': {'owner': 'foreign'}}),
        ('delete', '/documents/' + identifier, {'params': {'owner': 'foreign'}}),
        ('post', '/documents/' + identifier + '/retry', {'json': {'owner': 'foreign'}}),
        ('post', '/documents/query', {'json': dict(owner='foreign', action='calculate', attachment_id=identifier)}),
        ('post', '/documents/analysis', {'json': dict(owner='foreign', action='start', attachments=[identifier],
                                                  mode='scan', question='scan', request_id='foreign-owner-request')}),
    ]:
        response = getattr(host.client, method)('/api/miniclaw' + route, **kwargs)
        assert response.status_code == 400, response.text
    assert host.client.get('/api/miniclaw/attachments/' + identifier, params={'owner': 'foreign'}).status_code == 404
    assert host.documents.status(identifier, host.owner)['parse_status'] == 'ready'
    assert not host.model.requests


@pytest.fixture
def plugin(host):
    from hermes_cli.plugins import PluginContext, PluginManager, parse_manifest_file
    from tools.registry import registry
    directory = ROOT / 'plugins' / 'miniclaw-files'
    manifest = parse_manifest_file(directory / 'plugin.yaml', directory, 'user', '')
    assert manifest is not None
    manager = PluginManager()
    context = PluginContext(manifest, manager)
    spec = importlib.util.spec_from_file_location('miniclaw_document_api_plugin', directory / '__init__.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.register(context)
    definitions = registry.get_definitions({QUERY, ANALYZE}, quiet=True)
    host.session['agent'].tools = definitions
    try:
        yield SimpleNamespace(registry=registry, definitions=definitions, scope=manager.scope_key)
    finally:
        manager.unload()


def dispatch(plugin, name, args, session='document-owner'):
    return json.loads(plugin.registry.dispatch(name, args, scope=plugin.scope, session_id=session))


def test_real_plugin_schemas_and_all_four_task_paths_dispatch_offline(host, plugin):
    definitions = {item['function']['name']: item['function'] for item in plugin.definitions}
    assert set(definitions) == {QUERY, ANALYZE}
    assert set(definitions[QUERY]['parameters']['properties']['action']['enum']) == {'inspect', 'read', 'search', 'calculate', 'analysis_status'}
    assert definitions[ANALYZE]['parameters']['properties']['mode']['enum'] == ['scan', 'summarize']
    assert not definitions[QUERY]['parameters']['additionalProperties']
    assert 'NOT a full scan' in definitions[QUERY]['description']
    assert 'explicit user instruction' in definitions[ANALYZE]['description']
    identifier = upload(host)['id']
    assert dispatch(plugin, QUERY, dict(action='inspect', attachment_id=identifier))['success']
    search = dispatch(plugin, QUERY, dict(action='search', attachment_id=identifier, query='0.2'))
    assert search['retrieval_only'] and len(search['items']) == 1
    read = dispatch(plugin, QUERY, dict(action='read', attachment_id=identifier, limit=1))
    assert read['has_more']
    calculated = dispatch(plugin, QUERY, dict(action='calculate', attachment_id=identifier, operation='sum', column='amount'))
    assert calculated['groups'][0]['value'] == '0.3' and calculated['complete']
    assert not host.model.requests
    for mode in ('scan', 'summarize'):
        started = dispatch(plugin, ANALYZE, dict(action='start', attachments=[identifier], mode=mode,
                                              question='Process all source units', request_id='plugin-' + mode))
        assert started['success'] and started['state'] == 'queued' and not started['coverage']['complete']
        host.analysis._run(started['id'], host.owner)
        finished = dispatch(plugin, QUERY, dict(action='analysis_status', job_id=started['id']))
        assert finished['state'] == 'complete' and finished['coverage']['complete']
        assert finished['coverage']['completed_units'] == (2 if mode == 'scan' else 3)
    assert len(host.model.requests) == 3
    denied = dispatch(plugin, QUERY, dict(action='inspect', attachment_id=identifier), session='missing-session')
    assert not denied['success']
    foreign_session = dict(session_key='foreign', agent=host.session['agent'])
    server._sessions['document-foreign'] = foreign_session
    denied = dispatch(plugin, QUERY, dict(action='inspect', attachment_id=identifier), session='foreign')
    assert not denied['success']


def test_batch_search_and_context_through_real_api_and_plugin(host, plugin):
    identifier = upload(host, name='topics.txt', raw='前言\n附件主题\n章节解释\n解析规则\n附件与解析\n结尾'.encode())['id']
    args = dict(action='search', attachment_id=identifier, queries=['附件', '解析'], context=1, limit=2)
    response = host.client.post('/api/miniclaw/documents/query', json=dict(owner=host.owner, **args))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['hit_ordinals'] == [1, 3]
    assert result['context_ordinals'] == [0, 2, 4]
    assert [item['ordinal'] for item in result['items']] == [0, 1, 2, 3, 4]
    assert result['hit_count'] == 2 and result['context_count'] == 3
    assert result['next_offset'] == 2 and result['has_more'] and result['retrieval_only']
    assert not result['context_truncated']
    tool_result = dispatch(plugin, QUERY, args)
    assert tool_result['success'] and tool_result['items'] == result['items']
    next_page = dispatch(plugin, QUERY, dict(args, offset=result['next_offset']))
    assert next_page['hit_ordinals'] == [4] and not next_page['has_more']
    assert next_page['next_offset'] == 3
    definition = next(item['function'] for item in plugin.definitions if item['function']['name'] == QUERY)
    assert definition['parameters']['properties']['queries']['maxItems'] == 5
    assert definition['parameters']['properties']['context']['maximum'] == 2
    assert 'ONE search' in definition['description']
    assert not host.model.requests


@pytest.mark.parametrize('fields', [
    {}, {'query': '附件', 'queries': ['解析']}, {'query': None},
    {'query': None, 'queries': ['解析']}, {'query': '附件', 'queries': None},
    {'queries': []}, {'queries': ['']}, {'queries': [7]}, {'queries': '附件'},
    {'queries': ['附件'] * 6}, {'queries': ['x' * 501]},
    {'query': '附件', 'context': True}, {'query': '附件', 'context': -1}, {'query': '附件', 'context': 3},
])
def test_search_invalid_new_parameters_fail_at_api_and_plugin(host, plugin, fields):
    identifier = upload(host)['id']
    args = dict(action='search', attachment_id=identifier, **fields)
    response = host.client.post('/api/miniclaw/documents/query', json=dict(owner=host.owner, **args))
    assert response.status_code == 400, response.text
    result = dispatch(plugin, QUERY, args)
    assert not result['success']
    assert not host.model.requests


def test_search_context_fields_reject_other_actions_and_foreign_owner(host, plugin):
    identifier = upload(host)['id']
    args = dict(action='search', attachment_id=identifier, queries=['amount', 'name'], context=2)
    response = host.client.post('/api/miniclaw/documents/query', json=dict(owner='foreign', **args))
    assert response.status_code == 400
    for action in ('inspect', 'read', 'calculate'):
        assert not dispatch(plugin, QUERY, dict(action=action, attachment_id=identifier, context=1))['success']
    assert not host.model.requests


def test_complete_search_json_budget_drops_context_before_hits_without_skipping_page():
    # Realistic CJK chunk, keyword and workbook-schema sizes exercise the full
    # tool envelope rather than assuming a bounded chunk budget bounds JSON.
    hits = [0, 2, 4]
    items = [dict(id=str(ordinal), ordinal=ordinal, text='汉' * (3666 if ordinal in hits else 333),
                  source={'paragraph': ordinal + 1}) for ordinal in [0, 1, 2, 4]]
    raw = dict(items=items, hit_ordinals=hits, context_ordinals=[1], context_truncated=False,
               has_more=False, queries=[str(index) + '词' * 499 for index in range(5)],
               metadata={'tables': [{'name': 'sheet', 'columns': [str(index) + '列' * 499 for index in range(5)]}]})
    result = document_tools.bounded_search(raw, offset=5)
    assert len(json.dumps(dict(success=True, **result), ensure_ascii=False).encode()) <= 48_000
    assert result['context_count'] == 0 and result['context_truncated']
    assert result['hit_ordinals'] == [0, 2] and result['hit_count'] == 2
    assert result['next_offset'] == 7 and result['has_more']
    assert [item['ordinal'] for item in result['items']] == [0, 2]
    assert result['returned_bytes'] == sum(len(json.dumps(item, ensure_ascii=False, separators=(',', ':')).encode())
                                           for item in result['items'])


def test_analysis_unknown_receipt_and_duplicate_start_reuse_job_without_auto_cost(host, plugin):
    identifier = upload(host)['id']
    args = dict(action='start', attachments=[identifier], mode='scan', question='Process every record', request_id='duplicate-analysis')
    first = dispatch(plugin, ANALYZE, args)
    assert dispatch(plugin, ANALYZE, dict(args))['id'] == first['id']
    host.model.timeout = True
    host.analysis._run(first['id'], host.owner)
    unknown = dispatch(plugin, QUERY, dict(action='analysis_status', job_id=first['id']))
    assert unknown['state'] == 'unknown' and unknown['calls'] == 1
    assert dispatch(plugin, ANALYZE, dict(args))['id'] == first['id']
    assert len(host.model.requests) == 1
    denied = dispatch(plugin, ANALYZE, dict(action='resume', job_id=first['id'], max_calls=129))
    assert not denied['success'] and '明确确认' in denied['error']
    assert len(host.model.requests) == 1
    # Exercise the real human-answer transition. The test host has no native
    # model runner, so stop its unrelated chat-resume consumer before answering.
    coordinator = host.app.state.clarifications
    coordinator.closed.set()
    coordinator.wake.set()
    host.app.state.clarification_worker.join(3)
    from miniclaw_web.clarification_policy import question
    service = coordinator.service
    task = service.start(host.owner, 'Continue the analysis after checking the unknown receipt')
    clarification = service.prepare(task['id'], [question('Q_EXECUTION', 'Continue?', ['确认执行', '只整理方案'])], 'hook')
    service.seal(task['id'], host.owner, 0)
    item = service.request(clarification)
    service.answer([host.owner], item['id'], item['version'], {'Q_EXECUTION': '确认执行'}, 'offline-human-confirmation')
    host.session['agent']._hosted_turn_adapter = SimpleNamespace(service=service, task_id=task['id'])
    denied_unknown = dispatch(plugin, ANALYZE, dict(action='resume', job_id=first['id'], max_calls=129))
    assert not denied_unknown['success'] and 'retry_unknown=true' in denied_unknown['error']
    assert len(host.model.requests) == 1
    host.model.timeout = False
    resumed = dispatch(plugin, ANALYZE, dict(action='resume', job_id=first['id'], max_calls=129, retry_unknown=True))
    assert resumed['id'] == first['id'] and resumed['state'] == 'queued'
    host.analysis._run(first['id'], host.owner)
    assert dispatch(plugin, QUERY, dict(action='analysis_status', job_id=first['id']))['coverage']['complete']
    assert len(host.model.requests) == 2


def test_hosted_adapter_reuses_analysis_job_even_if_model_changes_request_id(host, plugin):
    from miniclaw_web.clarification_policy import ClarificationPolicy
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    identifier = upload(host)['id']
    service = host.app.state.clarifications.service
    task = service.start(host.owner, 'Scan every document record', context={'versions': {}, 'intent': 'discuss'})
    adapter = HermesClarificationAdapter(service, ClarificationPolicy(None), host.session, task['id'])
    received = []
    def execute(arguments):
        received.append(dict(arguments))
        return plugin.registry.dispatch(ANALYZE, arguments, scope=plugin.scope, session_id=host.owner)
    original = dict(action='start', attachments=[identifier], mode='scan', question='Process every record', request_id='model-created-one')
    first = json.loads(adapter.dispatch(ANALYZE, original, 'call-first', lambda: execute(original)))
    changed = {**original, 'request_id': 'model-created-two'}
    second = json.loads(adapter.dispatch(ANALYZE, changed, 'call-second', lambda: execute(changed)))
    assert first['success'] and second['id'] == first['id']
    assert len(received) == 1 and received[0]['request_id'] != 'model-created-one'
    with host.documents.store.connect() as db:
        assert db.execute('SELECT count(*) FROM document_analysis_jobs').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM chat_operations WHERE task_id=?', (task['id'],)).fetchone()[0] == 1
    higher = dict(action='resume', job_id=first['id'], max_calls=129)
    guarded = json.loads(adapter.dispatch(ANALYZE, higher, 'call-resume', lambda: pytest.fail('requires user instruction')))
    assert guarded['status'] == 'awaiting_input'
    assert not host.model.requests


def test_hosted_unknown_start_receipt_stops_repeat_before_duplicate_job(host, plugin):
    from miniclaw_web.clarification_policy import ClarificationPolicy
    from miniclaw_web.hermes_clarification_adapter import HermesClarificationAdapter
    identifier = upload(host)['id']
    service = host.app.state.clarifications.service
    task = service.start(host.owner, 'Scan every record', context={'versions': {}, 'intent': 'discuss'})
    adapter = HermesClarificationAdapter(service, ClarificationPolicy(None), host.session, task['id'])
    attempts = []
    original = dict(action='start', attachments=[identifier], mode='scan', question='Read every record', request_id='unknown-create-one')
    def lost_receipt():
        result = dispatch(plugin, ANALYZE, original)
        assert result['success']
        attempts.append(result['id'])
        raise TimeoutError('job persisted but tool receipt lost')
    with pytest.raises(TimeoutError):
        adapter.dispatch(ANALYZE, original, 'call-lost', lost_receipt)
    repeat = {**original, 'request_id': 'unknown-create-two'}
    guarded = json.loads(adapter.dispatch(ANALYZE, repeat, 'call-repeat', lambda: pytest.fail('unknown writes must reconcile')))
    assert guarded['status'] == 'awaiting_input'
    with host.documents.store.connect() as db:
        assert db.execute('SELECT count(*) FROM document_analysis_jobs').fetchone()[0] == 1
        assert db.execute('SELECT status FROM chat_operations WHERE task_id=?', (task['id'],)).fetchone()[0] == 'unknown'
    assert len(attempts) == 1 and not host.model.requests
