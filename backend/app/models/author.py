from sqlalchemy import Column, String, Text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Author(BaseModel):
    __tablename__ = "authors"

    name = Column(String(100), nullable=False,
                  unique=True, index=True)

    description = Column(Text)
    
    novels = relationship("Novel", back_populates="author")

    def __repr__(self):
        return f"<Author {self.name}>"
