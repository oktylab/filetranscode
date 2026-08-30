import asyncio
import os
import subprocess

from filetranscode import PhotoPipeline, VideoPipeline
from filetranscode.builtin.photo.config import PhotoConfig
from filetranscode.builtin.toolkit.output_resolve import AsBytes, AsStream
from filetranscode.builtin.video.config import VideoConfig
from filetranscode.registry import registry

import filetranscode_memstore_plugin as memstore
from filetranscode_pdf_plugin.config import PdfConfig
from filetranscode_pdf_plugin.main import PdfPipeline

VIDEO = "/tmp/test_video.mp4"
PHOTO = "/tmp/test_photo.png"
PAGES = ["/tmp/page1.png", "/tmp/page2.png"]


def ffprobe(path: str) -> str:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height:format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return " ".join(out.stdout.split())


async def video_demo() -> None:
    pipe = VideoPipeline()
    print("== video ==")

    metadata = await pipe.probe(input=VIDEO)
    print("probe ->", type(metadata).__name__, metadata.codec, f"{metadata.width}x{metadata.height}", metadata.fps, "audio:", metadata.audio and metadata.audio.codec)

    print("plan copy   ->", (plan := await pipe.plan(input=VIDEO, config=VideoConfig())).action, plan.reasons)
    print("plan remux  ->", (plan := await pipe.plan(input=VIDEO, config=VideoConfig(formats=["matroska"]))).action, plan.reasons)
    plan = await pipe.plan(input=VIDEO, config=VideoConfig(codecs=["hevc"], max_bytes=200_000, saturation=1.2))
    print("plan encode ->", plan.action, plan.reasons, "| rate", plan.rate.bitrate, "est", plan.rate.estimated_bytes, "| color", plan.color)

    presets = await pipe.presets()
    print(f"presets -> {len(presets)}:", ", ".join(sorted(presets)))
    plan = await pipe.plan(input=VIDEO, config=VideoConfig(preset="instagram_story"))
    print("preset plan ->", plan.action, plan.reasons, "format", plan.format)

    path = await pipe.export(input=VIDEO, output="/tmp/demo_path.mp4", config=VideoConfig())
    blob = await pipe.export(input=VIDEO, output=AsBytes(), config=VideoConfig(codecs=["hevc"]))
    stream = await pipe.export(input=VIDEO, output=AsStream(), config=VideoConfig(engine="pyav", codecs=["vp9"]))
    print("export path ->", path, ffprobe(path))
    print("export bytes ->", type(blob).__name__, len(blob))
    print("export stream ->", type(stream).__name__, len(stream.getvalue()))

    for engine in ("ffmpeg", "pyav", "moviepy", "opencv"):
        out = await pipe.export(input=VIDEO, output=f"/tmp/demo_{engine}.mp4", config=VideoConfig(engine=engine, saturation=1.3, max_width=200))
        print(f"engine {engine:8} ->", ffprobe(out))

    chunks = await pipe.split(input=VIDEO, output="/tmp/demo_chunks/part.mp4", config=VideoConfig(), chunk_seconds=1.0)
    merged = await pipe.merge(inputs=chunks, output="/tmp/demo_merged.mp4")
    print("split ->", len(chunks), "chunks | merge ->", ffprobe(merged))

    print("rate branch  ->", sorted(registry.get("video.rate").children))
    print("color branch ->", sorted(registry.get("video.color").children))

    memstore.STORE["demo/in.mp4"] = open(VIDEO, "rb").read()
    url = await pipe.export(input="mem://demo/in.mp4", output="mem://demo/out.mp4", config=VideoConfig(codecs=["hevc"]))
    print("memstore ->", url, len(memstore.STORE["demo/out.mp4"]), "bytes stored")


async def photo_demo() -> None:
    pipe = PhotoPipeline()
    print("== photo ==")
    out = await pipe.export(input=PHOTO, output="/tmp/demo_photo.jpg", config=PhotoConfig(formats=["jpeg"], max_width=400))
    print("export ->", out, os.path.getsize(out), "bytes")


async def pdf_demo() -> None:
    pipe = PdfPipeline()
    print("== pdf ==")
    out = await pipe.export(images=PAGES, output="/tmp/demo.pdf", config=PdfConfig(title="Demo"))
    print("export ->", out, os.path.getsize(out), "bytes")


async def main() -> None:
    await video_demo()
    await photo_demo()
    await pdf_demo()


asyncio.run(main())
