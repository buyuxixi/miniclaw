"""MiniMax image-to-video protocol; credentials stay in the backend."""
import os
from urllib.parse import urlsplit

MODELS={'MiniMax-Hailuo-2.3','MiniMax-Hailuo-2.3-Fast','MiniMax-Hailuo-02'}
PRICE_URL='https://platform.minimax.cn/docs/guides/pricing-paygo'

def configuration():
    key=(os.environ.get('MINIMAX_API_KEY') or os.environ.get('MINIMAX_API') or '').strip()
    base=os.environ.get('MINIMAX_API_BASE','https://api.minimax.cn/v1').rstrip('/')
    if base not in ('https://api.minimax.cn/v1','https://api.minimaxi.com/v1','https://api.minimax.io/v1'):
        raise ValueError('MiniMax 服务地址必须是官方 HTTPS API')
    model=os.environ.get('MINICLAW_VIDEO_MINIMAX_MODEL','MiniMax-Hailuo-2.3')
    if model not in MODELS: raise ValueError('MiniMax 视频模型配置无效')
    return {'key':key,'base':base,'model':model}

def public_status():
    cfg=configuration()
    return {'provider':'minimax','configured':bool(cfg['key']),'model':cfg['model'],'duration':6,
            'output_duration':5,'resolution':'768P','reference_cny':None,'price_source':PRICE_URL,
            'notice':'生成6秒，截取前5秒作为片段；按完整6秒计费，金额待账单核对'}

def checked_download(value):
    if not isinstance(value,str):raise ValueError('MiniMax 下载地址无效')
    p=urlsplit(value);host=p.hostname or ''
    official_cdn=host in ('public-cdn-video-data-algeng.oss-cn-wulanchabu.aliyuncs.com',
                         'algeng-video-infer.oss-cn-shanghai.aliyuncs.com')
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or not (official_cdn or any(host==domain or host.endswith('.'+domain) for domain in ('minimax.io','minimax.cn','minimaxi.com','minimax.chat','hailuoai.com'))):
        raise ValueError('MiniMax 下载地址不是官方域名')
    return value

def checked_body(response):
    if response.status_code!=200:raise ValueError('MiniMax API 请求未成功')
    body=response.json()
    if body.get('base_resp',{}).get('status_code')!=0:raise ValueError('MiniMax API 拒绝请求，请核对权限或余额')
    return body
