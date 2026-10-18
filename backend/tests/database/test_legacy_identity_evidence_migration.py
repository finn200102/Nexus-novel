"""A pre-UUID FK/hash cannot become new source-lifecycle read evidence."""
import json
import os
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from app.db_migrations import alembic_config
from app.models import User,Chapter,ReadingProgress,ChapterReadReceipt,ReadingAnnotation,ReadingHistory
from app.models.chapter_version import ChapterVersion
from app.services.chapter_document import from_text
from app.services.private_reading_evidence import verified_chapters
from app.services.reading_progress_service import save_reading_progress
from app.services.chapter_identity_service import identity
from app.routers.chapter import spoiler_safe_recap,get_reading_annotations


@pytest.fixture(params=['sqlite','postgresql'])
def legacy_engine(request,tmp_path):
    admin=None;schema=None
    if request.param=='postgresql':
        url=os.environ.get('NEXUS_MANIFEST_TEST_POSTGRES_URL')
        if not url:pytest.skip('Owned nexus_manifest_novel PostgreSQL required')
        assert '/nexus_manifest_novel' in url
        admin=create_engine(url);schema='legacy_evidence_'+uuid4().hex
        with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path/"legacy-identity-evidence.db"}')
    try:yield engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()


@pytest.mark.parametrize('change',['unchanged','reassigned_source','reused_pk'])
def test_migration_preserves_legacy_place_and_notes_without_authorizing_new_identity(legacy_engine,change):
    if change=='reused_pk' and legacy_engine.dialect.name=='postgresql':
        pytest.skip('PostgreSQL FK cascade removes this old receipt; in-place reassignment is covered separately')
    document=from_text('Identical permitted chapter body.');version=document['content_version'];run_key=str(uuid4())
    with legacy_engine.connect() as c:
        command.upgrade(alembic_config(c),'0051');c.commit()
        c.execute(text("INSERT INTO users(id,username,password,storage_id) VALUES(1,'audit','unused',:key)"),{'key':str(uuid4())})
        c.execute(text("INSERT INTO libraries(id,user_id,name) VALUES(1,1,'Private')"))
        c.execute(text("INSERT INTO novels(id,library_id,title) VALUES(1,1,'Private original')"))
        args={'version':version,'doc':json.dumps(document),'body':document['plain_text'],'run':run_key}
        c.execute(text("INSERT INTO chapters(id,novel_id,chapter_number,title,content,document,content_status,audio_status,retry_count,site_chapter_id) VALUES(1,1,1,'Read original',:body,:doc,'PRESENT','MISSING',0,11)"),args)
        c.execute(text("INSERT INTO reading_runs(id,user_id,novel_id,run_key,ordinal,status,requires_run_key,started_at_inferred,completed_at_inferred,progress_snapshot) VALUES(1,1,1,:run,1,'active',false,true,false,'{}')"),args)
        c.execute(text("INSERT INTO reading_progress(user_id,novel_id,chapter_id,chapter_number,position,percent,revision,furthest_chapter_number,furthest_percent,locator_content_version,reading_run_key) VALUES(1,1,1,1,100,100,1,1,100,:version,:run)"),args)
        c.execute(text("INSERT INTO chapter_read_receipts(user_id,chapter_id,content_version,completed,requires_review) VALUES(1,1,:version,true,false)"),args)
        c.execute(text("INSERT INTO reading_history(user_id,novel_id,chapter_number,reading_date,max_percent,reading_run_key) VALUES(1,1,1,'2025-02-14',100,:run)"),args)
        c.execute(text("INSERT INTO chapter_versions(chapter_id,content_version,title,source_url,content,document,byte_count,reason) VALUES(1,:version,'Original version snapshot','https://www.royalroad.com/fiction/11/chapter/11',:body,:doc,200,'source_revision')"),args)
        c.execute(text("INSERT INTO reading_annotations(user_id,novel_id,chapter_id,annotation_type,position,percent,quote,note,locator_content_version,exported_at) VALUES(1,1,1,'note',10,100,'Original source quote','SECRET_FROM_UNBOUND_ORIGINAL',:version,'2025-03-01')"),args)
        if change=='reused_pk':
            assert not c.exec_driver_sql('PRAGMA foreign_keys').scalar()
            c.execute(text('DELETE FROM chapters WHERE id=1'))
            c.execute(text("INSERT INTO chapters(id,novel_id,chapter_number,title,content,document,content_status,audio_status,retry_count,site_chapter_id) VALUES(1,1,1,'SECRET_REPLACEMENT_IDENTITY',:body,:doc,'PRESENT','MISSING',0,999)"),args)
        elif change=='reassigned_source':
            # No FK is broken, even under PostgreSQL's enforced CASCADE rules.
            c.execute(text("UPDATE chapters SET site_chapter_id=999,title='SECRET_REPLACEMENT_IDENTITY' WHERE id=1"))
        c.commit();command.upgrade(alembic_config(c),'head');c.commit()
    with Session(legacy_engine) as db:
        user=db.get(User,1);chapter=db.get(Chapter,1);point=db.query(ReadingProgress).one()
        assert point.chapter_key==point.furthest_chapter_key==chapter.chapter_key
        assert point.current_identity_inferred and point.furthest_identity_inferred
        assert (point.position,point.percent,point.furthest_percent,point.revision)==(100,100,100,1)
        assert point.locator_content_version==version
        assert point.source_content_version is None and point.furthest_content_version is None
        history=db.query(ReadingHistory).one()
        assert history.identity_inferred and history.max_percent==100 and history.reading_date.date().isoformat()=='2025-02-14'
        assert history.verified_percent==0 and history.verified_content_version is None
        # Version snapshots remain reachable for original recovery. This legacy
        # FK association remains inferred provenance, never read authorization.
        original=db.query(ChapterVersion).one()
        assert original.content==document['plain_text'] and original.title=='Original version snapshot'
        assert original.source_url=='https://www.royalroad.com/fiction/11/chapter/11'
        receipt=db.query(ChapterReadReceipt).one()
        assert receipt.completed and receipt.content_version==version and receipt.requires_review and receipt.chapter_key is None
        scope,rows=verified_chapters(db,1,1)
        assert list(rows)==[] and scope.through_chapter is None
        recap=spoiler_safe_recap(1,db,user)
        assert recap['chapters']==[] and recap['annotations']==[]
        note=db.query(ReadingAnnotation).one()
        assert note.note=='SECRET_FROM_UNBOUND_ORIGINAL' and note.locator_content_version==version
        assert note.exported_at.date().isoformat()=='2025-03-01'
        assert note.chapter_key is None and note.chapter_number is None
        exported=get_reading_annotations(1,db,user)
        assert len(exported)==1 and exported[0]['identity_unresolved'] and exported[0]['chapter_number'] is None
        # A new explicit, current-UUID confirmation can authorize the current
        # original; it must still never absorb the unrelated legacy note.
        header=identity(chapter)
        save_reading_progress(db,user_id=1,chapter=chapter,position=0,percent=100,intent='confirm_read',reading_run_key=run_key,
            expected_chapter_key=chapter.chapter_key,expected_manifest_epoch=header['manifest_epoch'],expected_manifest_revision=header['manifest_revision'],
            expected_content_version=version,content_version=version)
        scope,rows=verified_chapters(db,1,1)
        assert [item.chapter_key for item in rows]==[chapter.chapter_key]
        recap=spoiler_safe_recap(1,db,user)
        assert recap['chapters'] and recap['annotations']==[]
        assert db.query(ReadingAnnotation).one().note=='SECRET_FROM_UNBOUND_ORIGINAL'
