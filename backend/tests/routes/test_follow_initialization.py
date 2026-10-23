"""Follow initialization tolerates another request winning its first insert."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Novel
from app.models.follow import UserNovelFollow
from app.routers import novel as routes


def test_follow_initialization_reuses_concurrent_winner(db, test_user, test_library, monkeypatch):
    novel = Novel(title="Concurrent readers", library_id=test_library.id)
    db.add(novel)
    db.commit()
    winner = UserNovelFollow(user_id=test_user.id, novel_id=novel.id,
        state="reading", download_policy="next_n", download_count=3)
    db.add(winner)
    db.commit()
    existing = routes.get_existing_follow
    calls = 0

    def stale_first_read(*args):
        nonlocal calls
        calls += 1
        # Reproduce a request that read before the winner committed. The insert
        # still hits the real database constraint, rather than a mocked error.
        return None if calls == 1 else existing(*args)

    monkeypatch.setattr(routes, "get_existing_follow", stale_first_read)
    novel.title = "Pending outer update"
    result = routes.get_or_create_follow(db, test_user.id, novel)
    assert result.id == winner.id
    assert (result.state, result.download_policy, result.download_count) == ("reading", "next_n", 3)
    db.commit()
    db.refresh(novel)
    assert novel.title == "Pending outer update"
    assert db.query(UserNovelFollow).count() == 1


def test_follow_initialization_does_not_hide_other_integrity_failures(db, test_library):
    novel = Novel(title="Invalid owner", library_id=test_library.id)
    db.add(novel)
    db.commit()
    with pytest.raises(IntegrityError):
        routes.get_or_create_follow(db, None, novel)
    # The failed savepoint leaves the outer request's session usable.
    assert db.query(UserNovelFollow).count() == 0


def test_follow_initialization_is_idempotent(db, test_user, test_library):
    novel = Novel(title="Repeated reader", library_id=test_library.id, follow_state="on_hold")
    db.add(novel)
    db.commit()
    first = routes.get_or_create_follow(db, test_user.id, novel)
    db.commit()
    second = routes.get_or_create_follow(db, test_user.id, novel)
    assert first.id == second.id and second.state == "on_hold"
    assert db.query(UserNovelFollow).count() == 1
