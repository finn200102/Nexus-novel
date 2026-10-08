from tests.auth_helpers import bearer_headers
from app.services.library_services import get_library_by_name
from app.services.user_services import create_user
from fastapi import status


def create_test_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    return user


def get_auth_headers(user_id):
    """Generate authorization headers for a user"""
    return bearer_headers(user_id)


def add_library_response(client, db):
    # Test data
    library_data = {"name": "lib1"}
    # create user
    user = create_test_user(db)
    library_data["user_id"] = user.id
    # get auth header
    headers = get_auth_headers(user.id)

    # Make request
    response = client.post("/library/", json=library_data, headers=headers)

    return response, headers, library_data


def test_add_library(client, db):
    response, headers, library_data = add_library_response(client, db)
    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify libary was created
    db_library = get_library_by_name(db, "lib1")
    assert db_library is not None
    assert db_library.name == "lib1"


def test_library_names_are_scoped_to_the_owner(client, db):
    first_user = create_test_user(db)
    second_user = create_user(db, {"username": "user2", "password": "1234"})

    first_response = client.post(
        "/library/", json={"name": "Library"}, headers=get_auth_headers(first_user.id)
    )
    second_response = client.post(
        "/library/", json={"name": "Library"}, headers=get_auth_headers(second_user.id)
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_201_CREATED


def test_get_librarys(client, db):
    response, headers, library_data = add_library_response(client, db)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED
    # Verify library was created
    db_library = get_library_by_name(db, "lib1")
    assert db_library is not None
    assert db_library.name == "lib1"

    # get library
    response = client.get("/library/", headers=headers)
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
    response, headers, library_data = add_library_response(client, db)
    db_library = get_library_by_name(db, "lib1")

    # get library
    response = client.get(f"/library/{db_library.id}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())

    # Assertions for the GET request
    assert response.status_code == 200
    library = response.json()
    assert library is not None
    assert library["id"] == db_library.id


def test_delete_library_by_id(client, db):
    response, headers, library_data = add_library_response(client, db)
    db_library = get_library_by_name(db, "lib1")

    assert db_library.name == "lib1"
    client.post(f"/library/delete/{db_library.id}", headers=headers)
    db_library = get_library_by_name(db, "lib1")

    assert db_library is None


def test_update_library_by_id(client, db):
    response, headers, library_data = add_library_response(client, db)
    db_library = get_library_by_name(db, "lib1")

    assert db_library.name == "lib1"
    library_data = {"name": "lib2", "id": db_library.id}
    client.post("/library/update/", json=library_data, headers=headers)
    db_library = get_library_by_name(db, "lib2")

    assert db_library is not None
