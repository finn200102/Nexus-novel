"""Wipe the development database and rebuild it from the migrations.

    DATABASE_URL=... uv run python -m config.reset
"""

import os

from dotenv import load_dotenv
from sqlalchemy import MetaData, create_engine

from app.db_migrations import upgrade_database

load_dotenv()


def reset_database():
    engine = create_engine(os.environ["DATABASE_URL"])
    print("Dropping all tables...")
    metadata = MetaData()
    metadata.reflect(bind=engine)
    metadata.drop_all(bind=engine)
    print("Running migrations...")
    upgrade_database(engine)
    print("Database reset complete.")


if __name__ == "__main__":
    reset_database()
