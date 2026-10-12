"""Read-only local traces, scoped to canonical Hermes session lineage."""
import sqlite3
from fastapi import APIRouter, HTTPException, Query


def routes(traces):
    router = APIRouter()

    @router.get('/traces')
    def trace_page(owner: str = Query(min_length=1, max_length=256),
                   limit: int = Query(default=500, ge=1, le=1000),
                   before: int | None = Query(default=None, ge=1)):
        from hermes_state import SessionDB
        try:
            with SessionDB(db_path=traces.store.home / 'state.db', read_only=True) as db:
                if db.get_session(owner) is None:
                    raise HTTPException(404, '原聊天不存在，无法读取执行轨迹。')
                owners = list(dict.fromkeys([owner] + db.get_compression_lineage(owner)))
            return traces.page(owners, limit, before)
        except (sqlite3.Error, OSError):
            raise HTTPException(503, '轨迹存储暂时不可读取，请稍后刷新。') from None

    return router
