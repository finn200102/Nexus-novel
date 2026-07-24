from sqlalchemy import Boolean, Column, String, Text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(100), nullable=False, index=True)
    password = Column(String(255), nullable=False, index=True)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="0")

    libraries = relationship("Library", back_populates="user")

    def __repr__(self):
        return f"<User {self.username}>"
