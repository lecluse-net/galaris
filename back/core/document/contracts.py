"""Source-local coverage and derivatives; paths live only within caller temporaries."""

from pathlib import Path

from pydantic import BaseModel, Field


OFFICE_EXTENSIONS = frozenset({
    ".doc", ".docx", ".odt", ".rtf", ".odg", ".odp", ".ppt", ".pptx", ".xls", ".xlsx", ".ods",
})


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
