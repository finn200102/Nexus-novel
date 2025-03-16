import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
from app.services.novel_services import get_novel_by_url
from app.services.library_services import create_library


def test_add_novel(client, db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}
    # create lib
    library = create_library(db, library_data={"name": "lib1"})
    novel_data["library_id"] = library.id

    # Make request
    response = client.post("/novel/", json=novel_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url


def test_get_novels(client, db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}
    # create lib
    library = create_library(db, library_data={"name": "lib1"})
    novel_data["library_id"] = library.id
    novel_title = "Mother of Learning"
    author_name =  "nobody103"

    # Make request
    response = client.post("/novel/", json=novel_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client.get("/novel/")
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
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}
    # create lib
    library = create_library(db, library_data={"name": "lib1"})
    novel_data["library_id"] = library.id
    novel_title = "Mother of Learning"
    author_name =  "nobody103"

    # Make request
    response = client.post("/novel/", json=novel_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client.get(f"/novel/{db_novel.id}")
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    assert response.status_code == 200
    novel = response.json()
    assert novel is not None
    assert novel["id"] == db_novel.id
