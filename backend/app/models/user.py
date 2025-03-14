from sqlalchemy import Column, String, Text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(100), nullable=False, index=True)
    password = Column(String(255), nullable=False, index=True)

    libraries = relationship("Library", back_populates="user")

    def __repr__(self):
        return f"<User {self.username}>"
