import pytest
from fastapi import status
from app.services.user_services import get_user_by_username
from app.services.user_services import get_user_by_id
from app.auth.jwt import verify_token


def test_signup_success(client, db):
    # Test data
    user_data = {"username": "testuser", "password": "password123"}

    # Make request
    response = client.post("/auth/signup", json=user_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["username"] == "testuser"
    assert "id" in response.json()
    assert response.json()["access_token"]

    # Verify user was created in the test database
    from app.services.user_services import get_user_by_username
    db_user = get_user_by_username(db, "testuser").first()
    assert db_user is not None
    assert db_user.username == "testuser"


def test_signup_username_exists(client, db):
    # First create a user
    user_data = {"username": "existinguser", "password": "password123"}
    client.post("/auth/signup", json=user_data)

    # Try to create another user with the same username
    response = client.post("/auth/signup", json=user_data)

    # Assertions
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Username already registered" in response.json()["detail"]


def test_login_success(client, db):
    # Test data
    user_data = {"username": "testuser", "password": "password123"}

    # Make request to create user
    response = client.post("/auth/signup", json=user_data)

    # Assertions for signup
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["username"] == "testuser"
    assert "id" in response.json()
    assert response.json()["access_token"]

    # Verify user was created in the test database
    from app.services.user_services import get_user_by_username
    db_user = get_user_by_username(db, "testuser").first()
    assert db_user is not None
    assert db_user.username == "testuser"

    # Make login request
    response = client.post("/auth/login", json=user_data)

    # Assertions for login
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == "testuser"
    assert "id" in response.json()
    assert response.json()["message"] == "Login successful"
    token = response.json()["access_token"]
    assert token is not None
    print("Token:", token)
    # Verify the token manually
    token_data = verify_token(token)

    # Get the user from the database

    user = get_user_by_id(db, token_data["user_id"])
    print(user) 

    # Verify the returned ID matches the created user
    assert response.json()["id"] == db_user.id


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "shortpass", "password": "1234567"},
        {"username": "longpass", "password": "x" * 73},
        {"username": "   ", "password": "password123"},
    ],
)
def test_signup_rejects_invalid_credentials(client, db, payload):
    response = client.post("/auth/signup", json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_insecure_default_secret_is_replaced_by_persisted_key(tmp_path, monkeypatch):
    from config.settings import Settings

    monkeypatch.delenv("NEXUS_SECRET_KEY_FILE", raising=False)
    first = Settings(SECRET_KEY="nexus-local-development-secret-change-me", DOWNLOAD_PATH=str(tmp_path))
    second = Settings(SECRET_KEY="", DOWNLOAD_PATH=str(tmp_path))

    assert first.SECRET_KEY == second.SECRET_KEY
    assert len(first.SECRET_KEY) >= 32
    assert (tmp_path / ".nexus-secret-key").stat().st_mode & 0o777 == 0o600
    assert Settings(SECRET_KEY="operator-chosen", DOWNLOAD_PATH=str(tmp_path)).SECRET_KEY == "operator-chosen"

