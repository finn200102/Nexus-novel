from sqlalchemy import Column, Integer, DateTime, func
from config.database import Base

class BaseModel(Base):
    __abstract__ = True

    id = Column(Integer,
                primary_key=True,
                index=True)
    created_at = Column(DateTime,
                        default=func.now())
    updated_at = Column(DateTime,
                        default=func.now(),
                        onupdate=func.now())
