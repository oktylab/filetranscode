"""Derives the constants in builtin/photo/formats.py and color.py from pixel measurements.

Run: .venv/bin/python develop/phototests/measure.py
"""
import io
import sys
import time

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity


def corpus() -> np.ndarray:
    h, w = 900, 1200
    yy, xx = np.mgrid[0:h, 0:w]
    sky = np.dstack([120 + 100 * xx / w, 80 + 120 * yy / h, 200 - 80 * xx / w])
    rng = np.random.default_rng(7)
    texture = rng.normal(0, 14, (h, w, 1))
    img = np.clip(sky + texture, 0, 255)
    img[300:450, 200:400] = [220, 60, 50]
    img[500:650, 700:950] = [40, 200, 90]
    img[100:220, 800:1050] = [230, 180, 150]
    return img.astype(np.uint8)


def roundtrip(pixels: np.ndarray, pillow_format: str, **save_kwargs) -> tuple[np.ndarray, int, float]:
    buffer = io.BytesIO()
    start = time.perf_counter()
    Image.fromarray(pixels).save(buffer, format=pillow_format, **save_kwargs)
    took = time.perf_counter() - start
    decoded = np.asarray(Image.open(io.BytesIO(buffer.getvalue())).convert("RGB"))
    return decoded, buffer.tell(), took


def drift(source: np.ndarray, decoded: np.ndarray) -> dict:
    ssim = structural_similarity(source, decoded, channel_axis=2)
    mean_delta = (decoded.astype(float) - source.astype(float)).mean(axis=(0, 1))
    def hsv(px):
        import colorsys
        small = px[::9, ::9].astype(float) / 255.0
        out = np.array([colorsys.rgb_to_hsv(*p) for p in small.reshape(-1, 3)])
        return out[:, 0], out[:, 1]
    h0, s0 = hsv(source)
    h1, s1 = hsv(decoded)
    hue_delta = np.mean((h1 - h0 + 0.5) % 1.0 - 0.5) * 360
    sat_delta = np.mean(s1 - s0)
    return {"ssim": ssim, "mean_rgb": mean_delta.round(3).tolist(), "hue_deg": round(hue_delta, 4), "sat": round(sat_delta, 5)}


def main() -> None:
    pixels = corpus()
    total = pixels.shape[0] * pixels.shape[1]

    print("== JPEG subsampling at q87 ==")
    for sub, name in ((2, "4:2:0"), (1, "4:2:2"), (0, "4:4:4")):
        decoded, size, took = roundtrip(pixels, "JPEG", quality=87, optimize=True, subsampling=sub)
        print(f"  {name}: bpp={size/total:.3f} {drift(pixels, decoded)} {took*1000:.0f}ms")

    print("== quality sweeps ==")
    sweeps = {
        "JPEG": ([70, 80, 87, 92], {"optimize": True, "subsampling": 1}),
        "WEBP": ([70, 80, 85, 90], {"method": 4}),
        "AVIF": ([55, 65, 72, 80], {"speed": 6}),
        "HEIF": ([55, 65, 75, 85], {}),
    }
    for pillow_format, (qualities, kwargs) in sweeps.items():
        for quality in qualities:
            try:
                decoded, size, took = roundtrip(pixels, pillow_format, quality=quality, **kwargs)
            except Exception as error:
                print(f"  {pillow_format} q{quality}: FAILED {error}")
                continue
            print(f"  {pillow_format} q{quality}: bpp={size/total:.3f} {drift(pixels, decoded)} {took*1000:.0f}ms")

    print("== lossless ==")
    for pillow_format, kwargs in (("PNG", {"compress_level": 9}), ("PNG", {"compress_level": 6}), ("TIFF", {"compression": "tiff_adobe_deflate"}), ("BMP", {}), ("GIF", {})):
        decoded, size, took = roundtrip(pixels, pillow_format, **kwargs)
        print(f"  {pillow_format} {kwargs}: bpp={size/total:.3f} {drift(pixels, decoded)} {took*1000:.0f}ms")


if __name__ == "__main__":
    sys.exit(main())
