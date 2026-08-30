from typing import Any

from filetranscode.core.core import Branch, Sequence
from filetranscode.builtin.toolkit.input_resolve import InputBytesResolver, InputListResolver, InputPathResolver, InputStreamResolver, input_list_type, scheme_of
from filetranscode.builtin.toolkit.output_resolve import OutputBytesResolver, OutputPathResolver, OutputStreamResolver, output_scheme_of, output_type
from filetranscode.builtin.toolkit.pipeline import Pipeline, engine_node, node

from .config import PdfConfig
from .context import PdfContext
from .engines.img2pdf_engine import Img2PdfEngine
from .engines.reportlab_engine import ReportLabEngine

InputsLike = input_list_type(InputPathResolver, InputBytesResolver, InputStreamResolver)
OutputLike = output_type(OutputPathResolver, OutputBytesResolver, OutputStreamResolver)


class PdfPipeline(Pipeline):
    name = "pdf"
    media = "pdf"
    config_cls = PdfConfig
    context_cls = PdfContext

    @node("resolve")
    def resolve(self):
        return Branch(
            selector=scheme_of,
            default=InputPathResolver(),
            bytes=InputBytesResolver(),
            stream=InputStreamResolver(),
        )

    @node("output")
    def output(self):
        return Branch(
            selector=output_scheme_of,
            default=OutputPathResolver(),
            bytes=OutputBytesResolver(),
            stream=OutputStreamResolver(),
        )

    @engine_node("img2pdf")
    def img2pdf(self):
        return Img2PdfEngine()

    @engine_node("reportlab")
    def reportlab(self):
        return ReportLabEngine()

    @node("export", public=True)
    def export(self, images: InputsLike, output: OutputLike, config: PdfConfig) -> Any:
        return Sequence(InputListResolver(self._registry, f"{self.name}.resolve"), self.engine_operation("encode"), self.ref("output"))
