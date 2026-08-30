from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..toolkit.web import ui


###########################################################################################################
###########################################################################################################
class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


###########################################################################################################
###########################################################################################################
class PhotoMetadata(Model):
    format: str
    width: int
    height: int
    mode: str | None = None
    orientation: int = 1
    animated: bool = False
    frames: int = 1
    duration: float | None = None
    alpha: bool = False
    icc: str | None = None
    size: int | None = None


###########################################################################################################
###########################################################################################################
class PhotoConstraints(Model):
    formats: list[str] = Field(default=["jpeg"], min_length=1)
    min_width: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=8192, step=2))
    max_width: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=8192, step=2))
    min_height: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=8192, step=2))
    max_height: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=8192, step=2))
    min_aspect: float | None = None
    max_aspect: float | None = None
    aspects: list[str] | None = None
    max_pixels: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=100_000_000, step=1_000_000))
    max_bytes: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=25_000_000, step=250_000))
    srgb: bool = False


###########################################################################################################
###########################################################################################################
class Filters(Model):
    brightness: float = Field(default=1.0, ge=0, json_schema_extra=ui(css="brightness({})", widget="range", low=0, high=3, step=0.05))
    contrast: float = Field(default=1.0, ge=0, json_schema_extra=ui(css="contrast({})", widget="range", low=0, high=3, step=0.05))
    saturation: float = Field(default=1.0, ge=0, json_schema_extra=ui(css="saturate({})", widget="range", low=0, high=3, step=0.05))
    hue: float = Field(default=0.0, json_schema_extra=ui(css="hue-rotate({}deg)", widget="range", low=-180, high=180, step=1))
    grayscale: float = Field(default=0.0, ge=0, le=1, json_schema_extra=ui(css="grayscale({})", widget="range", low=0, high=1, step=0.01))
    sepia: float = Field(default=0.0, ge=0, le=1, json_schema_extra=ui(css="sepia({})", widget="range", low=0, high=1, step=0.01))
    invert: float = Field(default=0.0, ge=0, le=1, json_schema_extra=ui(css="invert({})", widget="range", low=0, high=1, step=0.01))


###########################################################################################################
###########################################################################################################
class Edits(Model):
    aspect: str | None = Field(default=None, json_schema_extra=ui(widget="aspect", choices=["9:16", "16:9", "1:1", "4:5", "2:3"]))
    background: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    still: bool = False


###########################################################################################################
###########################################################################################################
class CropPlan(Model):
    x: int
    y: int
    width: int
    height: int


###########################################################################################################
###########################################################################################################
def aspect_of(text: str) -> float:
    numerator, _, denominator = text.partition(":")
    try:
        ratio = float(numerator) / float(denominator) if denominator else float(numerator)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"invalid aspect ratio {text!r}; use W:H like 9:16")
    if ratio <= 0:
        raise ValueError(f"invalid aspect ratio {text!r}; must be positive")
    return ratio


###########################################################################################################
###########################################################################################################
class ColorPlan(Model):
    brightness: float = Field(default=1.0, ge=0)
    contrast: float = Field(default=1.0, ge=0)
    saturation: float = Field(default=1.0, ge=0)
    hue: float = 0.0
    grayscale: float = Field(default=0.0, ge=0, le=1)
    sepia: float = Field(default=0.0, ge=0, le=1)
    invert: float = Field(default=0.0, ge=0, le=1)

    def identity(self) -> bool:
        return self == ColorPlan()


###########################################################################################################
###########################################################################################################
class QualityPlan(Model):
    quality: int | None = None
    lossless: bool = False
    estimated_bytes: int | None = None


###########################################################################################################
###########################################################################################################
class FormatTraits(Model):
    format: str
    pillow: str
    extension: str
    lossy: bool = False
    alpha: bool = False
    animation: bool = False
    icc: bool = True
    exif: bool = True
    quality: int | None = None
    floor: int = 30
    bpp: float = 1.0
    floor_bpp: float = 0.0
    fitted_bpp: float = 0.0
    transfer: float = 1.0
    resample: float = 0.0
    resample_content: float = 0.0
    landing: float = 2.0
    options: dict[str, Any] = {}


###########################################################################################################
###########################################################################################################
class ExportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["copy", "encode"] = "encode"
    reasons: list[str] = []
    format: str = ""
    width: int = 0
    height: int = 0
    crop: CropPlan | None = None
    color: ColorPlan | None = None
    quality: QualityPlan | None = None
    background: str | None = None
    srgb: bool = False
    still: bool = False
    options: dict[str, Any] = {}


###########################################################################################################
###########################################################################################################
class PhotoPreset(Model):
    photo_constraints: PhotoConstraints | None = None
