from pydantic import BaseModel, ConfigDict
from typing import Dict, List, Literal, Optional


class PromptParamMetadata(BaseModel):
    """Conffile-like state for one packaged prompt."""

    default_value: str
    customized: bool
    default_changed: bool


class ParamBase(BaseModel):
    """Base parameter schema; the frontend owns translated labels."""
    value: Optional[str] = None


class ParamCreate(ParamBase):
    """Parameter creation schema."""
    name: str


class ParamUpdate(BaseModel):
    """Parameter value-update schema."""
    value: Optional[str] = None
    clear_secret: bool = False
    prompt_action: Optional[Literal["keep_custom", "use_default"]] = None


class Param(ParamBase):
    """Complete API parameter schema."""
    name: str

    model_config = ConfigDict(from_attributes=True)


class ParamListItem(BaseModel):
    """Parameter-list item."""
    name: str
    value: Optional[str] = None
    secret: bool = False
    configured: bool = False
    prompt: Optional[PromptParamMetadata] = None

    model_config = ConfigDict(from_attributes=True)


class ParamsListResponse(BaseModel):
    """Complete parameter-list response."""
    params: List[ParamListItem]


class ParamsDictResponse(BaseModel):
    """Simple dictionary response."""
    params: Dict[str, Optional[str]]


class ParamUpdateResponse(BaseModel):
    """Parameter-update response."""
    status: str
    name: str
    value: Optional[str] = None
    secret: bool = False
    configured: bool = False
    prompt: Optional[PromptParamMetadata] = None
