import img2pdf

from filetranscode.builtin.toolkit.output_resolve import OutputData
from filetranscode.builtin.toolkit.engine import Engine, operation
from filetranscode.exceptions import EngineError

_FAILURES = (ValueError, OSError, *(value for name, value in vars(img2pdf).items()
             if isinstance(value, type) and issubclass(value, Exception) and name.endswith("Error")))


class Img2PdfEngine(Engine):
    @operation
    async def encode(self, ctx):
        try:
            document = img2pdf.convert([data.path for data in ctx.input])
        except _FAILURES as error:
            raise EngineError(f"img2pdf cannot build a pdf from the given inputs: {error}")
        delivered = OutputData()
        with open(delivered.path, "wb") as out:
            out.write(document)
        ctx.page_count = len(ctx.input)
        ctx.output.append(delivered)
        return ctx
