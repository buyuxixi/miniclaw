"""Server-owned, task-specific model capabilities. Never return credentials."""
from .image_provider import settings
from .minimax_video import configuration


def catalog():
    configured = {'dashscope': bool(settings()['key']), 'minimax': bool(configuration()['key'])}
    models = []
    def add(provider, model, label, tasks, detail, **params):
        from .generation_audit import IMAGE_RATES, MINIMAX_VIDEO_RATES, PRICE_DATE, PRICE_URL
        unit = MINIMAX_VIDEO_RATES.get((model,params.get('resolution'))) if 'video' in tasks else IMAGE_RATES.get(model)
        if model == 'wan2.2-i2v-flash': unit = .2
        params.update(reference_unit_cny=unit, price_unit='秒' if 'video' in tasks else '张',
                      price_checked_at=PRICE_DATE, price_source='https://platform.minimax.cn/docs/guides/pricing-paygo' if provider=='minimax' else PRICE_URL)
        models.append(dict(provider=provider, model=model, label=label, tasks=tasks,
                           detail=detail, configured=configured[provider], **params))
    for model, label in [('qwen-image-2.0-pro', 'Qwen Image 2.0 Pro'), ('qwen-image-2.0', 'Qwen Image 2.0')]:
        add('dashscope', model, label, ['generate', 'edit'], '百炼 · 图片生成与编辑')
    add('dashscope', 'qwen-image-max', 'Qwen Image Max', ['generate'], '百炼 · 写实与文字表现')
    add('dashscope', 'qwen-image-plus', 'Qwen Image Plus', ['generate'], '百炼 · 图片生成')
    add('dashscope', 'qwen-image-edit-max', 'Qwen Image Edit Max', ['edit'], '百炼 · 精细图片编辑')
    add('dashscope', 'qwen-image-edit-plus', 'Qwen Image Edit Plus', ['edit'], '百炼 · 图片编辑')
    add('minimax', 'image-01', 'MiniMax Image 01', ['generate'], 'MiniMax · 图片生成')
    for model, label in [('MiniMax-H3', 'MiniMax H3'), ('MiniMax-H3-Max', 'MiniMax H3 Max')]:
        add('minimax', model, label, ['video'], 'MiniMax · 首帧 / 多图参考', duration=5, resolution='768P', references=True)
    for model, label in [('MiniMax-Hailuo-2.3', 'Hailuo 2.3'), ('MiniMax-Hailuo-2.3-Fast', 'Hailuo 2.3 Fast'), ('MiniMax-Hailuo-02', 'Hailuo 02')]:
        add('minimax', model, label, ['video'], 'MiniMax · 首帧生成', duration=6, resolution='768P', references=False)
    add('dashscope', 'wan2.2-i2v-flash', 'Wan 2.2 Flash', ['video'], '百炼 · 首帧生成', duration=5, resolution='720P', references=False)
    return models


def resolve(task, provider, model, *, require_key=True):
    option = next((m for m in catalog() if m['provider'] == provider and m['model'] == model and task in m['tasks']), None)
    if not option:
        raise ValueError('所选模型不支持这项任务，请重新选择模型')
    if require_key and not option['configured']:
        raise ValueError('所选模型尚未配置对应的 API Key')
    return option
