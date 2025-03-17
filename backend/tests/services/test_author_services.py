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
from app.models.user import User
from app.models.author import Author
from app.models.library import Library

# Load service
from app.services.author_services import *

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

def test_create_author(db):
    author_data = {}
    author_data["name"] = "Jim Butcher"
    author = create_author(db, author_data)
    # check that returned object is right
    assert author.name == "Jim Butcher"
    # check database
    result = db.query(Author).filter(Author.name == "Jim Butcher").first()

    assert result is not None
    assert result.name == "Jim Butcher"
    assert result.id is not None


def test_get_author_by_name(db):
    author_data = {}
    author_data["name"] = "Jim Butcher"
    author = create_author(db, author_data)
    # check that returned object is right
    assert author.name == "Jim Butcher"
    # get author
    author = get_author_by_name(db, "Jim Butcher")
    assert author[0].name == "Jim Butcher"


def test_delete_author(db):
    author_data = {}
    author_data["name"] = "Jim Butcher"
    author = create_author(db, author_data)
    # check that returned object is right
    assert author.name == "Jim Butcher"
    # check database
    db.query(Author).filter(Author.name == "Jim Butcher").first()
    # get author
    authors = get_author_by_name(db, "Jim Butcher")
    assert authors[0].name == "Jim Butcher"
    # delete author
    delete_author(db, authors[0].id)
    # check database
    result = db.query(Author).filter(Author.name == "Jim Butcher").first()
    assert result is None


def test_update_author(db):
    # Create a author
    author_data = {"name": "Jim Butcher"}
    author = create_author(db, author_data)

    # Check that returned object is right
    assert author.name == "Jim Butcher"

    # Check database
    author_from_db = db.query(Author).filter(Author.name == "Jim Butcher").first()
    # The variable should be author_from_db, not authors (which doesn't exist)
    assert author_from_db.name == "Jim Butcher"

    # Prepare update data
    author_data_new = {"name": "Jim Butcher 1"}

    # Update author
    result = update_author(db, author.id, author_data_new)
    assert result.name == "Jim Butcher 1"

    # Check database - need to query for the new name, not the old one
    updated_author = db.query(Author).filter(Author.id == author.id).first()
    assert updated_author.name == "Jim Butcher 1"
