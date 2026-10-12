"""Narrow document APIs and tools; session ownership is supplied by the host."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request

_documents = _analysis = None


def set_services(documents, analysis):
    global _documents, _analysis
    _documents, _analysis = documents, analysis


def bounded_metadata(result, table=None, offset=0, limit=10):
    """Page full column names under a UTF-8 budget; never invent truncated keys."""
    result = dict(result)
    metadata = result.get('metadata', {})
    tables = metadata.get('tables', [])
    if table is not None and (not isinstance(table, str) or not 1 <= len(table) <= 500):
        raise ValueError('表格名称无效')
    selected = [item for item in tables if table is None or item['name'] == table]
    if table is not None and not selected:
        raise ValueError('该工作表或表格不存在')
    result['metadata'] = {key: value[:500] if isinstance(value, str) else value
                          for key, value in metadata.items() if key != 'tables' and not isinstance(value, (dict, list))}
    result['warnings'] = [{key: warning[key][:300] for key in ('code', 'message') if isinstance(warning.get(key), str)}
                          for warning in result.get('warnings', [])[:5]]
    output = []
    result['metadata'].update(tables=output, table_count=len(tables),
                              has_more_tables=False, next_table_offset=offset,
                              schema_truncated=False)
    def size():
        return len(json.dumps({'metadata': result['metadata'], 'warnings': result['warnings']},
                              ensure_ascii=False).encode())
    page = selected if table is not None else selected[offset:offset + limit]
    for item in page:
        start = offset if table is not None else 0
        entry = dict(name=item['name'], header_row=item.get('header_row'), columns=[],
                     column_count=len(item['columns']), next_column_offset=start,
                     has_more_columns=start < len(item['columns']))
        output.append(entry)
        if size() > 8_000:
            output.pop()
            break
        for column in item['columns'][start:start + (limit if table is not None else 20)]:
            entry['columns'].append(column)
            if size() > 8_000:
                entry['columns'].pop()
                break
        entry['next_column_offset'] = start + len(entry['columns'])
        entry['has_more_columns'] = entry['next_column_offset'] < len(item['columns'])
    result['metadata']['next_table_offset'] = offset + len(output) if table is None else 0
    result['metadata']['has_more_tables'] = table is None and offset + len(output) < len(tables)
    result['metadata']['schema_truncated'] = result['metadata']['has_more_tables'] or any(item['has_more_columns'] for item in output)
    return result


def bounded_calculation(result):
    """Keep every computed group or fail explicitly; bound warning presentation."""
    result = dict(result)
    locator_fields = {'attachment_id', 'object_id', 'parser_version', 'page', 'line_start', 'line_end',
                      'paragraph', 'table', 'sheet', 'row_number', 'part', 'char_start', 'char_end'}
    warnings = result.get('warnings', [])
    result['warnings'] = []
    for warning in warnings[:5]:
        entry = {key: warning[key][:300] for key in ('code', 'message')
                 if isinstance(warning.get(key), str)}
        source = warning.get('source', {})
        entry['source'] = {key: value[:500] if isinstance(value, str) else value
                           for key, value in source.items() if key in locator_fields
                           and (isinstance(value, str) or type(value) is int)}
        if isinstance(source.get('formula_missing_columns'), list):
            columns = source['formula_missing_columns']
            entry['source']['formula_missing_columns'] = [value for value in columns[:20] if type(value) is int]
            entry['source']['formula_missing_count'] = source.get('formula_missing_count', len(columns))
            entry['source']['formula_missing_columns_truncated'] = bool(source.get('formula_missing_columns_truncated') or len(columns) > 20)
        result['warnings'].append(entry)
    result['warning_count'] = max(len(warnings), result.get('coverage', {}).get('warning_count', 0))
    result['warnings_truncated'] = result['warning_count'] > len(result['warnings'])
    # Include the success wrapper used by the model tool so the API and tool both fit.
    if len(json.dumps(dict(success=True, **result), ensure_ascii=False).encode('utf-8')) > 48_000:
        raise ValueError('计算结果超过48000字节，未返回任何截断分组；请减少group_by或缩小filters筛选范围')
    return result


def bounded_search(result, offset=0):
    """Bound the complete search response, trimming context before paged hits."""
    result = bounded_metadata(result)
    items = list(result['items'])
    hits = list(result['hit_ordinals'])
    context = list(result['context_ordinals'])
    result.update(items=items, hit_ordinals=hits, context_ordinals=context)

    def recount():
        result.update(hit_count=len(hits), context_count=len(context), next_offset=offset + len(hits),
                      returned_bytes=sum(len(json.dumps(item, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
                                         for item in items))

    recount()
    while len(json.dumps(dict(success=True, **result), ensure_ascii=False).encode('utf-8')) > 48_000:
        if context:
            # Preserve the nearest available context for every hit where possible.
            ordinal = max(context, key=lambda value: (min(abs(value - hit) for hit in hits), value))
            context.remove(ordinal)
            result['context_truncated'] = True
        elif hits:
            ordinal = hits.pop()
            result['has_more'] = True
        else:
            raise ValueError('搜索元数据超过48000字节，请缩短搜索词或减少关键词数量')
        items[:] = [item for item in items if item['ordinal'] != ordinal]
        recount()
    return result


def query(documents, analysis, owner, args):
    documents._validate_owner(owner)
    if not isinstance(args, dict):
        raise ValueError('资料工具参数无效')
    action = args.get('action')
    allowed = {
        'inspect': {'action', 'attachment_id', 'table', 'offset', 'limit'},
        'read': {'action', 'attachment_id', 'offset', 'limit'},
        'search': {'action', 'attachment_id', 'query', 'queries', 'context', 'offset', 'limit'},
        'calculate': {'action', 'attachment_id', 'operation', 'column', 'group_by', 'filters', 'table'},
        'analysis_status': {'action', 'job_id', 'offset', 'limit'},
    }
    if action not in allowed or set(args) - allowed[action]:
        raise ValueError('资料查询动作或字段无效')
    if action == 'search':
        if ('query' in args) == ('queries' in args):
            raise ValueError('搜索需且仅需提供query或queries之一')
        if 'query' in args and not isinstance(args['query'], str):
            raise ValueError('搜索词需为字符串')
        if 'queries' in args and not isinstance(args['queries'], list):
            raise ValueError('搜索关键词需为字符串数组')
    if action == 'analysis_status':
        return analysis.status(args['job_id'], owner, args.get('offset', 0), args.get('limit', 5))
    identifier = args['attachment_id']
    # Legacy UTF-8 attachments can enter the same local parsing/indexing path.
    documents.enqueue(identifier, owner)
    if action == 'inspect':
        offset, limit = args.get('offset', 0), args.get('limit', 10)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError('表格结构分页参数无效')
        return bounded_metadata(documents.status(identifier, owner), args.get('table'), offset, limit)
    if action == 'read':
        return bounded_metadata(documents.read(identifier, owner, args.get('offset', 0), args.get('limit', 10)))
    if action == 'search':
        offset = args.get('offset', 0)
        return bounded_search(documents.search(identifier, owner, args.get('query'), offset, args.get('limit', 10),
                                               max_bytes=36_000, queries=args.get('queries'), context=args.get('context', 0)), offset)
    return bounded_calculation(documents.aggregate(identifier, owner, args.get('operation', 'count'), args.get('column'),
                               args.get('group_by'), args.get('filters'), args.get('table')))


def analyze(analysis, owner, args):
    analysis.documents._validate_owner(owner)
    if not isinstance(args, dict):
        raise ValueError('分析工具参数无效')
    action = args.get('action')
    allowed = {
        'start': {'action', 'attachments', 'mode', 'question', 'request_id', 'max_calls', 'max_input_bytes'},
        'cancel': {'action', 'job_id'},
        'resume': {'action', 'job_id', 'max_calls', 'retry_unknown', 'max_input_bytes'},
    }
    if action not in allowed or set(args) - allowed[action]:
        raise ValueError('分析动作或字段无效')
    if action == 'start':
        return analysis.create(owner, args['attachments'], args['mode'], args['question'], args['request_id'],
                               args.get('max_calls', 128), args.get('max_input_bytes', 16 * 1024 * 1024))
    if action == 'cancel':
        return analysis.cancel(args['job_id'], owner)
    return analysis.resume(args['job_id'], owner, args['max_calls'], args.get('retry_unknown', False), args.get('max_input_bytes'))


def document_tool(name, args, session_id):
    from tui_gateway import server
    try:
        if _documents is None or _analysis is None or not session_id:
            raise ValueError('资料工具需要本机Web工作台的运行会话')
        session = next((value for value in server._sessions.values() if value.get('session_key') == session_id
                        or getattr(value.get('agent'), 'session_id', None) == session_id), None)
        if session is None:
            raise ValueError('资料工具会话不可用')
        if name not in {item['function']['name'] for item in getattr(session.get('agent'), 'tools', [])}:
            raise ValueError('本对话未加载资料工具，请启用资料附件并新建对话')
        if name == 'miniclaw_document_analyze':
            costly = (args.get('action') == 'resume' or args.get('retry_unknown')
                      or args.get('max_calls', 128) > 128 or args.get('max_input_bytes', 16777216) > 16777216)
            if costly:
                adapter = getattr(session.get('agent'), '_hosted_turn_adapter', None)
                if adapter is None or adapter.service.task(adapter.task_id)['confirmed'].get('Q_EXECUTION') != '确认执行':
                    raise ValueError('续跑、扩大预算或未知请求重试需要用户在当前任务明确确认')
        owner = session['session_key']
        result = query(_documents, _analysis, owner, args) if name == 'miniclaw_document_query' else analyze(_analysis, owner, args)
        return json.dumps(dict(success=True, **result), ensure_ascii=False)
    except (ValueError, KeyError, TypeError, OSError) as error:
        message = str(error) if isinstance(error, ValueError) else '资料请求无效或读取失败，原文件保留'
        return json.dumps(dict(success=False, error=message), ensure_ascii=False)


def register(ctx):
    query_properties = {
        'action': {'type': 'string', 'enum': ['inspect', 'read', 'search', 'calculate', 'analysis_status']},
        'attachment_id': {'type': 'string'}, 'job_id': {'type': 'string'},
        'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20},
        'query': {'type': 'string', 'minLength': 1, 'maxLength': 500,
                  'description': 'One literal keyword. Supply exactly one of query or queries.'},
        'queries': {'type': 'array', 'minItems': 1, 'maxItems': 5,
                    'items': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                    'description': 'Related literal keywords, OR-matched in one query; results are deduplicated in document order.'},
        'context': {'type': 'integer', 'minimum': 0, 'maximum': 2,
                    'description': 'Include up to this many adjacent chunks before/after hits, within the shared response budget. Default 0.'},
        'operation': {'type': 'string', 'enum': ['count', 'sum', 'avg']},
        'column': {'type': 'string'}, 'table': {'type': 'string'},
        'group_by': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3},
        'filters': {'type': 'array', 'maxItems': 10, 'items': {'type': 'object', 'properties': {
            'column': {'type': 'string'}, 'op': {'type': 'string', 'enum': ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains']},
            'value': {'type': ['string', 'number', 'null']}}, 'required': ['column', 'op', 'value'], 'additionalProperties': False}},
    }
    analysis_properties = {
        'action': {'type': 'string', 'enum': ['start', 'cancel', 'resume']},
        'attachments': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 10},
        'mode': {'type': 'string', 'enum': ['scan', 'summarize']}, 'question': {'type': 'string', 'maxLength': 2000},
        'request_id': {'type': 'string', 'minLength': 8, 'maxLength': 80}, 'job_id': {'type': 'string'},
        'max_calls': {'type': 'integer', 'minimum': 1, 'maximum': 10000},
        'max_input_bytes': {'type': 'integer', 'minimum': 64000, 'maximum': 1073741824},
        'retry_unknown': {'type': 'boolean'},
    }
    definitions = [
        ('miniclaw_document_query', 'Read owned document metadata and bounded chunks with page/line sources. First decide the task: for locating content or checking whether a topic exists, start with ONE search using queries for all related literal keywords (OR, max 5) and context=1 or 2 when surrounding text helps. Supply exactly one of query or queries. Hits and adjacent context are deduplicated; limit/offset/next_offset page matching chunks only, not context. hit_ordinals identify matches; context_truncated means some surrounding chunks did not fit. Read more only if the returned evidence is insufficient; do not separately search each keyword or repeat a successful query once the question is answered. Retrieval is NOT a full scan. For numeric totals use calculate count/sum/avg with validated filters/grouping (Decimal, no arbitrary SQL); inspect lists table names/columns and coverage only when that structure is needed. analysis_status reads persistent scan/summary progress and paginated outputs; never poll continuously inside the Chat loop.', query_properties),
        ('miniclaw_document_analyze', 'For user-requested full processing only: start mode=scan to process EVERY table row or text chunk, or summarize to map ALL chunks then merge hierarchically. Supply original attachments and question. This starts a bounded background text-model job; queued/running is not a result. Report job ID and inspect later via document_query analysis_status. Partial sources/failed units cannot be claimed complete. Defaults 128 calls/16MiB cumulative input; larger budgets and resume/retry_unknown require explicit user instruction because they can add model costs. Cancel stops future calls and retains completed units. Never use this for search or numeric totals.', analysis_properties),
    ]
    for name, description, properties in definitions:
        def handler(args, session_id=None, _name=name, **kwargs):
            return document_tool(_name, args, session_id)
        ctx.register_tool(name=name, toolset='miniclaw-documents', description=description,
                          schema={'name': name, 'description': description, 'parameters': {
                              'type': 'object', 'properties': properties, 'required': ['action'], 'additionalProperties': False}}, handler=handler)


def routes(documents, analysis, body):
    async def same_origin(request: Request):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '资料接口仅接受同源浏览器请求')
    router = APIRouter(dependencies=[Depends(same_origin)])
    async def call(function, *args, **kwargs):
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        except (KeyError, TypeError):
            raise HTTPException(400, '资料请求字段无效') from None
        except OSError:
            raise HTTPException(503, '本地资料读取失败') from None
    @router.get('/documents/{identifier}')
    async def status(identifier: str, owner: str):
        result = await call(documents.status, identifier, owner)
        # Cards poll this endpoint and persist its result in small draft records.
        # Full workbook schemas belong to the paginated inspect tool, not a poll.
        metadata = result.get('metadata', {})
        result['metadata'] = {key: metadata[key] for key in ('content_scope', 'scope_notes', 'ocr_supported') if key in metadata}
        warnings = []
        for item in result.get('warnings', [])[:5]:
            source = item.get('source', {})
            locator = {key: value[:100] if isinstance(value, str) else value for key, value in source.items()
                       if key in ('page', 'sheet', 'table', 'row_number', 'line_start', 'line_end', 'paragraph')}
            warnings.append(dict(code=item.get('code', '')[:100], message=item.get('message', '')[:300], source=locator))
        result['warnings'] = warnings
        return result
    @router.post('/documents/{identifier}/retry')
    async def retry(identifier: str, request: Request):
        payload = await body(request)
        if set(payload) != {'owner'}:
            raise HTTPException(400, '需要当前会话标识')
        return await call(documents.retry, identifier, payload['owner'])
    @router.delete('/documents/{identifier}')
    async def cancel(identifier: str, owner: str):
        return await call(documents.cancel, identifier, owner)
    @router.post('/documents/query')
    async def document_query(request: Request):
        payload = await body(request)
        if 'owner' not in payload:
            raise HTTPException(400, '需要当前会话标识')
        owner = payload.pop('owner')
        return await call(query, documents, analysis, owner, payload)
    @router.post('/documents/analysis')
    async def document_analyze(request: Request):
        payload = await body(request)
        if 'owner' not in payload:
            raise HTTPException(400, '需要当前会话标识')
        owner = payload.pop('owner')
        return await call(analyze, analysis, owner, payload)
    return router
