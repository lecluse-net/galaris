"""Bounded, provider-independent document preparation."""

from .contracts import OFFICE_EXTENSIONS, DocumentPage, PreparedDocument
from .service import prepare_document
from .visual import page_images

__all__ = ["OFFICE_EXTENSIONS", "DocumentPage", "PreparedDocument", "prepare_document", "page_images"]
