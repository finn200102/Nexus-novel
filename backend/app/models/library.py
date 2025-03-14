from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Library(BaseModel):
    __tablename__ = "libraries"

    name = Column(String(100), nullable=False,
                  unique=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))

    # Relationships
    user = relationship("User", back_populates="libraries")
    

    def __repr__(self):
        return f"<Library {self.name}>"
