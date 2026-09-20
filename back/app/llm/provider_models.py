"""Database models for provider connections and configured LLMs."""
from typing import Any, Optional, List
from sqlalchemy import String, Boolean, Index, Integer, Text, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB
from core.database import Base, HistoryMixin


class LLMProvider(HistoryMixin, Base):
    """
    User-owned connection to either a built-in catalog provider or a custom endpoint.

    ``catalog_code`` identifies a declarative built-in profile. A null value means the
    connection is custom and can coexist with any number of other custom connections.
    """
    __tablename__ = "llm_providers"

    # Identifiers
    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Display information
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    catalog_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Connection configuration
    provider_type: Mapped[str] = mapped_column(
        String(50),
        default="openai_compatible",
        server_default=text("'openai_compatible'"),
        nullable=False,
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Encrypted token.
    # Galaris account owning a personal subscription. Only the ChatGPT/Codex OAuth provider
    # accepts this field; the proxy enforces it before sending any upstream request.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subscription_acknowledged: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False,
    )
    # Encrypted JSON containing the OAuth access and refresh tokens. A text column is required
    # because JWTs and rotating refresh tokens are substantially larger than ordinary API keys.
    oauth_credentials: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Non-secret provider-specific values accepted by the registered bridge profile.
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Optional dedicated OpenAI-compatible audio-transcription endpoint. When set, STT models are
    # listed and invoked here instead of through ``base_url``.
    transcription_base_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    __table_args__ = (
        # Provider display names are unique.
        Index(
            "uq_llm_provider_name",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # PostgreSQL permits multiple nulls, so every fixed catalog entry is unique while custom
        # providers remain unlimited.
        Index(
            "uq_llm_provider_catalog_code",
            "catalog_code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # Configured LLM relationship.
    llms: Mapped[List["LLM"]] = relationship(back_populates="provider", cascade="all, delete-orphan")

    @property
    def is_custom(self) -> bool:
        """Whether the connection was created by the user rather than from the catalog."""
        return self.catalog_code is None

    @property
    def api_key_configured(self) -> bool:
        """Expose credential presence without returning the encrypted secret."""
        return bool(self.api_key)

    @property
    def oauth_connected(self) -> bool:
        """Expose OAuth connection state without exposing the encrypted credentials."""
        return bool(self.oauth_credentials)


class LLM(HistoryMixin, Base):
    """
    User-configured LLM table containing selected provider models.
    """
    __tablename__ = "llms"

    # Identifiers
    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Provider foreign key
    llm_provider_id: Mapped[int] = mapped_column(ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False, index=True)

    # Model information
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    llm_name: Mapped[str] = mapped_column(String(200), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)   # Ex: "Claude 3.5 Sonnet (Production)"
    # ``LLM`` remains the Python/table name for compatibility with agents and stable parameters,
    # but rows now represent any configured AI resource (model or voice).
    resource_type: Mapped[str] = mapped_column(
        String(30), default="model", server_default=text("'model'"), nullable=False
    )
    primary_capability: Mapped[str] = mapped_column(
        String(50), default="chat", server_default=text("'chat'"), nullable=False, index=True
    )
    service_capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: ["chat"],
        server_default=text("'[\"chat\"]'::jsonb"),
    )
    # Full provider pricing, including non-token units (character, second, image, megapixel...).
    pricing: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    # Total input and output context window. Persisted because the proxy exposes a stable code
    # that hides the provider-specific model name.
    context_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Cost in dollars per million tokens when reported by the provider.
    cost_per_input_token: Mapped[Optional[float]] = mapped_column(nullable=True)
    cost_per_cached_input_token: Mapped[Optional[float]] = mapped_column(nullable=True)
    cost_per_output_token: Mapped[Optional[float]] = mapped_column(nullable=True)
    # A subscription absorbs per-request billing while the configured rates remain useful for
    # comparing this resource with usage-billed alternatives.
    is_subscription: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    # Directional model modalities. Input capabilities select direct OpenAI content versus local
    # preprocessing such as description, STT, PDF rasterization, or text extraction. Text defaults
    # to enabled and other modalities default to disabled.
    input_text: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    input_image: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    input_file: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    input_video: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    input_audio: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    output_text: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    output_image: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    output_file: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    output_video: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    output_audio: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    __table_args__ = (
        # A provider model and a stable Galaris code are each unique.
        Index(
            "uq_llm_provider_model",
            "llm_provider_id",
            "llm_name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_llm_code",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    # Provider relationship
    provider: Mapped["LLMProvider"] = relationship(back_populates="llms")
