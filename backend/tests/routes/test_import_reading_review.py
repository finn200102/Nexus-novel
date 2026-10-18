from copy import deepcopy
from app.models import Chapter,Library,Novel,ReadingProgress,ReadingHistory,ReadingAnnotation,User
from app.models.import_reading_review import ImportReadingReview,ImportReadingOperation
from app.services.chapter_identity_service import source_version
from tests.auth_helpers import bearer_headers


def seed(db,user):
    library=Library(name='Portable',user_id=user.id);db.add(library);db.flush()
    novel=Novel(title='Retained original',url='https://www.royalroad.com/fiction/887766/portable',novel_site='royalroad',library_id=library.id)
    db.add(novel);db.flush()
    chapters=[Chapter(novel_id=novel.id,chapter_number=n,title=f'Original {n}',content=f'Original text {n}') for n in (-2,0,7)]
    db.add_all(chapters);db.commit();return novel,chapters


def document():return {'format':'nexus-user-export','version':1,'libraries':[{'name':'Portable','novels':[{'url':'https://www.royalroad.com/fiction/887766/portable','progress':{'chapter_number':-2,'percent':40,'furthest_chapter_number':0,'furthest_percent':60},'history':[{'chapter_number':0,'date':'2026-10-10','max_percent':100}],'annotations':[{'chapter_number':0,'annotation_type':'note','quote':'Original quote','note':'Private note','block_id':'old-block','locator_content_version':'a'*64}]}]}]}


def stage(client,db,user):
    novel,chapters=seed(db,user);headers=bearer_headers(user.id,db)
    response=client.post('/me/import',headers=headers,json=document());assert response.status_code==200,response.text
    return novel,chapters,headers,response.json()['libraries'][0]['novels'][0]['reading_review_id']


def mapping(review,chapters):
    return [{'ref':item['reference']['ref'],'chapter_key':next(ch.chapter_key for ch in chapters if ch.chapter_number==item['reference']['chapter_number']),'confirm_changed_content':True} for item in review['items']]


def test_legacy_reading_is_durable_unbound_and_reviewed_without_read_receipts(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    assert db.query(ReadingProgress).count()==db.query(ReadingHistory).count()==db.query(ReadingAnnotation).count()==0
    review=client.get(f'/me/import-reading-reviews/{id}',headers=headers);assert review.status_code==200,review.text
    value=review.json();assert value['total']==4 and value['applied']==0
    assert all('same_numeric_label_only' in item['candidates'][0]['evidence'] for item in value['items'])
    request={'expected_revision':value['revision'],'mappings':mapping(value,chapters)}
    preview=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json=request);assert preview.status_code==200,preview.text
    action={'review_token':preview.json()['review_token'],'operation_id':'reviewed-import-once'}
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json=action);assert response.status_code==200,response.text
    progress=db.query(ReadingProgress).one();assert (progress.chapter_number,progress.furthest_chapter_number)==(-2,0)
    assert progress.current_identity_inferred and progress.source_content_version is None
    history=db.query(ReadingHistory).one();assert history.identity_inferred and history.verified_percent==0 and history.verified_content_version is None
    note=db.query(ReadingAnnotation).one();assert note.quote=='Original quote' and note.note=='Private note' and note.block_id is None and note.locator_content_version=='a'*64
    replay=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json=action);assert replay.json()==response.json()
    assert db.query(ReadingHistory).count()==db.query(ReadingAnnotation).count()==db.query(ImportReadingOperation).count()==1


def test_preview_rejects_new_source_version_and_keeps_original_payload(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    review=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()
    preview=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':1,'mappings':mapping(review,chapters)}).json()
    chapters[0].content='A replacement after review';db.commit()
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':preview['review_token'],'operation_id':'stale-review'})
    assert response.status_code==409 and db.query(ReadingProgress).count()==0
    assert db.get(ImportReadingReview,id).payload['annotations'][0]['note']=='Private note'


def test_owner_fences_and_export_preserves_unresolved_material(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    other=User(username='other-import-owner',password='unused');db.add(other);db.commit()
    assert client.get(f'/me/import-reading-reviews/{id}',headers=bearer_headers(other.id,db)).status_code==404
    export=client.get('/me/export',headers=headers).json();assert export['version']==2
    retained=export['libraries'][0]['novels'][0]['pending_reading_imports'];assert len(retained)==1
    assert retained[0]['annotations'][0]['quote']=='Original quote'
    again=client.post('/me/import',headers=headers,json=export);assert again.status_code==200,again.text
    assert db.query(ImportReadingReview).count()==1


def test_unknown_content_requires_explicit_acknowledgement(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    review=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json();choices=mapping(review,chapters)
    choices[0]['confirm_changed_content']=False
    response=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':1,'mappings':choices})
    assert response.status_code==422 and db.query(ReadingProgress).count()==0


def test_v2_exact_owned_epoch_and_content_auto_bind_but_foreign_epoch_does_not(client,db,test_user):
    novel,chapters=seed(db,test_user);headers=bearer_headers(test_user.id,db)
    original=document();story=original['libraries'][0]['novels'][0];story['history']=[];story['annotations']=[]
    original['version']=2
    state=novel.manifest_state
    story['chapter_refs']=[dict(ref=str(n),chapter_key=chapter.chapter_key,manifest_epoch=state.manifest_epoch,chapter_number=chapter.chapter_number,source_version=source_version(chapter)) for n,chapter in enumerate(chapters[:2])]
    story['progress'].update(chapter_ref='0',furthest_chapter_ref='1')
    foreign=deepcopy(original);foreign['libraries'][0]['novels'][0]['chapter_refs'][0]['manifest_epoch']='99999999-9999-4999-8999-999999999999'
    response=client.post('/me/import',headers=headers,json=foreign);assert response.status_code==200,response.text
    assert db.query(ReadingProgress).count()==0
    response=client.post('/me/import',headers=headers,json=original);assert response.status_code==200,response.text
    progress=db.query(ReadingProgress).one();assert progress.chapter_key==chapters[0].chapter_key and progress.furthest_chapter_key==chapters[1].chapter_key
    assert progress.current_identity_inferred and progress.source_content_version is None


def test_old_preview_cannot_bind_after_renumber_and_operation_cannot_change_body(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user);value=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()
    first=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':1,'mappings':mapping(value,chapters)}).json()
    chapters[0].chapter_number=-7;db.commit()
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':first['review_token'],'operation_id':'topology-old'})
    assert response.status_code==409 and db.query(ReadingProgress).count()==0
    assert db.query(ImportReadingOperation).count()==0


def test_review_delete_cascades_private_payload_and_operations(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    # The archive-independent review has a direct story FK, not a chapter FK.
    from app.services.novel_services import delete_novel
    delete_novel(db,novel.id)
    assert db.query(ImportReadingReview).count()==0
    assert client.get(f'/me/import-reading-reviews/{id}',headers=headers).status_code==404


def test_partial_binding_rechecks_prior_body_before_completing_position(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    value=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json();choices=mapping(value,chapters)
    first=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':1,'mappings':choices[:1]}).json()
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':first['review_token'],'operation_id':'partial-first'});assert response.status_code==200,response.text
    assert db.query(ReadingProgress).count()==0
    chapters[0].content='Changed earlier reviewed original';db.commit()
    next_review=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json();assert not next_review['items'][0]['applied']
    second=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':2,'mappings':choices[1:]}).json()
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':second['review_token'],'operation_id':'partial-second'})
    assert response.status_code==409 and db.query(ReadingProgress).count()==0


def test_reference_versions_are_distinct_and_empty_furthest_does_not_become_zero(client,db,test_user):
    novel,chapters=seed(db,test_user);headers=bearer_headers(test_user.id,db)
    db.add(ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_id=chapters[0].id,chapter_key=chapters[0].chapter_key,chapter_number=-2,percent=0,source_content_version=source_version(chapters[0]),furthest_chapter_number=0,furthest_percent=0))
    db.add(ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=chapters[0].id,chapter_key=chapters[0].chapter_key,chapter_number=-2,locator_content_version='a'*64,note='Old edition note'))
    db.commit()
    item=client.get('/me/export',headers=headers).json()['libraries'][0]['novels'][0]
    assert item['progress']['furthest_chapter_ref'] is None and item['progress']['furthest_chapter_number'] is None
    assert item['progress']['chapter_ref']!=item['annotations'][0]['chapter_ref']
    versions={ref['source_version'] for ref in item['chapter_refs'] if ref['chapter_key']==chapters[0].chapter_key}
    assert versions=={'a'*64,source_version(chapters[0])}


def test_existing_place_requires_explicit_keep_and_preserves_both_places(client,db,test_user):
    novel,chapters,headers,id=stage(client,db,test_user)
    db.add(ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_id=chapters[2].id,chapter_key=chapters[2].chapter_key,chapter_number=7,percent=80));db.commit()
    value=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json();body={'expected_revision':1,'mappings':mapping(value,chapters)}
    assert client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json=body).status_code==422
    body['keep_existing_place']=True
    preview=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json=body).json()
    response=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':preview['review_token'],'operation_id':'keep-own-place'});assert response.status_code==200,response.text
    assert db.query(ReadingProgress).one().chapter_number==7
    exported=client.get('/me/export',headers=headers).json()['libraries'][0]['novels'][0]
    assert exported['pending_reading_imports'][0]['progress']['chapter_number']==-2
    assert any('kept the existing reading place' in text for text in client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()['warnings'])


def test_edited_imported_run_snapshot_is_not_overwritten_or_reactivated(client,db,test_user):
    from app.models.reading_run import ReadingRun
    novel,chapters=seed(db,test_user);headers=bearer_headers(test_user.id,db)
    data=document();story=data['libraries'][0]['novels'][0];runkey='44444444-4444-4444-8444-444444444444'
    story['progress']['reading_run_key']=runkey
    story['reading_runs']=[dict(reading_run_key=runkey,ordinal=1,status='active',progress=dict(story['progress']))]
    response=client.post('/me/import',headers=headers,json=data);assert response.status_code==200,response.text
    id=response.json()['libraries'][0]['novels'][0]['reading_review_id']
    run=db.query(ReadingRun).one();run.progress_snapshot={**run.progress_snapshot,'chapter_number':7,'percent':73};db.commit();before=deepcopy(run.progress_snapshot)
    value=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()
    choice=mapping(value,chapters)
    preview=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json={'expected_revision':1,'mappings':choice}).json()
    applied=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json={'review_token':preview['review_token'],'operation_id':'preserve-run-local-edit'});assert applied.status_code==200,applied.text
    db.refresh(run);assert run.progress_snapshot==before and run.archived_at is not None
    assert db.query(ReadingProgress).one().reading_run_key is None


def test_local_epub_json_placeholder_preserves_reading_until_same_original_uploaded(client,db,test_user,monkeypatch):
    import base64,hashlib
    from tests.routes.test_local_epub import book
    from app.models import ImportJob
    from app.models.novel_personal import NovelPersonalData
    from unittest.mock import AsyncMock
    network=AsyncMock(side_effect=AssertionError('No source request permitted'))
    monkeypatch.setattr('app.services.metadata_client.scrape_novel_by_url',network)
    data=book();url='nexus-local:epub:'+hashlib.sha256(data).hexdigest();headers=bearer_headers(test_user.id,db)
    incoming={'format':'nexus-user-export','version':1,'libraries':[{'name':'Private EPUB','novels':[{'url':url,'title':'My private title','progress':{'chapter_number':1,'percent':50},'annotations':[{'chapter_number':1,'note':'Remember this original'}],'personal':{'notes':'Keep my personal notes'}}]}]}
    response=client.post('/me/import',headers=headers,json=incoming);assert response.status_code==200,response.text
    novel=db.query(Novel).filter_by(url=url).one();novel_id=novel.id;library_id=novel.library_id
    assert novel.scrape_status=='awaiting_original' and db.query(Chapter).count()==0 and response.json()['import_job_ids']==[]
    id=response.json()['libraries'][0]['novels'][0]['reading_review_id']
    assert any('upload the same EPUB' in line for line in client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()['warnings'])
    uploaded=client.post('/imports/epub',headers=headers,json={'library_id':library_id,'files':[{'name':'same.epub','data_base64':base64.b64encode(data).decode()}]});assert uploaded.status_code==202,uploaded.text
    db.refresh(novel);assert novel.id==novel_id and novel.scrape_status=='completed' and novel.title=='My private title'
    chapter=db.query(Chapter).filter_by(novel_id=novel.id).one();assert '<strong>new</strong>' in chapter.document['blocks'][1]['html']
    assert db.query(NovelPersonalData).filter_by(novel_id=novel.id).one().notes=='Keep my personal notes'
    assert db.query(ReadingProgress).count()==db.query(ReadingAnnotation).count()==0
    assert db.get(ImportReadingReview,id).payload['annotations'][0]['note']=='Remember this original'
    network.assert_not_awaited()


def test_unknown_private_reference_retained_without_invented_fetch(client,db,test_user):
    data={'format':'nexus-user-export','version':1,'libraries':[{'name':'Private','novels':[{'url':'nexus-local:capture:unavailable-original','title':'Retained private capture','annotations':[{'chapter_number':None,'note':'An unbound original note'}]}]}]}
    headers=bearer_headers(test_user.id,db);response=client.post('/me/import',headers=headers,json=data)
    assert response.status_code==200 and response.json()['import_job_ids']==[]
    novel=db.query(Novel).one();assert novel.scrape_status=='awaiting_original'
    assert db.query(ImportReadingReview).one().payload['annotations'][0]['note']=='An unbound original note'
