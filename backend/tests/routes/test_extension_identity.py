"""Browser capture updates are confined to the originally captured one-page lifecycle."""
# ruff: noqa:F811
import pytest
from datetime import datetime
from sqlalchemy import text
from app.models import Chapter,Novel
from app.models.chapter_manifest import ChapterManifestState
from app.models.chapter_version import ChapterVersion
from app.models.ereader import AppPassword
from app.services import chapter_document
from tests.routes.test_extension import reader,library,basic,make_app_password,STORY_URL  # noqa:F401


def capture(client,auth_headers,reader,library):
    secret=make_app_password(client,auth_headers,'extension');headers=basic(reader.username,secret)
    payload=dict(library_id=library.id,url=STORY_URL,title='Original selected page',html='<p>Private captured original.</p>')
    response=client.post('/ext/capture',headers=headers,json=payload)
    assert response.status_code==201,response.text
    return response.json(),headers,payload


@pytest.mark.parametrize('change',['relinked','multiple','archived','reordered','remote_namespace','unknown_original','bound_metadata'])
def test_unsafe_capture_target_is_never_updated_or_recreated(client,db,auth_headers,reader,library,change):
    first,headers,payload=capture(client,auth_headers,reader,library)
    novel=db.get(Novel,first['novel_id']);chapter=db.query(Chapter).filter_by(novel_id=novel.id).one()
    if change=='relinked':novel.metadata_id=123
    elif change=='multiple':db.add(Chapter(novel_id=novel.id,chapter_number=7,content='A separate actual chapter.'))
    elif change=='archived':chapter.archived=True
    elif change=='reordered':chapter.chapter_number=-2
    elif change=='remote_namespace':novel.site='royalroad'
    elif change=='unknown_original':chapter.source_url=None
    else:
        state=db.query(ChapterManifestState).filter_by(novel_id=novel.id).one();state.metadata_manifest_key='12345678-1234-1234-1234-123456789abc'
    db.commit();before=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id).count()
    response=client.post('/ext/capture',headers=headers,json=payload|{'html':'<p>Must never overwrite an ambiguous original.</p>'})
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='capture_review_required'
    db.refresh(chapter);assert chapter.content=='Private captured original.'
    assert db.query(ChapterVersion).count()==0
    assert db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id).count()==before


@pytest.mark.parametrize('change',['same_pk_replacement','body','topology','account','credential','owner'])
def test_mutation_during_sanitation_is_rechecked_before_any_retained_version_write(client,db,auth_headers,reader,library,monkeypatch,change):
    first,headers,payload=capture(client,auth_headers,reader,library)
    novel_id=first['novel_id'];chapter=db.query(Chapter).filter_by(novel_id=novel_id).one();chapter_id=chapter.id
    actual=chapter_document.from_html
    def during(html):
        doc=actual(html)
        if change=='same_pk_replacement':
            db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':chapter_id});db.commit();db.expunge(chapter)
            replacement=Chapter(id=chapter_id,novel_id=novel_id,chapter_number=1,source_url=STORY_URL,title='Replacement',content='Private captured original.',document=actual('<p>Private captured original.</p>'))
            db.add(replacement)
        elif change=='body':
            row=db.get(Chapter,chapter_id);row.content='Newer concurrent private edit.';row.document=actual('<p>Newer concurrent private edit.</p>')
        elif change=='topology':db.get(Chapter,chapter_id).chapter_number=0
        elif change=='account':reader.is_disabled=True
        elif change=='credential':db.query(AppPassword).filter_by(user_id=reader.id,scope='extension').one().revoked_at=datetime.now()
        else:library.user_id=reader.id+1000
        db.commit();return doc
    monkeypatch.setattr(chapter_document,'from_html',during)
    response=client.post('/ext/capture',headers=headers,json=payload|{'html':'<p>Stale request must not publish.</p>'})
    assert response.status_code in {401,404,409},response.text
    row=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(id=chapter_id).one()
    assert row.content!='Stale request must not publish.' and db.query(ChapterVersion).count()==0


def test_capture_response_has_actual_identity_and_no_external_requests(client,db,auth_headers,reader,library,monkeypatch):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('Private capture must not fetch source/provider/shared metadata')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    first,headers,payload=capture(client,auth_headers,reader,library)
    assert len(first['chapter_key'])==36 and len(first['manifest_epoch'])==36 and len(first['source_version'])==64
    changed=client.post('/ext/capture',headers=headers,json=payload|{'html':'<p>Explicitly updated captured page.</p>'})
    assert changed.status_code==201
    after=changed.json()
    assert after['chapter_key']==first['chapter_key'] and after['manifest_epoch']==first['manifest_epoch'] and after['source_version']!=first['source_version']
    original=db.query(ChapterVersion).one();assert original.chapter_key==first['chapter_key'] and original.content=='Private captured original.'


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_simultaneous_first_capture_never_overwrites_another_accepted_request(tmp_path,monkeypatch,dialect):
    import os
    from uuid import uuid4
    from threading import Barrier
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request
    from fastapi import HTTPException
    from config.database import Base
    from app.models import User,Library
    from app.services import app_password_service
    from app.routers.ext import capture_page,ExtCaptureRequest
    admin=None;schema=None
    if dialect=='postgresql':
        url=os.getenv('NEXUS_TEST_POSTGRES_URL')
        if not url:pytest.skip('Requires owned disposable PostgreSQL; never uses a default/live database')
        options={'connect_timeout':5,'options':'-cstatement_timeout=15000 -clock_timeout=5000'}
        admin=create_engine(url,connect_args=options);schema='extension_capture_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args=options|{'options':options['options']+f' -csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path}/capture-race.db',connect_args={'timeout':10})
    try:
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
        with sessions() as db:
            user=User(username='capture-race-owner',password='unused');db.add(user);db.flush()
            owned=Library(user_id=user.id,name='Private');db.add(owned);db.commit()
            _,secret=app_password_service.create(db,user,'Extension','extension');ids=user.id,owned.id
        barrier=Barrier(2);actual=chapter_document.from_html
        def parsed(html):
            doc=actual(html);barrier.wait(timeout=10);return doc
        monkeypatch.setattr(chapter_document,'from_html',parsed)
        def publish(number):
            with sessions() as db:
                user=db.get(User,ids[0]);request=Request({'type':'http','headers':[(b'authorization',basic(user.username,secret)['Authorization'].encode())]})
                try:return capture_page(ExtCaptureRequest(library_id=ids[1],url=STORY_URL,title=f'Explicit request {number}',html=f'<p>Accepted request {number}.</p>'),request,db,user)
                except HTTPException as exc:db.rollback();return exc
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(publish,[1,2]))
        assert sum(isinstance(row,dict) for row in results)==1
        assert sum(isinstance(row,HTTPException) and row.status_code==409 for row in results)==1
        with sessions() as db:
            assert db.query(Novel).count()==1 and db.query(Chapter).count()==1 and db.query(ChapterVersion).count()==0
            accepted=next(row for row in results if isinstance(row,dict));assert db.query(Chapter).one().chapter_key==accepted['chapter_key']
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
            admin.dispose()


def test_capture_honors_complete_modern_proof_and_rejects_partial_or_stale_identity(client,db,auth_headers,reader,library):
    first,headers,payload=capture(client,auth_headers,reader,library)
    proof=dict(expected_chapter_key=first['chapter_key'],expected_manifest_epoch=first['manifest_epoch'],expected_manifest_revision=first['manifest_revision'],expected_content_version=first['source_version'])
    assert client.post('/ext/capture',headers=headers,json=payload|{'expected_chapter_key':first['chapter_key']}).status_code==409
    assert client.post('/ext/capture',headers=headers,json=payload|proof|{'expected_manifest_epoch':'12345678-1234-1234-1234-123456789abc'}).status_code==409
    response=client.post('/ext/capture',headers=headers,json=payload|proof|{'html':'<p>Modern exact capture update.</p>'})
    assert response.status_code==201 and response.json()['chapter_key']==first['chapter_key']
    assert client.post('/ext/capture',headers=headers,json=payload|proof).status_code==409
    assert db.query(Chapter).one().content=='Modern exact capture update.'
    assert db.query(ChapterVersion).count()==1


@pytest.mark.parametrize('invalid',[{'expected_chapter_key':'unknown'},{'expected_manifest_revision':'01'},{'unexpected_source_override':True},{'library_id':2**100},{'library_id':True}])
def test_capture_rejects_malformed_or_ignored_identity_fields_before_source_mutation(client,db,auth_headers,reader,library,invalid):
    first,headers,payload=capture(client,auth_headers,reader,library)
    response=client.post('/ext/capture',headers=headers,json=payload|invalid)
    assert response.status_code==422,response.text
    assert db.query(Chapter).one().content=='Private captured original.' and db.query(ChapterVersion).count()==0
