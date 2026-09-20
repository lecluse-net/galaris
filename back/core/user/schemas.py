from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field


def _validate_bcrypt_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    return value


PasswordValue = Annotated[
    str,
    Field(min_length=12, max_length=72),
    AfterValidator(_validate_bcrypt_password),
]

class UserBase(BaseModel):
    email: EmailStr
    display_name: str | None = None
    language: Literal["en", "fr", "zh"] | None = None

class UserCreate(UserBase):
    password: PasswordValue
    is_active: bool = True


class UserRegistration(UserBase):
    """Public registration input; activation and roles cannot be chosen by visitors."""

    password: PasswordValue


class RegistrationStatus(BaseModel):
    registration_open: bool
    initial_admin_required: bool


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    otp_code: str | None = Field(default=None, min_length=6, max_length=32)

class UserUpdate(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = None
    password: PasswordValue | None = None
    is_active: bool | None = None
    language: Literal["en", "fr", "zh"] | None = None
    document_open_mode: Literal["split", "dialog"] | None = None

class User(UserBase):
    id: int
    document_open_mode: Literal["split", "dialog"] = "split"
    is_active: bool
    avatar_url: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str


class MfaStatus(BaseModel):
    enabled: bool
    setup_pending: bool
    recovery_codes_remaining: int


class MfaSetup(BaseModel):
    secret: str
    provisioning_uri: str


class MfaCode(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisable(MfaCode):
    password: str


class MfaRecoveryCodes(BaseModel):
    recovery_codes: list[str]


# ============================================================================
# UserToken schemas
# ============================================================================

class UserTokenBase(BaseModel):
    label: str | None = None
    enabled: bool = True


class UserTokenCreate(UserTokenBase):
    pass


class UserTokenUpdate(BaseModel):
    label: str | None = None
    enabled: bool | None = None


class UserTokenResponse(BaseModel):
    id: int
    user_id: int
    label: str | None
    token: str  # Masked (for example ut_abc...xyz), or plaintext at creation.
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserTokenCreateResponse(BaseModel):
    """Creation response containing the plaintext token exactly once."""
    id: int
    user_id: int
    label: str | None
    token: str  # Plaintext token; copy it immediately.
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
