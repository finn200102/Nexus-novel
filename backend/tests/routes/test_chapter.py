import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
from app.services.novel_services import *
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

def create_test_novel(db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url,
                  "title": "title1"}
    # create lib
    library = create_test_library(db)
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)
    # get auth header
    user_id = library.user_id
    headers = get_auth_headers(user_id)

    return novel, headers, novel_data, url, library


def get_auth_headers(user_id):
    """Generate authorization headers for a user"""
    token = create_access_token(data={"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}

def add_chapter(client, novel_id, headers):
    # Chapter
    chapter_data = {"novel_id": novel_id,
                    "chapter_number": 1,
                    "title": "aaa",
                    "content_status": "MISSING"}
    
    response = client.post("/chapter/", json=chapter_data, headers=headers)
    return response


def test_add_chapter(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)


    assert response.status_code == status.HTTP_201_CREATED
    
    chapters = get_chapters_by_novel_id(db, novel.id)
    print(chapters.first())
    assert chapters.first() is not None


def test_get_chapters(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)

    # get chapter
    response = client.get(f"/chapter/{novel.id}",
                          headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    chapters = response.json()
    assert chapters is not None
    print(chapters)

    # Verify the created chapter is in the response
    found = False
    for chapter in chapters:
        if chapter["title"] == "aaa":
            found = True
            break
    assert found, "Created chapter not found in the response"





