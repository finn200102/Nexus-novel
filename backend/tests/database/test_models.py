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
from app.models.library import Library
from app.models.author import Author
from app.models.user import User
from app.models.genre import Genre
from app.models.tag import Tag
from app.models.chapter import Chapter

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


def test_create_tag(db):
    # Create a genre
    spaceships = Tag(name="spaceships")
    db.add(spaceships)
    db.commit()

    # Query the genre
    result = db.query(Tag).filter(Tag.name == "spaceships").first()

    # Assert
    assert result is not None
    assert result.name == "spaceships"
    assert result.id is not None

def test_create_user(db):
    user = User(username="hans", password="1234")
    db.add(user)
    db.commit()

    # Query the genre
    result = db.query(User).filter(User.username == "hans").first()

    # Assert
    assert result is not None
    assert result.username == "hans"
    assert result.id is not None

def test_create_library(db):
    user = User(username="hans", password="1234")
    db.add(user)
    db.commit()



    # Query the genre
    result_user = db.query(User).filter(User.username == "hans").first()

    library = Library(name="lib1", user_id=result_user.id)
    db.add(library)
    db.commit()


    result = db.query(Library).filter(Library.name == "lib1").first()
    

    # Assert
    assert result is not None
    assert result.name == "lib1"
    assert result.user_id == result_user.id
    assert result.id is not None



if __name__ == "__main__":
    # This allows running the tests directly with python
    pytest.main(["-xvs", __file__])


