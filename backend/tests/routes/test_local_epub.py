import base64
from io import BytesIO
from zipfile import ZipFile
from app.models.chapter import Chapter


def book():
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>')
        archive.writestr("book.opf", '<package><metadata><title>Local story</title><creator>Author</creator></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>')
        archive.writestr("one.xhtml", '<html><head><title>Ignored</title></head><body><h1>Arrival</h1><p>A <strong>new</strong> home.</p></body></html>')
    return data.getvalue()


def test_local_epub_is_readable_without_source_and_reimport_is_duplicate(client, db, test_user, test_library, auth_headers):
    payload = {"library_id": test_library.id, "files": [{"name": "local.epub", "data_base64": base64.b64encode(book()).decode()}]}
    response = client.post("/imports/epub", json=payload, headers=auth_headers)
    assert response.status_code == 202
    report = client.get(f'/imports/{response.json()["id"]}', headers=auth_headers).json()
    item = report["items"][0]
    assert item["status"] == "linked"
    chapter = db.query(Chapter).filter_by(novel_id=item["novel_id"]).one()
    assert "<strong>new</strong>" in chapter.document["blocks"][1]["html"]
    content = client.get(f'/chapter/content/library/{test_library.id}/{item["novel_id"]}/1', headers=auth_headers)
    assert content.status_code == 200
    assert content.json()["document"]["schema_version"] == 1
    again = client.post("/imports/epub", json=payload, headers=auth_headers)
    assert again.json()["counts"]["duplicate"] == 1


def test_image_only_imported_pages_are_readable(client, db, test_library, auth_headers):
    from app.models.novel import Novel
    from app.models.chapter import ContentStatus
    from app.services.chapter_document import from_html
    novel = Novel(title="Illustrated book", library_id=test_library.id, url="nexus-local:illustrated", novel_site="local")
    db.add(novel)
    db.flush()
    document = from_html('<img alt="Illustration" src="data:image/png;base64,aGVsbG8="/>')
    db.add(Chapter(novel_id=novel.id, chapter_number=1, title="Illustration", content="", document=document, content_status=ContentStatus.PRESENT))
    db.commit()
    response = client.get(f"/chapter/content/library/{test_library.id}/{novel.id}/1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["document"]["blocks"] == document["blocks"]


def test_exported_rich_author_notes_survive_epub_reimport(db, test_library):
    from app.models.novel import Novel
    from app.models.chapter import ContentStatus
    from app.services.chapter_document import from_html
    from app.services.epub_service import render_epub
    from app.services.local_epub import read_epub
    novel = Novel(title="Notes book", library_id=test_library.id, url="nexus-local:notes", novel_site="local")
    db.add(novel); db.flush()
    document = from_html('<p>Story.</p><aside class="author-note"><p>A <em>rich</em> note.</p></aside>')
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Opening", content=document["plain_text"], document=document, content_status=ContentStatus.PRESENT)
    db.add(chapter); db.commit()
    parsed = read_epub(render_epub(novel, [chapter]))
    notes = [block for block in parsed["chapters"][0]["document"]["blocks"] if block.get("role") == "author_note"]
    assert len(notes) == 1 and "<em>rich</em>" in notes[0]["html"]
