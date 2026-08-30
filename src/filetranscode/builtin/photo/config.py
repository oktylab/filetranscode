from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...registry import registry
from ..toolkit.engine import validate_engine
from ..toolkit.web import ui
from .models import Edits, Filters, PhotoConstraints


class PhotoConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    preset: str | None = Field(default=None, json_schema_extra=ui(primary=True, choices_branch="photo.preset", exclude=["none"]))
    engine: str = Field(default="pillow", json_schema_extra=ui(primary=True, choices_prefix="photo.engine"))
    photo_constraints: PhotoConstraints = Field(default=PhotoConstraints(), json_schema_extra=ui(group="photo"))
    filters: Filters = Field(default=Filters(), json_schema_extra=ui(group="filters"))
    edits: Edits = Field(default=Edits(), json_schema_extra=ui(group="edits"))

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        return validate_engine(registry, "photo.engine", value)
