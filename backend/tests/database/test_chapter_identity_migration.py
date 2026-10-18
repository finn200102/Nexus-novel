"""0052 preserves uncertain history without inventing identity evidence."""
import os
from uuid import uuid4, UUID
import pytest
from alembic import command
from sqlalchemy import create_engine, text, inspect
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_0052_preserves_originals_inferred_history_and_database_lifecycle_keys(tmp_path,dialect):
    admin=None
    if dialect=='postgresql':
        url=os.environ.get('NEXUS_MANIFEST_TEST_POSTGRES_URL')
        if not url:pytest.skip('Owned nexus_manifest_novel PostgreSQL required')
        assert '/nexus_manifest_novel' in url, 'Never use another feature test database'
        admin=create_engine(url);schema='manifest_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path / "identity-migration.db"}')
    try:
        with engine.connect() as c:
            command.upgrade(alembic_config(c),'0051');c.commit()
            c.execute(text("INSERT INTO users(id,username,password,storage_id) VALUES(1,'owner','unused','identity-migration')"))
            c.execute(text("INSERT INTO libraries(id,user_id,name) VALUES(1,1,'Private')"))
            c.execute(text("INSERT INTO novels(id,library_id,title) VALUES(1,1,'Originals')"))
            for id,number in [(1,-2),(2,7)]:
                c.execute(text("INSERT INTO chapters(id,novel_id,chapter_number,title,content,content_status,audio_status,retry_count) VALUES(:id,1,:number,'Original','Original body','PRESENT','MISSING',0)"),{'id':id,'number':number})
            c.execute(text('INSERT INTO reading_progress(user_id,novel_id,chapter_id,chapter_number,position,percent,furthest_chapter_number,furthest_percent) VALUES(1,1,1,-2,50,40,7,100)'))
            c.execute(text("INSERT INTO reading_history(user_id,novel_id,chapter_number,reading_date,max_percent) VALUES(1,1,7,'2025-02-14',100),(1,1,99,'2025-02-15',50)"))
            c.commit();command.upgrade(alembic_config(c),'0052');c.commit()
            chapters=c.execute(text('SELECT id,chapter_key,content FROM chapters ORDER BY id')).all()
            assert all(str(UUID(row.chapter_key))==row.chapter_key and row.content=='Original body' for row in chapters)
            assert chapters[0].chapter_key!=chapters[1].chapter_key
            progress=c.execute(text('SELECT chapter_key,furthest_chapter_key,furthest_identity_inferred FROM reading_progress')).one()
            assert progress==(chapters[0].chapter_key,chapters[1].chapter_key,1)
            history=c.execute(text('SELECT chapter_number,chapter_key,identity_inferred,max_percent FROM reading_history ORDER BY id')).all()
            assert history==[(7,chapters[1].chapter_key,True,100),(99,None,True,50)]
            original=c.execute(text('SELECT manifest_epoch,revision,identity_required FROM chapter_manifest_states')).one()
            assert str(UUID(original.manifest_epoch))==original.manifest_epoch and not original.identity_required
            command.downgrade(alembic_config(c),'0051');c.commit()
            assert 'chapter_key' not in {row['name'] for row in inspect(c).get_columns('chapters')}
            assert c.execute(text('SELECT chapter_number,max_percent FROM reading_history ORDER BY id')).all()==[(7,100),(99,50)]
            # A retained historical AO3 original remains sensitive even after
            # its current story/chapter URL no longer identifies that source.
            c.execute(text("INSERT INTO chapter_versions(chapter_id,content_version,source_url,content,document,byte_count,reason) VALUES(1,:version,'https://archiveofourown.org/works/81/chapters/100','Earlier AO3 original','{}',20,'source_revision')"),{'version':'a'*64})
            c.commit()
            command.upgrade(alembic_config(c),'0052');c.commit()
            assert c.execute(text('SELECT ao3_material FROM chapter_manifest_states')).scalar_one()
            with pytest.raises(Exception):c.execute(text('UPDATE chapter_manifest_states SET ao3_material=false'))
            c.rollback()
            original=c.execute(text('SELECT manifest_epoch,revision,identity_required FROM chapter_manifest_states')).one()
            c.execute(text("UPDATE chapters SET content='New body' WHERE id=1"));c.commit()
            assert c.execute(text('SELECT revision FROM chapter_manifest_states')).scalar_one()==original.revision
            c.execute(text('UPDATE chapters SET chapter_number=8 WHERE id=2'));c.commit()
            assert c.execute(text('SELECT revision FROM chapter_manifest_states')).scalar_one()>original.revision
            c.execute(text('DELETE FROM chapters WHERE id=2'))
            c.execute(text("INSERT INTO chapters(id,novel_id,chapter_number,title,content,content_status,audio_status,retry_count) VALUES(2,1,8,'Replacement','Replacement body','PRESENT','MISSING',0)"));c.commit()
            replacement=c.execute(text('SELECT chapter_key FROM chapters WHERE id=2')).scalar_one()
            assert replacement!=chapters[1].chapter_key
            with pytest.raises(Exception):
                c.execute(text('UPDATE chapters SET chapter_key=:key WHERE id=2'),{'key':chapters[1].chapter_key})
            c.rollback()
            with pytest.raises(Exception):c.execute(text('UPDATE chapter_manifest_states SET manifest_epoch=:key'),{'key':str(uuid4())})
            c.rollback()
            assert c.execute(text('SELECT chapter_number,max_percent FROM reading_history ORDER BY id')).all()==[(7,100),(99,50)]
            with pytest.raises(RuntimeError,match='identity fences'):
                command.downgrade(alembic_config(c),'0051')
            c.rollback()
            assert 'chapter_key' in {row['name'] for row in inspect(c).get_columns('chapters')}
            assert c.execute(text('SELECT chapter_number,max_percent FROM reading_history ORDER BY id')).all()==[(7,100),(99,50)]
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
