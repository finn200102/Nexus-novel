from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _password_fits_bcrypt(value: str) -> str:
    # bcrypt only hashes the first 72 bytes and newer releases reject more.
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)
    invite_code: str | None = Field(default=None, max_length=128)

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
        return _password_fits_bcrypt(value)


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
    expires_in: int
    is_admin: bool = False

    model_config = ConfigDict(from_attributes=True)


class NewPassword(BaseModel):
    new_password: str = Field(min_length=8)

    @field_validator("new_password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        return _password_fits_bcrypt(value)


class PasswordChange(NewPassword):
    current_password: str


class PasswordReset(NewPassword):
    token: str = Field(min_length=1, max_length=256)


class OIDCConfig(BaseModel):
    display_name: str


class SignupConfig(BaseModel):
    signup_mode: str
    # True while the instance has no account: the first sign-up is always
    # allowed and becomes the administrator.
    first_user: bool
    password_login: bool = True
    # Present when single sign-on is configured.
    oidc: OIDCConfig | None = None


class AdminUser(BaseModel):
    id: int
    username: str
    is_admin: bool
    is_disabled: bool
    created_at: datetime | None
    last_seen_at: datetime | None = None
    active_sessions: int = 0


class AdminUserUpdate(BaseModel):
    is_admin: bool | None = None
    is_disabled: bool | None = None


class PasswordResetLinkRequest(BaseModel):
    expires_in_hours: int = Field(default=24, ge=1, le=24 * 7)


class PasswordResetLink(BaseModel):
    token: str
    path: str
    expires_at: datetime


class InstanceSettings(BaseModel):
    signup_mode: str = Field(pattern="^(open|invite|closed)$")


class InviteCreate(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    max_uses: int | None = Field(default=1, ge=1, le=1000)
    expires_in_days: int | None = Field(default=7, ge=1, le=365)


class Invite(BaseModel):
    id: int
    label: str | None
    max_uses: int | None
    use_count: int
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime | None
    status: str
    # Only returned once, when the invite is created.
    code: str | None = None
