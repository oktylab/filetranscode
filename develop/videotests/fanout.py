"""Fanout export battery: chunked export must match the single-pass export frame for frame, with trims and speed.

Clips are generated locally (testsrc2 + a sine tone), nothing is downloaded. Each case runs `export` and `fanout`
with the same config and compares: duration, frame count, codec/size/fps/pix_fmt, audio length and A/V start offset,
silence at chunk joins, and the first/last frame against the source frame the trim points name.

Run: .venv/bin/python develop/videotests/fanout.py <workdir>
"""
import asyncio
import json
import os
import subprocess
import sys
import time

import numpy as np

from filetranscode import VideoPipeline
from filetranscode.builtin.video.config import VideoConfig
from filetranscode.builtin.video.models import Edits, VideoConstraints

PASSED = []
FAILED = []
ROWS = []

CLIPS = {
    # name: (size, fps, seconds, extra encoder args); the GOP lengths put the keyframe cuts off chunk_seconds
    "h264_bf": ("1280x720", 30, 20, ["-c:v", "libx264", "-preset", "veryfast", "-g", "90"]),
    "h264_nobf": ("1280x720", 30, 20, ["-c:v", "libx264", "-preset", "veryfast", "-g", "91", "-bf", "0"]),
    "hevc_4k60": ("3840x2160", 60, 30, ["-c:v", "libx265", "-preset", "ultrafast", "-g", "300", "-x265-params", "log-level=error", "-tag:v", "hvc1"]),
}

# (clip, chunk_seconds, codecs, trim_start, trim_end, speed)
CASES = [
    ("h264_bf", 4, ["h264"], None, None, 1.0),
    ("h264_bf", 4, ["h264"], 7.0, None, 1.0),
    ("h264_bf", 4, ["h264"], None, 13.5, 1.0),
    ("h264_bf", 4, ["h264"], 6.5, 8.5, 1.0),
    ("h264_bf", 4, ["h264"], 6.0, 9.0, 1.0),
    ("h264_bf", 4, ["h264"], 2.5, 16.25, 1.0),
    ("h264_bf", 4, ["h264"], None, None, 1.5),
    ("h264_bf", 4, ["h264"], None, None, 0.75),
    ("h264_bf", 4, ["h264"], 2.5, 16.25, 1.5),
    ("h264_bf", 4, ["h264"], 7.0, 13.5, 0.75),
    ("h264_nobf", 4, ["h264"], None, None, 1.0),
    ("h264_nobf", 4, ["h264"], 6.5, 8.5, 1.0),
    ("h264_nobf", 4, ["h264"], None, None, 1.5),
    ("h264_nobf", 4, ["h264"], 3.0, 17.0, 1.5),
    ("h264_nobf", 4, ["h264"], None, None, 0.75),
    ("hevc_4k60", 8, ["h264"], None, None, 1.0),
    ("hevc_4k60", 8, ["h264"], 4.25, 22.5, 1.0),
    ("hevc_4k60", 8, ["hevc"], 4.25, 22.5, 1.5),
]


def check(name: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(f"{name}{': ' + detail if detail and not condition else ''}")
    print(("  ok " if condition else "  FAIL ") + name + (f": {detail}" if detail else ""))


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def generate(workdir: str) -> dict[str, str]:
    paths = {}
    for name, (size, fps, seconds, codec) in CLIPS.items():
        path = os.path.join(workdir, f"{name}.mp4")
        if not os.path.exists(path):
            sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                "-t", str(seconds), *codec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", path])
        paths[name] = path
    return paths


def probe(path: str) -> dict:
    data = json.loads(sh(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]).stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    numerator, denominator = video["r_frame_rate"].split("/")
    return {
        "codec": video["codec_name"], "width": video["width"], "height": video["height"], "pix_fmt": video["pix_fmt"],
        "fps": int(numerator) / int(denominator), "frames": int(video["nb_frames"]), "duration": float(video["duration"]),
        "video_start": float(video.get("start_time") or 0), "audio_start": float(audio.get("start_time") or 0), "audio_duration": float(audio["duration"]),
        "format_duration": float(data["format"]["duration"]),
    }


def silences(path: str) -> list[str]:
    result = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-af", "silencedetect=n=-40dB:d=0.01", "-f", "null", "-"], capture_output=True, text=True)
    return [line.strip() for line in result.stderr.splitlines() if "silence_start" in line]


def frames(path: str, first: int, last: int, width: int, height: int) -> list[np.ndarray]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"select=between(n\\,{first}\\,{last})", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return [np.frombuffer(raw[i:i + width * height], dtype=np.uint8).reshape(height, width) for i in range(0, len(raw), width * height)]


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def nearest(frame: np.ndarray, candidates: list[np.ndarray], offset: int) -> tuple[int, float]:
    scores = [psnr(frame, candidate) for candidate in candidates]
    best = max(range(len(scores)), key=scores.__getitem__)
    return best + offset, scores[best]


async def run_case(pipe, source: str, workdir: str, label: str, chunk_seconds: float, codecs: list[str], start, end, speed) -> None:
    print(f"== {label}")
    config = VideoConfig(video_constraints=VideoConstraints(codecs=codecs), edits=Edits(trim_start=start, trim_end=end, speed=speed))
    expected = os.path.join(workdir, f"{label}_export.mp4")
    actual = os.path.join(workdir, f"{label}_fanout.mp4")
    began = time.time()
    await pipe.export(input=source, output=expected, config=config)
    single = time.time() - began
    began = time.time()
    await pipe.fanout(input=source, output=actual, config=config, chunk_seconds=chunk_seconds)
    chunked = time.time() - began
    want, got = probe(expected), probe(actual)
    frame = 1 / want["fps"]
    for key in ("codec", "width", "height", "pix_fmt", "fps"):
        check(f"{label} {key}", want[key] == got[key], f"export {want[key]} fanout {got[key]}")
    check(f"{label} frames", want["frames"] == got["frames"], f"export {want['frames']} fanout {got['frames']}")
    check(f"{label} duration", abs(want["duration"] - got["duration"]) <= frame + 1e-6, f"export {want['duration']:.4f} fanout {got['duration']:.4f}")
    check(f"{label} audio duration", abs(want["audio_duration"] - got["audio_duration"]) <= 1024 / 48000 + 1e-6, f"export {want['audio_duration']:.4f} fanout {got['audio_duration']:.4f}")
    offset_want, offset_got = want["audio_start"] - want["video_start"], got["audio_start"] - got["video_start"]
    check(f"{label} a/v start offset", abs(offset_want - offset_got) <= 1024 / 48000 + 1e-6, f"export {offset_want:.4f} fanout {offset_got:.4f}")
    quiet = silences(actual)
    check(f"{label} no silence at joins", not quiet, "; ".join(quiet))
    # first frame: the source frame the trim start names (speed leaves the first frame alone); last frame: the single pass's
    fps = probe(source)["fps"]
    first_index = round((start or 0.0) * fps)
    candidates = frames(source, max(first_index - 2, 0), first_index + 2, want["width"], want["height"]) if (want["width"], want["height"]) == (got["width"], got["height"]) else []
    first_got = frames(actual, 0, 0, got["width"], got["height"])[0]
    first_want = frames(expected, 0, 0, want["width"], want["height"])[0]
    index, score = nearest(first_got, candidates, max(first_index - 2, 0))
    check(f"{label} first frame is source frame {first_index}", index == first_index and score >= 28, f"nearest source frame {index} at {score:.1f} dB")
    check(f"{label} first frame matches export", psnr(first_got, first_want) >= 28, f"{psnr(first_got, first_want):.1f} dB")
    last_got = frames(actual, got["frames"] - 1, got["frames"] - 1, got["width"], got["height"])[0]
    last_want = frames(expected, want["frames"] - 1, want["frames"] - 1, want["width"], want["height"])[0]
    check(f"{label} last frame matches export", psnr(last_got, last_want) >= 28, f"{psnr(last_got, last_want):.1f} dB")
    if speed == 1.0:
        last_index = round((end if end is not None else probe(source)["duration"]) * fps) - 1
        candidates = frames(source, last_index - 2, last_index + 2, want["width"], want["height"])
        index, score = nearest(last_got, candidates, last_index - 2)
        check(f"{label} last frame is source frame {last_index}", index == last_index and score >= 28, f"nearest source frame {index} at {score:.1f} dB")
    ROWS.append((label, f"{want['duration']:.4f}/{got['duration']:.4f}", f"{want['frames']}/{got['frames']}", f"{want['audio_duration']:.4f}/{got['audio_duration']:.4f}",
                 f"{offset_want:.4f}/{offset_got:.4f}", str(len(quiet)), f"{psnr(first_got, first_want):.1f}/{psnr(last_got, last_want):.1f}", f"{single:.0f}s/{chunked:.0f}s"))


async def main_async(workdir: str) -> None:
    pipe = VideoPipeline()
    clips = generate(workdir)
    only = sys.argv[2:]
    for clip, chunk_seconds, codecs, start, end, speed in CASES:
        label = f"{clip}_{codecs[0]}_c{chunk_seconds:g}_{start if start is not None else 'x'}-{end if end is not None else 'x'}_s{speed:g}"
        if only and not any(token in label for token in only):
            continue
        await run_case(pipe, clips[clip], workdir, label, chunk_seconds, codecs, start, end, speed)


def main() -> int:
    workdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "videotests_work")
    os.makedirs(workdir, exist_ok=True)
    asyncio.run(main_async(workdir))
    print("\ncase | duration export/fanout | frames | audio duration | a/v offset | silences | first/last PSNR dB | time export/fanout")
    for row in ROWS:
        print(" | ".join(row))
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for failure in FAILED:
        print("  FAIL", failure)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
