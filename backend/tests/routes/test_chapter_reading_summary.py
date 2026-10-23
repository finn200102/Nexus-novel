"""Actual ordinals and run checkpoints, never chapter numbers as counts."""
from datetime import datetime
from uuid import uuid4
import pytest
from sqlalchemy import event
from app.models import Chapter,Novel,ReadingHistory,ReadingProgress,ReadingRun,User,Library,NovelPersonalData
from app.services.reading_order import next_unread_chapter
from app.services import chapter_reading_service as service
from app.services.reading_run_service import snapshot_progress


@pytest.fixture
def indexed(db,test_user,test_library):
    novel=Novel(library_id=test_library.id,title='Gapped story',chapter_count=100)
    db.add(novel);db.flush();chapters=[]
    for number in (-3,0,3,7,11):
        row=Chapter(novel_id=novel.id,chapter_number=number,title=f'Scene {number}',category='side_story' if number==-3 else 'story',content='PRIVATE BODY',document={'large':'PRIVATE DOCUMENT'})
        db.add(row);db.flush();db.refresh(row);chapters.append(row)
    run=ReadingRun(user_id=test_user.id,novel_id=novel.id,run_key=str(uuid4()),ordinal=1,status='active',requires_run_key=True,started_at=datetime(2026,1,1),progress_snapshot={})
    db.add(run);db.flush()
    point=ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_id=chapters[3].id,chapter_number=7,percent=40,position=0,furthest_chapter_number=11,furthest_percent=60,reading_run_key=run.run_key,revision=4)
    point.chapter_key=chapters[3].chapter_key;point.furthest_chapter_key=chapters[4].chapter_key
    point.current_identity_inferred=True;point.furthest_identity_inferred=1
    db.add(point)
    for number in (0,3):db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_number=number,
        chapter_key=next(row.chapter_key for row in chapters if row.chapter_number==number),identity_inferred=True,
        reading_run_key=run.run_key,reading_date=datetime(2026,1,1),max_percent=100))
    db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_number=11,reading_run_key=str(uuid4()),reading_date=datetime(2025,1,1),max_percent=100))
    db.commit();run.progress_snapshot=snapshot_progress(run,point);db.commit()
    return novel,chapters,run,point


def test_actual_ordinals_counts_markers_private_wire(client,db,test_user,auth_headers,indexed):
    novel,chapters,run,point=indexed
    response=client.get(f'/chapter/reading-summary/{novel.id}',headers=auth_headers)
    assert response.status_code==200,response.text
    value=response.json()
    assert response.headers['cache-control']=='private, no-store'
    assert value['total_chapters']==5 and value['followed_total']==4
    assert value['current']==dict(chapter_id=chapters[3].id,chapter_number=7,ordinal=4,followed_ordinal=3,percent=40)
    assert value['completed_chapters']==value['followed_completed_chapters']==2
    assert value['next_unread_chapter_number']==7 and not value['completed_reading']
    assert value['reading_run_key']==run.run_key and value['revision']==4
    assert value['categories']==['side_story','story'] and not value['categories_truncated']
    page=client.get(f'/chapter/reading-chapters/{novel.id}?offset=2&limit=2',headers=auth_headers)
    assert page.status_code==200,page.text
    body=page.json()
    assert body['total']==5 and [row['chapter_number'] for row in body['items']]==[3,7]
    assert [row['ordinal'] for row in body['items']]==[3,4]
    assert [row['completed_checkpoint'] for row in body['items']]==[True,False]
    assert 'PRIVATE BODY' not in page.text and 'PRIVATE DOCUMENT' not in page.text


def test_negative_zero_new_insert_not_range_inferred(db,test_user,indexed):
    novel,chapters,run,point=indexed
    db.add(NovelPersonalData(user_id=test_user.id,novel_id=novel.id,followed_categories=['story','side_story']));db.commit()
    assert next_unread_chapter(db,test_user.id,novel).chapter_number==-3
    db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_number=-3,reading_run_key=run.run_key,reading_date=datetime(2026,1,1),max_percent=95));db.commit()
    assert next_unread_chapter(db,test_user.id,novel).chapter_number==7
    new=Chapter(novel_id=novel.id,chapter_number=2,title='New earlier chapter',category='story');db.add(new);db.commit()
    assert next_unread_chapter(db,test_user.id,novel).id==new.id
    value=service.summary(db,test_user.id,novel.id)
    assert value['completed_chapters']==3 and value['total_chapters']==6 and value['current']['ordinal']==5
    assert not next(row for row in service.page(db,test_user.id,novel.id,0,100)['items'] if row['id']==new.id)['completed_checkpoint']


def test_search_filter_keep_global_ordinals_and_unknown_marks(db,test_user,indexed):
    novel,chapters,run,point=indexed
    page=service.page(db,test_user.id,novel.id,0,2,'Scene 11','followed')
    assert page['total']==1 and page['items'][0]['ordinal']==5 and page['items'][0]['followed_ordinal']==4
    assert not page['items'][0]['completed_checkpoint'] and page['items'][0]['max_percent']==60
    assert service.page(db,test_user.id,novel.id,0,2,'%','all')['total']==0
    row=service.page(db,test_user.id,novel.id,0,2,'-3','all')['items'][0]
    assert row['max_percent'] is None and row['followed_ordinal'] is None


def test_deleted_current_restore_keeps_run_revision_not_fake_ordinal(db,test_user,indexed):
    novel,chapters,run,point=indexed;key=run.run_key
    db.delete(point);db.delete(chapters[3]);db.commit()
    value=service.summary(db,test_user.id,novel.id)
    assert value['reading_run_key']==key and value['revision']==4
    assert value['current']==dict(chapter_id=None,chapter_number=7,ordinal=None,followed_ordinal=None,percent=40)
    assert value['total_chapters']==4 and value['completed_chapters']==2


def test_book_completion_does_not_fill_missing_chapter_checkpoints(db,test_user,indexed):
    from app.services.reading_continuity_service import complete
    novel,chapters,run,point=indexed
    complete(db,run);db.commit()
    value=service.summary(db,test_user.id,novel.id)
    assert value['completed_reading'] and value['completed_chapters']==2


def test_foreign_missing_empty_private_routes(client,db,auth_headers):
    user=User(username='other-index-owner',password='unused');db.add(user);db.flush()
    library=Library(user_id=user.id,name='Foreign');db.add(library);db.flush()
    novel=Novel(library_id=library.id,title='Foreign');db.add(novel);db.commit()
    for route in ('reading-summary','reading-chapters'):
        for id in (novel.id,999999):assert client.get(f'/chapter/{route}/{id}',headers=auth_headers).status_code==404
        assert client.get(f'/chapter/{route}/{novel.id}').status_code==401


def test_twenty_thousand_plus_count_without_body_load(db,test_user,indexed):
    novel,*_=indexed
    db.bulk_insert_mappings(Chapter,[dict(novel_id=novel.id,chapter_number=100+number,title=f'Extra {number}',category='story') for number in range(20005)])
    db.commit();queries=[]
    def observe(conn,cursor,statement,params,context,many):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',observe)
    try:value=service.summary(db,test_user.id,novel.id);page=service.page(db,test_user.id,novel.id,20000,10)
    finally:event.remove(db.bind,'before_cursor_execute',observe)
    assert value['total_chapters']==20010 and page['total']==20010 and len(page['items'])==10
    assert page['items'][-1]['ordinal']==20010
    assert not any('chapters.content AS chapters_content' in query or 'chapters.document AS chapters_document' in query for query in queries)


def test_fresh_reread_ignores_prior_checkpoints_and_preserves_explicit_zero(db,test_user,indexed):
    from app.services.reading_run_service import action
    from app.schemas.reading_runs import ReadingRunAction
    novel,chapters,run,point=indexed
    result=action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=4,operation_id='summary-reread',reading_run_key=run.run_key),'start')
    value=service.summary(db,test_user.id,novel.id)
    assert value['completed_chapters']==0 and value['next_unread_chapter_number']==0
    assert value['reading_run_key']==result['current_run_key'] and value['revision']==5
    assert value['current']['chapter_number']==0 and value['current']['ordinal']==2
    assert not any(row['completed_checkpoint'] for row in service.page(db,test_user.id,novel.id,0,100)['items'])


def test_renumbered_current_fk_resolves_actual_ordinal_and_no_revised_text_proof(db,test_user,indexed):
    novel,chapters,run,point=indexed
    point.percent=100;point.furthest_chapter_number=7;point.furthest_percent=100
    point.furthest_chapter_key=chapters[3].chapter_key
    chapters[3].chapter_number=8;chapters[3].content='Revised prose not proven by a positional checkpoint'
    db.commit()
    value=service.summary(db,test_user.id,novel.id)
    assert value['current']['chapter_number']==8 and value['current']['ordinal']==4
    assert value['completed_chapters']==3 and value['completion_basis']=='recorded_checkpoints'
    assert next(row for row in service.page(db,test_user.id,novel.id,0,100)['items'] if row['id']==chapters[3].id)['completed_checkpoint']
    # This explicitly historical-number/position mark must never be reused as
    # a current-version read receipt by companion/guide evidence checks.
    from app.models import ChapterReadReceipt
    assert not db.query(ChapterReadReceipt).filter_by(chapter_id=chapters[3].id).count()


def test_normalized_categories_and_page_bounds(client,db,test_user,auth_headers,indexed):
    novel,chapters,run,point=indexed
    chapters[2].category=' ';chapters[3].category=' STORY ';db.commit()
    value=service.summary(db,test_user.id,novel.id)
    assert value['followed_total']==4 and value['categories']==['side_story','story']
    row=next(row for row in service.page(db,test_user.id,novel.id,0,100)['items'] if row['id']==chapters[2].id)
    assert row['followed'] and row['category']=='story' and row['followed_ordinal']==2
    for query in ('limit=201','offset=-1','category_scope=invalid','q='+'x'*201):
        assert client.get(f'/chapter/reading-chapters/{novel.id}?{query}',headers=auth_headers).status_code==422


def test_postgresql_actual_aggregates_union_windows_and_identity():
    """Qualify native SQL on a uniquely namespaced disposable PostgreSQL."""
    import os
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='reading_summary_'+uuid4().hex
    admin=create_engine(url)
    engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='summary-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Fixture');db.add(library);db.flush()
            novel=Novel(library_id=library.id,title='PostgreSQL gapped fixture');db.add(novel);db.flush()
            chapters=[]
            for number in (0,3,7,11):
                chapter=Chapter(novel_id=novel.id,chapter_number=number,title=f'Event {number}',category='story',content='Never load this text')
                db.add(chapter);db.flush();chapters.append(chapter)
            run=ReadingRun(user_id=user.id,novel_id=novel.id,run_key=str(uuid4()),ordinal=1,status='active',requires_run_key=True,progress_snapshot={})
            db.add(run);db.flush()
            point=ReadingProgress(user_id=user.id,novel_id=novel.id,chapter_id=chapters[2].id,chapter_number=7,percent=40,
                furthest_chapter_number=11,furthest_percent=60,revision=8,reading_run_key=run.run_key)
            db.add(point)
            for number in (0,3):db.add(ReadingHistory(user_id=user.id,novel_id=novel.id,chapter_number=number,reading_run_key=run.run_key,reading_date=datetime(2026,1,1),max_percent=100))
            db.commit()
            value=service.summary(db,user.id,novel.id)
            assert value['completed_chapters']==2 and value['current']['ordinal']==3 and value['revision']==8
            assert value['next_unread_chapter_number']==7
            page=service.page(db,user.id,novel.id,1,2,'','followed')
            assert page['total']==4 and [row['ordinal'] for row in page['items']]==[2,3]
            assert [row['completed_checkpoint'] for row in page['items']]==[True,False]
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def test_range_filters_actual_numbers_before_paging_and_preserves_private_scope(client,auth_headers,indexed,db):
    novel,chapters,run,point=indexed
    response=client.get(f'/chapter/reading-chapters/{novel.id}?from_chapter=-3&to_chapter=3&offset=1&limit=1',headers=auth_headers)
    assert response.status_code==200,response.text
    assert response.json()['total']==3
    assert [row['chapter_number'] for row in response.json()['items']]==[0]
    assert 'PRIVATE BODY' not in response.text
    invalid=client.get(f'/chapter/reading-chapters/{novel.id}?from_chapter=3&to_chapter=0',headers=auth_headers)
    assert invalid.status_code==422
    owner=User(username='range-other',password='unused')
    db.add(owner);db.flush();library=Library(user_id=owner.id,name='Other')
    db.add(library);db.flush();other=Novel(library_id=library.id,title='Private other')
    db.add(other);db.commit()
    denied=client.get(f'/chapter/reading-chapters/{other.id}?from_chapter=0&to_chapter=3',headers=auth_headers)
    assert denied.status_code==404
