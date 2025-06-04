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
from app.models.genre import Genre
from app.models.tag import Tag
from app.models.chapter import Chapter
from app.models.author import Author

# Load service
from app.services.novel_services import *
from app.services.library_services import create_library
from app.services.user_services import create_user

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
    

def test_create_novel(db):
    library = create_test_library(db)
    novel_data = {}
    novel_data["title"] = "Harry Potter"
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)
    # check that returned object is right
    assert novel.title == "Harry Potter"
    # check database
    result = db.query(Novel).filter(Novel.title == "Harry Potter").first()

    assert result is not None
    assert result.title == "Harry Potter"
    assert result.id is not None


def test_get_novel_by_title(db):
    library = create_test_library(db)
    novel_data = {}
    novel_data["title"] = "Harry Potter"
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)
    # check that returned object is right
    assert novel.title == "Harry Potter"
    # get novel
    novels = get_novel_by_title(db, "Harry Potter")
    assert novels[0].title == "Harry Potter"


def test_delete_novel(db):
    library = create_test_library(db)
    novel_data = {}
    novel_data["title"] = "Harry Potter"
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)
    # check that returned object is right
    assert novel.title == "Harry Potter"
    # check database
    db.query(Novel).filter(Novel.title == "Harry Potter").first()
    # get novel
    novels = get_novel_by_title(db, "Harry Potter")
    assert novels[0].title == "Harry Potter"
    # delete novel
    delete_novel(db, novels[0].id)
    # check database
    result = db.query(Novel).filter(Novel.title == "Harry Potter").first()
    assert result is None

def test_update_novel(db):
    library = create_test_library(db)
    # Create a novel
    novel_data = {"title": "Harry Potter"}
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)

    # Check that returned object is right
    assert novel.title == "Harry Potter"

    # Check database
    novel_from_db = db.query(Novel).filter(Novel.title == "Harry Potter").first()
    # The variable should be novel_from_db, not novels (which doesn't exist)
    assert novel_from_db.title == "Harry Potter"

    # Prepare update data
    novel_data_new = {"title": "Harry Potter 1"}

    # Update novel
    result = update_novel(db, novel.id, novel_data_new)
    assert result.title == "Harry Potter 1"

    # Check database - need to query for the new title, not the old one
    updated_novel = db.query(Novel).filter(Novel.id == novel.id).first()
    assert updated_novel.title == "Harry Potter 1"


def test_get_novels(db):
    """Verify get_novels returns all novels"""
    library = create_test_library(db)

    # Create multiple novels
    create_novel(db, {"title": "Novel1", "library_id": library.id})
    create_novel(db, {"title": "Novel2", "library_id": library.id})

    novels_query = get_novels(db)
    novels = novels_query.all()

    assert len(novels) == 2
    titles = {n.title for n in novels}
    assert titles == {"Novel1", "Novel2"}


def test_get_novel_by_id(db):
    """Verify get_novel_by_id fetches the correct novel"""
    library = create_test_library(db)
    novel = create_novel(db, {"title": "Novel1", "library_id": library.id})

    fetched = get_novel_by_id(db, novel.id)

    assert fetched is not None
    assert fetched.id == novel.id
    assert fetched.title == "Novel1"


def test_get_novel_by_url(db):
    """Verify get_novel_by_url returns novels with the given URL"""
    library = create_test_library(db)
    url = "https://example.com/novel1"
    novel = create_novel(db, {"title": "Novel1", "library_id": library.id, "url": url})

    novels = get_novel_by_url(db, url)

    assert novels[0].id == novel.id
    assert novels[0].url == url

