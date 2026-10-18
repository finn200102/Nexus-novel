from app.models.chapter import Chapter, ContentStatus
from app.models.chapter_version import ChapterVersion
from app.models.novel import Novel
from app.services.chapter_document import from_html
from app.services.chapter_services import update_chapter


def fixture(db, library):
    novel = Novel(title="Revision history", library_id=library.id, url="nexus-local:versions")
    db.add(novel); db.flush()
    original = from_html("<p>The <em>original</em> passage.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Opening", content=original["plain_text"], document=original, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    return novel, chapter, original


def test_replacement_preserves_original_and_current_versions(client, db, test_library, auth_headers):
    novel, chapter, original = fixture(db, test_library)
    replacement = from_html("<p>The revised passage.</p>")
    update_chapter(db, chapter.id, {"content": replacement["plain_text"], "document": replacement})
    route = f"/chapter/versions/{novel.id}/1"
    listing = client.get(route, headers=auth_headers)
    assert listing.status_code == 200
    versions = listing.json()["versions"]
    assert [item["content_version"] for item in versions] == [replacement["content_version"], original["content_version"]]
    assert versions[0]["current"] and not versions[1]["current"]
    assert versions[1]["byte_count"] > len(original["plain_text"]) and versions[1]["saved_at"]
    archived = client.get(route + "/" + original["content_version"], headers=auth_headers).json()
    assert archived["document"] == original and archived["content"] == original["plain_text"]
    assert client.get(route + "/" + replacement["content_version"], headers=auth_headers).json()["document"] == replacement
    assert client.get(route + "/" + "f" * 64, headers=auth_headers).status_code == 404
    assert client.get(route + "/invalid", headers=auth_headers).status_code == 422
    from app.models.chapter_read_receipt import ChapterReadReceipt
    from app.models.reading_progress import ReadingProgressOperation
    assert db.query(ChapterReadReceipt).count() == 0
    assert db.query(ReadingProgressOperation).count() == 0


def test_repeated_revisions_are_idempotent_and_pagination_preserves_all_versions(client, db, test_library, auth_headers):
    novel, chapter, original = fixture(db, test_library)
    versions = [original]
    for index in range(5):
        document = from_html(f"<p>Revision {index}.</p>")
        update_chapter(db, chapter.id, {"document": document, "content": document["plain_text"]})
        versions.append(document)
    update_chapter(db, chapter.id, {"document": original, "content": original["plain_text"]})
    update_chapter(db, chapter.id, {"document": original, "content": original["plain_text"]})
    assert db.query(ChapterVersion).count() == 6
    route = f"/chapter/versions/{novel.id}/1?limit=2"
    hashes = []
    while True:
        response = client.get(route, headers=auth_headers).json()
        hashes += [row["content_version"] for row in response["versions"]]
        if response["next_cursor"] is None:
            break
        route = f"/chapter/versions/{novel.id}/1?limit=2&cursor={response['next_cursor']}"
    assert len(hashes) == len(set(hashes)) == 6
    assert set(hashes) == {item["content_version"] for item in versions}


def test_plain_text_replacement_clears_stale_rich_document_and_rollbacks_are_atomic(db, test_library):
    _, chapter, original = fixture(db, test_library)
    update_chapter(db, chapter.id, {"content": "New plain text"})
    assert chapter.document["plain_text"] == "New plain text"
    assert db.query(ChapterVersion).one().document == original
    from app.services.chapter_version_service import retain_current
    retain_current(db, chapter)
    chapter.content = "A transaction that fails"
    db.rollback(); db.refresh(chapter)
    assert chapter.content == "New plain text" and db.query(ChapterVersion).count() == 1


def test_versions_require_owning_library_and_delete_with_the_private_story(client, db, test_library, auth_headers):
    from app.models.user import User
    from tests.auth_helpers import bearer_headers
    other = User(username="other-version-reader", password="unused")
    db.add(other); db.commit()
    other_user_headers = bearer_headers(other.id, db)
    novel, chapter, _ = fixture(db, test_library)
    update_chapter(db, chapter.id, {"content": "Replacement"})
    route = f"/chapter/versions/{novel.id}/1"
    assert client.get(route, headers=other_user_headers).status_code == 403
    version = db.query(ChapterVersion).one().content_version
    assert client.get(route + "/" + version, headers=other_user_headers).status_code == 403
    db.delete(novel); db.commit()
    assert db.query(ChapterVersion).count() == 0
