import math

from ...core.core import Node
from ...core.trace import traced
from ...exceptions import UnsatisfiableError
from ...registry import registry
from ..toolkit.introspect import param
from .formats import audio_codec_of
from .models import AUDIO_DEFAULT_BPS, CodecTraits, RatePlan, trimmed_duration

GENERIC = CodecTraits(codec="*", encoders=[])
TRAITS: dict[str, CodecTraits] = {
    "h264": CodecTraits(
        codec="h264",
        encoders=["libx264"],
        bpp=0.3,
        landing=0.79,
        pix_fmt="yuv420p",
        containers=["mp4", "mov", "matroska", "mpegts", "avi"],
        rc={"libx264": "vbv"},
        quality={"libx264": {"crf": "23"}},
    ),
    "hevc": CodecTraits(
        codec="hevc",
        encoders=["libx265"],
        bpp=0.27,
        landing=0.45,
        pix_fmt="yuv420p",
        containers=["mp4", "mov", "matroska", "mpegts"],
        rc={"libx265": "vbv"},
        quality={"libx265": {"crf": "22"}},
        options={"libx265": {"x265-params": "log-level=error"}},
    ),
    "av1": CodecTraits(
        codec="av1",
        encoders=["libsvtav1", "libaom-av1"],
        bpp=0.2,
        landing=0.53,
        pix_fmt="yuv420p",
        containers=["mp4", "webm", "matroska"],
        rc={"libsvtav1": "vbv", "libaom-av1": "cq"},
        quality={"libsvtav1": {"crf": "34"}, "libaom-av1": {"crf": "34"}},
        options={"libsvtav1": {"preset": "8"}, "libaom-av1": {"cpu-used": "6", "row-mt": "1"}},
    ),
    "vp9": CodecTraits(
        codec="vp9",
        encoders=["libvpx-vp9"],
        bpp=0.29,
        landing=0.5,
        pix_fmt="yuv420p",
        containers=["webm", "mp4", "matroska"],
        rc={"libvpx-vp9": "cq"},
        quality={"libvpx-vp9": {"crf": "31"}},
        options={"libvpx-vp9": {"deadline": "good", "cpu-used": "2", "row-mt": "1"}},
    ),
    "vp8": CodecTraits(
        codec="vp8",
        encoders=["libvpx"],
        bpp=0.58,
        landing=0.88,
        pix_fmt="yuv420p",
        containers=["webm", "matroska"],
        rc={"libvpx": "budget"},
        quality={"libvpx": {"crf": "12"}},
        options={"libvpx": {"deadline": "good", "cpu-used": "2"}},
    ),
    "theora": CodecTraits(
        codec="theora",
        encoders=["libtheora"],
        bpp=0.7,
        landing=0.4,
        pix_fmt="yuv420p",
        containers=["ogg", "matroska"],
        quality={"libtheora": {"flags": "+qscale", "global_quality": "826"}},
    ),
    "mpeg4": CodecTraits(
        codec="mpeg4",
        encoders=["mpeg4", "libxvid"],
        bpp=0.7,
        landing=0.49,
        pix_fmt="yuv420p",
        containers=["mp4", "avi", "matroska"],
        rc={"mpeg4": "abr-vbv", "libxvid": "abr-vbv"},
        quality={"mpeg4": {"qmin": "4", "qmax": "4"}, "libxvid": {"qmin": "4", "qmax": "4"}},
    ),
    "mpeg2video": CodecTraits(
        codec="mpeg2video",
        encoders=["mpeg2video"],
        bpp=0.8,
        landing=0.55,
        pix_fmt="yuv420p",
        containers=["mpeg", "mpegts", "matroska"],
        rc={"mpeg2video": "abr-vbv"},
        quality={"mpeg2video": {"qmin": "4", "qmax": "4"}},
    ),
    "mjpeg": CodecTraits(
        codec="mjpeg",
        encoders=["mjpeg"],
        bpp=2.1,
        landing=0.29,
        overshoot=1.25,
        floor_bpp=0.5,
        pix_fmt="yuvj420p",
        containers=["avi", "matroska", "mov"],
        rc={"mjpeg": "abr-vbv"},
        quality={"mjpeg": {"qmin": "5", "qmax": "5"}},
    ),
    "prores": CodecTraits(
        codec="prores",
        encoders=["prores_ks", "prores_aw", "prores"],
        bpp=3.6,
        landing=1.16,
        abr=False,
        pix_fmt="yuv422p10le",
        containers=["mov", "matroska"],
        quality={"prores_ks": {"profile": "standard"}},
        options={"prores_ks": {"profile": "standard"}},
    ),
}

QUALITY_FLOOR_BPP = 0.02
CONTAINER_OVERHEAD = 0.95
QUALITY_CEILING_FACTOR = 2
VBV_MAXRATE_FACTOR = 1.5
VBV_BUFFER_FACTOR = 3
QUALITY_CAPPABLE = {"vbv", "cq", "budget"}


###########################################################################################################
###########################################################################################################
class CodecRate(Node):
    def __init__(self, traits: CodecTraits) -> None:
        self.traits = traits

    async def __call__(self, ctx):
        metadata, limits, plan = ctx.metadata.before[0], param(ctx, "config").video_constraints, ctx.plan
        fps = plan.fps or metadata.fps or 30.0
        actual = metadata.frame_count / metadata.duration if metadata.frame_count and metadata.duration else None
        pixel_rate = plan.width * plan.height * min(fps, actual or fps)
        quality_bps = self.traits.bpp * pixel_rate
        audio_bps = _audio_bps(metadata, plan)
        duration = trimmed_duration(plan, metadata) or (metadata.frame_count / metadata.fps if metadata.frame_count and metadata.fps else None)
        if limits.max_bytes and duration is None:
            raise UnsatisfiableError("max_bytes needs a source with a known duration; this source reports none")
        budget = (CONTAINER_OVERHEAD * limits.max_bytes * 8 - audio_bps * duration) / duration if limits.max_bytes and duration else None

        caps = [limit for limit in (limits.max_bitrate, budget) if limit]
        cap = int(min(caps) / self.traits.overshoot) if caps else None
        if cap and not self.traits.abr:
            raise UnsatisfiableError(f"{plan.codec} has no usable rate control; max_bytes and max_bitrate cannot be honored")
        if cap and cap < self.traits.floor_bpp * pixel_rate:
            raise UnsatisfiableError(f"{plan.codec} cannot land under {int(self.traits.floor_bpp * pixel_rate)} bps at {plan.width}x{plan.height}@{fps:g} but the caps demand {cap} bps")
        estimated = int((min(self.traits.landing * quality_bps, cap or math.inf) + audio_bps) * duration / 8) if duration else None

        cappable = not cap or any(style in QUALITY_CAPPABLE for style in self.traits.rc.values())
        if self.traits.quality and not limits.min_bytes and cappable:
            for encoder, options in self.traits.quality.items():
                plan.options.setdefault(encoder, {}).update(options)
            ceiling = cap or int(QUALITY_CEILING_FACTOR * quality_bps)
            plan.rate = RatePlan(mode="crf", maxrate=ceiling, bufsize=2 * ceiling, capped=bool(cap), estimated_bytes=estimated)
            return ctx

        target = min(quality_bps, cap or math.inf)
        if limits.min_bytes and duration:
            target = max(target, limits.min_bytes * 8 / duration - audio_bps)
        floor = QUALITY_FLOOR_BPP * pixel_rate
        if target < floor:
            raise UnsatisfiableError(f"{plan.codec} at {plan.width}x{plan.height}@{fps:g} needs at least {int(floor)} bps but the caps leave only {max(int(target), 0)} bps after audio")
        plan.rate = RatePlan(
            mode="abr",
            bitrate=int(target),
            maxrate=int(VBV_MAXRATE_FACTOR * target),
            bufsize=int(VBV_BUFFER_FACTOR * target),
            capped=bool(cap),
            estimated_bytes=int((target + audio_bps) * duration / 8) if duration else None,
        )
        return ctx


###########################################################################################################
###########################################################################################################
def _audio_bps(metadata, plan) -> int:
    if metadata.audio is None:
        return 0
    if plan.audio and plan.audio.encoders:
        return plan.audio.bitrate or AUDIO_DEFAULT_BPS
    if metadata.audio.bitrate:
        return metadata.audio.bitrate
    ceiling = audio_codec_of(metadata.audio.codec).max_bitrate
    return ceiling or AUDIO_DEFAULT_BPS


###########################################################################################################
###########################################################################################################
def traits_of(codec: str) -> CodecTraits:
    child = registry.get("video.rate").children.get(codec)
    if isinstance(child, CodecRate) and child.traits is not GENERIC:
        return child.traits
    return CodecTraits(codec=codec, encoders=[codec])


###########################################################################################################
###########################################################################################################
class SizeRetry(Node):
    def __init__(self, node: Node, attempts: int = 3) -> None:
        self.node = node
        self.attempts = attempts

    async def __call__(self, ctx):
        config = param(ctx, "config")
        limit = config.video_constraints.max_bytes if config else None
        source = list(ctx.input)
        for attempt in range(self.attempts):
            ctx.input = list(source)
            ctx = await traced(self.node, ctx, label=f"attempt {attempt + 1}" if attempt else "")
            delivered = ctx.output[-1]
            if not limit or ctx.plan.rate is None or delivered.size <= limit:
                return ctx
            squeeze = limit / delivered.size * CONTAINER_OVERHEAD
            ctx.output.pop().cleanup()
            rate = ctx.plan.rate
            scaled = {name: int(getattr(rate, name) * squeeze) for name in ("bitrate", "maxrate", "bufsize") if getattr(rate, name)}
            ctx.plan = ctx.plan.model_copy(update={"rate": rate.model_copy(update={**scaled, "capped": True})})
        raise UnsatisfiableError(f"output stayed over max_bytes={limit} after {self.attempts} attempts")

    def describe(self):
        from ...core.core import NodeDescription
        return NodeDescription(kind="SizeRetry", children=[self.node.describe()])
