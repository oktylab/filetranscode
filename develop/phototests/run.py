"""Photo pipeline test battery. Fast, real files, pixel-level assertions.

Run: .venv/bin/python develop/phototests/run.py <workdir>
"""
import asyncio
import hashlib
import io
import os
import sys
import tempfile
import time

import numpy as np
import pillow_heif
from PIL import Image
from skimage.metrics import structural_similarity

sys.path.insert(0, os.path.dirname(__file__))
import corpus as corpus_module

pillow_heif.register_heif_opener()

from filetranscode import PhotoPipeline
from filetranscode.builtin.photo.config import PhotoConfig
from filetranscode.builtin.photo.css import transform
from filetranscode.builtin.photo.models import ColorPlan
from filetranscode.exceptions import UnsatisfiableError

PASSED = []
FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(f"{name}{': ' + detail if detail and not condition else ''}")
    print(("  ok " if condition else "  FAIL ") + name + (f": {detail}" if detail else ""))


def run(awaitable):
    return asyncio.get_event_loop().run_until_complete(awaitable)


async def expect_error(awaitable, fragment: str) -> tuple[bool, str]:
    try:
        await awaitable
        return False, "no error raised"
    except UnsatisfiableError as error:
        return fragment in str(error), str(error)


def main() -> int:
    workdir = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
    corpus_dir = os.path.join(workdir, "corpus")
    os.makedirs(corpus_dir, exist_ok=True)
    files = corpus_module.build(corpus_dir)
    pipe = PhotoPipeline()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    started = time.perf_counter()

    def export(source, out, **config):
        return loop.run_until_complete(pipe.export(input=source, output=out, config=PhotoConfig(**config)))

    def plan(source, **config):
        return loop.run_until_complete(pipe.plan(input=source, config=PhotoConfig(**config)))

    def probe(source, engine="pillow"):
        return loop.run_until_complete(pipe.probe(input=source, engine=engine))

    source_pixels = np.asarray(Image.open(files["photo"]))

    print("== A. probe (both engines) ==")
    for engine in ("pillow", "imagemagick"):
        meta = probe(files["photo"], engine)[0]
        check(f"{engine} dims", (meta.width, meta.height) == (1200, 900), f"{meta.width}x{meta.height}")
        check(f"{engine} format", meta.format == "png", meta.format)
        oriented = probe(files["oriented"], engine)[0]
        check(f"{engine} orientation swap", (oriented.width, oriented.height, oriented.orientation) == (1200, 900, 6), f"{oriented.width}x{oriented.height} o={oriented.orientation}")
        alpha = probe(files["alpha"], engine)[0]
        check(f"{engine} alpha", alpha.alpha is True)
        animated = probe(files["animated"], engine)[0]
        check(f"{engine} animated", animated.animated is True)
        p3 = probe(files["p3"], engine)[0]
        check(f"{engine} icc", p3.icc == "Display P3", repr(p3.icc))
    heic = probe(files["heic"])[0]
    check("heic probe", heic.format == "heif" and heic.width == 1200, f"{heic.format} {heic.width}")

    print("== B. planner ==")
    p = plan(files["photo"], photo_constraints={"formats": ["jpeg"]})
    check("format reason", p.action == "encode" and p.reasons == ["format"], str(p.reasons))
    p = plan(files["photo"], photo_constraints={"formats": ["png", "jpeg"]})
    check("format kept", p.action == "copy" and p.format == "png")
    p = plan(files["tall"], preset="instagram_photo")
    check("aspect discrete OR range (9:16 tall)", p.action == "copy", f"{p.action} {p.reasons}")
    ok, msg = loop.run_until_complete(expect_error(pipe.plan(input=files["photo"], config=PhotoConfig(photo_constraints={"formats": ["png"], "min_aspect": 0.5, "max_aspect": 0.6})), "not allowed"))
    check("aspect violation loud", ok, msg)
    p = plan(files["photo"], edits={"aspect": "1:1"}, photo_constraints={"formats": ["png"]})
    check("crop centered", p.crop is not None and (p.crop.x, p.crop.y, p.crop.width, p.crop.height) == (150, 0, 900, 900), str(p.crop))
    p = plan(files["photo"], photo_constraints={"formats": ["png"], "max_width": 600})
    check("downscale", (p.width, p.height) == (600, 450), f"{p.width}x{p.height}")
    p = plan(files["photo"], photo_constraints={"formats": ["png"], "max_pixels": 270_000})
    check("max_pixels", p.width * p.height <= 270_000 and abs(p.width / p.height - 4 / 3) < 0.01, f"{p.width}x{p.height}")
    ok, msg = loop.run_until_complete(expect_error(pipe.plan(input=files["photo"], config=PhotoConfig(photo_constraints={"formats": ["png"], "min_width": 2000, "max_height": 400})), "cannot satisfy both"))
    check("min/max conflict loud", ok, msg)
    p = plan(files["alpha"], photo_constraints={"formats": ["jpeg"]})
    check("alpha to jpeg-only defaults to white flatten", p.background == "#ffffff" and "alpha" in p.reasons, f"{p.background} {p.reasons}")
    p = plan(files["alpha"], photo_constraints={"formats": ["jpeg", "webp"]})
    check("alpha prefers alpha-capable format", p.format == "webp" and "format" in p.reasons, f"{p.format} {p.reasons}")
    p = plan(files["alpha"], photo_constraints={"formats": ["jpeg", "png"]})
    check("alpha source format kept when allowed", p.format == "png" and p.action == "copy", f"{p.format} {p.action}")
    p = plan(files["p3"], preset="threads_photo")
    check("srgb reason", "srgb" in p.reasons and p.srgb, str(p.reasons))
    ok, msg = loop.run_until_complete(expect_error(pipe.plan(input=files["animated"], config=PhotoConfig(photo_constraints={"formats": ["jpeg"]})), "animated"))
    check("animated encode loud", ok, msg)
    p = plan(files["animated"], photo_constraints={"formats": ["gif"]})
    check("animated copy ok", p.action == "copy")

    print("== C. copy path untouched ==")
    out = os.path.join(workdir, "copy_out.png")
    export(files["photo"], out, photo_constraints={"formats": ["png", "jpeg"]})
    same = hashlib.sha256(open(files["photo"], "rb").read()).digest() == hashlib.sha256(open(out, "rb").read()).digest()
    check("copy bytes identical", same)

    print("== D. crop pixel-exact (png->png lossless) ==")
    out = os.path.join(workdir, "crop_out.png")
    export(files["photo"], out, photo_constraints={"formats": ["png"]}, edits={"aspect": "1:1"})
    cropped = np.asarray(Image.open(out))
    expected = source_pixels[:, 150:1050]
    check("crop rect exact", cropped.shape == expected.shape and np.array_equal(cropped, expected), str(cropped.shape))

    print("== E. css filter parity ==")
    color = ColorPlan(brightness=1.2, contrast=1.1, saturation=1.4, hue=30, sepia=0.2)
    reference = transform(color)(source_pixels)
    out = os.path.join(workdir, "filters_pillow.png")
    export(files["photo"], out, photo_constraints={"formats": ["png"]},
           filters={"brightness": 1.2, "contrast": 1.1, "saturation": 1.4, "hue": 30, "sepia": 0.2})
    delivered = np.asarray(Image.open(out))
    check("pillow filters exact", np.array_equal(delivered, reference), f"maxdiff={np.abs(delivered.astype(int)-reference.astype(int)).max()}")
    known = transform(ColorPlan(brightness=2.0))(np.full((1, 1, 3), 100, np.uint8))
    check("brightness math", known[0, 0].tolist() == [200, 200, 200], str(known[0, 0]))
    gray = transform(ColorPlan(saturation=0.0))(np.array([[[255, 0, 0]]], np.uint8))
    check("saturate0 = luma", gray[0, 0].tolist() == [54, 54, 54], str(gray[0, 0]))
    out = os.path.join(workdir, "filters_magick.png")
    export(files["photo"], out, engine="imagemagick", photo_constraints={"formats": ["png"]},
           filters={"brightness": 1.2, "contrast": 1.1, "saturation": 1.4, "hue": 30, "sepia": 0.2})
    magick = np.asarray(Image.open(out))
    diff = np.abs(magick.astype(int) - reference.astype(int))
    check("imagemagick filters parity", diff.max() <= 2 and diff.mean() < 0.5, f"max={diff.max()} mean={diff.mean():.3f}")

    print("== F. exif orientation ==")
    out = os.path.join(workdir, "oriented_copy.jpg")
    export(files["oriented"], out, photo_constraints={"formats": ["jpeg"]})
    check("no-reason copy keeps orientation tag", Image.open(out).getexif().get(0x0112) == 6)
    out = os.path.join(workdir, "oriented_out.png")
    export(files["oriented"], out, photo_constraints={"formats": ["png"]})
    upright = np.asarray(Image.open(out).convert("RGB"))
    check("oriented dims", upright.shape[:2] == (900, 1200), str(upright.shape))
    if upright.shape == source_pixels.shape:
        ssim = structural_similarity(source_pixels, upright, channel_axis=2)
        check("oriented pixels upright", ssim > 0.9, f"ssim={ssim:.3f}")
    check("orientation tag cleared on encode", Image.open(out).getexif().get(0x0112, 1) == 1)

    print("== G. alpha preservation ==")
    out = os.path.join(workdir, "alpha_out.webp")
    export(files["alpha"], out, photo_constraints={"formats": ["jpeg", "webp"], "max_width": 600})
    with Image.open(out) as img:
        delivered = np.asarray(img.convert("RGBA"))
        check("alpha survives to webp", img.format == "WEBP" and delivered[:90, :90, 3].max() == 0 and delivered[300:, 300:, 3].min() == 255,
              f"{img.format} corner_a={delivered[:90,:90,3].max()}")
    out = os.path.join(workdir, "alpha_out.png")
    export(files["alpha"], out, photo_constraints={"formats": ["jpeg", "png"], "max_width": 600})
    with Image.open(out) as img:
        delivered = np.asarray(img)
        check("alpha survives to png", img.format == "PNG" and delivered[:90, :90, 3].max() == 0, str(img.format))
    out = os.path.join(workdir, "alpha_white.jpg")
    export(files["alpha"], out, photo_constraints={"formats": ["jpeg"]})
    white = np.asarray(Image.open(out).convert("RGB"))
    corner = white[:90, :90].mean(axis=(0, 1))
    check("alpha export to jpeg-only lands on white", Image.open(out).format == "JPEG" and corner.min() > 240, str(corner.round(1)))
    for engine in ("pillow", "imagemagick"):
        out = os.path.join(workdir, f"alpha_flat_{engine}.jpg")
        export(files["alpha"], out, engine=engine, photo_constraints={"formats": ["jpeg"]}, edits={"background": "#ff0000"})
        flat = np.asarray(Image.open(out).convert("RGB"))
        corner = flat[:90, :90].mean(axis=(0, 1))
        check(f"{engine} explicit flatten onto red", corner[0] > 230 and corner[1] < 25 and corner[2] < 25, str(corner.round(1)))
    p = plan(files["alpha"], photo_constraints={"formats": ["jpeg", "webp"]}, edits={"background": "#ff0000"})
    check("explicit background always flattens", p.format == "jpeg" and "alpha" in p.reasons and p.background == "#ff0000", f"{p.format} {p.reasons}")
    out = os.path.join(workdir, "alpha_ig_flat")
    export(files["alpha"], out, preset="instagram_photo", edits={"background": "#ff0000"})
    with Image.open(out) as img:
        flat = np.asarray(img.convert("RGB"))
        no_alpha = "A" not in (img.mode or "")
        check("instagram + background flattens red", no_alpha and flat[:90, :90, 0].mean() > 230 and flat[:90, :90, 1].mean() < 25,
              f"{img.format} {img.mode} {flat[:90,:90].mean(axis=(0,1)).round(1)}")

    print("== H. icc preserved through re-encode ==")
    out = os.path.join(workdir, "icc_keep.jpg")
    export(files["p3"], out, photo_constraints={"formats": ["jpeg"], "max_width": 800})
    kept = Image.open(out).info.get("icc_profile")
    check("icc kept when not converting", bool(kept) and b"Display P3" in kept, "profile missing" if not kept else "desc missing")

    print("== I. srgb conversion (threads preset path) ==")
    out = os.path.join(workdir, "srgb_out.jpg")
    export(files["p3"], out, photo_constraints={"formats": ["jpeg"], "srgb": True})
    converted_img = Image.open(out)
    converted = np.asarray(converted_img.convert("RGB"))
    naive = np.asarray(Image.open(files["p3"]).convert("RGB"))
    red_patch_conv = converted[330:420, 230:370].mean(axis=(0, 1))
    red_patch_naive = naive[330:420, 230:370].mean(axis=(0, 1))
    check("srgb conversion changed pixels", not np.array_equal(converted, naive))
    check("srgb red gains saturation", red_patch_conv[0] >= red_patch_naive[0] and red_patch_conv[1] <= red_patch_naive[1] + 1,
          f"conv={red_patch_conv.round(1)} naive={red_patch_naive.round(1)}")

    print("== J. size fitting (quality + resolution knobs) ==")
    out = os.path.join(workdir, "squeezed.jpg")
    export(files["photo"], out, photo_constraints={"formats": ["jpeg"], "max_bytes": 150_000})
    landed = os.path.getsize(out)
    with Image.open(out) as img:
        squeezed_size = img.size
    check("lossy fits via quality", landed <= 150_000 and squeezed_size == (1200, 900), f"{landed}b {squeezed_size}")
    check("lossy not starved", landed > 75_000, str(landed))
    out = os.path.join(workdir, "tiny.jpg")
    export(files["photo"], out, photo_constraints={"formats": ["jpeg"], "max_bytes": 20_000})
    with Image.open(out) as img:
        check("lossy below floor downscales instead of erroring", os.path.getsize(out) <= 20_000 and img.size[0] < 1200, f"{os.path.getsize(out)}b {img.size}")
    out = os.path.join(workdir, "fit.png")
    export(files["photo"], out, photo_constraints={"formats": ["png"], "max_bytes": 600_000})
    with Image.open(out) as img:
        check("lossless downscales to fit", os.path.getsize(out) <= 600_000 and img.format == "PNG" and 400 < img.size[0] < 1200,
              f"{os.path.getsize(out)}b {img.size}")
    ok, msg = loop.run_until_complete(expect_error(
        pipe.plan(input=files["photo"], config=PhotoConfig(photo_constraints={"formats": ["png"], "max_bytes": 60_000, "min_width": 1000})), "cannot satisfy"))
    check("size vs min conflict loud BEFORE export", ok, msg)
    big = np.tile(np.asarray(Image.open(files["alpha"])), (2, 2, 1))
    big_path = os.path.join(workdir, "big_alpha.png")
    Image.fromarray(big).save(big_path)
    out = os.path.join(workdir, "big_alpha_fit.png")
    from filetranscode.core.trace import tracing

    def attempts_in(step):
        own = 1 if step.label and step.label.startswith("attempt") else 0
        return own + sum(attempts_in(child) for child in step.children)

    with tracing() as trace:
        export(big_path, out, photo_constraints={"formats": ["jpeg", "png"], "max_bytes": 1_500_000})
    with Image.open(out) as img:
        check("transparent over cap downscales keeping alpha", img.format == "PNG" and img.mode == "RGBA" and os.path.getsize(out) <= 1_500_000 and img.size[0] >= 800,
              f"{img.format} {img.mode} {img.size} {os.path.getsize(out)}b")
    check("lossless fit needs zero retries (planner math alone)", attempts_in(trace.root) == 0, str(attempts_in(trace.root)))

    print("== K/L. cmyk + 16-bit ==")
    out = os.path.join(workdir, "cmyk_out.jpg")
    export(files["cmyk"], out, photo_constraints={"formats": ["jpeg"]})
    rgb = np.asarray(Image.open(out).convert("RGB"))
    check("cmyk converts", structural_similarity(source_pixels, rgb, channel_axis=2) > 0.8)
    out = os.path.join(workdir, "16bit_out.jpg")
    export(files["16bit"], out, photo_constraints={"formats": ["jpeg"]})
    gray8 = np.asarray(Image.open(out).convert("RGB"))
    check("16bit converts", abs(float(gray8[..., 0].mean()) - float(source_pixels[..., 0].mean())) < 6, f"{gray8[...,0].mean():.1f} vs {source_pixels[...,0].mean():.1f}")

    print("== M. heif in and out ==")
    out = os.path.join(workdir, "from_heic.jpg")
    export(files["heic"], out, photo_constraints={"formats": ["jpeg"]})
    check("heic -> jpeg", Image.open(out).format == "JPEG")
    out = os.path.join(workdir, "to_heif.heic")
    export(files["photo"], out, photo_constraints={"formats": ["heif"]})
    check("png -> heif", Image.open(out).format == "HEIF")

    print("== N. engine cross-parity ==")
    outs = {}
    for engine in ("pillow", "imagemagick"):
        out = os.path.join(workdir, f"parity_{engine}.jpg")
        export(files["photo"], out, engine=engine, photo_constraints={"formats": ["jpeg"], "max_width": 800}, edits={"aspect": "1:1"})
        outs[engine] = np.asarray(Image.open(out).convert("RGB"))
    check("parity dims", outs["pillow"].shape == outs["imagemagick"].shape, f"{outs['pillow'].shape} vs {outs['imagemagick'].shape}")
    ssim = structural_similarity(outs["pillow"], outs["imagemagick"], channel_axis=2)
    check("parity ssim", ssim > 0.95, f"ssim={ssim:.4f}")

    print("== O. every preset ==")
    presets = loop.run_until_complete(pipe.presets())
    check("preset count", len(presets) == 19, str(len(presets)))
    for name, spec in sorted(presets.items()):
        limits = spec.photo_constraints
        aspect = None
        if limits.aspects:
            aspect = limits.aspects[0]
        elif limits.min_aspect and limits.min_aspect > 4 / 3:
            aspect = f"{limits.min_aspect:g}:1"
        source = files["photo"] if not aspect else None
        config = {"preset": name}
        if aspect:
            config["edits"] = {"aspect": aspect}
            source = files["photo"]
        out = os.path.join(workdir, f"preset_{name}")
        try:
            export(source, out, **config)
        except UnsatisfiableError as error:
            check(f"preset {name}", False, str(error))
            continue
        with Image.open(out) as img:
            width, height = img.size
            format = img.format.lower().replace("jpg", "jpeg").replace("heic", "heif")
        format = {"jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp", "tiff": "tiff", "bmp": "bmp", "heif": "heif", "avif": "avif"}.get(format, format)
        size = os.path.getsize(out)
        good = (format in limits.formats
                and (not limits.max_bytes or size <= limits.max_bytes)
                and (not limits.max_width or width <= limits.max_width)
                and (not limits.max_height or height <= limits.max_height)
                and (not limits.min_width or width >= limits.min_width)
                and (not limits.min_height or height >= limits.min_height)
                and (not limits.max_pixels or width * height <= limits.max_pixels))
        check(f"preset {name}", good, f"{format} {width}x{height} {size}b")

    print("== P. animated ==")
    p = plan(files["animated_webp"], preset="instagram_photo")
    check("animated picks animated format", p.format == "gif" and p.action == "encode" and "format" in p.reasons, f"{p.format} {p.reasons}")
    ok, msg = loop.run_until_complete(expect_error(pipe.plan(input=files["animated"], config=PhotoConfig(preset="tiktok_photo")), "edits.still"))
    check("no animated format loud", ok, msg)
    p = plan(files["animated"], preset="tiktok_photo", edits={"still": True})
    check("still plan", p.still and "still" in p.reasons and p.format == "jpeg", f"{p.format} {p.reasons}")
    out = os.path.join(workdir, "still_out.jpg")
    export(files["animated"], out, preset="tiktok_photo", edits={"still": True})
    with Image.open(out) as img:
        check("still export single jpeg", img.format == "JPEG" and img.size == (300, 225), f"{img.format} {img.size}")
    for engine in ("pillow", "imagemagick"):
        out = os.path.join(workdir, f"anim_resize_{engine}.gif")
        export(files["animated"], out, engine=engine, photo_constraints={"formats": ["gif"], "max_width": 150})
        with Image.open(out) as img:
            frames = img.n_frames
            duration = img.info.get("duration")
            check(f"{engine} animated resize keeps frames", img.size == (150, 112) and frames == 3, f"{img.size} frames={frames}")
        check(f"{engine} animated duration kept", 150 <= (duration or 0) <= 250, str(duration))
    out = os.path.join(workdir, "anim_webp_to_gif.gif")
    export(files["animated_webp"], out, preset="instagram_photo", edits={"aspect": "1:1"})
    with Image.open(out) as img:
        check("webp->gif crop", img.format == "GIF" and img.n_frames == 3 and abs(img.size[0] / img.size[1] - 1) < 0.02, f"{img.format} {img.size} {img.n_frames}")
    out = os.path.join(workdir, "anim_gray.gif")
    export(files["animated"], out, photo_constraints={"formats": ["gif"]}, filters={"grayscale": 1.0})
    with Image.open(out) as img:
        img.seek(1)
        frame = np.asarray(img.convert("RGB"))
    check("animated filters applied per frame", np.abs(frame[..., 0].astype(int) - frame[..., 1].astype(int)).max() <= 1, "frame 1 not gray")
    out = os.path.join(workdir, "anim_copy.gif")
    export(files["animated"], out, photo_constraints={"formats": ["gif", "webp"]})
    same = hashlib.sha256(open(files["animated"], "rb").read()).digest() == hashlib.sha256(open(out, "rb").read()).digest()
    check("animated copy untouched", same)

    print("== Q. animation timing + broken files ==")
    for engine in ("pillow", "imagemagick"):
        meta = probe(files["animated"], engine)[0]
        check(f"{engine} gif timing", meta.frames == 3 and abs((meta.duration or 0) - 0.6) < 0.01, f"frames={meta.frames} dur={meta.duration}")
        meta = probe(files["animated_webp"], engine)[0]
        check(f"{engine} webp timing", meta.frames == 3 and abs((meta.duration or 0) - 0.6) < 0.01, f"frames={meta.frames} dur={meta.duration}")
    meta = probe(files["photo"])[0]
    check("still has frames=1 no duration", meta.frames == 1 and meta.duration is None)
    meta = probe(files["zerodelay_gif"])[0]
    check("zero-delay gif reports 0.0 truth", meta.frames == 3 and meta.duration == 0.0)
    out = os.path.join(workdir, "timing_out.gif")
    export(files["animated_webp"], out, photo_constraints={"formats": ["gif"], "max_width": 150})
    with Image.open(out) as img:
        exported = []
        for index in range(img.n_frames):
            img.seek(index)
            exported.append(img.info.get("duration"))
    check("exported gif carries real per-frame timing", exported == [200, 200, 200], str(exported))

    giphy = "/home/crosspost/Downloads/giphy.webp"
    if os.path.exists(giphy):
        meta = probe(giphy)[0]
        check("giphy.webp probe timing", meta.frames == 120 and abs((meta.duration or 0) - 7.999) < 0.01, f"frames={meta.frames} dur={meta.duration}")
        out = os.path.join(workdir, "giphy_timed.gif")
        export(giphy, out, preset="instagram_photo")
        with Image.open(out) as img:
            total = 0
            for index in range(img.n_frames):
                img.seek(index)
                total += img.info.get("duration", 0)
        check("giphy export total duration within 2%", abs(total - 7999) / 7999 < 0.02, f"{total}ms vs 7999ms")
    else:
        print("  skip giphy.webp (not present)")

    from filetranscode.exceptions import EngineError, ProbeError
    def expect_loud(callable_, kinds, label):
        try:
            loop.run_until_complete(callable_())
            check(label, False, "no error raised")
        except kinds as error:
            check(label, True, f"{type(error).__name__}")
        except Exception as error:
            check(label, False, f"wrong error type {type(error).__name__}: {str(error)[:80]}")

    for name, key in (("fake.gif", "fake_gif"), ("page.gif", "page_gif"), ("truncated.webp", "truncated_webp")):
        expect_loud(lambda key=key: pipe.probe(input=files[key]), ProbeError, f"probe {name} loud")
        expect_loud(lambda key=key: pipe.probe(input=files[key], engine="imagemagick"), ProbeError, f"probe {name} loud (magick)")
    meta = probe(files["truncated_gif"])[0]
    check("truncated gif probes readable frames only", meta.frames == 2 and meta.animated, f"frames={meta.frames}")
    expect_loud(lambda: pipe.export(input=files["truncated_gif"], output=os.path.join(workdir, "nope.gif"), config=PhotoConfig(photo_constraints={"formats": ["gif"], "max_width": 150})), EngineError, "truncated gif export loud EngineError")
    out = os.path.join(workdir, "zerodelay_out.gif")
    export(files["zerodelay_gif"], out, photo_constraints={"formats": ["gif"], "max_width": 150})
    with Image.open(out) as img:
        img.seek(1)
        check("zero-delay preserved on export", img.info.get("duration", -1) == 0, str(img.info.get("duration")))

    took = time.perf_counter() - started
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed in {took:.1f}s")
    if FAILED:
        print("FAILURES:", *FAILED, sep="\n  ")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
