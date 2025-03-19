from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserLogin(UserBase):
    password: str

class User(UserBase):
    id: int

    class Config:
        orm_mode = True

class LoginResponse(BaseModel):
    id: int
    username: str
    message: str
    access_token: str
    token_type: str

    class Config:
        orm_mode = True
