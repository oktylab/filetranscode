"""Fanout export battery: chunked export must match the single-pass export frame for frame, with trims and speed.
A variable frame rate clip checks the timing itself: a fanout that keeps the frame timing must give every frame the
single pass's timestamp, and one that resamples (capped rate, speed) must show at every grid point the source frame the
fps filter's rule picks on one grid laid from the output's start, with nothing adding up across the chunks.

Clips are generated locally (testsrc2 + a sine tone), nothing is downloaded. Each case runs `export` and `fanout`
with the same config and compares: duration, frame count, codec/size/fps/pix_fmt, audio length and A/V start offset,
silence at chunk joins, and the first/last frame against the source frame the trim points name.

Run: .venv/bin/python develop/videotests/fanout.py <workdir>
"""
import asyncio
import json
import math
import os
import subprocess
import sys
import time
from fractions import Fraction

import numpy as np

from filetranscode import VideoPipeline
from filetranscode.builtin.video.config import VideoConfig
from filetranscode.builtin.video.fanout import chunk_plans
from filetranscode.builtin.video.models import Edits, VideoConstraints

PASSED = []
FAILED = []
ROWS = []

CLIPS = {
    # name: (size, fps, seconds, extra encoder args); the GOP lengths put the keyframe cuts off chunk_seconds
    "h264_bf": ("1280x720", 30, 20, ["-c:v", "libx264", "-preset", "veryfast", "-g", "90"]),
    "h264_nobf": ("1280x720", 30, 20, ["-c:v", "libx264", "-preset", "veryfast", "-g", "91", "-bf", "0"]),
    # an iPhone style 59.94 fps track on a 600 timescale: the chunks' probed rates differ from the plan's, so only some take the fps filter
    "h264_ntsc60_ts600": ("1280x720", "60000/1001", 12, ["-c:v", "libx264", "-preset", "veryfast", "-g", "45", "-video_track_timescale", "600"]),
    "hevc_4k60": ("3840x2160", 60, 30, ["-c:v", "libx265", "-preset", "ultrafast", "-g", "300", "-x265-params", "log-level=error", "-tag:v", "hvc1"]),
}

CROP = {"x1": 0.1, "y1": 0.15, "x2": 0.65, "y2": 0.85}

# (clip, chunk_seconds, codecs, trim_start, trim_end, speed, crop)
CASES = [
    ("h264_bf", 4, ["h264"], None, None, 1.0, None),
    ("h264_bf", 4, ["h264"], 7.0, None, 1.0, None),
    ("h264_bf", 4, ["h264"], None, 13.5, 1.0, None),
    ("h264_bf", 4, ["h264"], 6.5, 8.5, 1.0, None),
    ("h264_bf", 4, ["h264"], 6.0, 9.0, 1.0, None),
    ("h264_bf", 4, ["h264"], 2.5, 16.25, 1.0, None),
    ("h264_bf", 4, ["h264"], None, None, 1.5, None),
    ("h264_bf", 4, ["h264"], None, None, 0.75, None),
    ("h264_bf", 4, ["h264"], 2.5, 16.25, 1.5, None),
    ("h264_bf", 4, ["h264"], 7.0, 13.5, 0.75, None),
    ("h264_nobf", 4, ["h264"], None, None, 1.0, None),
    ("h264_nobf", 4, ["h264"], 6.5, 8.5, 1.0, None),
    ("h264_nobf", 4, ["h264"], None, None, 1.5, None),
    ("h264_nobf", 4, ["h264"], 3.0, 17.0, 1.5, None),
    ("h264_nobf", 4, ["h264"], None, None, 0.75, None),
    ("h264_ntsc60_ts600", 3, ["hevc"], None, None, 1.0, None),
    ("hevc_4k60", 8, ["h264"], None, None, 1.0, None),
    ("hevc_4k60", 8, ["h264"], 4.25, 22.5, 1.0, None),
    ("hevc_4k60", 8, ["hevc"], 4.25, 22.5, 1.5, None),
    # a crop rectangle off the center: every chunk exports the plan's one rectangle, with trims and speed rebased as without it
    ("h264_bf", 4, ["h264"], None, None, 1.0, CROP),
    ("h264_bf", 4, ["h264"], 2.5, 16.25, 1.5, CROP),
    ("h264_ntsc60_ts600", 3, ["hevc"], None, None, 1.0, CROP),
    ("hevc_4k60", 8, ["h264"], 4.25, 22.5, 1.0, CROP),
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


def frames(path: str, first: int, last: int, width: int, height: int, vf: str = "") -> list[np.ndarray]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", f"{vf + ',' if vf else ''}select=between(n\\,{first}\\,{last})", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return [np.frombuffer(raw[i:i + width * height], dtype=np.uint8).reshape(height, width) for i in range(0, len(raw), width * height)]


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def nearest(frame: np.ndarray, candidates: list[np.ndarray], offset: int) -> tuple[int, float]:
    scores = [psnr(frame, candidate) for candidate in candidates]
    best = max(range(len(scores)), key=scores.__getitem__)
    return best + offset, scores[best]


async def split_export_merge(pipe, source: str, workdir: str, label: str, config, chunk_seconds: float) -> str:
    # fanout's steps as separate calls, the way separate machines run them: only paths and plans cross between them
    folder = os.path.join(workdir, f"{label}_chunks")
    plan = await pipe.plan(input=source, config=config)
    split = await pipe.split(input=source, output=os.path.join(folder, "part.mp4"), config=config, chunk_seconds=chunk_seconds, plan=plan)
    chunks, durations = [chunk.output for chunk in split], [chunk.duration for chunk in split]
    exported = [
        await pipe.export(input=chunk, output=os.path.join(folder, f"out_{index:03d}.mp4"), config=config, plan=chunk_plan)
        for index, (chunk, chunk_plan) in enumerate(zip(chunks, chunk_plans(plan, durations))) if chunk_plan
    ]
    actual = os.path.join(workdir, f"{label}_split.mp4")
    await pipe.merge(inputs=exported, output=actual, input=source, plan=plan, durations=durations)
    return actual


async def run_case(pipe, source: str, workdir: str, label: str, chunk_seconds: float, codecs: list[str], start, end, speed, crop) -> None:
    print(f"== {label}")
    config = VideoConfig(video_constraints=VideoConstraints(codecs=codecs), edits=Edits(trim_start=start, trim_end=end, speed=speed, crop=crop))
    box = (await pipe.plan(input=source, config=config)).crop
    # source frames are compared through the plan's own rectangle
    cut = f"crop={box.width}:{box.height}:{box.x}:{box.y}" if box else ""
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
    candidates = frames(source, max(first_index - 2, 0), first_index + 2, want["width"], want["height"], cut) if (want["width"], want["height"]) == (got["width"], got["height"]) else []
    first_got = frames(actual, 0, 0, got["width"], got["height"])[0]
    first_want = frames(expected, 0, 0, want["width"], want["height"])[0]
    index, score = nearest(first_got, candidates, max(first_index - 2, 0))
    # the floor is what the single pass itself reaches on that frame (a default hevc encode of testsrc2 sits near 24 dB)
    floor = min(28, nearest(first_want, candidates, 0)[1] - 1)
    check(f"{label} first frame is source frame {first_index}", index == first_index and score >= floor, f"nearest source frame {index} at {score:.1f} dB")
    check(f"{label} first frame matches export", psnr(first_got, first_want) >= 28, f"{psnr(first_got, first_want):.1f} dB")
    last_got = frames(actual, got["frames"] - 1, got["frames"] - 1, got["width"], got["height"])[0]
    last_want = frames(expected, want["frames"] - 1, want["frames"] - 1, want["width"], want["height"])[0]
    check(f"{label} last frame matches export", psnr(last_got, last_want) >= 28, f"{psnr(last_got, last_want):.1f} dB")
    if speed == 1.0:
        last_index = round((end if end is not None else probe(source)["duration"]) * fps) - 1
        candidates = frames(source, last_index - 2, last_index + 2, want["width"], want["height"], cut)
        index, score = nearest(last_got, candidates, last_index - 2)
        check(f"{label} last frame is source frame {last_index}", index == last_index and score >= min(28, nearest(last_want, candidates, 0)[1] - 1), f"nearest source frame {index} at {score:.1f} dB")
    separate = await split_export_merge(pipe, source, workdir, label, config, chunk_seconds)
    split_probe = probe(separate)
    for key in ("codec", "width", "height", "pix_fmt", "fps", "frames"):
        check(f"{label} split/merge {key}", split_probe[key] == got[key], f"fanout {got[key]} split/merge {split_probe[key]}")
    check(f"{label} split/merge duration", abs(split_probe["duration"] - got["duration"]) <= frame + 1e-6, f"fanout {got['duration']:.4f} split/merge {split_probe['duration']:.4f}")
    check(f"{label} split/merge audio duration", abs(split_probe["audio_duration"] - got["audio_duration"]) <= 1e-3, f"fanout {got['audio_duration']:.4f} split/merge {split_probe['audio_duration']:.4f}")
    check(f"{label} split/merge no silence at joins", not silences(separate), "; ".join(silences(separate)))
    for index in (0, got["frames"] // 2, got["frames"] - 1):
        score = psnr(frames(separate, index, index, got["width"], got["height"])[0], frames(actual, index, index, got["width"], got["height"])[0])
        check(f"{label} split/merge frame {index} matches fanout", score >= 40, f"{score:.1f} dB")
    ROWS.append((label, f"{want['duration']:.4f}/{got['duration']:.4f}", f"{want['frames']}/{got['frames']}", f"{want['audio_duration']:.4f}/{got['audio_duration']:.4f}",
                 f"{offset_want:.4f}/{offset_got:.4f}", str(len(quiet)), f"{psnr(first_got, first_want):.1f}/{psnr(last_got, last_want):.1f}", f"{single:.0f}s/{chunked:.0f}s"))


VFR_CROP = {"x1": 0.1, "y1": 0.1, "x2": 0.9, "y2": 0.9}
# (label, chunk_seconds, config): one second chunks, so twenty joins would show any rounding that adds up
VFR_CASES = [
    ("vfr_keep_timing", 1, {"edits": {"crop": VFR_CROP}}),
    ("vfr_keep_timing_trim", 1, {"edits": {"crop": VFR_CROP, "trim_start": 3.3, "trim_end": 16.7}}),
    ("vfr_cap24", 1, {"video_constraints": {"max_fps": 24}, "edits": {"crop": VFR_CROP}}),
    ("vfr_cap24_trim", 1, {"video_constraints": {"max_fps": 24}, "edits": {"crop": VFR_CROP, "trim_start": 3.3, "trim_end": 16.7}}),
    ("vfr_speed1.5", 1, {"edits": {"crop": VFR_CROP, "speed": 1.5}}),
]


def generate_vfr(workdir: str) -> str:
    # a 60 fps source with about half its frames dropped at random: irregular gaps, B-frames, a 600 timescale like phones
    path = os.path.join(workdir, "vfr.mp4")
    if not os.path.exists(path):
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=60", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "20",
            "-vf", "select='gt(random(1),0.5)'", "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "veryfast", "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-video_track_timescale", "600", path])
    return path


def frame_times(path: str) -> list[float]:
    out = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time", "-of", "csv=p=0", path]).stdout
    times = sorted(float(value) for value in out.split() if value not in ("", "N/A"))
    return [time - times[0] for time in times]


def all_frames(path: str, width: int, height: int, vf: str = "") -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-fps_mode", "passthrough", *(["-vf", vf] if vf else []), "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width).astype(np.float64)


def picks(output: np.ndarray, source: np.ndarray, guesses: list[int]) -> list[int]:
    # the source frame each output frame shows: the closest one around where the ideal grid puts it
    return [low + int(np.argmin([np.mean((frame - candidate) ** 2) for candidate in source[low:guess + 4]]))
            for frame, guess in zip(output, guesses) for low in [max(guess - 4, 0)]]


async def run_vfr_case(pipe, source: str, workdir: str, label: str, chunk_seconds: float, config_data: dict) -> None:
    print(f"== {label}")
    config = VideoConfig(**config_data)
    plan = await pipe.plan(input=source, config=config)
    expected, actual = os.path.join(workdir, f"{label}_export.mp4"), os.path.join(workdir, f"{label}_fanout.mp4")
    await pipe.export(input=source, output=expected, config=config)
    await pipe.fanout(input=source, output=actual, config=config, chunk_seconds=chunk_seconds)
    separate = await split_export_merge(pipe, source, workdir, label, config, chunk_seconds)
    resampled = "fps" in plan.reasons.video or plan.speed != 1.0
    if not resampled:
        want = frame_times(expected)
        for name, path in (("fanout", actual), ("split/merge", separate)):
            got = frame_times(path)
            worst = max((abs(a - b) for a, b in zip(want, got)), default=0.0)
            check(f"{label} {name} keeps every frame's timestamp", len(got) == len(want) and worst < 0.001, f"{len(got)} frames vs {len(want)}, worst {worst * 1000:.1f} ms")
        return
    # the grid the fps filter lays from the output's start, and the source frame its rule shows at each point: the
    # last frame whose time rounds to that point or before (the first kept frame fills any point ahead of it)
    rate = float(Fraction(plan.fps).limit_denominator(1001))
    start, end = plan.trim_start or 0.0, plan.trim_end if plan.trim_end is not None else math.inf
    times = frame_times(source)
    kept = [index for index, time in enumerate(times) if start - 1e-9 <= time < end]
    slots = [round((times[index] - start) / plan.speed * rate) for index in kept]
    count = round((min(times[-1] + (times[-1] - times[-2]), end) - start) / plan.speed * rate)
    ideal = [kept[max((i for i, slot in enumerate(slots) if slot <= n), default=0)] for n in range(count)]
    box = plan.crop
    source_frames = all_frames(source, box.width, box.height, f"crop={box.width}:{box.height}:{box.x}:{box.y}")
    for name, path in (("fanout", actual), ("split/merge", separate)):
        out = all_frames(path, plan.width, plan.height)
        check(f"{label} {name} frame count is the grid's", abs(len(out) - count) <= 1, f"{len(out)} frames, grid {count}")
        got = picks(out, source_frames, ideal)
        off = [g - i for g, i in zip(got, ideal)]
        check(f"{label} {name} shows the grid's source frame everywhere", all(abs(o) <= 0 for o in off), str({k: off.count(k) for k in sorted(set(off))}))


async def main_async(workdir: str) -> None:
    pipe = VideoPipeline()
    clips = generate(workdir)
    only = sys.argv[2:]
    vfr = generate_vfr(workdir)
    for label, chunk_seconds, config_data in VFR_CASES:
        if only and not any(token in label for token in only):
            continue
        await run_vfr_case(pipe, vfr, workdir, label, chunk_seconds, config_data)
    for clip, chunk_seconds, codecs, start, end, speed, crop in CASES:
        label = f"{clip}_{codecs[0]}_c{chunk_seconds:g}_{start if start is not None else 'x'}-{end if end is not None else 'x'}_s{speed:g}{'_crop' if crop else ''}"
        if only and not any(token in label for token in only):
            continue
        await run_case(pipe, clips[clip], workdir, label, chunk_seconds, codecs, start, end, speed, crop)


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
