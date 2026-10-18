"""Bounded worker: one leased baseline or change page per iteration."""
import asyncio
from fastapi import HTTPException
from config.database import SessionLocal
from app.services import catalog_watch_service as service, catalog_query_client as catalog
from app.logging_config import get_logger

logger=get_logger('catalog_watch_worker')

def begin():
    with SessionLocal() as db:
        claimed=service.claim(db)
        if not claimed:return None
        watch_id,token=claimed
        snap=service.worker_snapshot(db,watch_id,token)
        return (snap,token) if snap else None

def finish(snap,token,data=None,error=None):
    with SessionLocal() as db:
        return service.finish_worker(db,snap,token,data,error=error)

async def run_once():
    item=await asyncio.to_thread(begin)
    if item is None:return False
    snap,token=item
    try:
        if snap['status']=='initializing':
            data=await catalog.request('baseline',{'prepared':snap['prepared'],**snap['baseline'],'limit':500})
        else:
            data=await catalog.request('events',{'prepared':snap['prepared'],'epoch':snap['epoch'],'after_seq':snap['cursor'],'limit':500})
        await asyncio.to_thread(finish,snap,token,data)
    except HTTPException as exc:
        await asyncio.to_thread(finish,snap,token,error='review_required' if exc.status_code in(409,422) else 'unavailable')
    except Exception:
        # No upstream response, private query, provider key or story is logged.
        logger.warning('catalog_watch.page_failed')
        await asyncio.to_thread(finish,snap,token,error='unavailable')
    return True
