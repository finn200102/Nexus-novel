from sqlalchemy import Column, String, Text
from app.models.base import BaseModel

class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(100), nullable=False, index=True)
    password = Column(String(255), nullable=False, index=True)
    
