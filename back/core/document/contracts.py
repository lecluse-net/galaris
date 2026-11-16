"""Source-local coverage and derivatives; paths live only within caller temporaries."""

from pathlib import Path
import traceback

from pydantic import BaseModel, Field


class PreparationFailure(BaseModel):
    """Safe worker diagnostics: never include exception text or document data."""

    exception_type: str
    locations: list[str] = Field(default_factory=list[str])
    exit_code: int | None = None
    converter_code: int | None = None

    @classmethod
    def from_exception(cls, error: BaseException) -> "PreparationFailure":
        code = getattr(error, "err_code", None)
        return cls(exception_type=type(error).__name__, converter_code=code if isinstance(code, int) else None, locations=[
            f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
            for frame in traceback.extract_tb(error.__traceback__)[-8:]
        ])


class DocumentPreparationError(ValueError):
    def __init__(self, failure: PreparationFailure) -> None:
        super().__init__("Document preparation failed; format, encryption or conversion limits")
        self.failure = failure


OFFICE_EXTENSIONS = frozenset({
    ".doc", ".docx", ".odt", ".rtf", ".odg", ".odp", ".ppt", ".pptx", ".xls", ".xlsx", ".ods",
})


def preparation_version(name: str) -> int:
    """Version of evidence used by both conversion checkpoints and caller caches."""
    return 4 if Path(name).suffix.lower() == ".xls" else 3


class DocumentPage(BaseModel):
    number: int = Field(ge=1)
    text: str = ""
    image: str | None = None
    ocr: bool = False
    warnings: list[str] = Field(default_factory=list)


class PreparedDocument(BaseModel):
    name: str
    sha256: str
    media_type: str
    converted: bool = False
    pages: list[DocumentPage] = Field(default_factory=list[DocumentPage])
    warnings: list[str] = Field(default_factory=list)
    structured_text: str = ""
    html: str = ""
    assets: list[str] = Field(default_factory=list)

    def coverage(self) -> dict[str, object]:
        return {
            "expected_units": len(self.pages), "prepared_units": len(self.pages),
            "text_units": sum(bool(p.text.strip()) for p in self.pages),
            "ocr_units": sum(p.ocr for p in self.pages),
            "visual_units": sum(p.image is not None for p in self.pages),
            "units_without_text": [p.number for p in self.pages if not p.text.strip()],
            "semantic_accuracy_verified": False,
        }

    def text(self) -> str:
        text = "\n\n".join(f"[Page {p.number}]\n{p.text}" for p in self.pages)
        return text + ("\n\n[Structured source data]\n" + self.structured_text if self.structured_text else "")

    def image_path(self, page: DocumentPage, directory: Path) -> Path | None:
        if page.image is None:
            return None
        path = directory / page.image
        if path.parent != directory or not path.is_file() or path.is_symlink():
            raise ValueError("Invalid document derivative")
        return path
