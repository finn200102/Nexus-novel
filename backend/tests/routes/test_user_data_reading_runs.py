from copy import deepcopy
from datetime import datetime
from uuid import UUID,uuid4

from app.models import User,Library,Novel,Chapter,ReadingProgress,ReadingHistory,ReadingRun,ReadingRunEvent
from app.schemas.reading_runs import ReadingRunAction
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action,current_run,restore_progress,display_ordinal
from app.services.reading_order import next_unread_chapter
from tests.routes.test_user_data import _seed,_headers,ROYAL_ROAD_URL


def source(client,db,user):
    novel=_seed(db,user)
    chapters=db.query(Chapter).filter_by(novel_id=novel.id).order_by(Chapter.chapter_number).all()
    for chapter in chapters:chapter.content=f'Original chapter {chapter.chapter_number}'
    db.commit()
    finished=save_reading_progress(db,user_id=user.id,chapter=chapters[-1],position=300,percent=100)
    old_key=finished.reading_run_key
    started=action(db,user.id,novel.id,ReadingRunAction(expected_revision=finished.revision,reading_run_key=old_key,operation_id='source-reread'),'start')
    current=save_reading_progress(db,user_id=user.id,chapter=chapters[0],position=12,percent=25,
        reading_run_key=started['current_run_key'],expected_revision=started['revision'])
    document=client.get('/me/export',headers=_headers(user)).json()
    return novel,chapters,current,old_key,document


def target(db,name='portable-target'):
    user=User(username=name,password='unused');db.add(user);db.commit();return user


def payload_novel(document):return next(item for library in document['libraries'] for item in library['novels'] if item['url']==ROYAL_ROAD_URL)


def review_import(client,db,user,response):
    """The test reader explicitly recognizes foreign chapters; numbers alone
    never authorize a production import. New originals simulate finished jobs.
    """
    for library in response.json()['libraries']:
        for imported in library['novels']:
            id=imported.get('reading_review_id')
            if not id:continue
            headers=_headers(user)
            review=client.get(f'/me/import-reading-reviews/{id}',headers=headers).json()
            chapters={row.chapter_number:row for row in db.query(Chapter).filter_by(novel_id=review['novel_id'])}
            mappings=[]
            for item in review['items']:
                ref=item['reference'];number=ref['chapter_number']
                if number is None:continue
                if number not in chapters:
                    chapters[number]=Chapter(novel_id=review['novel_id'],chapter_number=number,title=f'Original chapter {number}',content=f'Original chapter {number}')
                    db.add(chapters[number]);db.flush();db.refresh(chapters[number])
                mappings.append(dict(ref=ref['ref'],chapter_key=chapters[number].chapter_key,confirm_changed_content=True))
            db.commit()
            if not mappings:continue
            prepared=client.post(f'/me/import-reading-reviews/{id}/preview',headers=headers,json=dict(expected_revision=review['revision'],mappings=mappings,keep_existing_place=True))
            assert prepared.status_code==200,prepared.text
            applied=client.post(f'/me/import-reading-reviews/{id}/apply',headers=headers,json=dict(review_token=prepared.json()['review_token'],operation_id=f'test-reviewed-import-{id}-{review["revision"]}'))
            assert applied.status_code==200,applied.text


def test_portable_runs_restore_new_destination_and_same_file_is_idempotent(client,db,test_user):
    novel,chapters,current,old_key,document=source(client,db,test_user)
    exported=payload_novel(document)
    assert exported['progress']['reading_run_key']==current.reading_run_key
    assert len(exported['reading_runs'])==2
    assert {point['reading_run_key'] for point in exported['history']}=={old_key,current.reading_run_key}
    destination=target(db)
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200
    report=response.json();assert report['summary']['reading_runs_added']==2 and report['summary']['reading_current_restored']==0
    assert db.query(ReadingProgress).filter_by(user_id=destination.id).count()==0
    review_import(client,db,destination,response)
    restored=db.query(ReadingProgress).filter_by(user_id=destination.id).one()
    assert restored.novel_id!=novel.id and restored.reading_run_key!=current.reading_run_key
    # This legacy source position has no captured body version, so its pixel
    # offset stays in the private review rather than attaching to new text.
    assert exported['progress']['position']==12
    assert (restored.chapter_number,restored.percent,restored.position,restored.revision)==(1,25,0,1)
    rows=db.query(ReadingRun).filter_by(user_id=destination.id).all()
    assert {display_ordinal(row) for row in rows}=={1,2}
    assert all(UUID(row.run_key) for row in rows)
    completed=[row for row in rows if row.completed_at is not None or row.completed_at_inferred]
    assert len(completed)==1 and display_ordinal(completed[0])==1
    before=(db.query(ReadingRun).count(),db.query(ReadingRunEvent).count(),db.query(ReadingHistory).count())
    repeat=client.post('/me/import',headers=_headers(destination),json=document)
    assert repeat.status_code==200 and repeat.json()['summary']['reading_runs_added']==0 and repeat.json()['summary']['history_added']==0
    assert before==(db.query(ReadingRun).count(),db.query(ReadingRunEvent).count(),db.query(ReadingHistory).count())
    db.refresh(restored);assert restored.revision==1
    # Snapshot metadata survives actual saves and explicit finish/drop/archive.
    local_chapter=db.query(Chapter).filter_by(novel_id=restored.novel_id,chapter_number=1).one()
    db.info.pop('authenticated_session',None)
    saved=save_reading_progress(db,user_id=destination.id,chapter=local_chapter,position=15,percent=30,
        reading_run_key=restored.reading_run_key,expected_revision=1)
    run=current_run(db,destination.id,restored.novel_id,saved)
    assert run.progress_snapshot['_portable_ordinal']==2
    state=action(db,destination.id,restored.novel_id,ReadingRunAction(expected_revision=saved.revision,
        reading_run_key=saved.reading_run_key,operation_id='finish-imported'),'finish')
    db.refresh(run);assert run.progress_snapshot['_portable_ordinal']==2
    assert state['items'][0]['ordinal']==2


def test_existing_current_run_and_deleted_row_recovery_ignore_new_import_archives(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    destination=target(db)
    local=_seed(db,destination)
    first=db.query(Chapter).filter_by(novel_id=local.id,chapter_number=1).one();first.content='Local story';db.commit()
    db.info.pop('authenticated_session',None)
    progress=save_reading_progress(db,user_id=destination.id,chapter=first,position=7,percent=10)
    original=(progress.reading_run_key,progress.revision,progress.chapter_number,progress.percent)
    expected_next=next_unread_chapter(db,destination.id,local).chapter_number
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200 and response.json()['summary']['reading_current_restored']==0
    db.refresh(progress);assert (progress.reading_run_key,progress.revision,progress.chapter_number,progress.percent)==original
    archived=db.query(ReadingRun).filter(ReadingRun.user_id==destination.id,ReadingRun.run_key!=progress.reading_run_key).all()
    assert len(archived)==2 and all(run.archived_at is not None for run in archived)
    assert max(run.ordinal for run in archived)>current_run(db,destination.id,local.id,progress).ordinal
    before_next=next_unread_chapter(db,destination.id,local)
    assert before_next.chapter_number==expected_next  # imported archives cannot advance this run
    key,revision=progress.reading_run_key,progress.revision
    db.query(ReadingProgress).filter_by(id=progress.id).delete(synchronize_session=False);db.commit();db.expunge(progress)
    recovered=current_run(db,destination.id,local.id)
    assert recovered.run_key==key and restore_progress(recovered).revision==revision
    # Every new local ordinal considers imported archives too, avoiding collision.
    state=action(db,destination.id,local.id,ReadingRunAction(expected_revision=revision,reading_run_key=key,operation_id='after-import-reread'),'start')
    fresh=db.query(ReadingRun).filter_by(run_key=state['current_run_key']).one()
    assert fresh.ordinal>max(run.ordinal for run in archived)


def test_native_reimport_never_rewrites_live_run_or_adds_duplicate_completion(client,db,test_user):
    novel,chapters,current,_,document=source(client,db,test_user)
    before=(db.query(ReadingRun).count(),db.query(ReadingRunEvent).count(),db.query(ReadingHistory).count())
    altered=deepcopy(document);entry=payload_novel(altered)
    entry['progress']['chapter_number']=3;entry['progress']['percent']=100
    entry['history'].append(dict(chapter_number=3,date='2026-10-16',max_percent=100,reading_run_key=current.reading_run_key))
    response=client.post('/me/import',headers=_headers(test_user),json=altered)
    assert response.status_code==200 and response.json()['libraries'][0]['novels'][0]['progress']=='review_required'
    assert before==(db.query(ReadingRun).count(),db.query(ReadingRunEvent).count(),db.query(ReadingHistory).count())
    db.refresh(current);assert current.chapter_number==1 and current.percent==25


def test_cross_account_uuid_collision_is_remapped_and_unknown_run_reference_rejected(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    destination=target(db)
    first=client.post('/me/import',headers=_headers(destination),json=document)
    assert first.status_code==200
    source_keys={row.run_key for row in db.query(ReadingRun).filter_by(user_id=test_user.id)}
    destination_keys={row.run_key for row in db.query(ReadingRun).filter_by(user_id=destination.id)}
    assert source_keys.isdisjoint(destination_keys)
    invalid=deepcopy(document);payload_novel(invalid)['history'][0]['reading_run_key']=str(uuid4())
    assert client.post('/me/import',headers=_headers(destination),json=invalid).status_code==422


def test_inferred_legacy_completion_stays_undated_after_portable_import(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    entry=payload_novel(document);run=entry['reading_runs'][0]
    run['started_at']=None;run['started_at_inferred']=True;run['completed_at']=None;run['completed_at_inferred']=True
    run['events']=[dict(kind='started',occurred_at=None,inferred=True),dict(kind='completed',occurred_at=None,inferred=True)]
    destination=target(db)
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200 and response.json()['summary']['reading_run_inferred_events_added']>=2
    completed=db.query(ReadingRunEvent).filter_by(user_id=destination.id,kind='completed').one()
    assert completed.occurred_at is None and completed.inferred is True


def test_archive_only_import_does_not_become_current_and_first_local_save_allocates_free_ordinal(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    payload_novel(document)['progress']=None
    destination=target(db)
    result=client.post('/me/import',headers=_headers(destination),json=document)
    assert result.status_code==200 and result.json()['summary']['reading_current_restored']==0
    local=db.query(Novel).join(Library).filter(Library.user_id==destination.id,Novel.url==ROYAL_ROAD_URL).one()
    assert current_run(db,destination.id,local.id) is None and db.query(ReadingProgress).filter_by(user_id=destination.id).count()==0
    chapter=Chapter(novel_id=local.id,chapter_number=5,title='First actual',content='Local story')
    db.add(chapter);db.commit()
    current=save_reading_progress(db,user_id=destination.id,chapter=chapter,position=0,percent=10)
    run=current_run(db,destination.id,local.id,current)
    assert run.ordinal==3 and run.run_key==current.reading_run_key and not run.requires_run_key
    assert display_ordinal(run)==3


def test_uuid_owned_by_another_story_is_not_reused_as_authority(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    destination=target(db)
    library=Library(user_id=destination.id,name='Other library');db.add(library);db.flush()
    foreign=Novel(library_id=library.id,title='Different private story');db.add(foreign);db.flush()
    key=str(uuid4())
    foreign_run=ReadingRun(user_id=destination.id,novel_id=foreign.id,run_key=key,ordinal=1,progress_snapshot={'private_marker':'untouched'})
    db.add(foreign_run);db.commit()
    entry=payload_novel(document);old=entry['reading_runs'][0]['reading_run_key'];entry['reading_runs'][0]['reading_run_key']=key
    for point in entry['history']:
        if point.get('reading_run_key')==old:point['reading_run_key']=key
    result=client.post('/me/import',headers=_headers(destination),json=document)
    assert result.status_code==200
    db.refresh(foreign_run);assert foreign_run.progress_snapshot=={'private_marker':'untouched'}
    imported=db.query(ReadingRun).filter(ReadingRun.user_id==destination.id,ReadingRun.novel_id!=foreign.id).all()
    assert len(imported)==2 and all(run.run_key!=key for run in imported)


def test_export_recovers_canonical_current_after_progress_row_was_lost(client,db,test_user):
    _,_,current,_,_=source(client,db,test_user)
    key=current.reading_run_key;revision=current.revision
    db.query(ReadingProgress).filter_by(id=current.id).delete(synchronize_session=False);db.commit();db.expunge(current)
    document=client.get('/me/export',headers=_headers(test_user)).json()
    entry=payload_novel(document)
    assert entry['progress']['reading_run_key']==key and entry['progress']['percent']==25
    destination=target(db)
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200 and response.json()['summary']['reading_current_restored']==0
    review_import(client,db,destination,response)
    assert db.query(ReadingProgress).filter_by(user_id=destination.id).one().percent==25


def test_fresh_reread_zero_furthest_and_locator_survive_export_restore(client,db,test_user):
    novel,chapters,current,_,_=source(client,db,test_user)
    started=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=current.revision,
        reading_run_key=current.reading_run_key,operation_id='fresh-unread-reread'),'start')
    document=client.get('/me/export',headers=_headers(test_user)).json()
    incoming=payload_novel(document)['progress']
    assert incoming['furthest_chapter_number'] is None and incoming['furthest_percent']==0
    destination=target(db)
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200
    review_import(client,db,destination,response)
    restored=db.query(ReadingProgress).filter_by(user_id=destination.id).one()
    assert restored.furthest_chapter_number==0 and restored.furthest_percent==0 and restored.percent==0
    assert restored.chapter_number==started['first_chapter_number']
    for field in ('position','block_id','text_offset','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant'):
        assert getattr(restored,field)==incoming[field]


def test_deleted_progress_next_unread_uses_current_reread_snapshot_not_lifetime_history(client,db,test_user):
    novel,chapters,current,_,_=source(client,db,test_user)
    started=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=current.revision,
        reading_run_key=current.reading_run_key,operation_id='deleted-reread-position'),'start')
    row=db.query(ReadingProgress).filter_by(user_id=test_user.id,novel_id=novel.id).one()
    db.delete(row);db.commit()
    assert current_run(db,test_user.id,novel.id).run_key==started['current_run_key']
    assert next_unread_chapter(db,test_user.id,novel).id==chapters[0].id


def test_existing_archive_only_import_can_restore_designated_current_when_still_empty(client,db,test_user):
    _,_,_,_,document=source(client,db,test_user)
    archive=deepcopy(document);payload_novel(archive)['progress']=None
    destination=target(db)
    assert client.post('/me/import',headers=_headers(destination),json=archive).status_code==200
    response=client.post('/me/import',headers=_headers(destination),json=document)
    assert response.status_code==200 and response.json()['summary']['reading_current_restored']==0
    review_import(client,db,destination,response)
    assert response.json()['summary']['reading_runs_added']==0
    assert db.query(ReadingProgress).filter_by(user_id=destination.id).one().percent==25
