import math

from ...core.core import Node, NodeDescription
from ...core.trace import traced
from ...exceptions import UnsatisfiableError
from ..toolkit.introspect import param
from .formats import bytes_scale_exponent, density_of, format_of
from .models import FormatTraits, QualityPlan
from .planner import MIN_DIMENSION, SIZE_MARGIN

SQUEEZE_EXPONENT = 0.6


###########################################################################################################
###########################################################################################################
class FormatQuality(Node):
    def __init__(self, traits: FormatTraits | None = None) -> None:
        self.traits = traits

    async def __call__(self, ctx):
        plan, limits, metadata = ctx.plan, param(ctx, "config").photo_constraints, ctx.metadata.before[0]
        traits = self.traits or format_of(plan.format)
        count = metadata.frames if metadata.animated and not plan.still else 1
        source_width = plan.crop.width if plan.crop else metadata.width
        scale = min(plan.width / source_width, 1.0) if source_width else 1.0
        estimated = int(density_of(plan.format, metadata, scale=scale) * plan.width * plan.height * count)
        if traits.quality is None:
            plan.quality = QualityPlan(lossless=True, estimated_bytes=estimated)
            return ctx
        quality = traits.quality
        if limits.max_bytes and estimated > limits.max_bytes:
            quality = max(traits.floor, int(quality * (limits.max_bytes / estimated) ** SQUEEZE_EXPONENT))
        plan.quality = QualityPlan(quality=quality, estimated_bytes=int(estimated * (quality / traits.quality) ** (1 / SQUEEZE_EXPONENT)))
        return ctx


###########################################################################################################
###########################################################################################################
class SizeRetry(Node):
    def __init__(self, node: Node, attempts: int = 3) -> None:
        self.node = node
        self.attempts = attempts

    async def __call__(self, ctx):
        config = param(ctx, "config")
        limit = config.photo_constraints.max_bytes if config else None
        source = list(ctx.input)
        for attempt in range(self.attempts):
            ctx.input = list(source)
            ctx = await traced(self.node, ctx, label=f"attempt {attempt + 1}" if attempt else "")
            delivered = ctx.output[-1]
            if not limit or ctx.plan.quality is None or delivered.size <= limit:
                return ctx
            produced = delivered.size
            quality = ctx.plan.quality
            ctx.output.pop().cleanup()
            floor = format_of(ctx.plan.format).floor
            needed = limit * SIZE_MARGIN / produced
            if not quality.lossless and quality.quality > floor:
                squeezed = int(quality.quality * needed ** SQUEEZE_EXPONENT)
                if squeezed >= floor:
                    ctx.plan = ctx.plan.model_copy(update={"quality": quality.model_copy(update={"quality": squeezed})})
                    continue
                needed /= (floor / quality.quality) ** (1 / SQUEEZE_EXPONENT)
                ctx.plan = ctx.plan.model_copy(update={"quality": quality.model_copy(update={"quality": floor})})
                quality = ctx.plan.quality
            scale = min(needed, 1.0) ** (1 / bytes_scale_exponent(ctx.plan.format, ctx.metadata.before[0]))
            width, height = round(ctx.plan.width * scale), round(ctx.plan.height * scale)
            limits = config.photo_constraints
            if min(width, height) < MIN_DIMENSION or (limits.min_width and width < limits.min_width) or (limits.min_height and height < limits.min_height):
                raise UnsatisfiableError(
                    f"{ctx.plan.format} produced {produced} bytes at {ctx.plan.width}x{ctx.plan.height}, over max_bytes={limit}, "
                    f"and cannot shrink below the minimum size to fit"
                )
            ctx.plan = ctx.plan.model_copy(update={"width": width, "height": height})
        raise UnsatisfiableError(f"output stayed over max_bytes={limit} after {self.attempts} attempts")

    def describe(self):
        return NodeDescription(kind="SizeRetry", children=[self.node.describe()])
