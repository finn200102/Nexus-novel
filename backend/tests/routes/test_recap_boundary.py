from fastapi import status

from tests.routes.test_chapter import create_test_novel


def test_recap_never_includes_chapters_after_the_last_read_chapter(client, db):
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
    assert body["spoiler_boundary_chapter"] == 2
    assert [chapter["number"] for chapter in body["chapters"]] == [1, 2]


def test_recap_without_progress_has_no_chapters(client, db):
    novel, headers, _, _, _ = create_test_novel(db)
    client.post(
        "/chapter/",
        json={"novel_id": novel.id, "chapter_number": 1, "title": "Chapter 1", "content_status": "MISSING"},
        headers=headers,
    )

    response = client.get(f"/chapter/recap/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["spoiler_boundary_chapter"] == 0
    assert response.json()["chapters"] == []
