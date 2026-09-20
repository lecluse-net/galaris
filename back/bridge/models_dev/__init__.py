"""models.dev metadata bridge registration."""

from app.llm.provider_facade import register_model_catalog_metadata

from .service import ModelsDevMetadata


SERVICE = ModelsDevMetadata()
register_model_catalog_metadata(SERVICE)

__all__ = ["SERVICE"]
