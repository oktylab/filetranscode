from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..toolkit.web import ui


###########################################################################################################
###########################################################################################################
class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


###########################################################################################################
###########################################################################################################
class AudioMetadata(Model):
    codec: str
    bitrate: int | None = None
    channels: int | None = None
    sample_rate: int | None = None


###########################################################################################################
###########################################################################################################
class VideoMetadata(Model):
    codec: str
    container: str | None = None
    width: int
    height: int
    fps: float | None = None
    duration: float | None = None
    frame_count: int | None = None
    bitrate: int | None = None
    pix_fmt: str | None = None
    rotation: int = 0
    sar: float = 1.0
    size: int | None = None
    color_space: str | None = None
    color_range: str | None = None
    audio: AudioMetadata | None = None


###########################################################################################################
###########################################################################################################
class AudioConstraints(Model):
    codecs: list[str] | None = None
    max_bitrate: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=512_000, step=16_000))
    max_channels: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=8, step=1))
    samplerates: list[int] | None = Field(default=None, json_schema_extra=ui(choices=[48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000]))


###########################################################################################################
###########################################################################################################
class VideoConstraints(Model):
    codecs: list[str] = Field(default=["h264"], min_length=1, json_schema_extra=ui(choices_branch="video.rate", exclude=["default"]))
    formats: list[str] = Field(default=["mp4"], min_length=1)
    min_width: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7680, step=2))
    max_width: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7680, step=2))
    min_height: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7680, step=2))
    max_height: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7680, step=2))
    min_aspect: float | None = None
    max_aspect: float | None = None
    aspects: list[str] | None = None
    min_fps: float | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=240, step=1))
    max_fps: float | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=240, step=1))
    max_bitrate: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=150_000_000, step=250_000))
    min_bytes: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=2_000_000_000, step=10_000_000))
    max_bytes: int | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=2_000_000_000, step=10_000_000))
    min_duration: float | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7200, step=1))
    max_duration: float | None = Field(default=None, json_schema_extra=ui(widget="range", low=0, high=7200, step=1))


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
    trim_start: float | None = Field(default=None, ge=0, json_schema_extra=ui(widget="range", low=0, high=7200, step=0.1))
    trim_end: float | None = Field(default=None, ge=0, json_schema_extra=ui(widget="range", low=0, high=7200, step=0.1))
    aspect: str | None = Field(default=None, json_schema_extra=ui(widget="aspect", choices=["9:16", "16:9", "1:1", "4:5", "2:3"]))
    speed: float = Field(default=1.0, ge=0.1, le=5.0, json_schema_extra=ui(widget="range", low=0.1, high=5, step=0.1))
    volume: float = Field(default=1.0, ge=0.0, le=3.0, json_schema_extra=ui(widget="range", low=0, high=3, step=0.05))


###########################################################################################################
###########################################################################################################
class Reasons(Model):
    video: list[str] = []
    audio: list[str] = []


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
AUDIO_DEFAULT_BPS = 128_000


class RatePlan(Model):
    mode: Literal["abr", "crf"] = "abr"
    bitrate: int | None = None
    maxrate: int | None = None
    bufsize: int | None = None
    capped: bool = False
    estimated_bytes: int | None = None


###########################################################################################################
###########################################################################################################
class AudioPlan(Model):
    codec: str | None = None
    encoders: list[str] | None = None
    bitrate: int | None = None
    channels: int | None = None
    sample_rate: int | None = None


###########################################################################################################
###########################################################################################################
class CodecTraits(Model):
    codec: str
    encoders: list[str]
    bpp: float = 0.25
    pix_fmt: str = "yuv420p"
    containers: list[str] = ["mp4", "mov", "matroska"]
    options: dict[str, dict[str, str]] = {}
    quality: dict[str, dict[str, str]] = {}
    rc: dict[str, str] = {}
    landing: float = 1.0
    overshoot: float = 1.0
    floor_bpp: float = 0.0
    abr: bool = True


###########################################################################################################
###########################################################################################################
class ExportPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["copy", "remux", "encode"] = "encode"
    reasons: Reasons = Reasons()
    codec: str = ""
    encoders: list[str] = []
    pix_fmt: str = "yuv420p"
    options: dict[str, dict[str, str]] = {}
    rc: dict[str, str] = {}
    width: int = 0
    height: int = 0
    fps: float | None = None
    format: str = "mp4"
    audio: AudioPlan | None = None
    rate: RatePlan | None = None
    color: ColorPlan | None = None
    crop: CropPlan | None = None
    trim_start: float | None = None
    trim_end: float | None = None
    speed: float = 1.0
    volume: float = 1.0


###########################################################################################################
###########################################################################################################
def trimmed_duration(plan: "ExportPlan", metadata: "VideoMetadata") -> float | None:
    if plan.trim_start is not None or plan.trim_end is not None:
        window = (plan.trim_end or metadata.duration or 0.0) - (plan.trim_start or 0.0)
    else:
        window = metadata.duration
    return window / plan.speed if window is not None else None


def atempo_factors(speed: float) -> list[float]:
    factors: list[float] = []
    remainder = speed
    while remainder > 2.0:
        factors.append(2.0)
        remainder /= 2.0
    while remainder < 0.5:
        factors.append(0.5)
        remainder /= 0.5
    factors.append(remainder)
    return factors


###########################################################################################################
###########################################################################################################
class VideoPreset(Model):
    video_constraints: VideoConstraints | None = None
    audio_constraints: AudioConstraints | None = None
