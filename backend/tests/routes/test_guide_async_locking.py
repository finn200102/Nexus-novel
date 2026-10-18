"""Actual async ASGI/PostgreSQL regressions for sync row-lock waits."""
import asyncio
import os
from threading import Event
from uuid import uuid4
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from config.database import Base,get_db
from app.auth.dependencies import get_current_user
from app.models import User,Library
from app.routers import discovery,chapter
from tests.routes.test_discovery_story_guide import owned_scope


def test_guide_wait_does_not_block_summary_owner_or_event_loop(monkeypatch):
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='guide_async_'+uuid4().hex
    admin=create_engine(url);engine=None;release=Event();held=Event()
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema} -clock_timeout=1500'})
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        with sessions() as db:
            user=User(username='async-lock-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            novel,_,_,_=owned_scope(db,user,library,numbers=(-3,-2,0),percent=100)
            uid,nid=user.id,novel.id
        app=FastAPI();app.include_router(chapter.router);app.include_router(discovery.router)
        def database():
            with sessions() as db:yield db
        app.dependency_overrides[get_db]=database
        app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(id=uid)
        from app.services import chapter_reading_service
        original=chapter_reading_service.summary
        def delayed_summary(*args,**kwargs):
            result=original(*args,**kwargs)
            held.set()
            assert release.wait(5),'Event loop failed to release the lock owner'
            return result
        monkeypatch.setattr(chapter_reading_service,'summary',delayed_summary)
        upstream_calls=[]
        async def upstream(*args,**kwargs):
            # Guide proof must release its row lock before the network await.
            with sessions() as probe:
                probe.query(User.id).filter_by(id=uid).with_for_update(nowait=True).first()
            upstream_calls.append(kwargs)
            await asyncio.sleep(.02)
            return {'characters':[]}
        monkeypatch.setattr(discovery.metadata_client,'reader_story_guide',upstream)
        async def exercise():
            async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                summary=asyncio.create_task(client.get(f'/chapter/reading-summary/{nid}'))
                assert await asyncio.to_thread(held.wait,3)
                guide=asyncio.create_task(client.get('/discovery/novels/701/story-guide'))
                # This timer is starved by the old synchronous FOR UPDATE on
                # the event loop, so lock_timeout makes that defect fail fast.
                await asyncio.sleep(.08)
                release.set()
                first,second=await asyncio.gather(summary,guide)
                assert first.status_code==200,first.text
                assert second.status_code==200,second.text
                assert second.json()=={'characters':[]}
                assert len(upstream_calls)==1
        asyncio.run(exercise())
    finally:
        release.set()
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()
