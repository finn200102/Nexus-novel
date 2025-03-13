import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from app.models.base import BaseModel

from sqlalchemy.ext.declarative import declarative_base

# Import your models
from app.models.base import BaseModel
from app.models.novel import Novel
from app.models.genre import Genre
from app.models.tag import Tag
from app.models.chapter import Chapter

# Load environment variables
load_dotenv()

# Use a test database URL or in-memory SQLite for testing
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


def test_create_genre(db):
    # Create a genre
    fantasy = Genre(name="Fantasy")
    db.add(fantasy)
    db.commit()

    # Query the genre
    result = db.query(Genre).filter(Genre.name == "Fantasy").first()

    # Assert
    assert result is not None
    assert result.name == "Fantasy"
    assert result.id is not None


if __name__ == "__main__":
    # This allows running the tests directly with python
    pytest.main(["-xvs", __file__])


