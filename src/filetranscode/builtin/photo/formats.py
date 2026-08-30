import math

from ..toolkit.web import ui
from .models import FormatTraits, PhotoConstraints


###########################################################################################################
###########################################################################################################
FORMATS: dict[str, FormatTraits] = {}
PILLOW_NAMES: dict[str, str] = {}


def register_format(traits: FormatTraits) -> None:
    FORMATS[traits.format] = traits
    PILLOW_NAMES[traits.pillow] = traits.format


def format_of(name: str) -> FormatTraits:
    traits = FORMATS.get(name)
    if traits is None:
        raise ValueError(f"unknown photo format {name!r}, available: {list(FORMATS)}")
    return traits


def format_for_pillow(pillow_name: str | None) -> str:
    return PILLOW_NAMES.get(pillow_name or "", (pillow_name or "unknown").lower())


###########################################################################################################
###########################################################################################################
CONTENT_FACTOR_RANGE = (0.02, 10.0)
MIN_BYTES_SCALE_EXPONENT = 0.5


def content_factor(metadata) -> float:
    source = FORMATS.get(metadata.format)
    if source is None or not metadata.size or not metadata.width or not metadata.height:
        return 1.0
    density = metadata.size / (metadata.width * metadata.height * max(metadata.frames, 1))
    low, high = CONTENT_FACTOR_RANGE
    return min(max(density / source.bpp, low), high)


def density_of(name: str, metadata, scale: float = 1.0, floor: bool = False) -> float:
    traits = format_of(name)
    factor = content_factor(metadata)
    base = (traits.floor_bpp or traits.fitted_bpp or traits.bpp) if floor else (traits.fitted_bpp or traits.bpp)
    exponent = traits.resample + traits.resample_content * math.log(factor)
    return base * factor ** traits.transfer * scale ** exponent


def bytes_scale_exponent(name: str, metadata) -> float:
    traits = format_of(name)
    return max(2.0 + traits.resample + traits.resample_content * math.log(content_factor(metadata)), MIN_BYTES_SCALE_EXPONENT)


###########################################################################################################
###########################################################################################################
for traits in (
    FormatTraits(
        format="jpeg",
        pillow="JPEG",
        extension="jpg",
        lossy=True,
        quality=90,
        floor=35,
        bpp=0.4,
        fitted_bpp=0.402,
        transfer=0.442,
        resample=-0.091,
        resample_content=0.086,
        landing=1.91,
        floor_bpp=0.08,
        options={"optimize": True, "subsampling": 0},
    ),
    FormatTraits(
        format="png",
        pillow="PNG",
        extension="png",
        alpha=True,
        bpp=2.2,
        fitted_bpp=2.621,
        transfer=1.045,
        resample=0.029,
        resample_content=0.321,
        landing=1.95,
        options={"compress_level": 9},
    ),
    FormatTraits(
        format="webp",
        pillow="WEBP",
        extension="webp",
        lossy=True,
        alpha=True,
        animation=True,
        quality=85,
        floor=30,
        bpp=0.35,
        fitted_bpp=0.211,
        transfer=0.552,
        resample=-0.035,
        resample_content=0.13,
        landing=2.42,
        floor_bpp=0.11,
        options={"method": 4},
    ),
    FormatTraits(
        format="avif",
        pillow="AVIF",
        extension="avif",
        lossy=True,
        alpha=True,
        quality=72,
        floor=30,
        bpp=0.3,
        fitted_bpp=0.169,
        transfer=0.692,
        resample=-0.009,
        resample_content=0.238,
        landing=2.78,
        floor_bpp=0.013,
        options={"speed": 6},
    ),
    FormatTraits(
        format="heif",
        pillow="HEIF",
        extension="heic",
        lossy=True,
        alpha=True,
        quality=65,
        floor=30,
        bpp=0.5,
        fitted_bpp=0.444,
        transfer=0.719,
        resample=0.033,
        resample_content=0.231,
        landing=1.97,
        floor_bpp=0.105,
    ),
    FormatTraits(
        format="gif",
        pillow="GIF",
        extension="gif",
        alpha=True,
        animation=True,
        icc=False,
        exif=False,
        bpp=0.8,
        fitted_bpp=0.771,
        transfer=0.948,
        resample=-0.149,
        resample_content=0.167,
        landing=1.65,
    ),
    FormatTraits(
        format="tiff",
        pillow="TIFF",
        extension="tiff",
        alpha=True,
        bpp=2.4,
        fitted_bpp=2.4,
        transfer=1.045,
        resample=0.029,
        resample_content=0.321,
        landing=2.0,
        options={"compression": "tiff_adobe_deflate"},
    ),
    FormatTraits(
        format="bmp",
        pillow="BMP",
        extension="bmp",
        icc=False,
        exif=False,
        bpp=3.0,
        fitted_bpp=3.0,
        transfer=0.0,
        resample=0.0,
        resample_content=0.0,
        landing=1.05,
    ),
):
    register_format(traits)

PhotoConstraints.model_fields["formats"].json_schema_extra = ui(choices=lambda: list(FORMATS))
