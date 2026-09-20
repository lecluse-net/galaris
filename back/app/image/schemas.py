"""Output options shared by image generation and its MCP contract."""

from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator

ImageDimension = Annotated[
    int,
    Field(strict=True, ge=1, description="Preferred output dimension in pixels; native size is chosen best effort. Supply both width and height."),
]


class ImageGenerationOptions(BaseModel):
    """Validate options before resource access or provider requests."""

    width: ImageDimension | None = None
    height: ImageDimension | None = None

    @model_validator(mode="after")
    def check_dimensions(self) -> Self:
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be supplied together")
        return self
