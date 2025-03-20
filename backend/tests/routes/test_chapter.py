import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
from app.services.novel_services import get_novel_by_url
from app.services.chapter_services import get_chapters_by_novel_id
from app.services.library_services import create_library
from app.services.user_services import create_user
from app.auth.jwt import create_access_token

def create_test_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    return user

def create_test_library(db):
    user = create_test_user(db)
    library_data = {
        "name": "Library1",
        "user_id": user.id
        }
    library = create_library(db, library_data)
    return library

def get_auth_headers(user_id):
    """Generate authorization headers for a user"""
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def add_novel_resources(client, db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}
    # create lib
    library = create_test_library(db)
    novel_data["library_id"] = library.id

    # get auth header
    user_id = library.user_id
    headers = get_auth_headers(user_id)


    # Make request
    response = client.post("/novel/", json=novel_data, headers=headers)

    return response, headers, novel_data, url, library


def test_add_chapter(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # Chapter
    chapter_data = {"novel_id": db_novel.id,
                    "chapter_number": 1,
                    "title": "",
                    "content_status": "MISSING"}
    
    response = client.post("/chapter/", json=chapter_data, headers=headers)
    assert response.status_code == status.HTTP_201_CREATED
    
    chapters = get_chapters_by_novel_id(db, db_novel.id)
    print(chapters.first())
    assert chapters.first() is not None


