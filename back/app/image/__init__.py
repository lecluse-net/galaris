"""Image generation, editing, composition, and description domain.

The internal service is exposed through MCP tools and a standardized file transport that can
connect image generation or analysis to messaging, cloud storage, and canonical file providers.
"""

from . import image_service
from .image_service import describe_image, generate_image_bytes, image_markdown
from .transport import ImageFileTransport

__all__ = [
    "image_service",
    "generate_image_bytes",
    "describe_image",
    "image_markdown",
    "ImageFileTransport",
]
