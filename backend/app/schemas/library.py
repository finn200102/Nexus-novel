from pydantic import BaseModel, ConfigDict


class LibraryCreate(BaseModel):
    name: str
    user_id: int = None


class Library(BaseModel):
    id: int
    name: str
    user_id: int

    model_config = ConfigDict(from_attributes=True)


class LibraryUpdate(BaseModel):
    name: str
    id: int
