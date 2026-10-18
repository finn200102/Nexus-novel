from sqlalchemy import Column, ForeignKey, LargeBinary, String, Integer
from app.models.base import BaseModel


class LocalBookCover(BaseModel):
    __tablename__ = "local_book_covers"
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, unique=True)
    media_type = Column(String(32), nullable=False)
    data = Column(LargeBinary, nullable=False)
