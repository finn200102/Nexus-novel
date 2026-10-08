from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv
import os

load_dotenv()

# Use a local SQLite database if no DATABASE_URL is provided
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dev.db")

# SQL echo logs every statement with its parameters (including password
# hashes), so it is opt-in for debugging only.
engine = create_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO", "").lower() in {"1", "true", "yes"})

# create session factory
SessionLocal = sessionmaker(autocommit=False,
                            autoflush=False,
                            bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
