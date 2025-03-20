import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models.base import BaseModel

from sqlalchemy.ext.declarative import declarative_base

# Import models
from app.models.base import BaseModel
from app.models.novel import Novel
from app.models.user import User
from app.models.genre import Genre
from app.models.tag import Tag
from app.models.library import Library
from app.models.chapter import Chapter
from app.models.author import Author

# Load service
from app.services.library_services import *
from app.services.user_services import create_user
from app.services.novel_services import create_novel
from app.services.chapter_services import create_chapter, get_chapter_by_id

# Load environment variables
load_dotenv()

# Us in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite:///./test.db"

# Create test engine
engine = create_engine(TEST_DATABASE_URL)

# Create test session
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Fixture for database session
@pytest.fixture
def db():
    # Create all tables
    BaseModel.metadata.create_all(bind=engine)

    # Create a session
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop all tables after tests
        BaseModel.metadata.drop_all(bind=engine)

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
    novel_data = {"url": url, "title": "nov1"}
    # create lib
    library = create_test_library(db)
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)

    return novel, library

def test_create_chapter(db):
    
    novel, library = create_test_novel(db)
    chapter_data = {"novel_id": novel.id,
                    "chapter_number": 1,
                    "title": "",
                    "content_status": "MISSING"}
    chapter = create_chapter(db, chapter_data)
    chapter = get_chapter_by_id(db, chapter.id)
    assert chapter.chapter_number == 1
    
