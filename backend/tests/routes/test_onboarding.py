from unittest.mock import patch
from app.models import Chapter, ChapterReadReceipt, Library, Novel, User
from app.models.import_job import ImportJob
from tests.auth_helpers import bearer_headers


def test_demo_is_explicit_private_readable_and_retry_safe(client, db, test_library, auth_headers):
    assert db.query(Novel).count() == 0
    with patch("httpx.get", side_effect=AssertionError("Demo must not fetch sources")), patch("httpx.post", side_effect=AssertionError("Demo must not call models")):
        response = client.post("/onboarding/demo", headers=auth_headers, json={"library_id": test_library.id})
        assert response.status_code == 200
        result = response.json()
        assert result["license"] == "CC0-1.0" and len(result["stories"]) == 2
        assert all(row["created"] for row in result["stories"])
        first = result["stories"][0]
        content = client.get(f"/chapter/content/library/{test_library.id}/{first['novel_id']}/1", headers=auth_headers)
        assert content.status_code == 200
        assert "lighthouse" in content.json()["content"]
        assert "<em>" in str(content.json()["document"]) and len(content.json()["document"]["content_version"]) == 64
        again = client.post("/onboarding/demo", headers=auth_headers, json={"library_id": test_library.id}).json()
        assert [row["novel_id"] for row in again["stories"]] == [row["novel_id"] for row in result["stories"]]
        assert not any(row["created"] for row in again["stories"])
    assert db.query(Novel).count() == 2 and db.query(Chapter).count() == 3
    assert db.query(ImportJob).count() == 0 and db.query(ChapterReadReceipt).count() == 0
    assert all(row.metadata_id is None and row.site == "local" for row in db.query(Novel))


def test_demo_cannot_write_to_another_account_or_begin_an_unauthenticated_import(client, db, test_library, auth_headers):
    other = User(username="other-demo-reader", password="unused")
    db.add(other); db.flush()
    private = Library(name="Private demo", user_id=other.id)
    db.add(private); db.commit()
    assert client.post("/onboarding/demo", json={"library_id": test_library.id}).status_code == 401
    assert client.post("/onboarding/demo", headers=auth_headers, json={"library_id": private.id}).status_code == 404
    assert db.query(Novel).count() == 0
    response = client.post("/onboarding/demo", headers=bearer_headers(other.id, db), json={"library_id": private.id})
    assert response.status_code == 200
    assert db.query(Novel).filter_by(library_id=test_library.id).count() == 0


def test_signup_and_repeated_login_have_one_default_library(client, db):
    credentials = {"username": "new-home-reader", "password": "Long-demonstration-password-42"}
    signed = client.post("/auth/signup", json=credentials)
    assert signed.status_code == 201
    user = db.query(User).filter_by(username=credentials["username"]).one()
    assert db.query(Library).filter_by(user_id=user.id).count() == 1
    for _ in range(2):
        assert client.post("/auth/login", json=credentials).status_code == 200
    assert db.query(Library).filter_by(user_id=user.id).one().name == "My library"
