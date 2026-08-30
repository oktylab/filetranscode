from ...core.core import Node
from ..toolkit.introspect import param
from .models import ColorPlan

COMPENSATIONS: dict[str, ColorPlan] = {
    "h264": ColorPlan(),
    "hevc": ColorPlan(saturation=1.01),
    "av1": ColorPlan(saturation=1.01),
    "vp9": ColorPlan(saturation=1.01),
    "vp8": ColorPlan(saturation=1.02),
    "theora": ColorPlan(saturation=1.03),
    "mpeg4": ColorPlan(saturation=1.03, contrast=1.01),
    "mpeg2video": ColorPlan(saturation=1.03, contrast=1.01),
    "mjpeg": ColorPlan(saturation=1.04),
    "prores": ColorPlan(),
}


###########################################################################################################
###########################################################################################################
class CodecColor(Node):
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
