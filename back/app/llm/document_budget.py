"""Local input admission, with output/context reserves and no inference or network call."""

from typing import Any

from core.document import PreparedDocument
from .generation_capacity import estimate_request_tokens


def text_tokens(text: str) -> int:
    """Conservative UTF-8 estimate, not a provider tokenizer or billable usage."""
    return (len(text.encode("utf-8")) + 2) // 3


def document_input_budget(context_length: int | None, body: dict[str, Any]) -> int:
    context = context_length if context_length is not None and context_length > 0 else 32_000
    output = next((value for key in ("max_tokens", "max_output_tokens", "max_completion_tokens")
                   if isinstance(value := body.get(key), int) and not isinstance(value, bool) and value > 0),
                  min(8192, max(1024, context // 8)))
    # Keep 20% for tokenizer uncertainty and provider envelopes. The caller removes
    # document parts before this count; existing history/tools/media still consume space.
    return max(0, context * 4 // 5 - output - estimate_request_tokens(body))


def document_tokens(document: PreparedDocument, *, visual: bool) -> int:
    # Scanned/compressed PDFs cannot be measured from their source byte size.
    return text_tokens(document.text()) + (4096 * sum(page.image is not None for page in document.pages) if visual else 0)
