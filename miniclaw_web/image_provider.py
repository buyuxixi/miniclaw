"""App-owned DashScope adapter; no second planner or Agent loop."""
import base64
import io
import os
import re
from urllib.parse import urlsplit

import httpx
from PIL import Image

MAX_RESULT = 5 * 1024 * 1024


def settings():
    return {
        'key': os.environ.get('DASHSCOPE_API_KEY', '').strip(),
        'base': os.environ.get('MINICLAW_IMAGE_BASE_URL', 'https://dashscope.aliyuncs.com').rstrip('/'),
        'model': os.environ.get('MINICLAW_IMAGE_MODEL', 'qwen-image-edit-max'),
    }


def provider_status():
    cfg = settings()
    return {'configured': bool(cfg['key']), 'provider': 'dashscope', 'model': cfg['model']}


def checked_endpoint(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or not re.fullmatch(r'(?:dashscope(?:-intl|-us)?\.aliyuncs\.com|[a-zA-Z0-9-]+\.(?:cn-beijing|ap-southeast-1|us-east-1)\.maas\.aliyuncs\.com)', parsed.hostname or '')):
        raise ValueError('请在后端配置百炼官方HTTPS服务地址')
    return value.rstrip('/')


def checked_result_url(value):
    if not isinstance(value, str):
        raise ValueError('图像服务未返回有效图片地址')
    parsed = urlsplit(value)
    host = parsed.hostname or ''
    # Only the provider's OSS result host; never arbitrary URLs supplied by a model.
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not re.fullmatch(r'[a-zA-Z0-9-]+\.oss-[a-zA-Z0-9-]+\.aliyuncs\.com', host)):
        raise ValueError('图像服务返回的下载域名不在允许范围内')
    return value


def edit_image(raw, mime, prompt, client_factory=httpx.Client):
    cfg = settings()
    if not cfg['key']:
        raise ValueError('未配置百炼DASHSCOPE_API_KEY；本地修图仍可使用')
    endpoint = checked_endpoint(cfg['base'])
    payload = {
        'model': cfg['model'],
        'input': {'messages': [{'role': 'user', 'content': [
            {'image': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode('ascii')},
            {'text': prompt},
        ]}]},
        'parameters': {'n': 1, 'watermark': False, 'prompt_extend': False},
    }
    # No automatic retry: a timeout can still mean the provider charged the request.
    try:
        with client_factory(timeout=httpx.Timeout(90, connect=10), follow_redirects=False, trust_env=False) as client:
            response = client.post(endpoint + '/api/v1/services/aigc/multimodal-generation/generation',
                                   headers={'Authorization': 'Bearer ' + cfg['key']}, json=payload)
            if response.status_code != 200:
                raise ValueError(f'百炼图像编辑失败（HTTP {response.status_code}），请核对Key、地域与模型权限')
            try:
                body = response.json()
            except ValueError:
                raise ValueError('百炼返回了无法解析的结果') from None
            if body.get('code'):
                raise ValueError('百炼返回失败，请核对模型配置与服务额度')
            images = [item['image'] for choice in body.get('output', {}).get('choices', [])
                      for item in choice.get('message', {}).get('content', []) if 'image' in item]
            if not images:
                raise ValueError('百炼未返回图片结果')
            url = checked_result_url(images[0])
            # Deliberately do not forward the API credential to OSS.
            with client.stream('GET', url, timeout=30) as downloaded:
                if downloaded.status_code != 200:
                    raise ValueError('修图结果下载失败')
                data = bytearray()
                for chunk in downloaded.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESULT:
                        raise ValueError('修图结果超过5 MiB，请选择较小输出')
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 20_000_000 or image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError('修图结果格式或尺寸不支持')
            image.load()
            output = io.BytesIO()
            image.save(output, 'PNG')
        if output.tell() > MAX_RESULT:
            raise ValueError('修图结果转换后超过5 MiB')
        return output.getvalue(), body.get('request_id')
    except (httpx.HTTPError, OSError, KeyError, TypeError):
        # Do not expose URL query signatures, raw service bodies or credentials.
        raise ValueError('图像服务连接或结果读取失败；不会自动重试，云端可能已计费') from None
