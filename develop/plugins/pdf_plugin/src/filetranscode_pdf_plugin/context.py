from typing import Any

from filetranscode.builtin.toolkit.input_resolve import InputData
from filetranscode.builtin.toolkit.output_resolve import OutputData
from pydantic import BaseModel, ConfigDict



class PdfContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    input: list[InputData] = []
    output: list[OutputData] = []
    out: Any = None
    page_count: int | None = None
