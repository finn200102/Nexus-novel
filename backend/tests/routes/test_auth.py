import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
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

