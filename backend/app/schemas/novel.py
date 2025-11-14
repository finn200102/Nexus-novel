from pydantic import BaseModel, Field
from typing import Optional


class NovelCreate(BaseModel):
    url: str
    library_id: int


class Novel(BaseModel):
    id: int
    title: str
    url: str
    description: Optional[str] = None
    cover_image: Optional[str] = None
    library_id: int

    class Config:
        orm_mode = True


class NovelSearch(BaseModel):
    title: str
    url: str
    cover_image: Optional[str] = None


class NovelUpdate(BaseModel):
    id: int
    title: str
    url: str
