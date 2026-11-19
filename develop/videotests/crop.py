"""Crop battery: a free crop rectangle on every video engine, on the shapes phones and editors produce.

Clips are generated locally (testsrc2 + a sine tone), nothing is downloaded. Each case plans and exports a crop and
compares the delivered frames with the same source frames cut by ffmpeg's own crop filter on the displayed picture
(after rotation and pixel aspect), so a rectangle read on the stored instead of the displayed frame fails.

Run: .venv/bin/python develop/videotests/crop.py <workdir>
"""
import asyncio
import json
import os
import subprocess
import sys

import numpy as np
from pydantic import ValidationError

from filetranscode import VideoPipeline
from filetranscode.builtin.video.config import VideoConfig
from filetranscode.exceptions import UnsatisfiableError

PASSED = []
FAILED = []

TONE = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
AAC = ["-c:a", "aac", "-b:a", "128k"]
CLIPS = {
    # name: (container, ffmpeg args after the testsrc2 input)
    "h264": ("mp4", ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", *AAC]),
    # stored 640x360, displayed 360x640: a phone held upright
    "h264_rot90": ("mp4", ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", *AAC]),
    # stored 720x480 at 32:27 pixels, displayed 854x480
    "h264_sar": ("mp4", ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-vf", "setsar=32/27", *AAC]),
    # an odd height, which 4:2:0 cannot hold
    "h264_444_odd": ("mp4", ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv444p", *AAC]),
    "hevc_10bit": ("mp4", ["-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le", "-tag:v", "hvc1", "-x265-params", "log-level=error", *AAC]),
    "vp9": ("webm", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "1M", "-pix_fmt", "yuv420p", "-c:a", "libopus"]),
}
SIZES = {"h264": "640x360", "h264_rot90": "640x360", "h264_sar": "720x480", "h264_444_odd": "641x361", "hevc_10bit": "640x360", "vp9": "640x360"}
CROP = {"x1": 0.1, "y1": 0.2, "x2": 0.7, "y2": 0.9}


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(f"{name}{': ' + detail if detail and not condition else ''}")
    print(("  ok " if condition else "  FAIL ") + name + (f": {detail}" if detail else ""))


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def generate(workdir: str) -> dict[str, str]:
    paths = {}
    for name, (container, args) in CLIPS.items():
        path = os.path.join(workdir, f"{name}.{container}")
        if not os.path.exists(path):
            sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={SIZES[name]}:rate=30", *TONE, "-t", "3", *args, path])
            if name == "h264_rot90":
                turned = path.replace(".mp4", "_turned.mp4")
                sh(["ffmpeg", "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", path, "-c", "copy", turned])
                os.replace(turned, path)
        paths[name] = path
    return paths


def displayed(path: str) -> tuple[int, int]:
    # the size ffmpeg decodes to once it applies the rotation and the pixel aspect, which is what a viewer sees
    probe = json.loads(sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-print_format", "json", path]).stdout)["streams"][0]
    width, height = probe["width"], probe["height"]
    sar = probe.get("sample_aspect_ratio", "1:1")
    if sar not in ("1:1", "0:1"):
        numerator, denominator = (int(value) for value in sar.split(":"))
        width = 2 * round(width * numerator / denominator / 2)
    rotation = next((int(float(side["rotation"])) for side in probe.get("side_data_list", []) if "rotation" in side), 0) % 360
    return (height, width) if rotation % 180 == 90 else (width, height)


def frame(path: str, index: int, width: int, height: int, vf: str = "") -> np.ndarray:
    chain = f"{vf}," if vf else ""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"{chain}select=eq(n\\,{index})", "-fps_mode", "passthrough", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw[:width * height], dtype=np.uint8).reshape(height, width)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def stream(path: str) -> dict:
    return json.loads(sh(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_streams", "-print_format", "json", path]).stdout)["streams"][0]


def expected_box(width: int, height: int) -> tuple[int, int, int, int]:
    x, y = 2 * round(CROP["x1"] * width / 2), 2 * round(CROP["y1"] * height / 2)
    right, bottom = min(2 * round(CROP["x2"] * width / 2), width // 2 * 2), min(2 * round(CROP["y2"] * height / 2), height // 2 * 2)
    return x, y, right - x, bottom - y


async def expect_error(awaitable, fragment: str) -> tuple[bool, str]:
    try:
        await awaitable
        return False, "no error raised"
    except UnsatisfiableError as error:
        return fragment in str(error), str(error)


async def crop_case(pipe, source: str, workdir: str, label: str, engine: str) -> None:
    config = VideoConfig(engine=engine, edits={"crop": CROP})
    width, height = displayed(source)
    plan = await pipe.plan(input=source, config=config)
    box = expected_box(width, height)
    got = (plan.crop.x, plan.crop.y, plan.crop.width, plan.crop.height) if plan.crop else None
    check(f"{label} plan box on the displayed {width}x{height}", got == box and (plan.width, plan.height) == box[2:] and "crop" in plan.reasons.video, f"{got} want {box} {plan.reasons.video}")
    check(f"{label} box on even pixels", got is not None and all(value % 2 == 0 for value in got), str(got))
    out = os.path.join(workdir, f"{label}.mp4")
    await pipe.export(input=source, output=out, config=config)
    delivered = stream(out)
    check(f"{label} delivered size", (delivered["width"], delivered["height"]) == box[2:], f"{delivered['width']}x{delivered['height']} want {box[2]}x{box[3]}")
    if (delivered["width"], delivered["height"]) != box[2:]:
        return
    x, y, w, h = box
    reference = f"scale={width}:{height},setsar=1,crop={w}:{h}:{x}:{y}"
    check(f"{label} keeps every frame", int(delivered["nb_read_frames"]) == 90, f"{delivered['nb_read_frames']} of 90")
    for index in (0, 45, 89):
        score = psnr(frame(out, index, w, h), frame(source, index, w, h, reference))
        check(f"{label} frame {index} is the source rectangle", score >= 30, f"{score:.1f} dB")
    # the same frame cut 8 pixels to the side scores far lower, so the PSNR above cannot pass on a misplaced rectangle
    shifted = f"scale={width}:{height},setsar=1,crop={w}:{h}:{x + 8 if x + 8 + w <= width else x - 8}:{y}"
    right, wrong = psnr(frame(out, 45, w, h), frame(source, 45, w, h, reference)), psnr(frame(out, 45, w, h), frame(source, 45, w, h, shifted))
    check(f"{label} misplaced rectangle is told apart", wrong <= right - 10, f"{right:.1f} dB in place, {wrong:.1f} dB shifted")


async def main_async(workdir: str) -> None:
    pipe = VideoPipeline()
    clips = generate(workdir)
    only = sys.argv[2:]
    for engine in ("ffmpeg", "pyav", "moviepy"):
        for name, source in clips.items():
            label = f"{engine}_{name}"
            if only and not any(token in label for token in only):
                continue
            print(f"== {label}")
            try:
                await crop_case(pipe, source, workdir, label, engine)
            except Exception as error:
                check(f"{label} runs", False, f"{type(error).__name__}: {str(error)[:300]}")

    print("== planner rules")
    source = clips["h264"]
    plan = await pipe.plan(input=source, config=VideoConfig(edits={"crop": CROP, "aspect": "9:16"}))
    check("crop wins over aspect", plan.crop is not None and (plan.width, plan.height) == (384, 252) and "aspect" not in plan.reasons.video, f"{plan.width}x{plan.height} {plan.reasons.video}")
    plan = await pipe.plan(input=source, config=VideoConfig(edits={"crop": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}}))
    check("whole-frame crop is a copy", plan.action == "copy" and plan.crop is None, f"{plan.action} {plan.reasons.video}")
    plan = await pipe.plan(input=source, config=VideoConfig(edits={"crop": {"x1": 0.0004, "y1": 0, "x2": 0.9996, "y2": 1}}))
    check("crop within a pixel of the frame is a copy", plan.action == "copy" and plan.crop is None, f"{plan.action} {plan.reasons.video}")
    ok, msg = await expect_error(pipe.plan(input=source, config=VideoConfig(video_constraints={"aspects": ["9:16"]}, edits={"crop": CROP})), "crop 384x252 is not allowed")
    check("crop outside the allowed aspects loud", ok, msg)
    ok, msg = await expect_error(pipe.plan(input=source, config=VideoConfig(video_constraints={"min_aspect": 0.5, "max_aspect": 1.0}, edits={"crop": CROP})), "crop 384x252 is outside")
    check("crop outside the aspect range loud", ok, msg)
    ok, msg = await expect_error(pipe.plan(input=source, config=VideoConfig(edits={"crop": {"x1": 0.5, "y1": 0, "x2": 0.501, "y2": 1}})), "keeps no pixels")
    check("crop under two pixels loud", ok, msg)
    try:
        VideoConfig(edits={"crop": {"x1": 0, "y1": 0.8, "x2": 1, "y2": 0.2}})
        check("reversed crop refused", False, "accepted")
    except ValidationError as error:
        check("reversed crop refused", "y1 < y2" in str(error), str(error))
    try:
        VideoConfig(edits={"crop": {"x1": -0.1, "y1": 0, "x2": 1, "y2": 1}})
        check("crop outside 0..1 refused", False, "accepted")
    except ValidationError:
        check("crop outside 0..1 refused", True)
    plan = await pipe.plan(input=source, config=VideoConfig(video_constraints={"max_long_side": 200}, edits={"crop": CROP}))
    check("crop then fit to the size limits", plan.crop is not None and (plan.crop.width, plan.crop.height) == (384, 252) and max(plan.width, plan.height) == 200 and plan.width % 2 == 0 and plan.height % 2 == 0,
          f"crop {plan.crop} plan {plan.width}x{plan.height}")


def main() -> int:
    workdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "videotests_crop")
    os.makedirs(workdir, exist_ok=True)
    asyncio.run(main_async(workdir))
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print("  FAIL", failure)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
