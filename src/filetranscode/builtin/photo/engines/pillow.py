import io
import struct

import numpy as np
import pillow_heif
from PIL import Image, ImageCms, ImageFile, ImageOps, ImageSequence

from ....exceptions import EngineError, ProbeError
from ...toolkit.engine import Engine, operation, probing
from ...toolkit.output_resolve import OutputData
from ..css import transform
from ..formats import format_for_pillow, format_of
from ..models import PhotoMetadata

pillow_heif.register_heif_opener()

ORIENTATION_TAG = 0x0112
SWAPPED_ORIENTATIONS = {5, 6, 7, 8}
SIXTEEN_BIT_MODES = {"I", "I;16", "I;16B", "I;16L", "I;16N"}


###########################################################################################################
###########################################################################################################
def webp_frame_durations(stream) -> list[int] | None:
    header = stream.read(12)
    if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
        return None
    durations: list[int] = []
    while True:
        chunk = stream.read(8)
        if len(chunk) < 8:
            break
        fourcc, size = chunk[:4], struct.unpack("<I", chunk[4:8])[0]
        if fourcc == b"ANMF":
            head = stream.read(16)
            if len(head) < 16:
                break
            durations.append(int.from_bytes(head[12:15], "little"))
            stream.seek(size - 16 + (size & 1), 1)
        else:
            stream.seek(size + (size & 1), 1)
    return durations


###########################################################################################################
###########################################################################################################
def animation_timing(img: Image.Image, data) -> tuple[int, float]:
    if img.format == "WEBP":
        stream = open(data.raw_path, "rb") if data.raw_path is not None else data.stream
        try:
            durations = webp_frame_durations(stream)
        finally:
            if data.raw_path is not None:
                stream.close()
        if not durations:
            raise ProbeError(str(data.raw_path or "<stream>"), "animated webp with unreadable ANMF frame headers")
        return len(durations), sum(durations) / 1000
    frames, total = 0, 0
    try:
        for index in range(img.n_frames):
            img.seek(index)
            total += int(img.info.get("duration", 0) or 0)
            frames += 1
    except (EOFError, OSError, SyntaxError) as error:
        raise ProbeError(str(data.raw_path or "<stream>"), f"truncated or corrupt animation: {error}")
    img.seek(0)
    return frames, total / 1000


###########################################################################################################
###########################################################################################################
def profile_description(icc_bytes: bytes) -> str:
    try:
        return ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes)).profile.profile_description or "unknown"
    except (OSError, ImageCms.PyCMSError):
        return "unknown"


###########################################################################################################
###########################################################################################################
class PillowEngine(Engine):
    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            source = data.raw_path if data.raw_path is not None else data.stream
            try:
                with Image.open(source) as img:
                    orientation = int(img.getexif().get(ORIENTATION_TAG, 1) or 1)
                    width, height = img.size
                    if orientation in SWAPPED_ORIENTATIONS:
                        width, height = height, width
                    icc = img.info.get("icc_profile")
                    animated = bool(getattr(img, "is_animated", False))
                    frames, duration = animation_timing(img, data) if animated else (1, None)
                    sink.append(PhotoMetadata(
                        format=format_for_pillow(img.format),
                        width=width,
                        height=height,
                        mode=img.mode,
                        orientation=orientation if 1 <= orientation <= 8 else 1,
                        animated=animated,
                        frames=frames,
                        duration=duration,
                        alpha=img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info,
                        icc=profile_description(icc) if icc else None,
                        size=data.size,
                    ))
            except (OSError, ValueError, SyntaxError, EOFError) as error:
                raise ProbeError(str(data.raw_path or "<stream>"), str(error))
        return ctx

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        if metadata.animated and not plan.still:
            return self._encode_animated(ctx)
        traits = format_of(plan.format)
        try:
            with Image.open(ctx.input[0].path) as opened:
                img = ImageOps.exif_transpose(opened)
                img.load()
        except OSError as error:
            raise EngineError(f"pillow: cannot decode {metadata.format}: {error}")
        exif = img.getexif()
        icc_bytes = img.info.get("icc_profile")
        img, icc_bytes = _normalized(img, icc_bytes, metadata.alpha, plan.srgb)
        if plan.crop:
            img = img.crop((plan.crop.x, plan.crop.y, plan.crop.x + plan.crop.width, plan.crop.y + plan.crop.height))
        if (plan.width, plan.height) != img.size:
            img = img.resize((plan.width, plan.height), Image.LANCZOS)
        if plan.color and not plan.color.identity():
            img = _filtered(img, plan.color)
        if plan.background:
            flat = Image.new("RGB", img.size, plan.background)
            flat.paste(img, mask=img.getchannel("A") if img.mode == "RGBA" else None)
            img = flat
        options = dict(plan.options)
        if traits.lossy and plan.quality and plan.quality.quality:
            options["quality"] = plan.quality.quality
        if icc_bytes and traits.icc:
            options["icc_profile"] = icc_bytes
        if exif and traits.exif:
            options["exif"] = exif
        delivered = OutputData()
        ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, 4 * plan.width * plan.height)
        try:
            img.save(delivered.path, format=traits.pillow, **options)
        except (OSError, ValueError, KeyError) as error:
            delivered.cleanup()
            raise EngineError(f"pillow: cannot encode {plan.format}: {error}")
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    def _encode_animated(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        traits = format_of(plan.format)
        try:
            img = Image.open(ctx.input[0].path)
        except OSError as error:
            raise EngineError(f"pillow: cannot decode {metadata.format}: {error}")
        icc_bytes = img.info.get("icc_profile")
        loop = int(img.info.get("loop", 0) or 0)
        convert = None
        if plan.srgb and icc_bytes:
            convert = ImageCms.buildTransform(ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes)), ImageCms.createProfile("sRGB"), "RGBA", "RGBA")
            icc_bytes = None
        apply_color = plan.color is not None and not plan.color.identity()
        frames, durations = [], []
        try:
            for frame in ImageSequence.Iterator(img):
                rgba = frame.convert("RGBA")
                duration = frame.info.get("duration")
                if duration is None:
                    if metadata.format != "gif":
                        raise EngineError(f"pillow: {metadata.format} frame {len(frames)} reports no duration; cannot preserve timing")
                    duration = 0
                durations.append(int(duration))
                if convert is not None:
                    rgba = ImageCms.applyTransform(rgba, convert)
                if plan.crop:
                    rgba = rgba.crop((plan.crop.x, plan.crop.y, plan.crop.x + plan.crop.width, plan.crop.y + plan.crop.height))
                if (plan.width, plan.height) != rgba.size:
                    rgba = rgba.resize((plan.width, plan.height), Image.LANCZOS)
                if apply_color:
                    rgba = _filtered(rgba, plan.color)
                if plan.background:
                    flat = Image.new("RGB", rgba.size, plan.background)
                    flat.paste(rgba, mask=rgba.getchannel("A"))
                    rgba = flat
                frames.append(rgba)
        except (OSError, EOFError, SyntaxError) as error:
            img.close()
            raise EngineError(f"pillow: cannot decode animated {metadata.format} at frame {len(frames)}: {error}")
        img.close()
        options = dict(plan.options)
        if traits.lossy and plan.quality and plan.quality.quality:
            options["quality"] = plan.quality.quality
        if icc_bytes and traits.icc:
            options["icc_profile"] = icc_bytes
        if plan.format == "gif":
            options["disposal"] = 2
            quantized, carry = [], 0.0
            for duration in durations:
                exact = duration + carry
                snapped = max(0, round(exact / 10) * 10)
                carry = exact - snapped
                quantized.append(snapped)
            durations = quantized
        delivered = OutputData()
        try:
            frames[0].save(delivered.path, format=traits.pillow, save_all=True, append_images=frames[1:], duration=durations, loop=loop, **options)
        except (OSError, ValueError, KeyError) as error:
            delivered.cleanup()
            raise EngineError(f"pillow: cannot encode animated {plan.format}: {error}")
        ctx.output.append(delivered)
        return ctx


###########################################################################################################
###########################################################################################################
def _normalized(img: Image.Image, icc_bytes: bytes | None, alpha: bool, to_srgb: bool) -> tuple[Image.Image, bytes | None]:
    if img.mode in SIXTEEN_BIT_MODES:
        pixels = np.asarray(img, dtype=np.float64)
        img = Image.fromarray((pixels / pixels.max() * 255.0).round().astype(np.uint8), mode="L")
    if img.mode == "CMYK":
        if icc_bytes:
            img = ImageCms.profileToProfile(img, ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes)), ImageCms.createProfile("sRGB"), outputMode="RGB")
        else:
            img = img.convert("RGB")
        return img, None
    target = "RGBA" if alpha else "RGB"
    if img.mode != target:
        img = img.convert(target)
    if to_srgb and icc_bytes:
        img = ImageCms.profileToProfile(img, ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes)), ImageCms.createProfile("sRGB"), outputMode=target)
        return img, None
    return img, icc_bytes


###########################################################################################################
###########################################################################################################
def _filtered(img: Image.Image, color) -> Image.Image:
    apply = transform(color)
    if img.mode == "RGBA":
        pixels = np.asarray(img)
        merged = np.dstack([apply(pixels[..., :3]), pixels[..., 3]])
        return Image.fromarray(merged, mode="RGBA")
    return Image.fromarray(apply(np.asarray(img)), mode="RGB")
