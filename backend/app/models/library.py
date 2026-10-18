from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from uuid import uuid4

class Library(BaseModel):
    __tablename__ = "libraries"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_libraries_user_name"),
        Index('uq_libraries_identity_key', 'identity_key', unique=True),
    )

    name = Column(String(100), nullable=False, index=True)
    # Nullable for compatibility with older direct importers; saved rules bind
    # only after assigning an immutable identity, never to the numeric ID alone.
    identity_key = Column(String(36), nullable=True, default=lambda: str(uuid4()))
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="libraries")
    novels = relationship("Novel", back_populates="library", cascade="all, delete-orphan")
    

    def __repr__(self):
        return f"<Library {self.name}>"
