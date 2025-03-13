from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.models.base import BaseModel
from app.models.novel import Novel
from app.models.genre import Genre
from app.models.tag import Tag
from app.models.chapter import Chapter

from dotenv import load_dotenv
import os

config = context.config()

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = BaseModel.metadata
