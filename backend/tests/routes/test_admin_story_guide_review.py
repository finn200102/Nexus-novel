from unittest.mock import AsyncMock, patch

import pytest

from tests.auth_helpers import bearer_headers
from app.models.user import User


def _headers(user_id: int) -> dict[str, str]:
    return bearer_headers(user_id)


@pytest.fixture
def admin_user(db):
    user = User(username="story-guide-admin", password="hashed", is_admin=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


REVIEW_ROUTES = [
    ("GET", "/admin/integrations/story-guides/42/review-queue", None),
    ("GET", "/admin/integrations/story-guides/42/review-history", None),
    (
        "POST",
        "/admin/integrations/story-guides/assertions/ch-1:character:arya/review",
        {"review_state": "approved"},
    ),
    (
        "POST",
        "/admin/integrations/story-guides/assertions/ch-1:character:arya/restore",
        {"reason": "Re-open for editorial review"},
    ),
]


@pytest.mark.parametrize("method,path,payload", REVIEW_ROUTES)
def test_story_guide_review_bridge_requires_authentication(client, method, path, payload):
    response = client.request(method, path, json=payload)

    assert response.status_code == 401


@pytest.mark.parametrize("method,path,payload", REVIEW_ROUTES)
def test_story_guide_review_bridge_rejects_non_admin(client, test_user, method, path, payload):
    response = client.request(method, path, headers=_headers(test_user.id), json=payload)

    assert response.status_code == 403
    assert response.json()["detail"] == "Administrator access required"


def test_review_queue_forwards_novel_id_and_returns_metadata_payload(client, admin_user):
    upstream = {"items": [{"assertion_id": "ch-1:character:arya", "review_state": "machine_suggested"}]}
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(return_value=upstream),
    ) as metadata_admin:
        response = client.get(
            "/admin/integrations/story-guides/42/review-queue",
            headers=_headers(admin_user.id),
        )

    assert response.status_code == 200
    assert response.json() == upstream
    metadata_admin.assert_awaited_once_with(
        "GET", "/analysis/novels/42/story-guide/review-queue"
    )


def test_review_history_clamps_limit_before_forwarding(client, admin_user):
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(return_value={"items": []}),
    ) as metadata_admin:
        response = client.get(
            "/admin/integrations/story-guides/42/review-history?limit=9999",
            headers=_headers(admin_user.id),
        )

    assert response.status_code == 200
    metadata_admin.assert_awaited_once_with(
        "GET",
        "/analysis/novels/42/story-guide/review-history",
        params={"limit": 500},
    )


def test_review_history_clamps_non_positive_limit(client, admin_user):
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(return_value={"items": []}),
    ) as metadata_admin:
        response = client.get(
            "/admin/integrations/story-guides/42/review-history?limit=0",
            headers=_headers(admin_user.id),
        )

    assert response.status_code == 200
    metadata_admin.assert_awaited_once_with(
        "GET",
        "/analysis/novels/42/story-guide/review-history",
        params={"limit": 1},
    )


def test_review_action_forwards_review_state_and_reason_as_query_params(client, admin_user):
    upstream = {"assertion_id": "ch-1:character:arya", "review_state": "approved"}
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(return_value=upstream),
    ) as metadata_admin:
        response = client.post(
            "/admin/integrations/story-guides/assertions/ch-1:character:arya/review",
            headers=_headers(admin_user.id),
            json={"review_state": "approved", "reason": "Confirmed against chapter 1"},
        )

    assert response.status_code == 200
    assert response.json() == upstream
    metadata_admin.assert_awaited_once_with(
        "POST",
        "/analysis/story-guide/assertions/ch-1:character:arya/review",
        params={"review_state": "approved", "reason": "Confirmed against chapter 1"},
    )


def test_review_action_rejects_unknown_review_state(client, admin_user):
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(),
    ) as metadata_admin:
        response = client.post(
            "/admin/integrations/story-guides/assertions/ch-1:character:arya/review",
            headers=_headers(admin_user.id),
            json={"review_state": "published"},
        )

    assert response.status_code == 422
    metadata_admin.assert_not_awaited()


def test_restore_action_forwards_optional_reason(client, admin_user):
    upstream = {"assertion_id": "ch-1:character:arya", "review_state": "machine_suggested"}
    with patch(
        "app.routers.admin_integrations.metadata_admin",
        new=AsyncMock(return_value=upstream),
    ) as metadata_admin:
        response = client.post(
            "/admin/integrations/story-guides/assertions/ch-1:character:arya/restore",
            headers=_headers(admin_user.id),
            json={},
        )

    assert response.status_code == 200
    assert response.json() == upstream
    metadata_admin.assert_awaited_once_with(
        "POST",
        "/analysis/story-guide/assertions/ch-1:character:arya/restore",
        params={},
    )
