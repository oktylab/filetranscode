from ...core.core import Node, Registry
from ..toolkit.introspect import param
from pydantic import BaseModel

from .models import AudioConstraints, VideoConstraints, VideoPreset

MB = 1_000_000


###########################################################################################################
###########################################################################################################
class Preset(Node):
    def __init__(self, spec: VideoPreset) -> None:
        self.spec = spec

    async def __call__(self, ctx):
        config = param(ctx, "config")
        name = type(ctx.params).roles["config"]
        ctx.params = ctx.params.model_copy(update={name: _merged(config, self.spec)})
        return ctx


###########################################################################################################
###########################################################################################################
def _merged(config, spec):
    updates = {}
    for name, value in spec:
        if value is None:
            continue
        if isinstance(value, BaseModel):
            current = getattr(config, name)
            overrides = {sub: getattr(value, sub) for sub in value.model_fields_set if sub not in current.model_fields_set}
            if overrides:
                updates[name] = current.model_copy(update=overrides)
        elif name not in config.model_fields_set:
            updates[name] = value
    return config.model_copy(update=updates)


###########################################################################################################
###########################################################################################################
class PresetIndex(Node):
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    async def __call__(self, ctx):
        children = self.registry.get("video.preset").children
        ctx.out = {name: child.spec for name, child in children.items() if isinstance(child, Preset)}
        return ctx


###########################################################################################################
###########################################################################################################
_TWITTER_VIDEO = dict(
    min_aspect=0.3333,
    max_aspect=3.0,
    codecs=["h264"],
    pix_fmts=["yuv420p", "yuvj420p"],
    formats=["mp4"],
    max_bitrate=150_000_000,
    max_fps=60,
    min_duration=0.5,
    max_width=1280,
    max_height=1024,
)

_YOUTUBE_VIDEO = dict(
    codecs=["h264", "hevc"],
    formats=["mp4"],
    max_bitrate=150_000_000,
    max_fps=60,
    max_bytes=256_000 * MB,
)

PRESETS: dict[str, VideoPreset] = {
    "facebook_video": VideoPreset(
        video_constraints=VideoConstraints(
            codecs=["h264", "hevc"],
            formats=["mp4"],
            max_bitrate=150_000_000,
            max_fps=60,
            max_bytes=10_000 * MB,
            max_duration=14_400,
        ),
    ),
    "facebook_reel": VideoPreset(
        video_constraints=VideoConstraints(
            aspects=["9:16"],
            codecs=["h264", "hevc", "vp9", "av1"],
            pix_fmts=["yuv420p", "yuvj420p"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=24,
            max_fps=60,
            max_bytes=2000 * MB,
            min_duration=3,
            max_duration=90,
            min_width=540,
            min_height=960,
        ),
        audio_constraints=AudioConstraints(
            codecs=["aac"],
            max_bitrate=128_000,
            max_channels=2,
            samplerates=[48000],
        ),
    ),
    "facebook_story": VideoPreset(
        video_constraints=VideoConstraints(
            aspects=["9:16"],
            codecs=["h264", "hevc", "vp9", "av1"],
            pix_fmts=["yuv420p", "yuvj420p"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=24,
            max_fps=60,
            max_bytes=4000 * MB,
            min_duration=3,
            max_duration=60,
            min_width=540,
            min_height=960,
        ),
        audio_constraints=AudioConstraints(
            codecs=["aac"],
            max_bitrate=128_000,
            max_channels=2,
            samplerates=[48000],
        ),
    ),
    "instagram_reel": VideoPreset(
        video_constraints=VideoConstraints(
            min_aspect=0.01,
            max_aspect=10.0,
            codecs=["h264", "hevc"],
            pix_fmts=["yuv420p", "yuvj420p"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=23,
            max_fps=60,
            max_bytes=300 * MB,
            min_duration=3,
            max_duration=900,
            max_width=1920,
            max_height=3600,
        ),
        audio_constraints=AudioConstraints(
            codecs=["aac"],
            max_bitrate=128_000,
            max_channels=2,
            samplerates=[48000, 44100],
        ),
    ),
    "instagram_story": VideoPreset(
        video_constraints=VideoConstraints(
            min_aspect=0.1,
            max_aspect=10.0,
            codecs=["h264", "hevc"],
            pix_fmts=["yuv420p", "yuvj420p"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=23,
            max_fps=60,
            max_bytes=100 * MB,
            min_duration=3,
            max_duration=60,
            max_width=1920,
            max_height=3600,
        ),
        audio_constraints=AudioConstraints(
            codecs=["aac"],
            max_bitrate=128_000,
            max_channels=2,
            samplerates=[48000, 44100],
        ),
    ),
    "linkedin_video": VideoPreset(
        video_constraints=VideoConstraints(
            min_aspect=0.4167,
            max_aspect=2.4,
            codecs=["h264"],
            formats=["mp4"],
            max_bitrate=30_000_000,
            min_fps=10,
            max_fps=60,
            max_bytes=500 * MB,
            min_duration=3,
            max_duration=1800,
        ),
        audio_constraints=AudioConstraints(
            max_bitrate=192_000,
        ),
    ),
    "pinterest_video": VideoPreset(
        video_constraints=VideoConstraints(
            min_aspect=0.5,
            max_aspect=1.91,
            codecs=["h264", "hevc"],
            formats=["mp4"],
            max_bitrate=150_000_000,
            min_fps=24,
            max_fps=60,
            max_bytes=2000 * MB,
            min_duration=4,
            max_duration=900,
        ),
    ),
    "snapchat_video": VideoPreset(
        video_constraints=VideoConstraints(
            aspects=["9:16"],
            codecs=["h264"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=24,
            max_fps=60,
            max_bytes=1000 * MB,
            min_duration=5,
            max_duration=60,
        ),
    ),
    "threads_video": VideoPreset(
        video_constraints=VideoConstraints(
            min_aspect=0.01,
            max_aspect=10.0,
            codecs=["h264", "hevc"],
            pix_fmts=["yuv420p", "yuvj420p"],
            formats=["mp4"],
            max_bitrate=25_000_000,
            min_fps=23,
            max_fps=60,
            max_bytes=1000 * MB,
            max_duration=300,
            max_width=1920,
        ),
        audio_constraints=AudioConstraints(
            codecs=["aac"],
            max_bitrate=128_000,
            max_channels=2,
            samplerates=[48000],
        ),
    ),
    "tiktok_video": VideoPreset(
        video_constraints=VideoConstraints(
            codecs=["h264", "hevc"],
            formats=["mp4"],
            max_bitrate=150_000_000,
            min_fps=23,
            max_fps=60,
            max_bytes=10_000 * MB,
            min_duration=3,
            max_duration=600,
            min_width=360,
            max_width=4096,
            min_height=360,
            max_height=4096,
        ),
    ),
    # X: default accounts post up to 20 min / 8 GB, Premium or verified accounts up to 125 min / 16 GB
    # (docs.x.com media introduction, "size and duration limits"); everything else is shared.
    "twitter_video": VideoPreset(
        video_constraints=VideoConstraints(**_TWITTER_VIDEO, max_bytes=8000 * MB, max_duration=1200),
        audio_constraints=AudioConstraints(max_channels=2),
    ),
    "twitter_video_premium": VideoPreset(
        video_constraints=VideoConstraints(**_TWITTER_VIDEO, max_bytes=16_000 * MB, max_duration=7500),
        audio_constraints=AudioConstraints(max_channels=2),
    ),
    # YouTube: 256 GB or 12 hours; a channel without verified long uploads is capped at 15 minutes
    # (support.google.com/youtube/answer/71673, channel status.longUploadsStatus).
    "youtube_video": VideoPreset(
        video_constraints=VideoConstraints(**_YOUTUBE_VIDEO, max_duration=43_200),
    ),
    "youtube_video_unverified": VideoPreset(
        video_constraints=VideoConstraints(**_YOUTUBE_VIDEO, max_duration=900),
    ),
    "youtube_short": VideoPreset(
        video_constraints=VideoConstraints(
            max_aspect=1.0,
            codecs=["h264", "hevc"],
            formats=["mp4"],
            max_bitrate=150_000_000,
            max_fps=60,
            max_bytes=4000 * MB,
            max_duration=180,
        ),
    ),
}


