"""Preserve unknown old terminology and enforce reviewed scopes in both dialects."""
# ruff: noqa: F811
from datetime import datetime
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from alembic import command
from sqlalchemy import MetaData,select,inspect
from sqlalchemy.orm import sessionmaker
from app.db_migrations import alembic_config
from app.models import User,Library
from app.models.translation import StoryGlossary
from config.database import Base
from tests.database.test_reading_run_migration import run_engine  # noqa: F401
from tests.routes.test_glossary_identity import setup,approve


def test_0054_preserves_unknown_legacy_scope_without_fabricating_chapter_proof(run_engine):
    with run_engine.begin() as connection:command.upgrade(alembic_config(connection),'0053')
    tables=MetaData();tables.reflect(run_engine)
    with run_engine.begin() as connection:
        def add(table_name,**values):return connection.execute(tables.tables[table_name].insert().values(**values)).inserted_primary_key[0]
        user=add('users',username='glossary-owner',password='unused',storage_id=str(uuid4()))
        library=add('libraries',name='Private',user_id=user,identity_key=str(uuid4()))
        novel=add('novels',title='Original',library_id=library)
        row=add('story_glossaries',user_id=user,novel_id=novel,source='Old secret',target='Preserved target',language='de',through_chapter=0,created_at=datetime(2020,1,1))
    with run_engine.begin() as connection:command.upgrade(alembic_config(connection),'0054')
    tables=MetaData();tables.reflect(run_engine)
    with run_engine.begin() as connection:
        glossary=tables.tables['story_glossaries'];value=connection.execute(select(glossary)).mappings().one()
        assert value['id']==row and value['through_chapter']==0 and value['target']=='Preserved target' and value['identity_inferred'] is True
        assert all(value[key] is None for key in ('chapter_key','manifest_epoch','manifest_revision','source_version','prerequisites'))
        assert value['created_at']==datetime(2020,1,1)
        assert {index['name'] for index in inspect(connection).get_indexes('story_glossaries')} >= {'uq_story_glossary_legacy_scope','uq_story_glossary_identity_scope'}
    with run_engine.begin() as connection:command.downgrade(alembic_config(connection),'0053')
    assert 'prerequisites' not in {column['name'] for column in inspect(run_engine).get_columns('story_glossaries')}
    old=MetaData();old.reflect(run_engine)
    with run_engine.connect() as connection:
        value=connection.execute(select(old.tables['story_glossaries'])).mappings().one()
        assert value['id']==row and value['source']=='Old secret' and value['target']=='Preserved target'


def test_postgres_simultaneous_approvals_reuse_one_immutable_scope(run_engine):
    if run_engine.dialect.name!='postgresql':pytest.skip('Requires PostgreSQL row locks')
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='scope-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,rows=setup(db,library);ids=(user.id,novel.id,rows[-1].id)
    barrier=Barrier(2)
    def apply(_):
        with sessions() as db:
            from app.models import Novel,Chapter
            user=db.get(User,ids[0]);novel=db.get(Novel,ids[1]);row=db.get(Chapter,ids[2]);barrier.wait(timeout=10)
            return approve(db,user,novel,row)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(apply,range(2)))
    assert results[0]==results[1]
    with sessions() as db:assert db.query(StoryGlossary).count()==1



def test_signed_reorder_and_equal_text_pk_reuse_do_not_retarget_approved_terms(run_engine):
    from app.models import Chapter
    from app.services.translation_service import glossary_for
    from sqlalchemy import text
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='scope-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,rows=setup(db,library);floor=rows[-1]
        db.add(StoryGlossary(user_id=user.id,novel_id=novel.id,source='Unknown',target='Must not send',language='de',through_chapter=-2));db.commit()
        approve(db,user,novel,floor)
        assert glossary_for(db,user.id,novel.id,'de',7)=={'Secret':'Preferred'}
        floor.chapter_number=-3;db.commit()
        assert glossary_for(db,user.id,novel.id,'de',-2)=={}
        assert glossary_for(db,user.id,novel.id,'de',0)=={'Secret':'Preferred'}
        # Explicit review can intentionally approve this now earlier floor.
        approve(db,user,novel,floor)
        assert glossary_for(db,user.id,novel.id,'de',-2)=={'Secret':'Preferred'}
        pk,doc=floor.id,floor.document
        db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(floor)
        db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=-3,document=doc,content=doc['plain_text']));db.commit()
        assert glossary_for(db,user.id,novel.id,'de',0)=={}
        assert db.query(StoryGlossary).count()==2
