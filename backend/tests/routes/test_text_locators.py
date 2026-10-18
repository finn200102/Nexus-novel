import hashlib
import json
from datetime import datetime

from app.models.chapter import Chapter, ContentStatus
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgressOperation
from app.services.chapter_document import from_html


def story(db, library):
    novel = Novel(title="Anchored story", library_id=library.id, url="https://www.royalroad.com/fiction/123/anchored")
    db.add(novel); db.flush()
    document = from_html("<p>Before the exact saved passage. After the passage.</p>")
    chapter = Chapter(novel_id=novel.id, chapter_number=1, content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    return novel, chapter, document


def payload(document, **overrides):
    return {"chapter_number": 1, "position": 840, "percent": 50, "expected_revision": 0, "operation_id": "anchor-save",
        "content_version": document["content_version"], "block_id": document["blocks"][0]["id"], "text_offset": 11,
        "text_quote": "exact saved passage. After the passage.", "quote_prefix": "Before the", "quote_suffix": "",
        "locator_variant": "original", **overrides}


def test_progress_and_annotations_preserve_context_and_idempotent_replays(client, db, test_library, auth_headers):
    novel, _, document = story(db, test_library)
    route = f"/chapter/progress/{novel.id}"
    request = payload(document)
    saved = client.put(route, headers=auth_headers, json=request)
    assert saved.status_code == 200
    assert saved.json()["locator_content_version"] == document["content_version"]
    assert saved.json()["text_offset"] == 11 and saved.json()["text_quote"] == request["text_quote"]
    assert client.put(route, headers=auth_headers, json=request).json() == saved.json()
    altered = {**request, "quote_prefix": "Different context"}
    assert client.put(route, headers=auth_headers, json=altered).status_code == 409
    annotation = {key: request[key] for key in ("chapter_number", "block_id", "text_offset", "text_quote", "quote_prefix", "quote_suffix", "locator_variant")}
    annotation.update(annotation_type="note", quote="exact saved passage", note="Retain this anchor", locator_content_version=document["content_version"])
    note = client.post(f"/chapter/annotations/{novel.id}", headers=auth_headers, json=annotation)
    assert note.status_code == 201
    assert note.json()["text_quote"] == request["text_quote"]
    exported = client.get("/me/export", headers=auth_headers).json()["libraries"][0]["novels"][0]
    assert exported["progress"]["text_quote"] == request["text_quote"]
    assert exported["annotations"][0]["locator_content_version"] == document["content_version"]


def test_revised_text_cannot_be_marked_read_by_replaying_an_old_locator(client, db, test_user, test_library, auth_headers):
    novel, chapter, document = story(db, test_library)
    route = f"/chapter/progress/{novel.id}"
    assert client.put(route, headers=auth_headers, json=payload(document)).status_code == 200
    revised = from_html("<p>A new opening. Before the exact saved passage. After the passage.</p>")
    chapter.document, chapter.content = revised, revised["plain_text"]
    db.commit()
    stale = payload(document, expected_revision=1, operation_id="old-completion", percent=100)
    assert client.put(route, headers=auth_headers, json=stale).status_code == 409
    stale["intent"] = "reconcile"
    kept = client.put(route, headers=auth_headers, json=stale)
    assert kept.status_code == 200
    assert kept.json()["locator_content_version"] == document["content_version"]
    assert not db.query(ChapterReadReceipt).filter_by(content_version=revised["content_version"], user_id=test_user.id).first()
    reviewed = payload(revised, expected_revision=2, operation_id="new-version", percent=100)
    assert client.put(route, headers=auth_headers, json=reviewed).status_code == 200
    db.expire_all()
    receipt = db.query(ChapterReadReceipt).filter_by(content_version=revised["content_version"], user_id=test_user.id).one()
    assert not receipt.completed and receipt.requires_review
    reviewed.update(expected_revision=3, operation_id="explicit-review", intent="confirm_read")
    assert client.put(route, headers=auth_headers, json=reviewed).status_code == 200
    db.expire_all()
    assert db.get(ChapterReadReceipt, receipt.id).completed


def test_legacy_operation_receipts_remain_replayable_after_locator_migration(client, db, test_user, test_library, auth_headers):
    novel, chapter, _ = story(db, test_library)
    signature = hashlib.sha256(json.dumps([chapter.id, 10, 25.0, None, 0, "automatic"]).encode()).hexdigest()
    db.add(ReadingProgressOperation(user_id=test_user.id, novel_id=novel.id, operation_id="legacy-save", fingerprint=signature,
        response={"novel_id": novel.id, "chapter_number": 1, "position": 10, "percent": 25, "revision": 1,
                  "updated_at": datetime.utcnow().isoformat()}))
    db.commit()
    response = client.put(f"/chapter/progress/{novel.id}", headers=auth_headers, json={"chapter_number": 1, "position": 10,
        "percent": 25, "operation_id": "legacy-save", "expected_revision": 0})
    assert response.status_code == 200
    assert response.json()["locator_content_version"] is None
    assert response.json()["position"] == 10


def test_locator_payloads_are_bounded(client, db, test_library, auth_headers):
    novel, _, document = story(db, test_library)
    for extra in ({"text_quote": "x" * 241}, {"quote_prefix": "x" * 81}, {"locator_variant": "untrusted:123"}, {"text_offset": 16_000_001}):
        assert client.put(f"/chapter/progress/{novel.id}", headers=auth_headers, json=payload(document, **extra)).status_code == 422
