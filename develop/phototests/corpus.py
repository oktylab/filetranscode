"""Builds the photo test corpus into a directory: every input shape a phone or editor produces."""
import io
import struct
import sys

import numpy as np
import pillow_heif
from PIL import Image, ImageCms

pillow_heif.register_heif_opener()


###########################################################################################################
###########################################################################################################
def base_pixels() -> np.ndarray:
    h, w = 900, 1200
    yy, xx = np.mgrid[0:h, 0:w]
    sky = np.dstack([120 + 100 * xx / w, 80 + 120 * yy / h, 200 - 80 * xx / w])
    rng = np.random.default_rng(7)
    img = np.clip(sky + rng.normal(0, 14, (h, w, 1)), 0, 255)
    img[300:450, 200:400] = [220, 60, 50]
    img[500:650, 700:950] = [40, 200, 90]
    img[100:220, 800:1050] = [230, 180, 150]
    return img.astype(np.uint8)


###########################################################################################################
###########################################################################################################
def _s15(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536))


def _tag(sig: bytes, body: bytes) -> bytes:
    return sig + b"\x00" * 4 + body


def display_p3_profile() -> bytes:
    desc = _tag(b"desc", struct.pack(">I", 11) + b"Display P3\x00" + b"\x00" * 12 + b"\x00" * 67)
    wtpt = _tag(b"XYZ ", _s15(0.96420) + _s15(1.0) + _s15(0.82491))
    rxyz = _tag(b"XYZ ", _s15(0.51512) + _s15(0.24120) + _s15(-0.00105))
    gxyz = _tag(b"XYZ ", _s15(0.29198) + _s15(0.69225) + _s15(0.04189))
    bxyz = _tag(b"XYZ ", _s15(0.15710) + _s15(0.06657) + _s15(0.78407))
    trc = _tag(b"curv", struct.pack(">IH", 1, round(2.2 * 256)))
    cprt = _tag(b"text", b"none\x00")
    tags = [(b"desc", desc), (b"wtpt", wtpt), (b"rXYZ", rxyz), (b"gXYZ", gxyz), (b"bXYZ", bxyz),
            (b"rTRC", trc), (b"gTRC", trc), (b"bTRC", trc), (b"cprt", cprt)]
    table = struct.pack(">I", len(tags))
    offset = 128 + 4 + 12 * len(tags)
    bodies = b""
    for sig, body in tags:
        padded = body + b"\x00" * (-len(body) % 4)
        table += sig + struct.pack(">II", offset, len(body))
        bodies += padded
        offset += len(padded)
    size = 128 + 4 + 12 * len(tags) + len(bodies)
    header = struct.pack(">I4sI4s4s4s", size, b"lcms", 0x02400000, b"mntr", b"RGB ", b"XYZ ")
    header += struct.pack(">HHHHHH", 2026, 1, 1, 0, 0, 0)
    header += b"acsp" + b"\x00" * 4 + struct.pack(">I", 0) + b"\x00" * 16 + struct.pack(">I", 0)
    header += _s15(0.96420) + _s15(1.0) + _s15(0.82491)
    header += b"\x00" * 4 + b"\x00" * 44
    profile = header[:128] + table + bodies
    assert len(header[:128]) == 128, len(header)
    return profile


###########################################################################################################
###########################################################################################################
def build(directory: str) -> dict:
    pixels = base_pixels()
    base = Image.fromarray(pixels)
    files = {}

    base.save(f"{directory}/photo.png")
    files["photo"] = f"{directory}/photo.png"

    base.save(f"{directory}/photo.jpg", quality=95, subsampling=0)
    files["jpeg"] = f"{directory}/photo.jpg"

    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    base.save(f"{directory}/tagged_srgb.jpg", quality=95, icc_profile=srgb.tobytes())
    files["tagged_srgb"] = f"{directory}/tagged_srgb.jpg"

    p3_bytes = display_p3_profile()
    ImageCms.ImageCmsProfile(io.BytesIO(p3_bytes))
    base.save(f"{directory}/p3.jpg", quality=95, subsampling=0, icc_profile=p3_bytes)
    files["p3"] = f"{directory}/p3.jpg"

    from PIL import Image as PILImage
    exif = PILImage.Exif()
    exif[0x0112] = 6
    base.transpose(Image.Transpose.ROTATE_90).save(f"{directory}/oriented.jpg", quality=95, subsampling=0, exif=exif)
    files["oriented"] = f"{directory}/oriented.jpg"

    rgba = np.dstack([pixels, np.full(pixels.shape[:2], 255, dtype=np.uint8)])
    rgba[:200, :200, 3] = 0
    Image.fromarray(rgba).save(f"{directory}/alpha.png")
    files["alpha"] = f"{directory}/alpha.png"

    frames = [Image.fromarray(np.roll(pixels, shift * 60, axis=1)).resize((300, 225)) for shift in range(3)]
    frames[0].save(f"{directory}/animated.gif", save_all=True, append_images=frames[1:], duration=200, loop=0)
    files["animated"] = f"{directory}/animated.gif"

    frames[0].save(f"{directory}/animated.webp", save_all=True, append_images=frames[1:], duration=200, loop=0)
    files["animated_webp"] = f"{directory}/animated.webp"

    for name, source in (("truncated.gif", f"{directory}/animated.gif"), ("truncated.webp", f"{directory}/animated.webp")):
        blob = open(source, "rb").read()
        with open(f"{directory}/{name}", "wb") as handle:
            handle.write(blob[:int(len(blob) * 0.6)])
        files[name.replace(".", "_")] = f"{directory}/{name}"

    with open(f"{directory}/fake.gif", "wb") as handle:
        handle.write(b"GIF89a" + bytes(range(256)) * 40)
    files["fake_gif"] = f"{directory}/fake.gif"

    with open(f"{directory}/page.gif", "w") as handle:
        handle.write("<!doctype html><html><body>404 not found</body></html>")
    files["page_gif"] = f"{directory}/page.gif"

    frames[0].save(f"{directory}/zerodelay.gif", save_all=True, append_images=frames[1:], duration=0, loop=0)
    files["zerodelay_gif"] = f"{directory}/zerodelay.gif"

    base.convert("CMYK").save(f"{directory}/cmyk.jpg", quality=95)
    files["cmyk"] = f"{directory}/cmyk.jpg"

    sixteen = (pixels[..., 0].astype(np.uint16) * 257)
    Image.fromarray(sixteen).save(f"{directory}/16bit.png")
    files["16bit"] = f"{directory}/16bit.png"

    base.save(f"{directory}/photo.heic", quality=90)
    files["heic"] = f"{directory}/photo.heic"

    base.save(f"{directory}/photo.webp", quality=95)
    files["webp"] = f"{directory}/photo.webp"

    tall = Image.fromarray(pixels[:, :506])
    tall.save(f"{directory}/tall.jpg", quality=95)
    files["tall"] = f"{directory}/tall.jpg"

    return files


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else "."))
