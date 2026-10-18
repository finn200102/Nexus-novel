from decimal import Decimal
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from app.models import Chapter, User, Library
from app.models.translation import TranslationJob, StoryGlossary
from app.models.story_processing_permission import StoryProcessingPermission
from app.services import translation_batch_service as service
from config.settings import settings
from tests.routes.test_reader_tools import story, provider


def setup(client,db,library,headers,monkeypatch):
    novel,first,second=story(db,library)
    provider_id=provider(client,headers,monkeypatch)
    request=dict(chapter_ids=[first.id,second.id],provider_id=provider_id,language='de')
    def forbidden(*args,**kwargs):raise AssertionError('Batch routes must never invoke a provider')
    monkeypatch.setattr('app.services.translation_service.invoke',forbidden)
    monkeypatch.setattr('app.services.reader_provider.direct_request',forbidden)
    return novel,first,second,request



def approved_term(db,user,novel,chapter,source,target):
    from app.services.glossary_identity_service import upsert
    from app.services.chapter_identity_service import identity,source_version
    upsert(db,user.id,novel.id,source=source,target=target,language='de',through_chapter=chapter.chapter_number,
        expected_content_version=source_version(chapter),**{f'expected_{key}':value for key,value in identity(chapter).items()})


def url(novel):return f'/reader/stories/{novel.id}/translation-batch'


def test_review_is_read_only_then_explicit_queue_is_deduplicated(client,db,test_library,auth_headers,monkeypatch):
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    listing=client.get(f'/reader/stories/{novel.id}/translation-chapters?offset=1&limit=1',headers=auth_headers)
    assert listing.status_code==200 and listing.json()['total']==2
    assert listing.json()['items'][0]['id']==second.id and listing.json()['items'][0]['downloaded']
    assert listing.headers['cache-control']=='private, no-store'
    preview=client.post(url(novel)+'/preview',headers=auth_headers,json=request)
    assert preview.status_code==200
    result=preview.json();assert result['queueable']==2 and result['estimated_max_usd']==0 and result['permission']['allowed']
    assert db.query(TranslationJob).count()==0
    payload={**request,'review_token':result['review_token']}
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json=payload)
    assert queued.status_code==202 and queued.json()['queued']==2
    assert all(row['outcome']=='queued' for row in queued.json()['items'])
    replay=client.post(url(novel)+'/jobs',headers=auth_headers,json=payload)
    assert replay.status_code==202 and replay.json()['queued']==0
    assert all(row['outcome']=='already_queued' for row in replay.json()['items'])
    assert db.query(TranslationJob).count()==2


@pytest.mark.parametrize('change',['source','provider','glossary','pricing','budget','permission'])
def test_changed_review_inputs_require_fresh_review_before_any_queue(client,db,test_user,test_library,auth_headers,monkeypatch,change):
    from app.models.translation import ReaderProvider
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    result=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    configured=db.get(ReaderProvider,request['provider_id'])
    if change=='source':first.content='A changed chapter.'
    elif change=='provider':configured.model='new-model'
    elif change=='glossary':approved_term(db,test_user,novel,first,'Alice','Alicia')
    elif change=='pricing':configured.input_price=Decimal('1.25')
    elif change=='budget':configured.budget_microusd=123456
    elif change=='permission':db.add(StoryProcessingPermission(user_id=test_user.id,novel_id=novel.id,provider_id=configured.id,translation=False))
    db.commit()
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':result['review_token']})
    assert queued.status_code==409 and 'changed' in queued.json()['detail']
    assert db.query(TranslationJob).count()==0


def test_mixed_chapters_keep_individual_outcomes_and_failed_jobs_require_retry(client,db,test_library,auth_headers,monkeypatch):
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    token=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()['review_token']
    client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':token})
    jobs=db.query(TranslationJob).order_by(TranslationJob.id).all()
    jobs[0].status='completed';jobs[0].translated_blocks=jobs[0].source_blocks
    jobs[1].status='failed';jobs[1].error='Existing failure'
    third=Chapter(novel_id=novel.id,chapter_number=3,title='Unavailable')
    fourth=Chapter(novel_id=novel.id,chapter_number=4,title='Available',content='Another chapter.')
    db.add_all([third,fourth]);db.commit()
    request['chapter_ids'] += [third.id,fourth.id]
    review=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert [row['outcome'] for row in review['items']]==['already_ready','needs_retry','unavailable','ready_to_queue']
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':review['review_token']}).json()
    assert queued['queued']==1 and db.query(TranslationJob).count()==3
    db.refresh(jobs[1]);assert jobs[1].status=='failed' and jobs[1].error=='Existing failure'


def test_paid_batch_respects_aggregate_budget_permissions_and_ao3_consent(client,db,test_library,auth_headers,monkeypatch):
    from app.models.translation import ReaderProvider
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    configured=db.get(ReaderProvider,request['provider_id'])
    configured.kind='openai_compatible';configured.base_url='https://example.test/v1'
    configured.secret_ciphertext='ciphertext-not-read';configured.input_price=Decimal('1');configured.output_price=Decimal('1');configured.budget_microusd=1_000_000
    novel.url='https://archiveofourown.org/works/123';db.commit()
    blocked=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert blocked['permission']['allowed'] is False and blocked['queueable']==0
    request['external_consent']=True
    blocked=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert blocked['permission']['is_ao3'] and 'AO3' in blocked['permission']['error']
    request['ao3_consent']=True
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert reviewed['permission']['allowed'] and reviewed['estimated_max_usd']>0 and reviewed['queueable']==2
    estimate=round(reviewed['estimated_max_usd']*1_000_000)
    configured.budget_microusd=estimate-1;db.commit()
    blocked=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert blocked['queueable']==0 and all(row['outcome']=='blocked' for row in blocked['items'])
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':blocked['review_token']}).json()
    assert queued['queued']==0 and db.query(TranslationJob).count()==0
    configured.budget_microusd=1_000_000;db.commit()
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':reviewed['review_token']})
    assert queued.status_code==202 and queued.json()['queued']==2
    assert configured.reserved_microusd==0 and configured.used_microusd==0
    assert all(job.provider_snapshot['authorization']['ao3'] for job in db.query(TranslationJob))


def test_unicode_glossary_dedupe_and_future_entries_do_not_change_review(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    db.add(StoryGlossary(user_id=test_user.id,novel_id=novel.id,source='Castle',target='Schlösschen',language='de',through_chapter=1));db.commit()
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    db.add(StoryGlossary(user_id=test_user.id,novel_id=novel.id,source='Secret',target='Spoiler',language='de',through_chapter=99));db.commit()
    payload={**request,'review_token':reviewed['review_token']}
    assert client.post(url(novel)+'/jobs',headers=auth_headers,json=payload).json()['queued']==2
    assert client.post(url(novel)+'/jobs',headers=auth_headers,json=payload).json()['queued']==0
    assert all('Secret' not in job.glossary for job in db.query(TranslationJob))


def test_review_credentials_and_bounds_fail_closed(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    token=reviewed['review_token']
    claims=jwt.decode(token,settings.SECRET_KEY,algorithms=[settings.ALGORITHM]);claims['exp']=datetime.now(timezone.utc)-timedelta(seconds=1)
    expired=jwt.encode(claims,settings.SECRET_KEY,algorithm=settings.ALGORITHM)
    for invalid in (expired,token+'tampered'):
        assert client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':invalid}).status_code==409
    assert client.post(url(novel)+'/jobs',headers=auth_headers,json=request).status_code==422
    assert client.post(url(novel)+'/preview',json=request).status_code==401
    for ids in ([],[first.id,first.id],[True],list(range(1,202))):
        assert client.post(url(novel)+'/preview',headers=auth_headers,json={**request,'chapter_ids':ids}).status_code==422
    assert client.post(url(novel)+'/preview',headers=auth_headers,json={**request,'chapter_ids':[999999]}).status_code==404
    monkeypatch.setattr(service,'MAX_BYTES',1)
    assert client.post(url(novel)+'/preview',headers=auth_headers,json=request).status_code==422
    assert db.query(TranslationJob).count()==0


@pytest.mark.parametrize('mutation',['source','provider','permission','glossary'])
def test_changed_item_between_commits_is_not_silently_queued(client,db,test_user,test_library,auth_headers,monkeypatch,mutation):
    from app.models.translation import ReaderProvider
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    original=service._enqueue_snapshot
    def enqueue(*args,**kwargs):
        result=original(*args,**kwargs)
        if result[0].chapter_id==first.id:
            if mutation=='source':second.content='Changed after the first commit.'
            elif mutation=='provider':db.get(ReaderProvider,request['provider_id']).model='changed-model'
            elif mutation=='permission':db.add(StoryProcessingPermission(user_id=test_user.id,novel_id=novel.id,provider_id=request['provider_id'],translation=False))
            elif mutation=='glossary':approved_term(db,test_user,novel,second,'Name','New name')
            db.commit()
        return result
    monkeypatch.setattr(service,'_enqueue_snapshot',enqueue)
    response=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':reviewed['review_token']})
    assert response.status_code==202
    assert response.json()['queued']==1 and response.json()['items'][0]['outcome']=='queued'
    assert response.json()['items'][1]['outcome']=='review_changed'
    assert db.query(TranslationJob).count()==1


def test_postgres_batch_review_queue_and_dedupe_queries(monkeypatch):
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models.translation import ReaderProvider
    from app.schemas.translation_batches import TranslationBatchSelection, TranslationBatchSubmission
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Set NEXUS_TEST_POSTGRES_URL to an owned disposable PostgreSQL database')
    schema='translation_batch_'+uuid4().hex
    admin=create_engine(url)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://batch-fixture:8020/v1')
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='pg-batch-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.commit()
            novel,first,second=story(db,library)
            provider=ReaderProvider(user_id=user.id,name='Local',kind='local',base_url='http://batch-fixture:8020/v1',model='fixture')
            db.add(provider);db.commit()
            selection=TranslationBatchSelection(chapter_ids=[first.id,second.id],provider_id=provider.id,language='de')
            listing=service.chapter_list(db,user.id,novel.id,1,1)
            assert listing['total']==2 and listing['items'][0]['id']==second.id
            review=service.preview(db,user,novel.id,selection)
            assert review['queueable']==2 and db.query(TranslationJob).count()==0
            submission=TranslationBatchSubmission(**selection.model_dump(),review_token=review['review_token'])
            assert service.submit(db,user,novel.id,submission)['queued']==2
            assert service.submit(db,user,novel.id,submission)['queued']==0
            assert db.query(TranslationJob).count()==2
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_translation_only_permission_preserves_unset_companion_and_shared_consent(client,db,test_user,test_library,auth_headers,monkeypatch):
    from app.models.translation import ReaderProvider
    from app.services import processing_permissions
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    configured=db.get(ReaderProvider,request['provider_id']);configured.kind='openai_compatible';configured.base_url='https://example.test/v1'
    novel.url='https://archiveofourown.org/works/123';db.commit()
    endpoint=f'/reader/permissions/{novel.id}/{configured.id}/translation'
    assert client.patch(endpoint,headers=auth_headers,json={'translation':True}).status_code==422
    grant=client.patch(endpoint,headers=auth_headers,json={'translation':True,'ao3_consent':True})
    assert grant.status_code==200 and grant.json()['companion'] is None and grant.json()['ao3_consent']
    row=db.query(StoryProcessingPermission).one();assert row.companion is None
    # Unset requires a separate explicit companion request; it is not a denial.
    with pytest.raises(PermissionError):processing_permissions.check(db,test_user.id,novel,configured,'companion')
    processing_permissions.check(db,test_user.id,novel,configured,'companion',consent=True)
    revoke=client.patch(endpoint,headers=auth_headers,json={'translation':False})
    assert revoke.status_code==200 and revoke.json()['companion'] is None and revoke.json()['ao3_consent']
    row.companion=False;db.commit()
    client.patch(endpoint,headers=auth_headers,json={'translation':True,'ao3_consent':True})
    db.refresh(row);assert row.companion is False
    with pytest.raises(PermissionError):processing_permissions.check(db,test_user.id,novel,configured,'companion',consent=True)
    row.companion=True;db.commit()
    client.patch(endpoint,headers=auth_headers,json={'translation':False})
    db.refresh(row);assert row.companion is True and row.ao3_consent is True


def test_translation_permission_revoke_cancels_only_its_jobs(client,db,test_library,auth_headers,monkeypatch):
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    review=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':review['review_token']})
    jobs=db.query(TranslationJob).order_by(TranslationJob.id).all()
    jobs[0].status='processing';jobs[0].lease_owner='current-worker';jobs[1].status='completed';db.commit()
    endpoint=f"/reader/permissions/{novel.id}/{request['provider_id']}/translation"
    assert client.patch(endpoint,headers=auth_headers,json={'translation':False}).status_code==200
    db.expire_all();assert jobs[0].status=='cancelled' and jobs[0].lease_owner is None and jobs[1].status=='completed'
    assert client.patch(endpoint,json={'translation':True}).status_code==401
    assert client.patch(f'/reader/permissions/{novel.id}/999999/translation',headers=auth_headers,json={'translation':True}).status_code==404


def test_batch_created_variant_uses_existing_paragraph_resume_worker(client,db,test_library,auth_headers,monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.services.translation_service import process_translation
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    first.content='First paragraph.\n\nSecond paragraph.';db.commit()
    request['chapter_ids']=[first.id]
    review=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    queued=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':review['review_token']}).json()
    job_id=queued['items'][0]['job_id']
    calls=[]
    def interrupted(*args,**kwargs):
        calls.append(kwargs['prompt'])
        if len(calls)==2:raise ValueError('Local fixture interrupted')
        return 'Erster Absatz.',1,2,0
    monkeypatch.setattr('app.services.translation_service.invoke',interrupted)
    process_translation(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(TranslationJob,job_id)
    assert job.status=='failed' and len(job.translated_blocks)==1
    repeat=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert repeat['items'][0]['outcome']=='needs_retry' and repeat['items'][0]['job_id']==job_id
    assert client.post(f'/reader/translation-jobs/{job_id}',headers=auth_headers,json={'action':'retry'}).status_code==200
    resumed=[]
    def finish(*args,**kwargs):resumed.append(kwargs['prompt']);return 'Zweiter Absatz.',1,2,0
    monkeypatch.setattr('app.services.translation_service.invoke',finish)
    process_translation(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='completed' and [block['text'] for block in job.translated_blocks]==['Erster Absatz.','Zweiter Absatz.']
    assert len(resumed)==1 and 'Second paragraph.' in resumed[0] and 'First paragraph.' not in resumed[0]


@pytest.mark.parametrize('counter,exhaust_budget',[('used_microusd',False),('reserved_microusd',False),('used_microusd',True),('reserved_microusd',True)])
def test_earlier_approved_work_can_update_usage_without_invalidating_later_static_review(client,db,test_library,auth_headers,monkeypatch,counter,exhaust_budget):
    from app.models.translation import ReaderProvider
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    configured=db.get(ReaderProvider,request['provider_id'])
    configured.kind='openai_compatible';configured.base_url='https://example.test/v1'
    configured.secret_ciphertext='ciphertext-not-read';configured.input_price=Decimal('1');configured.output_price=Decimal('1');configured.budget_microusd=1_000_000
    db.commit();request['external_consent']=True
    reviewed=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    assert reviewed['queueable']==2 and reviewed['estimated_max_usd']<1
    original=service._enqueue_snapshot
    def enqueue(*args,**kwargs):
        result=original(*args,**kwargs)
        if result[0].chapter_id==first.id:
            current=db.get(ReaderProvider,request['provider_id'])
            setattr(current,counter,current.budget_microusd if exhaust_budget else 1)
            db.commit()
        return result
    monkeypatch.setattr(service,'_enqueue_snapshot',enqueue)
    response=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':reviewed['review_token']})
    assert response.status_code==202
    body=response.json()
    assert body['items'][0]['outcome']=='queued'
    if exhaust_budget:
        assert body['queued']==1 and body['items'][1]['outcome']=='blocked'
        assert 'budget' in body['items'][1]['error'] and db.query(TranslationJob).count()==1
    else:
        assert body['queued']==2 and body['items'][1]['outcome']=='queued'
        assert db.query(TranslationJob).count()==2


def test_usage_change_before_review_submission_still_requires_new_review(client,db,test_library,auth_headers,monkeypatch):
    from app.models.translation import ReaderProvider
    novel,first,second,request=setup(client,db,test_library,auth_headers,monkeypatch)
    review=client.post(url(novel)+'/preview',headers=auth_headers,json=request).json()
    configured=db.get(ReaderProvider,request['provider_id']);configured.used_microusd=1;db.commit()
    response=client.post(url(novel)+'/jobs',headers=auth_headers,json={**request,'review_token':review['review_token']})
    assert response.status_code==409 and db.query(TranslationJob).count()==0
