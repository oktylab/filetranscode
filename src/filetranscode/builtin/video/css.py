import math

import numpy as np

from .models import ColorPlan, VideoMetadata

LUMA = (0.213, 0.715, 0.072)
GRAY_LUMA = (0.2126, 0.7152, 0.0722)
SEPIA_FULL = ((0.393, 0.769, 0.189), (0.349, 0.686, 0.168), (0.272, 0.534, 0.131))
MIXER_LIMIT = 2.0

Matrix = tuple[tuple[float, float, float], ...]


###########################################################################################################
###########################################################################################################
def saturate_matrix(amount: float) -> Matrix:
    r, g, b = LUMA
    return (
        (r + (1 - r) * amount, g - g * amount, b - b * amount),
        (r - r * amount, g + (1 - g) * amount, b - b * amount),
        (r - r * amount, g - g * amount, b + (1 - b) * amount),
    )


def hue_matrix(degrees: float) -> Matrix:
    cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return (
        (0.213 + cos * 0.787 - sin * 0.213, 0.715 - cos * 0.715 - sin * 0.715, 0.072 - cos * 0.072 + sin * 0.928),
        (0.213 - cos * 0.213 + sin * 0.143, 0.715 + cos * 0.285 + sin * 0.140, 0.072 - cos * 0.072 - sin * 0.283),
        (0.213 - cos * 0.213 - sin * 0.787, 0.715 - cos * 0.715 + sin * 0.715, 0.072 + cos * 0.928 + sin * 0.072),
    )


def grayscale_matrix(amount: float) -> Matrix:
    keep = 1 - min(amount, 1.0)
    r, g, b = GRAY_LUMA
    return (
        (r + (1 - r) * keep, g - g * keep, b - b * keep),
        (r - r * keep, g + (1 - g) * keep, b - b * keep),
        (r - r * keep, g - g * keep, b + (1 - b) * keep),
    )


def sepia_matrix(amount: float) -> Matrix:
    keep = 1 - min(amount, 1.0)
    identity = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return tuple(
        tuple(full + (one - full) * keep for full, one in zip(full_row, identity_row))
        for full_row, identity_row in zip(SEPIA_FULL, identity)
    )


###########################################################################################################
###########################################################################################################
def stages(color: ColorPlan) -> list[tuple[str, object]]:
    ops: list[tuple[str, object]] = []
    if color.brightness != 1.0:
        ops.append(("lut", (color.brightness, 0.0)))
    if color.contrast != 1.0:
        ops.append(("lut", (color.contrast, 0.5 - 0.5 * color.contrast)))
    if color.saturation != 1.0:
        amount = color.saturation
        while amount > MIXER_LIMIT:
            ops.append(("mix", saturate_matrix(MIXER_LIMIT)))
            amount /= MIXER_LIMIT
        ops.append(("mix", saturate_matrix(amount)))
    if color.hue:
        ops.append(("mix", hue_matrix(color.hue)))
    if color.grayscale:
        ops.append(("mix", grayscale_matrix(color.grayscale)))
    if color.sepia:
        ops.append(("mix", sepia_matrix(color.sepia)))
    if color.invert:
        amount = min(color.invert, 1.0)
        ops.append(("lut", (1 - 2 * amount, amount)))
    return ops


###########################################################################################################
###########################################################################################################
TAGGED_MATRICES = {"bt470bg": "bt601", "smpte170m": "bt601", "bt709": "bt709"}


def source_matrix(metadata: "VideoMetadata | None", height: int) -> str:
    tagged = TAGGED_MATRICES.get(metadata.color_space or "") if metadata else None
    return tagged or ("bt709" if (metadata.height if metadata and metadata.height else height) > 576 else "bt601")


def avfilter_stages(color: ColorPlan | None, height: int, pix_fmt: str, metadata: "VideoMetadata | None" = None) -> list[tuple[str, str]]:
    if color is None or color.identity():
        return []
    ops = stages(color)
    if not ops:
        return []
    in_matrix = source_matrix(metadata, height)
    in_range = "pc" if metadata and metadata.color_range == "pc" else "tv"
    matrix = "bt709" if height > 576 else "bt601"
    tag = "bt709" if height > 576 else "bt470bg"
    steps = [
        ("scale", f"in_color_matrix={in_matrix}:in_range={in_range}:flags=accurate_rnd+full_chroma_int"),
        ("format", "gbrp"),
        ("zscale", "dither=none"),
        ("format", "gbrp16"),
    ]
    for kind, value in ops:
        if kind == "lut":
            slope, intercept = value
            expression = f"clip(val*{slope:.10g}+{intercept * 65535:.10g},0,65535)"
            steps.append(("lutrgb", f"r={expression}:g={expression}:b={expression}"))
        else:
            ((rr, rg, rb), (gr, gg, gb), (br, bg, bb)) = value
            steps.append(("colorchannelmixer", f"rr={rr:.10f}:rg={rg:.10f}:rb={rb:.10f}:gr={gr:.10f}:gg={gg:.10f}:gb={gb:.10f}:br={br:.10f}:bg={bg:.10f}:bb={bb:.10f}"))
    steps += [
        ("zscale", "dither=none"),
        ("format", "gbrp"),
        ("scale", f"out_color_matrix={matrix}:out_range=tv:flags=accurate_rnd+full_chroma_int"),
        ("format", pix_fmt),
        ("setparams", f"range=tv:colorspace={tag}"),
    ]
    return steps


###########################################################################################################
###########################################################################################################
def transform(color: ColorPlan):
    ops = stages(color)
    matrices = {index: np.array(value).T for index, (kind, value) in enumerate(ops) if kind == "mix"}

    def apply(frame: np.ndarray) -> np.ndarray:
        pixels = frame.astype(np.float64) / 255.0
        for index, (kind, value) in enumerate(ops):
            if kind == "lut":
                slope, intercept = value
                pixels = np.clip(pixels * slope + intercept, 0.0, 1.0)
            else:
                pixels = np.clip(pixels @ matrices[index], 0.0, 1.0)
        return (pixels * 255.0).round().astype(np.uint8)

    return apply
