"""A matching numeric FK and text hash never borrow an old lifecycle's note."""
# ruff: noqa:F811
from sqlalchemy import delete
from app.models import Chapter,ReadingAnnotation
from app.services.reading_progress_service import save_reading_progress
from tests.contracts.test_chapter_identity import original,captured  # noqa:F401
from tests.routes.conftest import db,test_user,test_library,client,auth_headers  # noqa:F401


def test_recap_excludes_preserved_note_after_pk_reuse_even_with_same_source_version(client,db,test_user,original,auth_headers):
    novel,chapter=original
    identifier,old_key=chapter.id,chapter.chapter_key
    document,body=chapter.document,chapter.content
    version=document['content_version']
    old_note=ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=identifier,
        annotation_type='note',quote='Original source quote',note='SECRET_FUTURE_FROM_OTHER_EDITION',locator_content_version=version)
    db.add(old_note);db.commit();old_note_id=old_note.id
    db.expunge(chapter)
    db.execute(delete(Chapter).where(Chapter.id==identifier).execution_options(synchronize_session=False));db.commit()
    current=Chapter(id=identifier,novel_id=novel.id,chapter_number=1,title='Current known original',content=body,document=document)
    db.add(current);db.commit();db.refresh(current)
    assert current.chapter_key!=old_key
    assert db.get(ReadingAnnotation,old_note_id).chapter_key==old_key
    save_reading_progress(db,user_id=test_user.id,chapter=current,position=0,percent=100,content_version=version,**captured(current))
    db.add(ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=identifier,
        annotation_type='note',quote='Known current quote',note='Safe current note',locator_content_version=version))
    db.commit()
    response=client.get(f'/chapter/recap/{novel.id}',headers=auth_headers)
    assert response.status_code==200,response.text
    assert response.json()['chapters']==[{'number':1,'title':'Current known original'}]
    assert response.json()['annotations']==[{'chapter_number':1,'quote':'Known current quote','note':'Safe current note','type':'note'}]
    assert 'SECRET_FUTURE' not in response.text
