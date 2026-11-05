from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

RGBColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class SubtitleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    font: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120, pattern=r"^[^\x00-\x1f\x7f]+$")] = "sans-serif"
    font_size: float = Field(default=38, ge=1, le=200)
    color: RGBColor = "#ffffff"
    border_size: float = Field(default=1.65, ge=0, le=20)
    border_color: RGBColor = "#000000"
    shadow_offset: float = Field(default=0, ge=0, le=20)
    position: float = Field(default=100, ge=0, le=100)
    speed: float = Field(default=1, ge=0.1, le=10)
