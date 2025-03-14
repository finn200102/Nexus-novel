from sqlalchemy import Column, String, Text, Integer, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Chapter(BaseModel):
    __tablename__ = "chapters"

    title = Column(String(255), nullable=False, index=True)
    content = Column(String(255))
    novel_id = Column(Integer, ForeignKey('novels.id'))
    novel = relationship("Novel",
                         back_populates="chapters")

    def __repr__(self):
        return f"<Chapter {self.title}>"

