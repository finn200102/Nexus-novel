from app.models.novel import Novel
from app.models.reader_preference import ReaderPreference


def save(client, headers, values, revision=0, operation="prefs-1", route="/reader/preferences"):
    return client.put(route, headers=headers, json={"expected_revision": revision, "operation_id": operation, "values": values})


def test_private_preferences_preserve_conflicting_devices_and_replays(client, db, auth_headers):
    assert client.get("/reader/preferences", headers=auth_headers).json() == {"scope": "global", "revision": 0, "values": {}}
    first = save(client, auth_headers, {"typography": {"fontSize": 22}, "layout": "paged"})
    assert first.status_code == 200
    assert first.json()["revision"] == 1
    assert save(client, auth_headers, {"typography": {"fontSize": 22}, "layout": "paged"}).json() == first.json()
    stale = save(client, auth_headers, {"typography": {"fontSize": 18}}, operation="other-device")
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"] == first.json()
    assert db.query(ReaderPreference).one().values["typography"]["fontSize"] == 22
    second = save(client, auth_headers, {"typography": {"fontSize": 18}}, revision=1, operation="reconcile")
    assert second.json()["revision"] == 2
    assert save(client, auth_headers, {"typography": {"fontSize": 22}, "layout": "paged"}).json() == first.json()
    assert save(client, auth_headers, {"typography": {"fontSize": 20}}).status_code == 409


def test_story_overrides_reset_with_a_revision_and_require_ownership(client, db, test_library, test_user, auth_headers):
    from app.models.library import Library
    from app.models.user import User
    novel = Novel(title="Own", library_id=test_library.id)
    other_user = User(username="other-reader", password="unused")
    db.add_all([novel, other_user])
    db.flush()
    other_library = Library(name="Other", user_id=other_user.id)
    db.add(other_library)
    db.flush()
    other_novel = Novel(title="Private", library_id=other_library.id)
    db.add(other_novel)
    db.commit()
    route = f"/reader/preferences/stories/{novel.id}"
    first = save(client, auth_headers, {"typography": {"theme": "sepia"}}, route=route)
    assert first.json()["values"] == {"typography": {"theme": "sepia"}}
    reset = save(client, auth_headers, {"typography": None}, 1, "reset-story", route)
    assert reset.json() == {"scope": f"story:{novel.id}", "revision": 2, "values": {}}
    assert save(client, auth_headers, {"layout": "paged"}, 2, "wrong-scope", route).status_code == 422
    other_route = f"/reader/preferences/stories/{other_novel.id}"
    assert client.get(other_route, headers=auth_headers).status_code == 404
    assert save(client, auth_headers, {}, operation="other-story", route=other_route).status_code == 404
    assert db.query(ReaderPreference).filter_by(user_id=other_user.id).count() == 0


def test_typography_contract_rejects_unknown_fields_and_invalid_sizes(client, auth_headers):
    for values in ({"typography": {"fontSize": 200}}, {"typography": {"font": "untrusted"}}, {"api_key": "not-a-preference"}):
        assert save(client, auth_headers, values).status_code == 422


def test_reader_settings_are_portable_and_import_never_overwrites_a_local_choice(client, db, test_user, test_library, auth_headers):
    novel = Novel(title="Exported", url="https://www.royalroad.com/fiction/123/exported", library_id=test_library.id)
    db.add(novel)
    db.commit()
    save(client, auth_headers, {"typography": {"fontSize": 22}, "layout": "paged"})
    save(client, auth_headers, {"typography": {"theme": "sepia"}}, operation="story-export", route=f"/reader/preferences/stories/{novel.id}")
    document = client.get("/me/export", headers=auth_headers).json()
    assert document["reader_preferences"] == {"typography": {"fontSize": 22}, "layout": "paged"}
    assert document["libraries"][0]["novels"][0]["reader_typography"] == {"theme": "sepia"}
    assert "scope" not in str(document)
    db.query(ReaderPreference).filter_by(user_id=test_user.id).delete()
    db.commit()
    first = client.post("/me/import", headers=auth_headers, json=document)
    assert first.status_code == 200
    assert first.json()["reader_preferences"] == "applied"
    second = client.post("/me/import", headers=auth_headers, json=document)
    assert second.json()["reader_preferences"] == "unchanged"
    save(client, auth_headers, {"typography": {"fontSize": 26}}, revision=1, operation="local-after-import")
    third = client.post("/me/import", headers=auth_headers, json=document)
    assert third.json()["reader_preferences"] == "kept_local"
    assert client.get("/reader/preferences", headers=auth_headers).json()["values"]["typography"]["fontSize"] == 26
