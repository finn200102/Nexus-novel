"""Account removal explicitly purges paged topology plans with FK checks off."""
# ruff: noqa: F811
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from app.models import Library, Novel, User
from app.models.chapter_manifest import ChapterManifestReview, ChapterManifestReviewItem, ChapterManifestOperation, ChapterManifestState
from app.models.import_reading_review import ImportReadingReview, ImportReadingOperation
from app.models.portable_story_link import PortableStoryLink
from app.services.account_service import delete_user_account
from tests.contracts.test_chapter_identity import original  # noqa: F401
from tests.routes.conftest import db, test_user, test_library  # noqa: F401


@pytest.fixture
def isolated_foreign_keys(db, foreign_keys):
    # PRAGMA state belongs to a physical connection. Pin the FK-mode scenario
    # across commits, then restore that same connection before pooling it.
    db.rollback()
    original_bind = db.bind
    connection = original_bind.connect()
    db.bind = connection
    try:
        connection.exec_driver_sql(f'PRAGMA foreign_keys={"ON" if foreign_keys else "OFF"}')
        connection.commit()
        yield
    finally:
        db.rollback()
        db.bind = original_bind
        connection.rollback()
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.commit()
        connection.close()


@pytest.mark.parametrize('foreign_keys', [False, True])
def test_account_delete_purges_only_owned_topology_reviews_and_items(db, test_user, original, foreign_keys, isolated_foreign_keys):
    novel, _ = original
    victim_id, novel_id = test_user.id, novel.id
    db.rollback()
    db.connection().exec_driver_sql(f'PRAGMA foreign_keys={"ON" if foreign_keys else "OFF"}')
    assert bool(db.connection().exec_driver_sql('PRAGMA foreign_keys').scalar()) == foreign_keys
    other = User(username='review-owner', password='unused')
    db.add(other)
    db.flush()
    library = Library(user_id=other.id, name='Other library')
    db.add(library)
    db.flush()
    other_story = Novel(library_id=library.id, title='Other story')
    db.add(other_story)
    db.flush()
    for user_id, story_id in ((victim_id, novel_id), (other.id, other_story.id)):
        review = ChapterManifestReview(user_id=user_id, novel_id=story_id, review_key=str(uuid4()),
            fingerprint='a' * 64, plan={'private': 'Review belongs only to this owner'},
            expires_at=datetime.now() + timedelta(hours=1))
        db.add(review)
        db.flush()
        db.add(ChapterManifestReviewItem(review_id=review.id, ordinal=0, item_kind='local',
            detail={'private': 'Owned chapter review'}))
        db.add(ChapterManifestOperation(user_id=user_id, novel_id=story_id, operation_id='same-private-id',
            fingerprint='b' * 64, response={'review': review.review_key}))
        imported=ImportReadingReview(user_id=user_id,novel_id=story_id,fingerprint='c'*64,payload={'private':'Unmatched imported annotation'},applied_refs=[])
        db.add(imported);db.flush()
        db.add(ImportReadingOperation(user_id=user_id,review_id=imported.id,operation_id='same-import-id',fingerprint='d'*64,response={'private':'Reviewed import'}))
        account=db.get(User,user_id);story=db.get(Novel,story_id);destination=db.get(Library,story.library_id)
        db.add(PortableStoryLink(user_id=user_id,library_id=destination.id,destination_account_key=account.storage_id,
            destination_library_key=destination.identity_key,source_account_key=str(uuid4()),source_story_epoch=str(uuid4()),
            novel_id=story_id,target_story_epoch=story.manifest_state.manifest_epoch,pending_payload={'private':'Pending original reading'}))
    db.commit()
    other_story_id = other_story.id
    delete_user_account(db, test_user)
    assert db.get(User, victim_id) is None
    assert db.get(ChapterManifestState, novel_id) is None
    assert db.query(ChapterManifestReview).count() == 1
    assert db.query(ChapterManifestReviewItem).count() == 1
    assert db.query(ChapterManifestOperation).count() == 1
    assert db.query(ChapterManifestReview).one().novel_id == other_story_id
    assert db.query(ImportReadingReview).count()==1 and db.query(ImportReadingReview).one().novel_id==other_story_id
    assert db.query(ImportReadingOperation).count()==1 and db.query(ImportReadingOperation).one().user_id==other.id
    assert db.query(PortableStoryLink).count()==1 and db.query(PortableStoryLink).one().novel_id==other_story_id
    assert db.get(ChapterManifestState, other_story_id) is not None
    db.rollback()
    db.connection().exec_driver_sql('PRAGMA foreign_keys=OFF')
