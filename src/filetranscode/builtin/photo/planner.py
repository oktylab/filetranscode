import math
import os
import shutil
from urllib.parse import urlsplit

from ...core.core import Node
from ...exceptions import UnsatisfiableError
from ..toolkit.introspect import param
from ..toolkit.output_resolve import OutputData
from .formats import bytes_scale_exponent, density_of, format_of
from .models import ColorPlan, CropPlan, ExportPlan, aspect_of

SIZE_MARGIN = 0.95
MIN_DIMENSION = 16


###########################################################################################################
###########################################################################################################
class PlanFormat(Node):
    async def __call__(self, ctx):
        config = param(ctx, "config")
        metadata, limits = ctx.metadata.before[0], config.photo_constraints
        for name in limits.formats:
            format_of(name)
        still = config.edits.still and metadata.animated
        format = metadata.format if metadata.format in limits.formats else limits.formats[0]
        if metadata.animated and not still:
            candidates = [name for name in limits.formats if format_of(name).animation]
            if candidates:
                format = metadata.format if metadata.format in candidates else candidates[0]
        else:
            keeps_alpha = metadata.alpha and config.edits.background is None
            if keeps_alpha:
                candidates = [name for name in limits.formats if format_of(name).alpha]
                if candidates:
                    format = metadata.format if metadata.format in candidates else candidates[0]
            if limits.max_bytes and not format_of(format).lossy and density_of(format, metadata) * metadata.width * metadata.height > limits.max_bytes:
                lossy = [name for name in limits.formats if format_of(name).lossy and (not keeps_alpha or format_of(name).alpha)]
                if lossy:
                    format = lossy[0]
        traits = format_of(format)
        ctx.plan = ExportPlan(format=format, options=dict(traits.options), width=metadata.width, height=metadata.height, still=still)
        if format != metadata.format:
            ctx.plan.reasons.append("format")
        if still:
            ctx.plan.reasons.append("still")
        return ctx


###########################################################################################################
###########################################################################################################
ASPECT_TOLERANCE = 0.01


def _aspect_allowed(effective: float, limits) -> bool:
    if not limits.aspects and limits.min_aspect is None and limits.max_aspect is None:
        return True
    in_list = bool(limits.aspects) and any(abs(effective / aspect_of(allowed) - 1) <= ASPECT_TOLERANCE for allowed in limits.aspects)
    in_range = (limits.min_aspect is not None or limits.max_aspect is not None) \
        and (limits.min_aspect is None or effective >= limits.min_aspect * (1 - ASPECT_TOLERANCE)) \
        and (limits.max_aspect is None or effective <= limits.max_aspect * (1 + ASPECT_TOLERANCE))
    return in_list or in_range


def _aspect_demand(limits) -> str:
    parts = []
    if limits.aspects:
        parts.append(f"one of {', '.join(limits.aspects)}")
    if limits.min_aspect is not None or limits.max_aspect is not None:
        parts.append(f"within [{limits.min_aspect or 0:g}, {limits.max_aspect or math.inf:g}] (width:height)")
    return " or ".join(parts)


class PlanCrop(Node):
    async def __call__(self, ctx):
        config, plan = param(ctx, "config"), ctx.plan
        limits, requested = config.photo_constraints, config.edits.aspect
        target = aspect_of(requested) if requested else None
        source = plan.width / plan.height
        effective = target or source
        if not _aspect_allowed(effective, limits):
            subject = f"aspect {requested}" if requested else f"source aspect {plan.width}:{plan.height}"
            raise UnsatisfiableError(f"{subject} is not allowed; requires {_aspect_demand(limits)}")
        if target is None or abs(source / target - 1) <= ASPECT_TOLERANCE:
            return ctx
        if target < source:
            width, height = round(plan.height * target), plan.height
        else:
            width, height = plan.width, round(plan.width / target)
        plan.crop = CropPlan(x=(plan.width - width) // 2, y=(plan.height - height) // 2, width=width, height=height)
        plan.width, plan.height = width, height
        plan.reasons.append("aspect")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanGeometry(Node):
    async def __call__(self, ctx):
        plan, limits, metadata = ctx.plan, param(ctx, "config").photo_constraints, ctx.metadata.before[0]
        width, height = plan.width, plan.height
        down = min((limits.max_width or width) / width, (limits.max_height or height) / height, 1.0)
        if limits.max_pixels and width * height * down * down > limits.max_pixels:
            down = math.sqrt(limits.max_pixels / (width * height))
        demand = "the maximum size constraints"
        if limits.max_bytes:
            frames = metadata.frames if metadata.animated and not plan.still else 1
            budget = limits.max_bytes * SIZE_MARGIN
            pixels = width * height * down * down * frames
            traits = format_of(plan.format)
            landing = 1.0 if traits.lossy else math.sqrt(traits.landing)
            if density_of(plan.format, metadata, floor=True) * pixels * landing > budget:
                overshoot = budget / (density_of(plan.format, metadata) * pixels * landing)
                byte_scale = overshoot ** (1 / bytes_scale_exponent(plan.format, metadata))
                if byte_scale < 1.0:
                    down *= byte_scale
                    demand = f"max_bytes={limits.max_bytes}"
        up = max((limits.min_width or width) / width, (limits.min_height or height) / height, 1.0)
        if down < 1.0 and up > 1.0:
            raise UnsatisfiableError(f"{width}x{height} cannot satisfy both the minimum size constraints and {demand} at once")
        scale = down if down < 1.0 else up
        fit = math.floor if scale < 1.0 else math.ceil
        fitted = fit(width * scale), fit(height * scale)
        if min(fitted) < MIN_DIMENSION:
            raise UnsatisfiableError(f"fitting {demand} would shrink {width}x{height} below {MIN_DIMENSION}px; the constraints are unsatisfiable")
        if (limits.min_width and fitted[0] < limits.min_width) or (limits.min_height and fitted[1] < limits.min_height):
            raise UnsatisfiableError(f"{width}x{height} cannot satisfy both the minimum size constraints and {demand} at once")
        if fitted != (width, height):
            plan.width, plan.height = fitted
            plan.reasons.append("resolution")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanColorSpace(Node):
    async def __call__(self, ctx):
        plan, limits, metadata = ctx.plan, param(ctx, "config").photo_constraints, ctx.metadata.before[0]
        if limits.srgb and metadata.icc and "srgb" not in metadata.icc.lower():
            plan.srgb = True
            plan.reasons.append("srgb")
        return ctx


###########################################################################################################
###########################################################################################################
DEFAULT_BACKGROUND = "#ffffff"


class PlanAlpha(Node):
    async def __call__(self, ctx):
        plan, config, metadata = ctx.plan, param(ctx, "config"), ctx.metadata.before[0]
        if not metadata.alpha or (metadata.animated and not plan.still):
            return ctx
        if config.edits.background is not None:
            plan.background = config.edits.background
            plan.reasons.append("alpha")
        elif not format_of(plan.format).alpha:
            plan.background = DEFAULT_BACKGROUND
            plan.reasons.append("alpha")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanLimits(Node):
    async def __call__(self, ctx):
        plan, limits, metadata = ctx.plan, param(ctx, "config").photo_constraints, ctx.metadata.before[0]
        if limits.max_bytes and metadata.size and metadata.size > limits.max_bytes:
            plan.reasons.append("size")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanAction(Node):
    async def __call__(self, ctx):
        plan, filters, metadata = ctx.plan, param(ctx, "config").filters, ctx.metadata.before[0]
        color = ColorPlan(brightness=filters.brightness, contrast=filters.contrast, saturation=filters.saturation, hue=filters.hue,
                          grayscale=filters.grayscale, sepia=filters.sepia, invert=filters.invert)
        if not color.identity():
            plan.reasons.append("color")
        plan.action = "encode" if plan.reasons else "copy"
        if plan.action == "encode" and metadata.animated and not plan.still and not format_of(plan.format).animation:
            raise UnsatisfiableError(
                f"animated {metadata.format} needs re-encoding ({', '.join(plan.reasons)}) but {plan.format} cannot hold animation; "
                "allow an animated format (gif, webp) or set edits.still to deliver the first frame"
            )
        return ctx


###########################################################################################################
###########################################################################################################
class Copy(Node):
    async def __call__(self, ctx):
        data = OutputData()
        source = ctx.input[0]
        if source.raw_bytes is not None:
            data.bytes_ = source.raw_bytes
        elif source.raw_path is not None and urlsplit(os.fspath(source.raw_path)).scheme in ("http", "https"):
            with open(data.path, "wb") as sink:
                shutil.copyfileobj(source.stream, sink)
        else:
            shutil.copyfile(source.path, data.path)
        ctx.output.append(data)
        return ctx
