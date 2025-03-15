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

def test_create_library(db):
    library_data = {}
    library_data["name"] = "library1"
    library = create_library(db, library_data)
    # check that returned object is right
    assert library.name == "library1"
    # check database
    result = db.query(Library).filter(Library.name == "library1").first()

    assert result is not None
    assert result.name == "library1"
    assert result.id is not None


def test_get_library_by_name(db):
    library_data = {}
    library_data["name"] = "library1"
    library = create_library(db, library_data)
    # check that returned object is right
    assert library.name == "library1"
    # get library
    library = get_library_by_name(db, "library1")
    assert library[0].name == "library1"


def test_delete_library(db):
    library_data = {}
    library_data["name"] = "library1"
    library = create_library(db, library_data)
    # check that returned object is right
    assert library.name == "library1"
    # check database
    db.query(Library).filter(Library.name == "library1").first()
    # get library
    librarys = get_library_by_name(db, "library1")
    assert librarys[0].name == "library1"
    # delete library
    delete_library(db, librarys[0].id)
    # check database
    result = db.query(Library).filter(Library.name == "library1").first()
    assert result is None


def test_update_library(db):
    # Create a library
    library_data = {"name": "library1"}
    library = create_library(db, library_data)

    # Check that returned object is right
    assert library.name == "library1"

    # Check database
    library_from_db = db.query(Library).filter(Library.name == "library1").first()
    # The variable should be library_from_db, not librarys (which doesn't exist)
    assert library_from_db.name == "library1"

    # Prepare update data
    library_data_new = {"name": "library2"}

    # Update library
    result = update_library(db, library.id, library_data_new)
    assert result.name == "library2"

    # Check database - need to query for the new name, not the old one
    updated_library = db.query(Library).filter(Library.id == library.id).first()
    assert updated_library.name == "library2"
