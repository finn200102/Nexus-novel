"""Actual metadata service/DTO ASGI responses consumed by the Novel pagination client."""
import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from app.services import metadata_client as client


def test_actual_metadata_service_wire_hash_signed_keysets_revision_and_pk_reuse(tmp_path, monkeypatch):
    metadata_src = Path(__file__).resolve().parents[4] / 'nexus-server' / 'src'
    if not metadata_src.is_dir():
        pytest.skip('Cross-service qualification requires the code-only metadata checkout')
    monkeypatch.syspath_prepend(str(metadata_src))
    pytest.importorskip('aiosqlite', reason='Run cross-service wire qualification using the metadata test runtime')
    pytest.importorskip('greenlet', reason='Run cross-service wire qualification using the metadata test runtime')
    from fastapi import FastAPI, Depends, Query
    from sqlalchemy import update, delete, event
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    import nexus.database.models  # noqa: F401
    from nexus.database.base import Base
    from nexus.database.models.novel import Novel, Chapter
    from nexus.services.chapter_manifest import page, capabilities
    from nexus.schemas.chapter_manifest import ChapterManifestPage, ManifestCapabilities

    async def qualify():
        engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "metadata-wire.db"}')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                db.add(Novel(id=123, title='Synthetic source', novel_site='royalroad', story_id=123,
                    source_url='https://www.royalroad.com/fiction/123',created_at=datetime.now(),updated_at=datetime.now()))
                await db.flush()
                for id, number in [(30,7),(10,-2),(20,0)]:
                    db.add(Chapter(id=id,novel_fk=123,site='royalroad',story_id=123,chapter_id=987000+id,
                        chapter_number=number,title=f'Original {number}',text='Private body must never be selected',
                        rich_html='<p>Private body</p>',created_at=datetime.now(),updated_at=datetime.now()))
                await db.commit()
            observed_sql = []
            @event.listens_for(engine.sync_engine, 'before_cursor_execute')
            def sql(_connection,_cursor,statement,_parameters,_context,_many):
                observed_sql.append(statement)
            app = FastAPI()
            async def database():
                async with sessions() as session:
                    yield session
            # Mount the real metadata service and response DTO directly. The
            # unrelated scraper router imports native bindings not installed in
            # the Novel runtime; no parser stub or replacement is introduced.
            @app.get('/chapters/manifest-capabilities',response_model=ManifestCapabilities)
            async def capability(): return capabilities()
            @app.get('/chapters/novel/{novel_id}/manifest',response_model=ChapterManifestPage)
            async def manifest(novel_id:int,limit:int=Query(1000,ge=1,le=1000),cursor:str|None=None,
                               revision:str|None=None,db=Depends(database)):
                return await page(db,novel_id,limit=limit,cursor=cursor,revision=revision)
            from nexus.api.routers import chapters as gateway
            from nexus.api.deps import get_db as metadata_db
            app.include_router(gateway.router,prefix='/chapters')
            from nexus.api.routers.source_manifests import router as source_router
            from nexus.api.auth import verify_api_key
            app.include_router(source_router,prefix='/chapters')
            app.dependency_overrides[verify_api_key]=lambda: None
            app.dependency_overrides[metadata_db]=database
            def no_source(*args,**kwargs):raise AssertionError('Cached identity-qualified content must never fetch a source')
            monkeypatch.setattr(gateway,'get_source_client',no_source)
            calls = []
            mutate = False
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://metadata.test') as upstream:
                async def request(method,path,**kwargs):
                    nonlocal mutate
                    response = await upstream.request(method,path,params=kwargs.get('params'))
                    calls.append((path,response.status_code))
                    response.raise_for_status()
                    if mutate and path.endswith('/manifest') and 'cursor' not in kwargs.get('params',{}):
                        mutate = False
                        async with sessions() as writer:
                            await writer.execute(update(Chapter).where(Chapter.id==20).values(title='Changed between pages'))
                            await writer.commit()
                    return response
                monkeypatch.setattr(client,'_request',request)
                client.clear_cache()
                first = await client.get_chapter_manifest(123,page_size=1)
                assert [row['chapter_number'] for row in first.items] == [-2,0,7]
                assert [row['id'] for row in first.items] == [10,20,30]
                assert len(calls)==5 and first.total==3
                assert not any('chapters.text' in statement or 'chapters.rich_html' in statement for statement in observed_sql)
                # Body-only downloads neither change topology nor force all pages again.
                async with sessions() as writer:
                    await writer.execute(update(Chapter).where(Chapter.id==10).values(text='Revised body only'))
                    await writer.commit()
                again = await client.get_chapter_manifest(123,page_size=1)
                assert again.revision==first.revision and again.fingerprint==first.fingerprint and len(calls)==8
                client.clear_cache(); mutate = True
                with pytest.raises(client.ChapterManifestError) as conflict:
                    await client.get_chapter_manifest(123,page_size=1)
                assert conflict.value.category=='manifest_changed' and client.cache._cache=={}
                fresh = await client.get_chapter_manifest(123,page_size=1)
                assert fresh.items[1]['title']=='Changed between pages' and fresh.revision!=first.revision
                original_key=fresh.items[-1]['chapter_key']
                # SQLite highest-primary-key reuse must expose a different lifecycle key.
                async with sessions() as writer:
                    await writer.execute(delete(Chapter).where(Chapter.id==30))
                    await writer.flush()
                    writer.add(Chapter(id=30,novel_fk=123,site='royalroad',story_id=123,chapter_id=555,
                        chapter_number=7,title='Replacement',created_at=datetime.now(),updated_at=datetime.now()))
                    await writer.commit()
                replaced = await client.get_chapter_manifest(123,page_size=1)
                assert replaced.items[-1]['id']==30 and replaced.items[-1]['chapter_key']!=original_key
                assert replaced.revision!=fresh.revision
                # Consume the REAL guarded-only endpoint through the Novel
                # client. A stale ordinal resolves the exact immutable key,
                # even when another source chapter now occupies that number.
                original=replaced.items[0]
                payload=await client.fetch_public_chapter_text(123,-2,expected_manifest_key=replaced.manifest_key,expected_chapter_key=original['chapter_key'],expected_source=replaced.source)
                assert payload['text']=='Revised body only' and payload['chapter_key']==original['chapter_key']
                async with sessions() as writer:
                    await writer.execute(update(Chapter).where(Chapter.id==10).values(chapter_number=-9))
                    writer.add(Chapter(id=40,novel_fk=123,site='royalroad',story_id=123,chapter_id=555000,chapter_number=-2,
                        title='Unrelated replacement',text='Never substitute this body',created_at=datetime.now(),updated_at=datetime.now()))
                    await writer.commit()
                moved=await client.fetch_public_chapter_text(123,-2,expected_manifest_key=replaced.manifest_key,expected_chapter_key=original['chapter_key'],expected_source=replaced.source)
                assert moved['chapter_number']==-9 and moved['text']=='Revised body only'
                assert calls[-1][0].endswith('/-2/fetch-by-identity')
                with pytest.raises(httpx.HTTPStatusError) as rejected:
                    await client.fetch_public_chapter_text(123,7,expected_manifest_key=replaced.manifest_key,expected_chapter_key=original_key,expected_source=replaced.source)
                assert rejected.value.response.status_code==409
        finally:
            client.clear_cache()
            await engine.dispose()
    asyncio.run(qualify())
