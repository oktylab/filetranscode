from typing import Any

from pydantic import BaseModel, ConfigDict


###########################################################################################################
###########################################################################################################
def ui(**hints: Any) -> dict[str, Any]:
    return {"ui": hints}


def ui_of(field) -> dict[str, Any]:
    extra = field.json_schema_extra
    return extra.get("ui", {}) if isinstance(extra, dict) else {}


###########################################################################################################
###########################################################################################################
class WebContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    group: str = ""
    values: dict[str, str] = {}
    files: dict[str, list[bytes]] = {}
    html: str | None = None
    result: Any = None
    body: bytes | None = None
    parts: list[bytes] | None = None
    trace: dict[str, Any] | None = None
    content_type: str = "application/octet-stream"
    headers: dict[str, str] = {}
