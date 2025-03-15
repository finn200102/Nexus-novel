from pydantic import BaseModel

class NovelCreate(BaseModel):
    url: str

class Novel(BaseModel):
    id: int
    title: str
    url: str

    class Config:
        orm_mode = True
