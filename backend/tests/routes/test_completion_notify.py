from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services import novel_services
from app.services.completion_service import is_complete_status


def _user(db, name: str) -> User:
    user = User(username=name, password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _novel(db, user: User, status: str | None) -> Novel:
    library = Library(name=f"lib-{user.username}", user_id=user.id)
    db.add(library)
    db.commit()
    novel = Novel(
        title="Serial", url=f"https://www.royalroad.com/fiction/{user.id}{status}",
        library_id=library.id, novel_site="royalroad", status=status,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _flag(db, user: User, novel: Novel, value: bool = True) -> None:
    db.add(NovelPersonalData(user_id=user.id, novel_id=novel.id, notify_when_complete=value))
    db.commit()


def _completed_events(db, novel: Novel) -> list[NovelUpdateEvent]:
    return db.query(NovelUpdateEvent).filter(
        NovelUpdateEvent.novel_id == novel.id, NovelUpdateEvent.event_type == "completed"
    ).all()


def test_transition_to_complete_notifies_only_flagged_users(db, test_user):
    other = _user(db, "other")
    novel = _novel(db, test_user, "Ongoing")
    _flag(db, test_user, novel)
    _flag(db, other, novel, value=False)

    novel_services.update_novel(db, novel.id, {"status": "Completed"})

    events = _completed_events(db, novel)
    assert [event.user_id for event in events] == [test_user.id]
    assert events[0].notification_visible is True
    assert "finished" in events[0].message


def test_repeated_complete_update_creates_no_extra_event(db, test_user):
    novel = _novel(db, test_user, "Ongoing")
    _flag(db, test_user, novel)

    novel_services.update_novel(db, novel.id, {"status": "complete"})
    novel_services.update_novel(db, novel.id, {"status": "Complete", "title": "Serial"})

    assert len(_completed_events(db, novel)) == 1


def test_already_complete_novel_does_not_notify(db, test_user):
    novel = _novel(db, test_user, "completed")
    _flag(db, test_user, novel)

    novel_services.update_novel(db, novel.id, {"status": "Complete"})

    assert _completed_events(db, novel) == []


def test_ongoing_update_does_not_notify(db, test_user):
    novel = _novel(db, test_user, "Ongoing")
    _flag(db, test_user, novel)

    novel_services.update_novel(db, novel.id, {"status": "Ongoing"})

    assert _completed_events(db, novel) == []


def test_status_normalisation():
    assert is_complete_status(" Completed ")
    assert is_complete_status("COMPLETE")
    assert not is_complete_status("Hiatus")
    assert not is_complete_status(None)
