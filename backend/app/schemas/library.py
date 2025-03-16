from pydantic import BaseModel

class LibraryCreate(BaseModel):
    name: str

class Library(BaseModel):
    id: int
    name: str

    class Config:
        orm_mode = True
