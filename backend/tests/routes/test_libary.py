import pytest
from fastapi import status
from app.schemas.library import LibraryCreate
from app.services.library_services import get_library_by_name
from app.services.user_services import create_user

def create_test_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    return user


def test_add_library(client, db):q
    # Test data
    library_data = {"name": "lib1"}
    # create user
    user = create_test_user(db)
    library_data["user_id"] = user.id

    # Make request
    response = client.post("/library/", json=library_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify libary was created
    db_library = get_library_by_name(db, "lib1")
    assert db_library is not None
    assert db_library.name == "lib1"


def test_get_librarys(client, db):
    # Test data
    library_data = {"name": "lib1"}
    # create user
    user = create_test_user(db)
    library_data["user_id"] = user.id

    # Make request
    response = client.post("/library/", json=library_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED
    # Verify library was created
    db_library = get_library_by_name(db, "lib1")
    assert db_library is not None
    assert db_library.name == "lib1"

    # get library
    response = client.get("/library/")
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    assert response.status_code == 200
    librarys = response.json()
    assert librarys is not None
    assert len(librarys) > 0

    # Verify the created library is in the response
    found = False
    for library in librarys:
        if library["name"] == "lib1":
            found = True
            break
    assert found, "Created library not found in the response"



def test_get_library_by_id(client, db):
    # Test data
    library_data = {"name": "lib1"}
    # create user
    user = create_test_user(db)
    library_data["user_id"] = user.id

    # Make request
    response = client.post("/library/", json=library_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED
    
    # Verify nove was created
    db_library = get_library_by_name(db, "lib1")
    assert db_library is not None
    assert db_library.name == "lib1"


    # get library
    response = client.get(f"/library/{db_library.id}")
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())


    # Assertions for the GET request
    assert response.status_code == 200
    library = response.json()
    assert library is not None
    assert library["id"] == db_library.id
