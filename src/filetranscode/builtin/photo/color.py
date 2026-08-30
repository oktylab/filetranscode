from ...core.core import Node
from ..toolkit.introspect import param
from .models import ColorPlan

COMPENSATIONS: dict[str, ColorPlan] = {
    "jpeg": ColorPlan(),
    "png": ColorPlan(),
    "webp": ColorPlan(),
    "avif": ColorPlan(),
    "heif": ColorPlan(),
    "gif": ColorPlan(),
    "tiff": ColorPlan(),
    "bmp": ColorPlan(),
}


###########################################################################################################
###########################################################################################################
class FormatColor(Node):
    def __init__(self, compensation: ColorPlan | None = None) -> None:
        self.compensation = compensation or ColorPlan()

    async def __call__(self, ctx):
        filters, compensation = param(ctx, "config").filters, self.compensation
        ctx.plan.color = ColorPlan(
            brightness=filters.brightness * compensation.brightness,
            contrast=filters.contrast * compensation.contrast,
            saturation=filters.saturation * compensation.saturation,
            hue=filters.hue + compensation.hue,
            grayscale=filters.grayscale,
            sepia=filters.sepia,
            invert=filters.invert,
        )
        return ctx
