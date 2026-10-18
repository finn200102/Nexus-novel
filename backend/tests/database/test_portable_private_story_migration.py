from alembic import command
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.orm import Session
from app.db_migrations import alembic_config
from app.models import User,Library,Novel
from app.models.portable_story_link import PortableStoryLink
from uuid import uuid4
import pytest


def test_0057_private_link_tombstone_and_library_cleanup(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path}/portable-private.db')
    with engine.connect() as connection:
        command.upgrade(alembic_config(connection),'0056');connection.commit()
        assert 'portable_story_links' not in inspect(connection).get_table_names()
        command.upgrade(alembic_config(connection),'0057');connection.commit()
        connection.exec_driver_sql('PRAGMA foreign_keys=ON');connection.commit()
        with Session(bind=connection) as db:
            user=User(username='private-migration',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            book=Novel(library_id=library.id,title='No source URL',url=None);db.add(book);db.flush()
            link=PortableStoryLink(user_id=user.id,library_id=library.id,destination_account_key=user.storage_id,destination_library_key=library.identity_key,source_account_key=str(uuid4()),source_story_epoch=str(uuid4()),novel_id=book.id,target_story_epoch=book.manifest_state.manifest_epoch)
            db.add(link);db.commit();link_id=link.id;book_id=book.id;library_id=library.id;epoch=link.target_story_epoch
        connection.execute(text('DELETE FROM novels WHERE id=:id'),{'id':book_id});connection.commit()
        row=connection.execute(text('SELECT novel_id,target_story_epoch FROM portable_story_links WHERE id=:id'),{'id':link_id}).one()
        assert row.novel_id is None and row.target_story_epoch==epoch
        with pytest.raises(RuntimeError,match='lose repeat-import identity'):command.downgrade(alembic_config(connection),'0056')
        connection.rollback()
        connection.execute(text('DELETE FROM libraries WHERE id=:id'),{'id':library_id});connection.commit()
        assert connection.execute(text('SELECT count(*) FROM portable_story_links')).scalar()==0
    engine.dispose()
