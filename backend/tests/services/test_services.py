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

# Load service
from app.services.novel_services import *

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

def test_create_novel(db):
    novel_data = {}
    novel_data["title"] = "Harry Potter"
    novel_data["author"] = "JK"
    novel = create_novel(db, novel_data)
    # check that returned object is rigth
    assert novel.title == "Harry Potter"
    # check database
    result = db.query(Novel).filter(Novel.title == "Harry Potter").first()

    assert result is not None
    assert result.title == "Harry Potter"
    assert result.author == "JK"
    assert result.id is not None
    
