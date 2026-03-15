import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from fastapi import status
from jose import jwt
from dotenv import load_dotenv

from app.main import app
from config.database import get_db
from app.models.base import BaseModel
from app.models.user import User
from app.models.library import Library
from config.settings import settings

load_dotenv()

TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    BaseModel.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
        BaseModel.metadata.drop_all(bind=engine)


@pytest.fixture
def test_user(db):
    user = User(username="testuser", password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user):
    token = jwt.encode(
        {"sub": test_user.username, "user_id": test_user.id},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_library(db, test_user):
    library = Library(name="Test Library", user_id=test_user.id)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


@pytest.fixture
def client(db):
    """Client fixture without pre-created user - use for auth tests."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def client_with_auth(db, test_user, test_library):
    """Client fixture with pre-created user and library - use for novel tests."""

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    mock_scraped_data = {
        "id": 1,
        "title": "Mother of Learning",
        "author": "noneabout",
        "author_id": 12345,
        "source_url": "https://www.royalroad.com/fiction/21220/mother-of-learning",
        "story_id": 21220,
        "novel_site": "royalroad",
        "img_url": "https://www.royalroad.com/cover/21220.jpg",
        "description": "A time loop story...",
        "word_count": 500000,
        "reviews": 100,
        "favorites": 500,
        "follows": 50,
        "status": "In Progress",
        "views": 10000,
        "rating": 4,
        "publish_date": datetime(2020, 1, 1, 0, 0, 0),
        "updated_date": datetime(2024, 1, 1, 0, 0, 0),
        "chapter_count": 100,
        "analyzed_at": None,
        "analysis_type": None,
        "analyzed_chapter_count": None,
        "parsed_at": datetime(2024, 1, 1, 0, 0, 0),
    }

    mock_chapters = [
        {
            "id": i,
            "novel_fk": 1,
            "site": "royalroad",
            "story_id": 21220,
            "chapter_id": i,
            "chapter_number": i,
            "title": f"Chapter {i}",
            "word_count": 5000,
            "created_at": datetime(2024, 1, 1, 0, 0, 0),
        }
        for i in range(1, 11)
    ]

    with (
        patch(
            "app.routers.novel.metadata_client.scrape_novel_by_url",
            new_callable=AsyncMock,
        ) as mock_scrape,
        patch(
            "app.routers.novel.metadata_client.get_chapters_from_metadata",
            new_callable=AsyncMock,
        ) as mock_chapters_fn,
        patch(
            "app.routers.novel.metadata_client.get_novel_metadata",
            new_callable=AsyncMock,
        ) as mock_get_metadata,
        patch(
            "app.routers.novel.metadata_client.invalidate_novel_cache",
        ) as mock_invalidate_cache,
    ):
        mock_scrape.return_value = mock_scraped_data
        mock_chapters_fn.return_value = mock_chapters
        mock_get_metadata.return_value = mock_scraped_data
        mock_invalidate_cache.return_value = None

        with TestClient(app) as test_client:
            yield test_client

    app.dependency_overrides.clear()
