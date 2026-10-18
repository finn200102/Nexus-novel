"""Device-file provenance is never manufactured for historical builds."""
# ruff: noqa: F811
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from alembic import command
from sqlalchemy import MetaData,select,inspect
from sqlalchemy.orm import sessionmaker
from app.db_migrations import alembic_config
from config.database import Base
from app.models import User,Library,ReadingProgress,ReadingRunEvent
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.models.reading_progress import ReadingProgressOperation
from app.models.ereader import EpubBuild
from app.services import ereader_identity_service as identity
from tests.database.test_reading_run_migration import run_engine  # noqa: F401
from tests.routes.test_ereader_identity import story


def test_0056_keeps_legacy_files_and_bookmarks_unknown_until_explicit_review(run_engine):
    with run_engine.begin() as connection:command.upgrade(alembic_config(connection),'0055')
    tables=MetaData();tables.reflect(run_engine)
    with run_engine.begin() as connection:
        def add(table,**values):return connection.execute(tables.tables[table].insert().values(**values)).inserted_primary_key[0]
        user=add('users',username='ereader-owner',password='unused',storage_id=str(uuid4()))
        library=add('libraries',name='Private',user_id=user,identity_key=str(uuid4()))
        novel=add('novels',title='Stored original',library_id=library)
        build=add('epub_builds',novel_id=novel,fingerprint='a'*64,partial_md5='b'*32,size_bytes=123,file_name='original.epub',spine=[-2,0,7])
        device=add('kobo_devices',user_id=user,label='Clara',token_hash='c'*64)
        add('kobo_synced_books',device_id=device,novel_id=novel,entitlement_id=str(uuid4()),fingerprint='a'*64,bookmark_source='OEBPS/chapter-3.xhtml',progress_percent=87)
        add('kosync_progress',user_id=user,novel_id=novel,document='b'*32,progress='/DocFragment[3]',percentage=.87)
    with run_engine.begin() as connection:command.upgrade(alembic_config(connection),'0056')
    tables=MetaData();tables.reflect(run_engine)
    with run_engine.connect() as connection:
        value=connection.execute(select(tables.tables['epub_builds'])).mappings().one()
        assert value['id']==build and value['spine']==[-2,0,7] and value['size_bytes']==123
        assert all(value[name] is None for name in ('spine_identity','source_snapshot','owner_storage_id','manifest_epoch','reading_run_key'))
        device=connection.execute(select(tables.tables['kobo_synced_books'])).mappings().one()
        assert device['bookmark_source']=='OEBPS/chapter-3.xhtml' and device['progress_percent']==87
        assert device['confirmed_fingerprint'] is None and device['bookmark_fingerprint'] is None
        assert device['progress_review_reason']=='book_version_confirmation_required'
        point=connection.execute(select(tables.tables['kosync_progress'])).mappings().one()
        assert point['progress']=='/DocFragment[3]' and point['percentage']==.87 and point['progress_review_reason']=='book_identity_unknown'
    with run_engine.begin() as connection:command.downgrade(alembic_config(connection),'0055')
    assert 'spine_identity' not in {column['name'] for column in inspect(run_engine).get_columns('epub_builds')}
    tables=MetaData();tables.reflect(run_engine)
    with run_engine.connect() as connection:
        assert connection.execute(select(tables.tables['epub_builds'].c.file_name)).scalar_one()=='original.epub'
        assert connection.execute(select(tables.tables['kosync_progress'].c.progress)).scalar_one()=='/DocFragment[3]'


def test_duplicate_device_packets_serialize_without_verified_read_or_completion(run_engine,monkeypatch,tmp_path):
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='device-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,rows,built=story(db,library,monkeypatch,tmp_path);ids=user.id,built.build.id
    barrier=Barrier(2)
    def packet(_):
        with sessions() as db:
            build=db.get(EpubBuild,ids[1]);barrier.wait(timeout=10)
            reason=identity.inferred(db,ids[0],build,2,1,operation='same-device-packet');db.commit();return reason
    with ThreadPoolExecutor(max_workers=2) as pool:assert list(pool.map(packet,range(2)))==[None,None]
    with sessions() as db:
        progress=db.query(ReadingProgress).one()
        assert progress.revision==1 and progress.chapter_number==7 and progress.current_identity_inferred
        assert db.query(ReadingProgressOperation).count()==1
        assert db.query(ChapterReadReceipt).count()==0
        assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==0
