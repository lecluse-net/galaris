"""Abstract base class for LLM provider handlers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict


@dataclass
class LLMModelInfo:
    """Normalized information about an available AI model or voice."""
    id: str  # Technical model identifier.
    name: Optional[str] = None  # Display name.
    description: Optional[str] = None
    context_length: Optional[int] = None  # Context size in tokens.
    pricing: Optional[Dict[str, Any]] = None  # Input and output token prices.
    # Provider-reported I/O modalities, or None when unknown.
    modalities: Optional[Dict[str, bool]] = None
    capabilities: Optional[Dict[str, bool]] = None
    release_date: Optional[str] = None
    status: Optional[str] = None
    metadata_source: Optional[str] = None
    resource_type: str = "model"
    service_capabilities: List[str] = field(default_factory=lambda: list[str]())


class BaseLLMHandler(ABC):
    """
    Abstract base class for LLM provider handlers.

    Each provider implements ``list_models`` for its own response format.
    """

    def supports_model_management(self) -> bool:
        """
        Return whether this handler supports model installation and deletion.

        Returns:
            Whether model management is supported.
        """
        return False

    @abstractmethod
    async def list_models(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> List[LLMModelInfo]:
        """
        Fetch available models from the provider.

        Args:
            base_url: API base URL.
            api_key: Optional authentication key.
            extra_headers: Provider-specific headers merged into the request.

        Returns:
            Available models.
        """
        pass

    async def pull_model(self, base_url: str, model_name: str, api_key: Optional[str] = None) -> str:
        """
        Install a model on the provider.

        Args:
            base_url: API base URL.
            model_name: Model to install.
            api_key: Optional authentication key.

        Returns:
            Provider status message.

        Raises:
            NotImplementedError: The handler does not support this operation.
        """
        raise NotImplementedError("This provider does not support model installation")

    async def delete_model(self, base_url: str, model_name: str, api_key: Optional[str] = None) -> str:
        """
        Delete a model from the provider.

        Args:
            base_url: API base URL.
            model_name: Model to delete.
            api_key: Optional authentication key.

        Returns:
            Provider status message.

        Raises:
            NotImplementedError: The handler does not support this operation.
        """
        raise NotImplementedError("This provider does not support model deletion")

    def _clean_base_url(self, base_url: str) -> str:
        """
        Remove the trailing slash from a base URL.

        Args:
            base_url: URL to normalize.

        Returns:
            Normalized URL.
        """
        return base_url.rstrip("/")
