from pydantic import BaseModel, ConfigDict, Field, field_validator

from filetranscode.registry import registry
from filetranscode.builtin.toolkit.engine import validate_engine
from filetranscode.builtin.toolkit.web import ui


class PdfConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    engine: str = Field(default="img2pdf", json_schema_extra=ui(choices_prefix="pdf.engine"))
    page_size: str | None = Field(default=None, json_schema_extra=ui(choices=["A4", "LETTER"]))
    title: str | None = None

    @field_validator("engine")
    @classmethod
    def _validate_engine(cls, value: str) -> str:
        return validate_engine(registry, "pdf.engine", value)
