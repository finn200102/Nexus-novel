from pydantic import BaseModel

class LibraryCreate(BaseModel):
    name: str

class Library(BaseModel):
    id: int
    name: str
    user_id: int

    class Config:
        orm_mode = True
