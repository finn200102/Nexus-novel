"""Exports retain old notes without lending them a replacement chapter title."""
# ruff: noqa: F811
from sqlalchemy import delete
from app.models import Chapter,ReadingAnnotation
from tests.routes.test_highlights_export import _story
from tests.routes.conftest import db,test_user,client,auth_headers  # noqa: F401


def test_archived_original_highlights_remain_exportable(client,db,test_user,auth_headers):
    novel=_story(db,test_user)
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one()
    chapter.archived=True;db.commit()
    response=client.get(f'/export/highlights?format=json&novel_id={novel.id}',headers=auth_headers)
    assert response.status_code==200,response.text
    saved=next(row for row in response.json()[0]['highlights'] if row['quote']=='First quote')
    assert saved['chapter_key']==chapter.chapter_key and saved['chapter_archived'] is True
    assert saved['identity_verified'] is True


def test_reused_chapter_fk_cannot_relabel_old_private_highlights(client,db,test_user,auth_headers):
    novel=_story(db,test_user)
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one()
    identifier,original_key=chapter.id,chapter.chapter_key
    db.expunge(chapter)
    db.execute(delete(Chapter).where(Chapter.id==identifier).execution_options(synchronize_session=False));db.commit()
    replacement=Chapter(id=identifier,novel_id=novel.id,chapter_number=1,title='UNRELATED_REPLACEMENT_TITLE',source_url='https://replacement.invalid/secret')
    db.add(replacement);db.commit()
    assert replacement.chapter_key!=original_key
    response=client.get(f'/export/highlights?format=json&novel_id={novel.id}',headers=auth_headers)
    assert response.status_code==200,response.text
    saved=next(row for row in response.json()[0]['highlights'] if row['quote']=='First quote')
    assert saved['chapter_key']==original_key and saved['identity_verified'] is False
    assert saved['chapter_url'] is None and saved['chapter_title']=='Chapter 1 · original reference'
    markdown=client.get(f'/export/highlights?format=markdown&novel_id={novel.id}',headers=auth_headers)
    assert 'First quote' in markdown.text and 'UNRELATED_REPLACEMENT_TITLE' not in markdown.text
    assert 'replacement.invalid' not in markdown.text


def test_unbound_legacy_note_is_retained_without_a_guessed_chapter_link(client,db,test_user,auth_headers):
    novel=_story(db,test_user)
    annotation=db.query(ReadingAnnotation).filter_by(novel_id=novel.id,quote='First quote').one()
    annotation.chapter_key=None;db.commit()
    response=client.get(f'/export/highlights?format=json&novel_id={novel.id}',headers=auth_headers)
    saved=next(row for row in response.json()[0]['highlights'] if row['quote']=='First quote')
    assert saved['chapter_url'] is None and saved['identity_verified'] is False
    assert saved['chapter_key'] is None and saved['chapter_number']==1
