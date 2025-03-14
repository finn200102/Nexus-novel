from pydantic import BaseModel

class NovelBase(BaseModel):
    title: str

class NovelCreate(UserBase):
    url: str

class Novel(UserBase):
    id: int

    class Config:
        orm_mode = True
