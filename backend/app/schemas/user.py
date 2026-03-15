from pydantic import BaseModel, EmailStr, ConfigDict


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class UserLogin(UserBase):
    password: str


class User(UserBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    id: int
    username: str
    message: str
    access_token: str
    token_type: str

    model_config = ConfigDict(from_attributes=True)
