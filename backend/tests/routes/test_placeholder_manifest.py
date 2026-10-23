from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import Chapter, Novel
from app.models.chapter_manifest import ChapterManifestState
from app.models.reading_progress import ReadingProgress
from app.services.chapter_manifest_service import ingest_metadata_snapshot
from app.services.metadata_client import ChapterManifestSnapshot


def placeholder(db, library):
    url = 'https://www.fanfiction.net/s/8005922/1/example'
    novel = Novel(title='Imported', library_id=library.id, metadata_id=2,
        novel_site='fanfiction', source_url=url, story_id=8005922)
    db.add(novel)
    db.commit()
    key = str(uuid4())
    state = db.get(ChapterManifestState, novel.id)
    state.metadata_manifest_key = key
    state.metadata_source = {'site': 'fanfiction', 'story_id': None, 'source_url': url}
    db.commit()
    remote = ChapterManifestSnapshot(novel_id=2, manifest_key=key, revision='1'*64,
        fingerprint='2'*64, identity_kind='stable_source_id', total=1,
        source={'site': 'fanfiction', 'story_id': 8005922, 'source_url': url},
        items=[dict(id=1, chapter_key=str(uuid4()), site='fanfiction', story_id=8005922,
            chapter_id=800592201, chapter_number=1, title='First', url=url,
            category='story', word_count=10, identity_kind='stable_source_id')])
    return novel, state, remote


def test_pristine_empty_placeholder_can_learn_work_id(db, test_library):
    novel, state, remote = placeholder(db, test_library)
    created = ingest_metadata_snapshot(db, novel, remote)
    db.commit()
    assert len(created) == 1 and created[0].chapter_key
    assert state.metadata_source == remote.source


@pytest.mark.parametrize('change', ['known_id', 'url', 'manifest', 'archived', 'deleted', 'progress'])
def test_placeholder_enrichment_preserves_identity_boundaries(db, test_user, test_library, change):
    novel, state, remote = placeholder(db, test_library)
    if change == 'known_id':
        state.metadata_source = {**state.metadata_source, 'story_id': 99}
    elif change == 'url':
        state.metadata_source = {**state.metadata_source, 'source_url': 'https://www.fanfiction.net/s/8005922/1/other'}
    elif change == 'manifest':
        state.metadata_manifest_key = str(uuid4())
    elif change in ('archived', 'deleted'):
        chapter = Chapter(novel_id=novel.id, chapter_number=1, title='Historical', archived=True)
        db.add(chapter)
        db.commit()
        if change == 'deleted':
            db.delete(chapter)
    else:
        db.add(ReadingProgress(user_id=test_user.id, novel_id=novel.id))
    db.commit()
    before = dict(state.metadata_source)
    with pytest.raises(HTTPException) as error:
        ingest_metadata_snapshot(db, novel, remote)
    assert error.value.status_code == 409
    db.rollback()
    assert db.get(ChapterManifestState, novel.id).metadata_source == before
