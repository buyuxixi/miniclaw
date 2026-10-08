"""Keep the original 9170 link useful, preserving its browser project selection."""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
@app.get('/{path:path}')
def redirect(path:str):
    return HTMLResponse('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>正在恢复创作项目</title><p>正在打开你的创作项目…</p><script>
    let workspace='';try{workspace=JSON.parse(localStorage.getItem('video-workspace-03')||'{}').workspaceId||'';}catch{}
    const destination=new URL('http://127.0.0.1:9120/studio/index.html');
    if(workspace)destination.searchParams.set('workspace',workspace);
    location.replace(destination.href);
    </script></html>''')
if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=9170,access_log=False)
