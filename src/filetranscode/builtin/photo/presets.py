from pydantic import BaseModel

from ...core.core import Node, Registry
from ..toolkit.introspect import param
from .models import PhotoConstraints, PhotoPreset

MB = 1_000_000


###########################################################################################################
###########################################################################################################
class Preset(Node):
    def __init__(self, spec: PhotoPreset) -> None:
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
        children = self.registry.get("photo.preset").children
        ctx.out = {name: child.spec for name, child in children.items() if isinstance(child, Preset)}
        return ctx


###########################################################################################################
###########################################################################################################
PRESETS: dict[str, PhotoPreset] = {
    "facebook_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "gif", "bmp", "tiff"],
            max_width=2048,
            max_height=2048,
            max_bytes=10 * MB,
        ),
    ),
    "facebook_story": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "gif", "bmp", "tiff"],
            max_bytes=4 * MB,
        ),
    ),
    "facebook_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png"],
            aspects=["9:16"],
            max_bytes=10 * MB,
        ),
    ),
    "instagram_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "gif"],
            min_width=320,
            max_width=1440,
            min_aspect=0.8,
            max_aspect=1.91,
            aspects=["9:16"],
            max_bytes=8 * MB,
        ),
    ),
    "instagram_story": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=320,
            max_width=1440,
            max_bytes=8 * MB,
        ),
    ),
    "instagram_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            max_bytes=8 * MB,
        ),
    ),
    "linkedin_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "gif"],
            max_pixels=36_152_320,
            max_bytes=5 * MB,
        ),
    ),
    "linkedin_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=600,
            max_width=1920,
            max_height=1080,
            max_bytes=5 * MB,
        ),
    ),
    "pinterest_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "webp", "gif", "bmp", "tiff"],
            min_width=600,
            min_height=900,
            max_width=2000,
            max_height=3000,
            aspects=["2:3"],
            max_bytes=20 * MB,
        ),
    ),
    "pinterest_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=600,
            max_width=1000,
            max_height=1500,
            max_bytes=10 * MB,
        ),
    ),
    "snapchat_story": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png"],
            max_bytes=20 * MB,
        ),
    ),
    "snapchat_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=720,
            max_width=1080,
            max_height=1920,
            max_bytes=5 * MB,
        ),
    ),
    "threads_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png"],
            min_width=320,
            max_width=1440,
            min_aspect=0.1,
            max_aspect=10.0,
            max_bytes=8 * MB,
            srgb=True,
        ),
    ),
    "threads_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=640,
            max_width=1080,
            max_height=1350,
            max_bytes=8 * MB,
        ),
    ),
    "tiktok_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            max_width=1920,
            max_height=1920,
            max_bytes=20 * MB,
        ),
    ),
    "tiktok_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=720,
            max_width=1080,
            max_height=1920,
            max_bytes=5 * MB,
        ),
    ),
    "twitter_photo": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png", "webp", "gif"],
            min_width=4,
            min_height=4,
            max_width=8192,
            max_height=8192,
            max_bytes=5 * MB,
        ),
    ),
    "twitter_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg"],
            min_width=600,
            max_width=1280,
            max_height=720,
            max_bytes=5 * MB,
        ),
    ),
    "youtube_thumbnail": PhotoPreset(
        photo_constraints=PhotoConstraints(
            formats=["jpeg", "png"],
            min_width=640,
            max_bytes=2 * MB,
        ),
    ),
}
