from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)

    @field_validator("username")
    @classmethod
    def username_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username must not be blank")
        return value

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        # bcrypt only hashes the first 72 bytes and newer releases reject more.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return value


class UserLogin(UserBase):
    password: str


class User(UserBase):
    id: int
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    id: int
    username: str
    message: str
    access_token: str
    token_type: str
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)
