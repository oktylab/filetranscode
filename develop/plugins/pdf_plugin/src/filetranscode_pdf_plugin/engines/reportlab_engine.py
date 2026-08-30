from PIL import Image
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfgen import canvas

from filetranscode.builtin.toolkit.introspect import param
from filetranscode.builtin.toolkit.output_resolve import OutputData
from filetranscode.builtin.toolkit.engine import Engine, operation
from filetranscode.exceptions import EngineError

_PAGE_SIZES = {"A4": A4, "LETTER": LETTER}


class ReportLabEngine(Engine):
    @operation
    async def encode(self, ctx):
        config = param(ctx, "config")
        page = _PAGE_SIZES.get(config.page_size, A4) if config.page_size else A4
        delivered = OutputData()
        doc = canvas.Canvas(delivered.path, pagesize=page)
        if config.title:
            doc.setTitle(config.title)
        for data in ctx.input:
            try:
                self._draw_page(doc, data.path, page)
            except (OSError, ValueError) as error:
                raise EngineError(f"reportlab cannot draw one of the inputs as an image: {error}")
        doc.save()
        ctx.page_count = len(ctx.input)
        ctx.output.append(delivered)
        return ctx

    def _draw_page(self, doc, path, page):
        with Image.open(path) as img:
            width, height = img.size
        scale = min(page[0] / width, page[1] / height)
        draw_width, draw_height = width * scale, height * scale
        x, y = (page[0] - draw_width) / 2, (page[1] - draw_height) / 2
        doc.drawImage(path, x, y, width=draw_width, height=draw_height)
        doc.showPage()
