from sqlalchemy import Column, String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class Library(BaseModel):
    __tablename__ = "libraries"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_libraries_user_name"),
    )

    name = Column(String(100), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)

    # Relationships
    user = relationship("User", back_populates="libraries")
    novels = relationship("Novel", back_populates="library", cascade="all, delete-orphan")
    

    def __repr__(self):
        return f"<Library {self.name}>"
