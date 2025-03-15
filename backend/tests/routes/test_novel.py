import pytest
from fastapi import status
import bcrypt
from app.schemas.user import UserCreate
from app.services.novel_services import get_novel_by_url


def test_add_novel(client, db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}

    # Make request
    response = client.post("/novel/add", json=novel_data)

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url
    
