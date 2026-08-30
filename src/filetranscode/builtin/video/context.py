from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ..toolkit.input_resolve import InputData
from ..toolkit.output_resolve import OutputData
from ..toolkit.pipeline import Probed
from .models import ExportPlan, VideoMetadata


class VideoContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    input: list[InputData] = []
    output: list[OutputData] = []
    out: Any = None
    metadata: Probed[VideoMetadata] = Probed()
    plan: ExportPlan | None = None
    probe: Literal["before", "after"] = "before"
