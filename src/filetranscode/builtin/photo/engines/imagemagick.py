import asyncio
import io
import subprocess

from PIL import ImageCms

from ....exceptions import EngineError, ProbeError
from ...toolkit.engine import Engine, operation, probing
from ...toolkit.output_resolve import OutputData
from ..css import stages
from ..formats import format_of
from ..models import PhotoMetadata

BINARY = "magick"

IM_FORMATS = {
    "JPEG": "jpeg", "JPG": "jpeg", "PNG": "png", "WEBP": "webp", "GIF": "gif",
    "TIFF": "tiff", "BMP": "bmp", "BMP3": "bmp", "AVIF": "avif", "HEIC": "heif", "HEIF": "heif",
}
IM_NAMES = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "tiff": "TIFF", "bmp": "BMP", "avif": "AVIF", "heif": "HEIC"}
IM_ORIENTATIONS = {
    "TopLeft": 1, "TopRight": 2, "BottomRight": 3, "BottomLeft": 4,
    "LeftTop": 5, "RightTop": 6, "RightBottom": 7, "LeftBottom": 8,
}
SWAPPED_ORIENTATIONS = {5, 6, 7, 8}


###########################################################################################################
###########################################################################################################
async def _run(args: list[str]) -> str:
    result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True)
    if result.returncode:
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        raise EngineError(f"{BINARY}: " + (" | ".join(lines[-3:]) if lines else f"exit {result.returncode}"))
    return result.stdout


###########################################################################################################
###########################################################################################################
def _writable_formats() -> set[str]:
    listing = subprocess.run([BINARY, "-list", "format"], capture_output=True, text=True).stdout
    names = set()
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "w" in parts[2]:
            names.add(parts[0].rstrip("*").upper())
    return names


###########################################################################################################
###########################################################################################################
class ImageMagickEngine(Engine):
    def __init__(self) -> None:
        self._writable: set[str] | None = None

    def _check_writable(self, format: str) -> None:
        if self._writable is None:
            self._writable = _writable_formats()
        if IM_NAMES.get(format, format.upper()) not in self._writable:
            raise EngineError(f"imagemagick: this build cannot write {format!r}; use the pillow engine")

    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            out = await asyncio.to_thread(
                subprocess.run,
                [BINARY, "identify", "-ping", "-format", r"%m,%w,%h,%A,%[orientation],%T,%[profile:icc]\n", data.path],
                capture_output=True, text=True,
            )
            lines = [line for line in out.stdout.splitlines() if line.strip()]
            if out.returncode or not lines:
                raise ProbeError(data.path, out.stderr.strip() or "identify produced no output")
            im_format, width_text, height_text, alpha_text, orientation_text, delay_text, icc_text = lines[0].split(",", 6)
            orientation = IM_ORIENTATIONS.get(orientation_text, 1)
            width, height = int(width_text), int(height_text)
            if orientation in SWAPPED_ORIENTATIONS:
                width, height = height, width
            animated = len(lines) > 1
            try:
                ticks = sum(int(line.split(",", 6)[5]) for line in lines)
            except (ValueError, IndexError) as error:
                raise ProbeError(data.path, f"unreadable frame delays: {error}")
            sink.append(PhotoMetadata(
                format=IM_FORMATS.get(im_format.upper(), im_format.lower()),
                width=width,
                height=height,
                orientation=orientation,
                animated=animated,
                frames=len(lines),
                duration=ticks / 100 if animated else None,
                alpha=alpha_text in ("True", "Blend"),
                icc=icc_text.strip() or None,
                size=data.size,
            ))
        return ctx

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        self._check_writable(plan.format)
        traits = format_of(plan.format)
        animated = metadata.animated and not plan.still
        delivered = OutputData()
        if animated:
            args = [BINARY, ctx.input[0].path, "-coalesce"]
        else:
            args = [BINARY, f"{ctx.input[0].path}[0]", "-auto-orient"]
        if plan.srgb:
            srgb_path = delivered.temp(suffix=".icc")
            with open(srgb_path, "wb") as handle:
                handle.write(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
            args += ["-profile", srgb_path]
        if plan.crop:
            args += ["-crop", f"{plan.crop.width}x{plan.crop.height}+{plan.crop.x}+{plan.crop.y}", "+repage"]
        args += ["-resize", f"{plan.width}x{plan.height}!"]
        if plan.color and not plan.color.identity():
            args += ["-channel", "RGB"]
            for kind, value in stages(plan.color):
                if kind == "lut":
                    slope, intercept = value
                    args += ["-function", "Polynomial", f"{slope:.10g},{intercept:.10g}"]
                else:
                    args += ["-color-matrix", " ".join(f"{cell:.10f}" for row in value for cell in row)]
                args += ["-clamp"]
            args += ["+channel"]
        if plan.background:
            args += ["-background", plan.background, "-alpha", "remove", "-alpha", "off"]
        elif not traits.alpha:
            args += ["-alpha", "off"]
        if traits.lossy and plan.quality and plan.quality.quality:
            args += ["-quality", str(plan.quality.quality)]
        if not traits.icc:
            args += ["+profile", "icc"]
        if not traits.exif:
            args += ["+profile", "exif"]
        args.append(f"{IM_NAMES.get(plan.format, plan.format.upper())}:{delivered.path}")
        try:
            await _run(args)
        except EngineError:
            delivered.cleanup()
            raise
        ctx.output.append(delivered)
        return ctx
