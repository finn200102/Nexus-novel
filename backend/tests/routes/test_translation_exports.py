from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from app.models import Chapter, Novel, User
from app.models.translation import ReaderProvider, TranslationJob
from app.services.chapter_document import from_html, from_text
from app.services import translation_export_service as service


def saved(db, user, library):
    novel = Novel(title='Private translated story', author='Author', library_id=library.id)
    provider = ReaderProvider(user_id=user.id, name='Unused provider', kind='local', base_url='http://never-called', model='fixture')
    db.add_all([novel, provider]); db.flush()
    jobs = []
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNQ6pgJAAITAUTGjr3DAAAAAElFTkSuQmCC'
    for number in (1, 2):
        document = from_html(f'<p><em>Chapter {number}</em><img src="{image}" alt="Map" /></p><aside class="author-note"><p>Note</p></aside>')
        chapter = Chapter(novel_id=novel.id, chapter_number=number, title=f'Part {number}', document=document, content=document['plain_text'])
        db.add(chapter); db.flush()
        blocks = deepcopy(document['blocks'])
        blocks[0]['html'] = blocks[0]['html'].replace('Chapter', 'Kapitel')
        blocks[0]['text'] = blocks[0]['text'].replace('Chapter', 'Kapitel')
        job = TranslationJob(user_id=user.id, novel_id=novel.id, chapter_id=chapter.id, provider_id=provider.id,
            language='de', fingerprint=str(number).zfill(64), source_version=document['content_version'],
            provider_snapshot={'kind': 'local', 'model': 'fixture', 'authorization': {'private': 'not-returned'}},
            source_blocks=document['blocks'], translated_blocks=blocks, glossary={}, status='completed')
        from app.services.chapter_identity_service import identity
        db.refresh(chapter);captured=identity(chapter)
        job.chapter_key=captured['chapter_key'];job.manifest_epoch=captured['manifest_epoch'];job.manifest_revision=captured['manifest_revision']
        job.chapter_title_snapshot=chapter.title;job.chapter_number_snapshot=chapter.chapter_number
        db.add(job); jobs.append(job)
    db.commit()
    return novel, jobs


def endpoint(novel):return f'/reader/stories/{novel.id}/translations'


def test_exact_selected_variants_export_ordered_rich_private_book_without_provider(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,jobs=saved(db,test_user,test_library)
    def forbidden(*args,**kwargs):raise AssertionError('Export must not invoke a provider')
    monkeypatch.setattr('app.services.translation_service.invoke',forbidden)
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':[job.id for job in reversed(jobs)]})
    assert result.status_code==200 and result.headers['content-type']=='application/epub+zip'
    assert result.headers['cache-control']=='private, no-store'
    assert 'translated-story-' in result.headers['content-disposition']
    with ZipFile(BytesIO(result.content)) as book:
        first=book.read('OEBPS/chapter-1.xhtml').decode()
        assert '<em>Kapitel 1</em>' in first and 'data-nexus-role="author_note"' in first
        assert jobs[0].translated_blocks[0]['id'] in first
        assert '<em>Kapitel 2</em>' in book.read('OEBPS/chapter-2.xhtml').decode()
        assert any(name.endswith('.png') for name in book.namelist())
        assert '<dc:language>de</dc:language>' in book.read('OEBPS/content.opf').decode()
    assert all(job.status=='completed' for job in jobs)


def test_workspace_pages_metadata_and_flags_stale_without_bodies_or_private_snapshot(client,db,test_user,test_library,auth_headers):
    novel,jobs=saved(db,test_user,test_library)
    chapter=db.get(Chapter,jobs[1].chapter_id);chapter.document=from_text('Revised story');db.commit()
    response=client.get(endpoint(novel)+'?offset=1&limit=1',headers=auth_headers)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    body=response.json();assert (body['total'],body['offset'],body['limit'])==(2,1,1)
    row=body['items'][0]
    assert row['id']==jobs[1].id and row['source_current'] is False and row['exportable'] is True
    assert row['provider']=={'kind':'local','model':'fixture'} and 'document' not in row and 'source_blocks' not in row
    assert client.get(endpoint(novel)+'?limit=201',headers=auth_headers).status_code==422
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':[jobs[1].id]})
    assert result.status_code==200  # explicit saved variant export preserves its original source, not a replacement
    with ZipFile(BytesIO(result.content)) as book:assert b'Kapitel 2' in book.read('OEBPS/chapter-1.xhtml')


@pytest.mark.parametrize('mutation,code,detail',[
    ('language',422,'one language'),('incomplete',409,'Finish'),('alignment',409,'alignment'),
    ('missing',404,'missing'),('other_owner',404,'missing'),('duplicate_chapter',422,'one translation')])
def test_export_rejects_invalid_selections_atomically(client,db,test_user,test_library,auth_headers,mutation,code,detail):
    novel,jobs=saved(db,test_user,test_library)
    ids=[job.id for job in jobs]
    if mutation=='language':jobs[1].language='fr'
    elif mutation=='incomplete':jobs[1].status='processing'
    elif mutation=='alignment':
        blocks=deepcopy(jobs[1].translated_blocks);blocks[0]['id']='incorrect';jobs[1].translated_blocks=blocks
    elif mutation=='missing':ids[1]=999999
    elif mutation=='other_owner':
        other=User(username='foreign-translator',password='unused');db.add(other);db.flush();jobs[1].user_id=other.id
    elif mutation=='duplicate_chapter':
        jobs[1].chapter_id=jobs[0].chapter_id;jobs[1].chapter_key=jobs[0].chapter_key
    db.commit()
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':ids})
    assert result.status_code==code and detail in result.json()['detail']


def test_export_bounds_schema_ownership_and_safe_markup(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,jobs=saved(db,test_user,test_library)
    for ids in ([],[jobs[0].id,jobs[0].id],[True],[0],list(range(1,202))):
        assert client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':ids}).status_code==422
    assert client.post(endpoint(novel)+'/epub',json={'translation_job_ids':[jobs[0].id]}).status_code==401
    monkeypatch.setattr(service,'MAX_INPUT_BYTES',10)
    assert client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':[jobs[0].id]}).status_code==422
    monkeypatch.setattr(service,'MAX_INPUT_BYTES',20*1024**2)
    blocks=deepcopy(jobs[0].translated_blocks)
    blocks[0]['html']+='<script>privateDanger()</script><img src="https://invalid.test/tracker" onerror="bad()" />'
    jobs[0].translated_blocks=blocks;db.commit()
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':[jobs[0].id]})
    assert result.status_code==200
    with ZipFile(BytesIO(result.content)) as book:
        content=book.read('OEBPS/chapter-1.xhtml')
        assert b'privateDanger' not in content and b'https://invalid.test' not in content and b'onerror' not in content


def test_legacy_text_source_and_output_resource_limits(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,jobs=saved(db,test_user,test_library)
    chapter=db.get(Chapter,jobs[0].chapter_id)
    document=from_text('Legacy source chapter')
    chapter.document=None;chapter.content=document['plain_text']
    jobs[0].source_version=document['content_version'];jobs[0].source_blocks=document['blocks'];jobs[0].translated_blocks=document['blocks']
    db.commit()
    first=client.get(endpoint(novel)+'?limit=1',headers=auth_headers).json()['items'][0]
    assert first['source_current'] and first['exportable']
    request={'translation_job_ids':[jobs[0].id]}
    assert client.post(endpoint(novel)+'/epub',headers=auth_headers,json=request).status_code==200
    monkeypatch.setattr(service,'MAX_LEGACY_SOURCE_BYTES',1)
    uncertain=client.get(endpoint(novel)+'?limit=1',headers=auth_headers).json()['items'][0]
    assert not uncertain['source_current'] and uncertain['exportable']  # saved artifact needs no current-source body load
    monkeypatch.setattr(service,'MAX_LEGACY_SOURCE_BYTES',8*1024**2)
    monkeypatch.setattr(service,'MAX_BLOCKS',0)
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json=request)
    assert result.status_code==422 and 'blocks' in result.json()['detail']
    monkeypatch.setattr(service,'MAX_BLOCKS',20_000);monkeypatch.setattr(service,'MAX_OUTPUT_BYTES',1)
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json=request)
    assert result.status_code==422 and 'download size' in result.json()['detail']


def test_foreign_story_and_removed_chapter_cannot_be_exported(client,db,test_user,test_library,auth_headers):
    from app.models import Library
    novel,jobs=saved(db,test_user,test_library)
    other=User(username='foreign-export-owner',password='unused');db.add(other);db.flush()
    library=Library(user_id=other.id,name='Foreign');db.add(library);db.flush()
    foreign=Novel(library_id=library.id,title='Foreign story');db.add(foreign);db.commit()
    assert client.get(endpoint(foreign),headers=auth_headers).status_code==404
    assert client.post(endpoint(foreign)+'/epub',headers=auth_headers,json={'translation_job_ids':[jobs[0].id]}).status_code==404
    # SQL fixtures without FK enforcement can retain a job whose source vanished.
    db.query(Chapter).filter_by(id=jobs[0].chapter_id).delete(synchronize_session=False);db.commit()
    result=client.post(endpoint(novel)+'/epub',headers=auth_headers,json={'translation_job_ids':[jobs[0].id]})
    assert result.status_code==200
    with ZipFile(BytesIO(result.content)) as book:assert b'Kapitel 1' in book.read('OEBPS/chapter-1.xhtml')


def test_postgres_translation_workspace_and_export_queries(monkeypatch):
    """Qualify JSON extraction/array counts and byte bounds on real PG17."""
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models import Library
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Set NEXUS_TEST_POSTGRES_URL to an owned disposable PostgreSQL database')
    schema='translation_export_'+uuid4().hex
    admin=create_engine(url)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='pg-export-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.commit()
            novel,jobs=saved(db,user,library)
            workspace=service.list_variants(db,user.id,novel.id,1,1)
            assert workspace['total']==2 and workspace['items'][0]['chapter_number']==2
            assert workspace['items'][0]['source_current'] and workspace['items'][0]['completed_blocks']==2
            data,language=service.export_variants(db,user.id,novel.id,[job.id for job in reversed(jobs)])
            assert language=='de' and ZipFile(BytesIO(data)).testzip() is None
            monkeypatch.setattr(service,'MAX_INPUT_BYTES',10)
            with pytest.raises(HTTPException) as error:service.export_variants(db,user.id,novel.id,[jobs[0].id])
            assert error.value.status_code==422
    finally:
        engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()
