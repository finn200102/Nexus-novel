from pydantic import BaseModel

class NovelCreate(BaseModel):
    url: str
    library_id: int

class Novel(BaseModel):
    id: int
    title: str
    url: str
    library_id: int

    class Config:
        orm_mode = True

class NovelUpdate(BaseModel):
    id: int
    title: str
    url: str
