"""Pydantic schemas compatible with the OpenAI Chat Completions API."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.i18n import t


# ──────────────────────────────────────────────
# Messages
# ──────────────────────────────────────────────

class ToolCallFunction(BaseModel):
    """Tool function call arguments."""
    name: str
    arguments: str  # JSON string


class ToolCall(BaseModel):
    """Function tool call in an assistant message."""
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class Message(BaseModel):
    """OpenAI-format conversation message."""
    role: Literal["system", "user", "assistant", "tool"]
    content: Union[str, List[Dict[str, Any]], None] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


# ──────────────────────────────────────────────
# Tools / Function Calling
# ──────────────────────────────────────────────

class FunctionDefinition(BaseModel):
    """Function-calling definition."""
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None  # JSON Schema


class Tool(BaseModel):
    """Tool available to the model."""
    type: Literal["function"] = "function"
    function: FunctionDefinition


# ──────────────────────────────────────────────
# Chat completion request
# ──────────────────────────────────────────────

class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible request with a Galaris ``conversation_id`` extension."""
    model_config = ConfigDict(extra="allow")

    model: str = Field(..., description="Model identifier")
    messages: List[Message] = Field(..., min_length=1, description="Conversation history")
    conversation_id: Optional[str] = Field(
        default=None,
        description="Conversation ID to preserve and pass through Galaris"
    )
    stream: bool = Field(default=False, description="Enable SSE streaming")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    stop: Optional[Union[str, List[str]]] = None
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None

    @field_validator("messages")
    @classmethod
    def check_messages_not_empty(cls, v: List[Message]) -> List[Message]:
        if len(v) == 0:
            raise ValueError(t("agent_api.errors.messages_required"))
        return v

    def get_extra_fields(self) -> Dict[str, Any]:
        """Return additional client fields not defined by the schema."""
        return dict(self.__pydantic_extra__) if self.__pydantic_extra__ else {}


# ──────────────────────────────────────────────
# Non-streaming chat completion response
# ──────────────────────────────────────────────

class Usage(BaseModel):
    """Token usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class Choice(BaseModel):
    """Completion choice."""
    index: int = 0
    message: Message
    finish_reason: Optional[Literal["stop", "length", "tool_calls", "content_filter"]] = None
    logprobs: Optional[Any] = None


class ChatCompletionResponse(BaseModel):
    """Non-streaming chat completion response."""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:16]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: 0)
    model: str
    choices: List[Choice]
    usage: Optional[Usage] = None
    conversation_id: Optional[str] = Field(
        default=None,
        description="Preserved Galaris conversation ID"
    )


# ──────────────────────────────────────────────
# Streaming
# ──────────────────────────────────────────────

class ChunkChoice(BaseModel):
    """Choice in a streaming chunk."""
    index: int = 0
    delta: Dict[str, Any] = Field(default_factory=lambda: {})
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    """SSE streaming chunk."""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex[:16]}")
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[ChunkChoice] = Field(default_factory=lambda: []) # type: ignore
    conversation_id: Optional[str] = Field(
        default=None,
        description="Preserved Galaris conversation ID"
    )


# ──────────────────────────────────────────────
# /v1/models
# ──────────────────────────────────────────────

class ModelObject(BaseModel):
    """Available model."""
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "galaris"


class ModelListResponse(BaseModel):
    """Available model list."""
    object: Literal["list"] = "list"
    data: List[ModelObject]


# ──────────────────────────────────────────────
# Error
# ──────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """OpenAI-format error response."""
    error: Dict[str, Any]
