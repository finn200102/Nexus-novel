from unittest.mock import AsyncMock, patch

from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from tests.auth_helpers import bearer_headers


def _add_novel(db, *, library_id: int, metadata_id: int) -> Novel:
    novel = Novel(
        title="Reader-safe guide test",
        url=f"https://example.test/novel/{metadata_id}",
        metadata_id=metadata_id,
        library_id=library_id,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _guide_response(*, cutoff: int) -> dict:
    return {"safe_through_chapter": cutoff, "items": []}


def _headers(user_id: int) -> dict[str, str]:
    return bearer_headers(user_id)


def test_story_guide_clamps_requested_cutoff_to_reading_progress(
    client, db, test_user, test_library
):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=701)
    db.add(
        ReadingProgress(
            user_id=test_user.id,
            novel_id=novel.id,
            chapter_number=4,
            percent=1,
        )
    )
    db.commit()

    metadata_guide = AsyncMock(return_value=_guide_response(cutoff=4))
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide",
        metadata_guide,
    ):
        response = client.get(
            "/discovery/novels/701/story-guide?through_chapter=99",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    metadata_guide.assert_awaited_once_with(701, 4)


def test_story_guide_without_library_or_progress_uses_cutoff_zero(
    client, db, test_user
):
    metadata_guide = AsyncMock(return_value=_guide_response(cutoff=0))
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide",
        metadata_guide,
    ):
        response = client.get(
            "/discovery/novels/702/story-guide?through_chapter=7",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    metadata_guide.assert_awaited_once_with(702, 0)


def test_story_guide_preserves_lower_requested_cutoff(
    client, db, test_user, test_library
):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=703)
    db.add(
        ReadingProgress(
            user_id=test_user.id,
            novel_id=novel.id,
            chapter_number=4,
            percent=1,
        )
    )
    db.commit()

    metadata_guide = AsyncMock(return_value=_guide_response(cutoff=2))
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide",
        metadata_guide,
    ):
        response = client.get(
            "/discovery/novels/703/story-guide?through_chapter=2",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    metadata_guide.assert_awaited_once_with(703, 2)


def test_story_guide_hides_the_current_unfinished_chapter(client, db, test_user, test_library):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=704)
    db.add(ReadingProgress(user_id=test_user.id, novel_id=novel.id, chapter_number=4, percent=.37))
    db.commit()

    metadata_guide = AsyncMock(return_value=_guide_response(cutoff=3))
    with patch("app.routers.discovery.metadata_client.get_story_guide", metadata_guide):
        response = client.get("/discovery/novels/704/story-guide", headers=_headers(test_user.id))

    assert response.status_code == 200
    metadata_guide.assert_awaited_once_with(704, 3)


def test_chapter_dossier_is_clamped_to_reader_progress(client, db, test_user, test_library):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=705)
    db.add(ReadingProgress(user_id=test_user.id, novel_id=novel.id, chapter_number=5, percent=1))
    db.commit()

    dossier = AsyncMock(return_value={"chapter": 4, "status": "ready"})
    with patch("app.routers.discovery.metadata_client.get_story_guide_chapter_dossier", dossier):
        response = client.get(
            "/discovery/novels/705/story-guide/chapters/4?through_chapter=999",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    dossier.assert_awaited_once_with(705, 4, 5)


def test_entity_article_is_hidden_without_reader_progress(client, test_user):
    article = AsyncMock(return_value={"entity": None, "through_chapter": 0})
    with patch("app.routers.discovery.metadata_client.get_story_guide_entity_article", article):
        response = client.get(
            "/discovery/novels/706/story-guide/entities/entity-1?through_chapter=9",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    article.assert_awaited_once_with(706, "entity-1", 0)


def test_story_guide_changes_clamps_cutoff_and_preserves_baseline(
    client, db, test_user, test_library
):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=707)
    db.add(
        ReadingProgress(
            user_id=test_user.id,
            novel_id=novel.id,
            chapter_number=4,
            percent=1,
        )
    )
    db.commit()

    payload = {
        "from_chapter": 2,
        "through_chapter": 4,
        "count": 1,
        "changes": {"characters": [{"chapter": 3, "summary": "A change"}]},
    }
    metadata_changes = AsyncMock(return_value=payload)
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide_changes",
        metadata_changes,
    ):
        response = client.get(
            "/discovery/novels/707/story-guide/changes"
            "?from_chapter=2&through_chapter=99",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    assert response.json() == payload
    metadata_changes.assert_awaited_once_with(707, 2, 4)


def test_story_guide_entity_profile_clamps_to_unfinished_reader_progress(
    client, db, test_user, test_library
):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=708)
    db.add(
        ReadingProgress(
            user_id=test_user.id,
            novel_id=novel.id,
            chapter_number=4,
            percent=0.37,
        )
    )
    db.commit()

    payload = {
        "entity": {"id": "entity-1", "name": "Aster"},
        "through_chapter": 3,
        "facts": [],
    }
    metadata_profile = AsyncMock(return_value=payload)
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide_entity_profile",
        metadata_profile,
    ):
        response = client.get(
            "/discovery/novels/708/story-guide/entities/entity-1/profile"
            "?through_chapter=99",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    assert response.json() == payload
    metadata_profile.assert_awaited_once_with(708, "entity-1", 3)


def test_story_guide_relationship_timeline_clamps_cutoff_and_forwards_entity_filter(
    client, db, test_user, test_library
):
    novel = _add_novel(db, library_id=test_library.id, metadata_id=709)
    db.add(
        ReadingProgress(
            user_id=test_user.id,
            novel_id=novel.id,
            chapter_number=5,
            percent=1,
        )
    )
    db.commit()

    payload = {
        "through_chapter": 5,
        "relationships": [
            {"from": "Aster", "to": "Bram", "chapter": 4, "status": "ally"}
        ],
    }
    metadata_timeline = AsyncMock(return_value=payload)
    with patch(
        "app.routers.discovery.metadata_client.get_story_guide_relationship_timeline",
        metadata_timeline,
    ):
        response = client.get(
            "/discovery/novels/709/story-guide/relationships/timeline"
            "?through_chapter=99&entity_id=entity-1",
            headers=_headers(test_user.id),
        )

    assert response.status_code == 200
    assert response.json() == payload
    metadata_timeline.assert_awaited_once_with(709, 5, "entity-1")
