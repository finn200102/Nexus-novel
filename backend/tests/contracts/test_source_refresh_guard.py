"""Source I/O cannot outlive ownership, account or story lifecycle authority."""
# ruff: noqa: F811
import asyncio
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from app.models import Library, Novel, User
from app.services.source_refresh_guard import await_source
from tests.contracts.test_chapter_identity import original  # noqa: F401
from tests.routes.conftest import db, test_user, test_library, client, auth_headers  # noqa: F401


@pytest.mark.parametrize('change,code', [('source', 409), ('namespace', 409), ('owner', 404), ('disabled', 401), ('replacement', 409), ('none', None)])
def test_remote_result_rechecks_current_authority_in_independent_transaction(db, test_user, original, change, code):
    novel, _ = original
    novel.metadata_id = 123
    novel.url = 'https://synthetic.invalid/original'
    db.commit()
    user_id, novel_id, library_id = test_user.id, novel.id, novel.library_id

    async def source():
        with Session(bind=db.get_bind()) as writer:
            if change == 'source':
                writer.get(Novel, novel_id).url = 'https://synthetic.invalid/replacement'
            elif change == 'namespace':
                writer.get(Novel, novel_id).story_id = 999
            elif change == 'owner':
                other = User(username='new-owner', password='unused')
                writer.add(other)
                writer.flush()
                writer.get(Library, library_id).user_id = other.id
            elif change == 'disabled':
                writer.get(User, user_id).is_disabled = True
            elif change == 'replacement':
                # Exercise a feasible owned deletion with real FK enforcement,
                # including the existing ORM cascades, then recycle the PK.
                writer.delete(writer.get(Novel,novel_id));writer.flush()
                writer.execute(Novel.__table__.insert().values(id=novel_id, library_id=library_id,
                    metadata_id=123, url='https://synthetic.invalid/original', title='Replacement story'))
            writer.commit()
        return {'title': 'Untrusted remote result'}

    if code is None:
        result, current = asyncio.run(await_source(db, user_id, novel, source))
        assert result['title'] == 'Untrusted remote result'
        assert current.id == novel_id and current.title == 'Private'
    else:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(await_source(db, user_id, novel, source))
        assert caught.value.status_code == code
        db.rollback()
        current = db.get(Novel, novel_id)
        assert current.title != 'Untrusted remote result'


def test_refresh_route_does_not_apply_response_after_source_changes(client, db, test_user, original, auth_headers, monkeypatch):
    novel, _ = original
    novel.metadata_id = 123
    novel.url = 'https://synthetic.invalid/original'
    db.commit()
    novel_id, library_id = novel.id, novel.library_id

    async def refresh(_metadata_id):
        with Session(bind=db.get_bind()) as writer:
            writer.get(Novel, novel_id).url = 'https://synthetic.invalid/new-source'
            writer.commit()
        return {'title': 'Wrong source response'}

    monkeypatch.setattr('app.services.metadata_client.refresh_novel_metadata', refresh)
    response = client.get(f'/novel/refresh/{novel_id}', params={'library_id': library_id}, headers=auth_headers)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'story_source_changed'
    db.rollback()
    assert db.get(Novel, novel_id).title == 'Private'


def test_refresh_route_rechecks_session_revocation_after_source_response(client, db, original, auth_headers, monkeypatch):
    from app.models.account import UserSession
    from app.services.job_lease import utcnow
    novel, _ = original
    novel.metadata_id = 123
    db.commit()
    novel_id, library_id = novel.id, novel.library_id

    async def refresh(_metadata_id):
        session_id = db.info['authenticated_session'][1]
        with Session(bind=db.get_bind()) as writer:
            writer.get(UserSession, session_id).revoked_at = utcnow()
            writer.commit()
        return {'title': 'Response after sign out'}

    monkeypatch.setattr('app.services.metadata_client.refresh_novel_metadata', refresh)
    response = client.get(f'/novel/refresh/{novel_id}', params={'library_id': library_id}, headers=auth_headers)
    assert response.status_code == 401
    db.rollback()
    assert db.get(Novel, novel_id).title == 'Private'


@pytest.mark.parametrize('fails', [False, True])
def test_background_import_cannot_write_success_or_error_to_changed_source(db, original, monkeypatch, fails):
    from app.routers.novel import scrape_novel_background
    novel, _ = original
    novel.metadata_id = 123
    novel.url = 'https://synthetic.invalid/original'
    db.commit()
    novel_id = novel.id
    calls = []

    def source(coroutine, _loop):
        coroutine.close()
        calls.append(True)
        with Session(bind=db.get_bind()) as writer:
            writer.get(Novel, novel_id).url = 'https://synthetic.invalid/new-source'
            writer.commit()
        if fails:
            raise RuntimeError('The old source failed after being replaced')
        return {'title': 'Wrong source title', 'status': 'completed'}

    monkeypatch.setattr('app.routers.novel._run_metadata_call', source)
    scrape_novel_background(novel_id, 123, sessionmaker(bind=db.get_bind()))
    db.expire_all()
    current = db.get(Novel, novel_id)
    assert current.title == 'Private'
    assert current.scrape_status != 'failed'
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['source', 'limits'])
def test_delayed_household_check_cannot_delete_changed_story_or_changed_policy(db, test_user, original, monkeypatch, change):
    from app.routers.novel import scrape_within_limits
    novel, _ = original
    novel.metadata_id = 123
    novel.url = 'https://synthetic.invalid/original'
    novel.scrape_status = 'completed'
    test_user.max_content_rating = 'teen'
    db.commit()
    novel_id, user_id = novel.id, test_user.id

    def source(coroutine, _loop):
        coroutine.close()
        with Session(bind=db.get_bind()) as writer:
            if change == 'source':
                writer.get(Novel, novel_id).url = 'https://synthetic.invalid/new-source'
            else:
                writer.get(User, user_id).max_content_rating = None
            writer.commit()
        return False

    monkeypatch.setattr('app.routers.novel._run_metadata_call', source)
    scrape_within_limits(novel_id, 123, sessionmaker(bind=db.get_bind()), None, user_id, scrape=lambda *_args: None)
    db.expire_all()
    assert db.get(Novel, novel_id) is not None


def test_partial_metadata_does_not_erase_existing_facts_or_source_bindings(db, original):
    from app.services.source_refresh_guard import refresh_fields
    novel, _ = original
    novel.author = 'Known author'
    novel.source_url = 'https://synthetic.invalid/known-source'
    novel.story_id = 123
    novel.site_story_id = 123
    db.commit()
    incoming = {'title': 'Updated title', 'word_count': 0}
    proposed = {'title': 'Updated title', 'author': None, 'word_count': 0,
                'source_url': None, 'story_id': None, 'site_story_id': None}
    assert refresh_fields(db, novel, incoming, proposed) == incoming
    unknown_source = {'source_url': None, 'story_id': None}
    assert refresh_fields(db, novel, unknown_source, unknown_source) == {}


def test_refresh_response_cannot_relink_an_established_source(client, db, original, auth_headers, monkeypatch):
    novel, _ = original
    novel.metadata_id = 123
    novel.source_url = 'https://synthetic.invalid/known-source'
    db.commit()
    novel_id, library_id = novel.id, novel.library_id

    async def refresh(_metadata_id):
        return {'title': 'A different work', 'source_url': 'https://synthetic.invalid/different-source'}

    monkeypatch.setattr('app.services.metadata_client.refresh_novel_metadata', refresh)
    response = client.get(f'/novel/refresh/{novel_id}', params={'library_id': library_id}, headers=auth_headers)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'chapter_review_required'
    db.rollback()
    assert db.get(Novel, novel_id).source_url == 'https://synthetic.invalid/known-source'
    assert db.get(Novel, novel_id).title == 'Private'


def test_private_story_without_source_url_rejects_refresh_without_fetch(client,db,original,auth_headers,monkeypatch):
    novel,_=original
    novel.url=None;novel.metadata_id=None
    db.commit()
    def forbidden(*args,**kwargs):raise AssertionError('A private original has no source to crawl')
    monkeypatch.setattr('app.services.metadata_client.scrape_novel_by_url',forbidden)
    response=client.get(f'/novel/refresh/{novel.id}',params={'library_id':novel.library_id},headers=auth_headers)
    assert response.status_code==400
    assert db.get(Novel,novel.id).url is None
