import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
from app.services.novel_services import get_novel_by_url
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


def test_add_novel(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url


def test_add_novel_unauthorized(client, db):
    """Test that adding a novel fails without authentication"""
    # Create a user and library
    user = create_test_user(db)
    library = create_test_library(db)

    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {
        "url": url,
        "library_id": library.id
    }

    # Make request without auth
    response = client.post("/novel/", json=novel_data)

    # Should fail with 401 Unauthorized
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Verify novel was not created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is None



def test_get_novels(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)
    
    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client.get(f"/novel/?library_id={library.id}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    assert response.status_code == 200
    novels = response.json()
    assert novels is not None
    assert len(novels) > 0

    # Verify the created novel is in the response
    found = False
    for novel in novels:
        if novel["url"] == url:
            found = True
            break
    assert found, "Created novel not found in the response"



def test_get_novel_by_id(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)
    
    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client.get(f"/novel/{db_novel.id}?library_id={library.id}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    assert response.status_code == 200
    novel = response.json()
    assert novel is not None
    assert novel["id"] == db_novel.id


def test_delete_novel_by_id(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)
    
    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None

    # delete novel
    response = client.post(f"/novel/delete/{db_novel.id}", headers=headers)

    # Verify nove was deleted
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is None

def test_update_novel(client, db):
    response, headers, novel_data, url, library = add_novel_resources(client, db)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    new_novel_data = novel_data
    new_novel_data["id"] = db_novel.id
    new_novel_data["title"] = "newtitle"
    

    # update novel
    response = client.post(f"/novel/update", json=new_novel_data, headers=headers)

    # Verify nove was updated
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.title == "newtitle"
