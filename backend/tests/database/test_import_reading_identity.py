import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.orm import Session
from app.db_migrations import alembic_config
from app.models import User,Library,Novel,Chapter
from app.models.import_reading_review import ImportReadingOperation
from app.schemas.user_data import ExportNovel
from app.schemas.import_reading_review import ImportReadingPreviewInput,ImportReadingApplyInput
from app.services import import_reading_review_service as service


def migrate(engine,revision):
    with engine.connect() as connection:
        command.upgrade(alembic_config(connection),revision);connection.commit()


def test_0055_upgrade_keeps_pending_material_and_refuses_lossy_downgrade(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path}/portable.db')
    migrate(engine,'0054');migrate(engine,'0055')
    assert {'import_reading_reviews','import_reading_operations'}<=set(inspect(engine).get_table_names())
    with Session(engine) as db:
        user=User(username='portable-migration',password='unused');db.add(user);db.flush()
        library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
        novel=Novel(library_id=library.id,title='Private original');db.add(novel);db.flush()
        row=service.stage(db,user,novel,ExportNovel(url='https://www.royalroad.com/fiction/888/fixture',annotations=[dict(chapter_number=None,note='Unbound original note')]),{})
        db.commit();assert row.payload['annotations'][0]['note']=='Unbound original note'
    with engine.connect() as connection:
        with pytest.raises(RuntimeError,match='unresolved imported reading material'):command.downgrade(alembic_config(connection),'0054')
        connection.rollback()
    engine.dispose()


@pytest.mark.parametrize('same_operation',[True,False])
def test_postgres_two_devices_apply_once_in_private_schema(same_operation):
    url=os.getenv('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('NEXUS_TEST_POSTGRES_URL not configured')
    schema='portable_'+uuid4().hex
    admin=create_engine(url,connect_args={'connect_timeout':5})
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine=create_engine(url,connect_args={'connect_timeout':5,'options':f'-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000'})
    try:
        migrate(engine,'0055')
        with Session(engine) as db:
            user=User(username='portable-owner',password='unused');db.add(user);db.flush();uid=user.id
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            novel=Novel(library_id=library.id,title='Private original');db.add(novel);db.flush()
            chapter=Chapter(novel_id=novel.id,chapter_number=0,content='Private original');db.add(chapter);db.flush();db.refresh(chapter)
            row=service.stage(db,user,novel,ExportNovel(url='https://www.royalroad.com/fiction/888/fixture',annotations=[dict(chapter_number=0,note='Reviewed note')]),{});db.commit();rid=row.id
            prepared=service.preview(db,user,row,ImportReadingPreviewInput(expected_revision=1,mappings=[dict(ref=row.payload['chapter_refs'][0]['ref'],chapter_key=chapter.chapter_key,confirm_changed_content=True)]))
        barrier=Barrier(2)
        def device(index):
            with Session(engine) as db:
                user=db.get(User,uid);row=service.owned(db,user,rid);barrier.wait(timeout=10)
                try:return 200,service.apply(db,user,row,ImportReadingApplyInput(review_token=prepared['review_token'],operation_id='same-op' if same_operation else f'device-{index}'))
                except HTTPException as error:db.rollback();return error.status_code,error.detail
        with ThreadPoolExecutor(max_workers=2) as pool:responses=list(pool.map(device,[1,2]))
        assert sorted(code for code,_ in responses)==([200,200] if same_operation else [200,409])
        with Session(engine) as db:assert db.query(ImportReadingOperation).count()==1
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
