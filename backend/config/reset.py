import os
from sqlalchemy import create_engine
from dotenv import load_dotenv
from app.models.library import Library
from app.models.user import User
from app.models.author import Author
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.tag import Tag
from app.models.genre import Genre
from config.database import Base 

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=True)

def reset_database():
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Database reset complete.")

if __name__ == "__main__":
    reset_database()

