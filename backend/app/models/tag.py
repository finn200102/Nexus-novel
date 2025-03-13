from sqlalchemy import Column, String, Text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from app.models.novel import novel_tag

class Tag(BaseModel):
    __tablename__ = "tags"

    name = Column(String(50), nullable=False,
                  unique=True, index=True)

    novels = relationship("Novel", secondary=novel_tag,
                          back_populates="tags")

    def __repr__(self):
        return f"<Tag {self.name}>"
