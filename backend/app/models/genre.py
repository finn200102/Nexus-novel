from sqlalchemy import Column, String, Text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Genre(BaseModel):
    __tablename__ = "genres"

    name = Column(String(50), nullable=False,
                  unique=True, index=True)
    description = Column(Text)

    novels = relationship("Novel", back_populates="genre")

    def __repr__(self):
        return f"<Genre {self.name}>"
