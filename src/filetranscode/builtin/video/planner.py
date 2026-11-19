import math
import os
import shutil
from urllib.parse import urlsplit

from ...core.core import Node
from ...exceptions import UnsatisfiableError
from ...registry import registry
from .formats import AUDIO_CODECS, audio_codec_of, container_holds, format_of
from .models import AUDIO_DEFAULT_BPS, AudioPlan, ColorPlan, CropPlan, ExportPlan, aspect_of, trimmed_duration
from ..toolkit.introspect import param
from ..toolkit.output_resolve import OutputData
from .rate import traits_of

# A trim end that overshoots the probed duration by under a frame (or this many seconds) means "the end":
# probes round durations (ffprobe prints 6 decimals) and clients read them from a different stream or clock.
TRIM_END_SLACK = 0.1


###########################################################################################################
###########################################################################################################
class PlanCodec(Node):
    async def __call__(self, ctx):
        metadata, limits = ctx.metadata.before[0], param(ctx, "config").video_constraints
        codec = metadata.codec if metadata.codec in limits.codecs else limits.codecs[0]
        traits = traits_of(codec)
        ctx.plan = ExportPlan(
            codec=codec,
            encoders=traits.encoders,
            pix_fmt=traits.pix_fmt,
            options=dict(traits.options),
            rc=dict(traits.rc),
            format=next((name for name in limits.formats if name in traits.containers), traits.containers[0]),
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
        )
        if codec != metadata.codec:
            ctx.plan.reasons.video.append("codec")
        if limits.pix_fmts and metadata.pix_fmt not in limits.pix_fmts:
            ctx.plan.pix_fmt = limits.pix_fmts[0]
            ctx.plan.reasons.video.append("pix_fmt")
        return ctx


###########################################################################################################
###########################################################################################################
ASPECT_TOLERANCE = 0.01


def _check_aspect(effective: float, subject: str, limits) -> None:
    if limits.aspects and all(abs(effective / aspect_of(allowed) - 1) > ASPECT_TOLERANCE for allowed in limits.aspects):
        raise UnsatisfiableError(f"{subject} is not allowed; requires one of {', '.join(limits.aspects)}")
    if (limits.min_aspect and effective < limits.min_aspect * (1 - ASPECT_TOLERANCE)) or (limits.max_aspect and effective > limits.max_aspect * (1 + ASPECT_TOLERANCE)):
        raise UnsatisfiableError(f"{subject} is outside [{limits.min_aspect or 0:g}, {limits.max_aspect or math.inf:g}] (width:height)")


def _crop_box(crop, width: int, height: int) -> CropPlan:
    # every edge lands on an even pixel: 4:2:0 video keeps one color sample per 2x2 pixels, and its encoders refuse odd sizes
    x, y = 2 * round(crop.x1 * width / 2), 2 * round(crop.y1 * height / 2)
    right, bottom = min(2 * round(crop.x2 * width / 2), width // 2 * 2), min(2 * round(crop.y2 * height / 2), height // 2 * 2)
    if right <= x or bottom <= y:
        raise UnsatisfiableError(f"crop ({crop.x1:g}, {crop.y1:g}) to ({crop.x2:g}, {crop.y2:g}) keeps no pixels of the {width}x{height} frame")
    return CropPlan(x=x, y=y, width=right - x, height=bottom - y)


class PlanCrop(Node):
    async def __call__(self, ctx):
        config, plan = param(ctx, "config"), ctx.plan
        limits, edits = config.video_constraints, config.edits
        if edits.crop:
            # a crop rectangle wins over an aspect, which is then ignored
            box = _crop_box(edits.crop, plan.width, plan.height)
            _check_aspect(box.width / box.height, f"crop {box.width}x{box.height}", limits)
            if (box.width, box.height) != (plan.width, plan.height):
                plan.crop = box
                plan.width, plan.height = box.width, box.height
                plan.reasons.video.append("crop")
            return ctx
        requested = edits.aspect
        target = aspect_of(requested) if requested else None
        source = plan.width / plan.height
        _check_aspect(target or source, f"aspect {requested}" if requested else f"source aspect {plan.width}:{plan.height}", limits)
        if target is None or abs(source / target - 1) <= ASPECT_TOLERANCE:
            return ctx
        if target < source:
            width, height = 2 * round(plan.height * target / 2), plan.height
            refined = 2 * round(width / target / 2)
            if refined <= plan.height:
                height = refined
        else:
            width, height = plan.width, 2 * round(plan.width / target / 2)
            refined = 2 * round(height * target / 2)
            if refined <= plan.width:
                width = refined
        plan.crop = CropPlan(x=(plan.width - width) // 2 // 2 * 2, y=(plan.height - height) // 2 // 2 * 2, width=width, height=height)
        plan.width, plan.height = width, height
        plan.reasons.video.append("aspect")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanGeometry(Node):
    async def __call__(self, ctx):
        plan, limits = ctx.plan, param(ctx, "config").video_constraints
        width, height = plan.width, plan.height
        short, long = min(width, height), max(width, height)
        down = min((limits.max_width or width) / width, (limits.max_height or height) / height, (limits.max_short_side or short) / short, (limits.max_long_side or long) / long, 1.0)
        up = max((limits.min_width or width) / width, (limits.min_height or height) / height, (limits.min_short_side or short) / short, (limits.min_long_side or long) / long, 1.0)
        if down < 1.0 and up > 1.0:
            raise UnsatisfiableError(f"{width}x{height} cannot satisfy both the minimum and maximum size constraints at once")
        scale = down if down < 1.0 else up
        fitted = 2 * round(width * scale / 2), 2 * round(height * scale / 2)
        if fitted != (width, height):
            plan.width, plan.height = fitted
            plan.reasons.video.append("resolution")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanFrameRate(Node):
    async def __call__(self, ctx):
        config, plan, metadata = param(ctx, "config"), ctx.plan, ctx.metadata.before[0]
        limits = config.video_constraints
        if plan.fps is None:
            return ctx
        # platforms count the frames that are there, so the limits are checked at the lower of the declared and the
        # average rate (a clip declaring 30/1 that averages 20 is raised to min_fps). A clip kept on its own timing keeps
        # its declared rate, the one every frame the export adds (a cover) must run on; a new constant rate grid (a capped
        # rate, a speed change) is laid at the measured rate instead, as a declared rate can be a timestamp artifact
        measured = min(plan.fps, metadata.average_fps or plan.fps)
        clamped = min(measured, limits.max_fps or measured)
        clamped = max(clamped, limits.min_fps or clamped)
        if clamped != measured:
            plan.reasons.video.append("fps")
        if clamped != measured or config.edits.speed != 1.0:
            plan.fps = clamped
        return ctx


###########################################################################################################
###########################################################################################################
class PlanAudio(Node):
    async def __call__(self, ctx):
        plan, config, audio = ctx.plan, param(ctx, "config"), ctx.metadata.before[0].audio
        if audio is None:
            return ctx
        limits = config.audio_constraints
        traits = format_of(plan.format)
        default, held = traits.audio_default, traits.audio_codecs
        checks = {
            "speed": plan.speed != 1.0,
            "volume": plan.volume != 1.0,
            "codec": (limits.codecs is not None and audio.codec not in limits.codecs) or (held is not None and audio.codec not in held),
            "bitrate": bool(limits.max_bitrate and audio.bitrate and audio.bitrate > limits.max_bitrate),
            "channels": bool(limits.max_channels and audio.channels and audio.channels > limits.max_channels),
            "samplerate": bool(limits.samplerates and audio.sample_rate and audio.sample_rate not in limits.samplerates),
        }
        plan.reasons.audio.extend(name for name, hit in checks.items() if hit)
        if not plan.reasons.audio:
            plan.audio = AudioPlan()
            return ctx
        candidates = [codec for codec in (limits.codecs or [default or audio.codec]) if held is None or codec in held] or [default or audio.codec]
        target = audio_codec_of(audio.codec if audio.codec in candidates else candidates[0])
        source = AUDIO_CODECS.get(audio.codec)
        source_bitrate = (audio.bitrate or AUDIO_DEFAULT_BPS) if source and not source.lossless else AUDIO_DEFAULT_BPS
        sample_rate = limits.samplerates[0] if checks["samplerate"] else audio.sample_rate
        if sample_rate and target.samplerates and sample_rate not in target.samplerates:
            sample_rate = min(target.samplerates, key=lambda rate: abs(rate - sample_rate))
        bitrate = int(min(source_bitrate, limits.max_bitrate or math.inf, target.max_bitrate or math.inf))
        if target.bitrates:
            bitrate = min(target.bitrates, key=lambda legal: abs(legal - bitrate))
        plan.audio = AudioPlan(
            codec=target.codec,
            encoders=target.encoders,
            bitrate=bitrate,
            channels=min(audio.channels, limits.max_channels) if audio.channels and limits.max_channels else audio.channels,
            sample_rate=sample_rate,
        )
        return ctx


###########################################################################################################
###########################################################################################################
class PlanEdits(Node):
    async def __call__(self, ctx):
        plan, edits, metadata = ctx.plan, param(ctx, "config").edits, ctx.metadata.before[0]
        if edits.speed != 1.0:
            plan.speed = edits.speed
            plan.reasons.video.append("speed")
        if edits.volume != 1.0:
            plan.volume = edits.volume
        if edits.frame_image:
            plan.frame_image, plan.frame_image_at, plan.frame_image_frames = edits.frame_image, edits.frame_image_at, edits.frame_image_frames
            plan.reasons.video.append("frame_image")
        if edits.trim_start is None and edits.trim_end is None:
            return ctx
        duration = metadata.duration
        start, end = edits.trim_start or 0.0, edits.trim_end or duration
        if end is None:
            raise UnsatisfiableError("trim_end is required when the source reports no duration")
        if end <= start:
            raise UnsatisfiableError(f"trim range [{start:g}s, {end:g}s] is empty")
        if duration and end > duration and end - duration <= max(1 / metadata.fps if metadata.fps else 0.0, TRIM_END_SLACK):
            end = duration
        if duration and (start >= duration or end > duration):
            raise UnsatisfiableError(f"trim range [{start:g}s, {end:g}s] exceeds the source duration {duration:g}s")
        plan.trim_start, plan.trim_end = start, end
        plan.reasons.video.append("trim")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanLimits(Node):
    async def __call__(self, ctx):
        plan, limits, metadata = ctx.plan, param(ctx, "config").video_constraints, ctx.metadata.before[0]
        duration = trimmed_duration(plan, metadata)
        if duration and ((limits.max_duration and duration > limits.max_duration) or (limits.min_duration and duration < limits.min_duration)):
            raise UnsatisfiableError(f"duration {duration:g}s is outside [{limits.min_duration or 0:g}s, {limits.max_duration or math.inf:g}s]")
        if limits.max_bitrate and metadata.bitrate and metadata.bitrate > limits.max_bitrate:
            plan.reasons.video.append("bitrate")
        if limits.max_bytes and metadata.size and metadata.size > limits.max_bytes:
            plan.reasons.video.append("size")
        if limits.min_bytes and metadata.size and metadata.size < limits.min_bytes:
            plan.reasons.video.append("min_size")
        return ctx


###########################################################################################################
###########################################################################################################
class PlanAction(Node):
    async def __call__(self, ctx):
        plan, config, metadata = ctx.plan, param(ctx, "config"), ctx.metadata.before[0]
        filters = param(ctx, "config").filters
        color = ColorPlan(brightness=filters.brightness, contrast=filters.contrast, saturation=filters.saturation, hue=filters.hue,
                          grayscale=filters.grayscale, sepia=filters.sepia, invert=filters.invert)
        if not color.identity():
            plan.reasons.video.append("color")
        if not container_holds(metadata.container, plan.format):
            plan.reasons.video.append("container")
        video = [reason for reason in plan.reasons.video if reason != "container"]
        if video:
            plan.action = "encode"
        elif plan.reasons.video or plan.reasons.audio:
            plan.action = "remux" if "remux" in engine_operations(config) else "encode"
        else:
            plan.action = "copy"
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


###########################################################################################################
###########################################################################################################
def engine_operations(config) -> list[str]:
    return type(registry.get(f"video.engine.{config.engine}")).operations()
