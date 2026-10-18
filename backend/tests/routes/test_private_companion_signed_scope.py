"""Adversarial outbound evidence checks for signed/private reading scopes."""
import json
import pytest
from app.models import Chapter,Novel,ReaderProvider,StoryGlossary,ReadingProgress
from app.services.chapter_document import from_text
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action
from app.schemas.reading_runs import ReadingRunAction


@pytest.fixture
def signed_reread(db,test_user,test_library,monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings,'ANALYSIS_ENGINE_URL','http://analysis.invalid')
    monkeypatch.setattr(settings,'ANALYSIS_ENGINE_API_KEY','synthetic-test-key')
    novel=Novel(library_id=test_library.id,title='Signed private memory');db.add(novel);db.flush()
    chapters={}
    for number,label in ((-3,'SAFE_NEGATIVE'),(-2,'FUTURE_PARTIAL'),(0,'FUTURE_ZERO'),(7,'FUTURE_SEVEN')):
        doc=from_text(f'ALICE {label} knows only this chapter fact.')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=label,content=doc['plain_text'],document=doc)
        db.add(chapter);db.flush();chapters[number]=chapter
    provider=ReaderProvider(user_id=test_user.id,name='Local fixture',kind='local',base_url='http://local-reader.invalid/v1',model='fixture')
    db.add(provider);db.commit()
    for chapter in chapters.values():
        point=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=100,content_version=chapter.document['content_version'])
    started=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=point.revision,reading_run_key=point.reading_run_key,operation_id='signed-private-reread'),'start')
    key=started['current_run_key']
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[-3],position=0,percent=100,reading_run_key=key,content_version=chapters[-3].document['content_version'])
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[-2],position=0,percent=40,reading_run_key=key,content_version=chapters[-2].document['content_version'])
    prompts=[]
    def model(_db,_provider,*,prompt,**kwargs):
        value=json.loads(prompt);prompts.append(value)
        evidence=value['evidence'][0]
        return json.dumps({'answer':'Only confirmed facts.','citations':[{'chapter':evidence['chapter'],'block_id':evidence['block_id'],'quote':evidence['text'][:24]}]}),1,1,0
    monkeypatch.setattr('app.services.reader_provider.invoke',model)
    return novel,chapters,provider,key,prompts


def ask(client,headers,data,through=None):
    novel,chapters,provider,key,prompts=data
    body={'provider_id':provider.id,'question':'What does ALICE know?'}
    if through is not None:body['through_chapter']=through
    return client.post(f'/reader/companion/{novel.id}/questions',headers=headers,json=body)


def test_negative_partial_cannot_widen_old_future_zero_or_seven_receipts(client,db,test_user,auth_headers,signed_reread):
    response=ask(client,auth_headers,signed_reread,7)
    assert response.status_code==200,response.text
    assert response.json()['through_chapter']==-3
    prompts=signed_reread[-1]
    assert len(prompts)==1 and prompts[0]['through_chapter']==-3
    assert {row['chapter'] for row in prompts[0]['evidence']}=={-3}
    serialized=json.dumps(prompts[0])
    assert 'SAFE_NEGATIVE' in serialized and 'FUTURE_' not in serialized
    recap=client.get(f'/chapter/recap/{signed_reread[0].id}',headers=auth_headers)
    assert recap.status_code==200 and recap.json()['spoiler_boundary_chapter']==-3
    assert [row['number'] for row in recap.json()['chapters']]==[-3]
    assert 'FUTURE_' not in recap.text


def test_read_zero_is_real_zero_and_skipped_partial_remains_excluded(client,db,test_user,auth_headers,signed_reread):
    novel,chapters,provider,key,prompts=signed_reread
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[0],position=0,percent=100,reading_run_key=key,content_version=chapters[0].document['content_version'])
    response=ask(client,auth_headers,signed_reread,0)
    assert response.status_code==200 and response.json()['through_chapter']==0
    assert {row['chapter'] for row in prompts[0]['evidence']}=={-3,0}
    assert 'FUTURE_PARTIAL' not in json.dumps(prompts[0]) and 'FUTURE_SEVEN' not in json.dumps(prompts[0])
    before=ask(client,auth_headers,signed_reread,-4)
    assert before.status_code==200 and before.json()['through_chapter'] is None and len(prompts)==1


@pytest.mark.parametrize('mutation',['rich_revision','stale_plain','requires_review','missing_checkpoint'])
def test_revised_or_unapproved_current_read_material_never_reaches_model(client,db,test_user,auth_headers,signed_reread,mutation):
    from app.models import ChapterReadReceipt,ReadingHistory
    novel,chapters,provider,key,prompts=signed_reread
    first=chapters[-3]
    if mutation=='rich_revision':first.document=from_text('ALICE NEW_UNREAD_VERSION has unseen secrets.');first.content=first.document['plain_text']
    elif mutation=='stale_plain':first.content='ALICE NEW_UNREAD_VERSION differs from approved document.'
    elif mutation=='requires_review':db.query(ChapterReadReceipt).filter_by(chapter_id=first.id).one().requires_review=True
    else:
        db.query(ReadingHistory).filter_by(novel_id=novel.id,reading_run_key=key,chapter_number=-3).delete()
        # Remove the saved furthest/current synthetic checkpoint for that row.
        point=db.query(ReadingProgress).filter_by(novel_id=novel.id).one();point.furthest_chapter_number=-2;point.furthest_percent=40
    db.commit()
    response=ask(client,auth_headers,signed_reread,7)
    assert response.status_code==200 and response.json()['through_chapter'] is None
    assert response.json()['citations']==[] and prompts==[]


def test_reread_cache_cannot_reuse_previous_run_and_deleted_progress_stays_empty(client,db,test_user,auth_headers,signed_reread):
    novel,chapters,provider,key,prompts=signed_reread
    first=ask(client,auth_headers,signed_reread)
    assert first.status_code==200 and len(prompts)==1
    point=db.query(ReadingProgress).filter_by(novel_id=novel.id).one()
    action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=point.revision,reading_run_key=key,operation_id='again-empty'),'start')
    db.query(ReadingProgress).filter_by(novel_id=novel.id).delete();db.commit()
    empty=ask(client,auth_headers,signed_reread)
    assert empty.status_code==200 and empty.json()['through_chapter'] is None and len(prompts)==1


def test_manual_glossary_remains_manageable_before_reading_and_signed_entries_work(client,db,test_user,test_library,auth_headers):
    novel=Novel(library_id=test_library.id,title='Manual terminology');db.add(novel);db.commit()
    from app.models.chapter import ContentStatus
    from app.services.chapter_identity_service import identity
    floors=[]
    for number,source in ((-3,'Prologue name'),(0,'Legacy global term'),(7,'Future name')):
        document=from_text(f'{source} appears in this original.')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=source,content=document['plain_text'],document=document,content_status=ContentStatus.PRESENT)
        db.add(chapter);floors.append((chapter,source))
    db.commit()
    for chapter,source in floors:
        proof=identity(chapter)
        response=client.post(f'/reader/glossary/{novel.id}',headers=auth_headers,json={
            'source':source,'target':'Preferred term','language':'de','through_chapter':chapter.chapter_number,
            **{f'expected_{key}':proof[key] for key in ('chapter_key','manifest_epoch','manifest_revision')},
            'expected_content_version':chapter.document['content_version']})
        assert response.status_code==200,response.text
    assert db.query(ReadingProgress).filter_by(novel_id=novel.id).count()==0
    visible=client.get(f'/reader/glossary/{novel.id}?language=de&through_chapter=0',headers=auth_headers)
    assert visible.status_code==200 and set(visible.json())=={'Prologue name','Legacy global term'}
    assert db.query(StoryGlossary).filter_by(novel_id=novel.id).count()==3


def test_new_reading_during_inference_discards_prior_answer_without_cache(client,db,test_user,auth_headers,signed_reread,monkeypatch):
    from app.models import CompanionAnswer
    novel,chapters,provider,key,prompts=signed_reread
    def model(_db,_provider,*,prompt,**kwargs):
        value=json.loads(prompt);prompts.append(value)
        point=db.query(ReadingProgress).filter_by(novel_id=novel.id).one()
        action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=point.revision,reading_run_key=key,operation_id='during-model'),'start')
        row=value['evidence'][0]
        return json.dumps({'answer':'OLD RUN MUST NOT RETURN','citations':[{'chapter':row['chapter'],'block_id':row['block_id'],'quote':row['text'][:24]}]}),1,1,0
    monkeypatch.setattr('app.services.reader_provider.invoke',model)
    response=ask(client,auth_headers,signed_reread)
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='reading_run_changed'
    assert 'OLD RUN MUST NOT RETURN' not in response.text and not db.query(CompanionAnswer).count()


def test_private_evidence_postgresql_signed_receipt_and_json_projection():
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models import User,Library,ReadingHistory
    from app.services.private_reading_evidence import verified_chapters
    from tests.routes.test_discovery_story_guide import owned_scope
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='private_companion_'+uuid4().hex
    admin=create_engine(url);engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='private-evidence-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private evidence');db.add(library);db.flush()
            novel,chapters,run,point=owned_scope(db,user,library,numbers=(-3,-2,0),percent=40)
            db.query(ReadingHistory).filter_by(novel_id=novel.id,reading_run_key=run.run_key,chapter_number=-2).update({'max_percent':40});db.commit()
            scope,rows=verified_chapters(db,user.id,novel.id)
            assert [row.chapter_number for row in rows]==[-3] and scope.through_chapter==-3
            scope,rows=verified_chapters(db,user.id,novel.id,-4)
            assert list(rows)==[] and scope.through_chapter is None
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def test_recap_loads_only_twelve_verified_chapters_not_an_entire_read_library(client,db,test_user,auth_headers,signed_reread):
    from datetime import datetime
    from sqlalchemy import event
    from app.models import ReadingHistory,ChapterReadReceipt
    novel,chapters,provider,key,prompts=signed_reread
    for number in range(20,40):
        document=from_text(f'ALICE verified scene {number}.')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=f'Known {number}',content=document['plain_text'],document=document)
        db.add(chapter);db.flush();db.refresh(chapter)
        db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,reading_run_key=key,chapter_number=number,
            chapter_key=chapter.chapter_key,identity_inferred=False,verified_content_version=document['content_version'],verified_percent=100,
            reading_date=datetime(2026,1,1),max_percent=100))
        db.add(ChapterReadReceipt(user_id=test_user.id,chapter_id=chapter.id,content_version=document['content_version'],completed=True,requires_review=False))
    db.commit();bodies=[]
    def observe(conn,cursor,statement,params,context,many):
        if 'chapters.content AS chapters_content' in statement and 'WHERE chapters.id =' in statement:bodies.append(statement)
    event.listen(db.bind,'before_cursor_execute',observe)
    try:response=client.get(f'/chapter/recap/{novel.id}',headers=auth_headers)
    finally:event.remove(db.bind,'before_cursor_execute',observe)
    assert response.status_code==200,response.text
    assert response.json()['spoiler_boundary_chapter']==39
    assert [row['number'] for row in response.json()['chapters']]==list(range(28,40))
    assert len(bodies)==12 and prompts==[]


def test_concurrent_revocation_fences_preloaded_permission_even_with_explicit_consent(monkeypatch):
    """Real account lock: a newer denial wins over a stale loaded grant."""
    import os
    from uuid import uuid4
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from config.database import Base
    from app.models import User,Library
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.routers.reader_tools import question,QuestionInput,set_story_permission,StoryPermissionInput
    from tests.routes.test_discovery_story_guide import owned_scope
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='private_revoke_'+uuid4().hex
    admin=create_engine(url);engine=None
    locked=Event();release=Event();loaded=Event();begin=Event();outbound=[]
    monkeypatch.setattr('app.services.reader_provider.invoke',lambda *a,**k:outbound.append(k))
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine,expire_on_commit=False)
        with sessions() as db:
            user=User(username='permission-race',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            novel,_,_,_=owned_scope(db,user,library,numbers=(-3,-2,0),percent=40)
            provider=ReaderProvider(user_id=user.id,name='Paid fixture',kind='openai_compatible',base_url='https://provider.invalid/v1',model='fixture')
            db.add(provider);db.flush()
            db.add(StoryProcessingPermission(user_id=user.id,novel_id=novel.id,provider_id=provider.id,companion=True,translation=False,ao3_consent=True));db.commit()
            uid,nid,pid=user.id,novel.id,provider.id
        def request():
            with sessions() as db:
                user=db.get(User,uid)
                # Hold a reference so populate_existing must refresh identity-map data.
                prior=db.query(StoryProcessingPermission).filter_by(user_id=uid).one()
                assert prior.companion is True
                loaded.set();assert begin.wait(5)
                try:question(nid,QuestionInput(provider_id=pid,question='What does ALICE know?',external_consent=True,ao3_consent=True),db,user)
                except HTTPException as exc:return exc.status_code,exc.detail,prior.companion
                raise AssertionError('Revoked request unexpectedly succeeded')
        def revoke():
            with sessions() as db:
                user=db.get(User,uid)
                db.query(User.id).filter_by(id=uid).with_for_update().first()
                locked.set();assert release.wait(5)
                return set_story_permission(nid,pid,StoryPermissionInput(companion=False),db,user)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending=pool.submit(request);assert loaded.wait(5)
            revoking=pool.submit(revoke);assert locked.wait(5);begin.set()
            try:
                from concurrent.futures import TimeoutError
                with pytest.raises(TimeoutError):pending.result(timeout=.15)
            finally:release.set()
            assert revoking.result(timeout=5)['companion'] is False
            status,detail,refreshed=pending.result(timeout=5)
            assert status==422 and 'blocked' in detail and refreshed is False
        assert outbound==[]
    finally:
        release.set();begin.set()
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()
