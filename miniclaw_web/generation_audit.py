"""Generation ledger: recorded requests and reference estimates, never fake bills."""
import json

PRICE_URL = 'https://help.aliyun.com/zh/model-studio/model-pricing'
PRICE_DATE = '2026-10-08'
IMAGE_RATES = {'qwen-image-edit-max': .5, 'qwen-image-edit-plus': .2, 'qwen-image-edit': .3,
               'qwen-image-2.0-pro': .5, 'qwen-image-2.0': .2, 'qwen-image-max': .5,
               'qwen-image-plus': .2, 'image-01': .025}
MINIMAX_VIDEO_RATES = {('MiniMax-H3','768P'): .5, ('MiniMax-H3','2K'): .8,
                       ('MiniMax-H3-Max','480P'): .33, ('MiniMax-H3-Max','768P'): .5}


def usage_fields(value):
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if k in
            ('image_count', 'video_duration', 'input_tokens', 'output_tokens', 'total_tokens')
            and type(v) in (int, float) and 0 <= v < 1e12}


def entry(job, kind, name='', adopted=False):
    model = job.get('model')
    quantity = job.get('generation_duration',job.get('duration', 5)) if kind == 'video' else 1
    price = IMAGE_RATES.get(model) if kind != 'video' else (.2 if model == 'wan2.2-i2v-flash' else MINIMAX_VIDEO_RATES.get((model,job.get('resolution'))))
    extra = 0
    if kind == 'video' and model in ('MiniMax-H3','MiniMax-H3-Max'):
        count = job.get('reference_count',len(job.get('input_paths') or [])) if job.get('mode') == 'reference' else 1
        extra = max(0,count-(5 if model=='MiniMax-H3' else 2)) * (.2 if model=='MiniMax-H3' else .5)
    # A completed rejected candidate still incurred generation. Failed/unknown
    # transport does not prove that the provider did or did not bill it.
    estimate = round(price * quantity + extra, 4) if price is not None and job['state'] == 'succeeded' else None
    return {'id': job['id'], 'kind': kind, 'name': name or job.get('name', ''),
            'state': job['state'], 'model': model, 'provider': job.get('provider', 'dashscope'),
            'provider_request_id': job.get('task_id') or job.get('provider_request_id'),
            'created_at': job.get('created_at', job.get('created')), 'adopted': adopted,
            'quantity': quantity, 'unit': '秒' if kind == 'video' else '张',
            'usage': usage_fields(job.get('usage')), 'estimate_cny': estimate,
            'unit_price_cny':price, 'input_estimate_cny':extra, 'resolution':job.get('resolution'),
            'estimate_reason': ('按记录的模型、时长与分辨率估算' if kind=='video' else '按记录的模型与生成张数估算') if estimate is not None else '模型、分辨率或执行结果不足以估算',
            'actual_cny': None, 'price_region': '中国内地参考标价' if price is not None else None,
            'region': job.get('provider_region'), 'price_checked_at': PRICE_DATE if price is not None else None,
            'price_source': 'https://platform.minimax.cn/docs/guides/pricing-paygo' if job.get('provider')=='minimax' else PRICE_URL,
            'output_duration':job.get('duration') if kind=='video' else None}


def project_ledger(studio, workspace):
    record = studio.workspaces.get(workspace)
    if not record:
        raise ValueError('项目不存在')
    with studio.store.connect() as db:
        links = db.execute('SELECT object_id,data FROM video_precision_links WHERE workspace=?', (workspace,)).fetchall()
        projects = {}
        for obj, raw in links:
            projects.setdefault(json.loads(raw)['project'], []).append(obj)
        images = []
        for project, objects in projects.items():
            asset = next((a for a in record['state']['assets'] if a['id'] in objects), None)
            name = asset['name'] if asset else '图片精修'
            for raw, in db.execute('SELECT data FROM canvas_jobs WHERE project=?', (project,)):
                job = json.loads(raw)
                row = entry(job, 'image', name, job.get('review', {}).get('decision') == 'keep')
                row['objects'] = objects
                images.append(row)
    adopted = {s.get('job') for s in record['state']['sequence'] if isinstance(s, dict)}
    videos = [entry(j, 'video', adopted=j['id'] in adopted) for j in studio.video.list(workspace)]
    entries = sorted(images + videos, key=lambda j: j['created_at'] or 0, reverse=True)
    return {'workspace': workspace, 'entries': entries, 'estimate_cny': round(sum(j['estimate_cny'] or 0 for j in entries), 4),
            'unestimated_count': sum(j['estimate_cny'] is None for j in entries), 'actual_cny': None,
            'notice': '参考估算按中国内地标价，未扣免费额度、折扣；旧记录未保存模型或地域时保持未知。实际扣费待供应商账单核对。'}
