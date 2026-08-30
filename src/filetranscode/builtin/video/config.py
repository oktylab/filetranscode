from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...registry import registry
from ..toolkit.engine import validate_engine
from ..toolkit.web import ui
from .models import AudioConstraints, Edits, Filters, VideoConstraints


class VideoConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preset: str | None = Field(default=None, json_schema_extra=ui(primary=True, choices_branch="video.preset", exclude=["none"]))
    engine: str = Field(default="ffmpeg", json_schema_extra=ui(primary=True, choices_prefix="video.engine"))
    video_constraints: VideoConstraints = Field(default=VideoConstraints(), json_schema_extra=ui(group="video"))
    audio_constraints: AudioConstraints = Field(default=AudioConstraints(), json_schema_extra=ui(group="audio"))
    filters: Filters = Field(default=Filters(), json_schema_extra=ui(group="filters"))
    edits: Edits = Field(default=Edits(), json_schema_extra=ui(group="edits"))

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        return validate_engine(registry, "video.engine", value)
