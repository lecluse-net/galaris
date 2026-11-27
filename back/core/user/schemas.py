from datetime import datetime
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, PositiveInt, model_validator


def _validate_bcrypt_password(value: str) -> str:
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes")
    compact = "".join(char for char in value.lower() if char.isalnum())
    if (
        len(set(value.strip())) < 4
        or re.fullmatch(r"(.{1,4})\1+", value.lower(), flags=re.DOTALL)
        or re.fullmatch(r"(?:password|passw0rd|motdepasse|qwerty|azerty|letmein|admin)[0-9]*", compact)
        or (compact and compact in "012345678901234567890123456789")
        or (compact and compact in "abcdefghijklmnopqrstuvwxyz")
    ):
        raise ValueError("Choose a less predictable password")
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


class UserAdminCreate(UserBase):
    password: PasswordValue | None = None
    invite: bool = False
    is_active: bool = True
    settings: dict[str, dict[str, object]] = Field(default_factory=dict[str, dict[str, object]])
    role_ids: list[PositiveInt] = Field(default_factory=list[int])
    default_role_id: PositiveInt | None = None
    team_ids: list[PositiveInt] = Field(default_factory=list[int])
    managed_team_ids: list[PositiveInt] = Field(default_factory=list[int])

    @model_validator(mode="after")
    def validate_default_role(self) -> "UserAdminCreate":
        if self.invite == (self.password is not None):
            raise ValueError("Provide either a password or an invitation")
        if self.default_role_id is not None and self.default_role_id not in self.role_ids:
            raise ValueError("The default role must be one of the assigned roles")
        if set(self.managed_team_ids) - set(self.team_ids):
            raise ValueError("Managed teams must be among the assigned teams")
        return self


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
    document_library_mode: Literal["folders", "topics", "agents"] | None = None

class UserAdminUpdate(UserUpdate):
    settings: dict[str, dict[str, object]] = Field(default_factory=dict[str, dict[str, object]])


class User(UserBase):
    id: int
    document_open_mode: Literal["split", "dialog"] = "split"
    document_library_mode: Literal["folders", "topics", "agents"] = "folders"
    is_active: bool
    invitation_pending: bool = False
    avatar_url: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserAdminCreated(User):
    invitation_sent: bool | None = None


class PlatformSmtpTest(BaseModel):
    recipient: EmailStr


class UserInvitationAcceptance(BaseModel):
    token: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]
    password: PasswordValue
    password_confirmation: Annotated[str, Field(max_length=72)]

    @model_validator(mode="after")
    def confirm_password(self) -> "UserInvitationAcceptance":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class UserListRole(BaseModel):
    id: int
    code: str
    display_name: str | None

    model_config = ConfigDict(from_attributes=True)


class UserListTeam(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class UserListEntry(User):
    assignments: list[UserListRole] | None = None
    teams: list[UserListTeam] | None = None


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
