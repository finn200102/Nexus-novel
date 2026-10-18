from fastapi import status

from tests.routes.test_chapter import create_test_novel


def test_legacy_numeric_progress_does_not_authorize_unverified_chapter_titles(client, db):
    novel, headers, _, _, _ = create_test_novel(db)
    for number in (1, 2, 3):
        response = client.post(
            "/chapter/",
            json={"novel_id": novel.id, "chapter_number": number, "title": f"Chapter {number}", "content_status": "MISSING"},
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED

    client.put(
        f"/chapter/progress/{novel.id}",
        json={"chapter_number": 2, "position": 0, "percent": 50},
        headers=headers,
    )

    response = client.get(f"/chapter/recap/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    # Missing bodies and a partial numeric position prove neither an exact
    # edition nor completed chapters. Even their titles remain out of the recap.
    assert body["spoiler_boundary_chapter"] is None
    assert body["chapters"] == []


def test_recap_without_progress_has_no_chapters(client, db):
    novel, headers, _, _, _ = create_test_novel(db)
    client.post(
        "/chapter/",
        json={"novel_id": novel.id, "chapter_number": 1, "title": "Chapter 1", "content_status": "MISSING"},
        headers=headers,
    )

    response = client.get(f"/chapter/recap/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["spoiler_boundary_chapter"] is None
    assert response.json()["chapters"] == []


def test_recap_includes_only_completed_verified_chapters_before_partial_progress(client, db):
    from app.models import Chapter
    from app.services.chapter_document import from_text
    from app.services.reading_progress_service import save_reading_progress

    novel, headers, _, _, library = create_test_novel(db)
    chapters = {}
    for number, title in ((1, "Known arrival"), (2, "UNREAD_PARTIAL_IDENTITY"), (3, "UNREAD_FUTURE_ENDING")):
        document = from_text(f"Text for {title}.")
        chapter = Chapter(novel_id=novel.id, chapter_number=number, title=title,
                          content=document["plain_text"], document=document)
        db.add(chapter)
        db.flush()
        chapters[number] = chapter
    db.commit()
    for number, percent in ((1, 100), (2, 50)):
        chapter = chapters[number]
        save_reading_progress(db, user_id=library.user_id, chapter=chapter,
                              position=0, percent=percent,
                              content_version=chapter.document["content_version"])

    response = client.get(f"/chapter/recap/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["spoiler_boundary_chapter"] == 1
    assert [chapter["number"] for chapter in response.json()["chapters"]] == [1]
    assert "UNREAD_" not in response.text
