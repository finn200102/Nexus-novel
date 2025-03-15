from pydantic import BaseModel

class NovelCreate(BaseModel):
    url: str

class Novel(BaseModel):
    id: int

    class Config:
        orm_mode = True
