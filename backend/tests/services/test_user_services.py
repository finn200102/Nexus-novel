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
from app.services.user_services import *

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

def test_create_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    # check that returned object is right
    assert user.username == "user1"
    # check database
    result = db.query(User).filter(User.username == "user1").first()

    assert result is not None
    assert result.username == "user1"
    assert result.id is not None


def test_get_user_by_username(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    # check that returned object is right
    assert user.username == "user1"
    # get user
    user = get_user_by_username(db, "user1")
    assert user[0].username == "user1"


def test_delete_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    # check that returned object is right
    assert user.username == "user1"
    # check database
    db.query(User).filter(User.username == "user1").first()
    # get user
    users = get_user_by_username(db, "user1")
    assert users[0].username == "user1"
    # delete user
    delete_user(db, users[0].id)
    # check database
    result = db.query(User).filter(User.username == "user1").first()
    assert result is None


def test_update_user(db):
    # Create a user
    user_data = {"username": "user1"}
    user_data["password"] = "1234"
    user = create_user(db, user_data)

    # Check that returned object is right
    assert user.username == "user1"

    # Check database
    user_from_db = db.query(User).filter(User.username == "user1").first()
    # The variable should be user_from_db, not users (which doesn't exist)
    assert user_from_db.username == "user1"

    # Prepare update data
    user_data_new = {"username": "user2"}

    # Update user
    result = update_user(db, user.id, user_data_new)
    assert result.username == "user2"

    # Check database - need to query for the new name, not the old one
    updated_user = db.query(User).filter(User.id == user.id).first()
    assert updated_user.username == "user2"
