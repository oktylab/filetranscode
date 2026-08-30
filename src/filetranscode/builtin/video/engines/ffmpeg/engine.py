import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from glob import glob

from .....exceptions import EngineError, ProbeError
from ....toolkit.engine import Engine, operation, probing
from ....toolkit.output_resolve import OutputData
from ...formats import format_of, segment_format
from ...models import AudioMetadata, VideoMetadata
from ..encoders import pick_encoder
from .filters import audio_filters, video_filters
from .rate import rate_args

BINARY = "ffmpeg"
PROBE_BINARY = "ffprobe"


###########################################################################################################
###########################################################################################################
async def _run(args: list[str]) -> None:
    result = await asyncio.to_thread(subprocess.run, args, capture_output=True, text=True)
    if result.returncode:
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        raise EngineError(f"{args[0]}: " + (" | ".join(lines[-3:]) if lines else f"exit {result.returncode}"))


###########################################################################################################
###########################################################################################################
def _sar(text: str | None) -> float:
    if not text or ":" not in text:
        return 1.0
    numerator, denominator = text.split(":")
    return float(numerator) / float(denominator) if int(denominator or 0) and int(numerator or 0) else 1.0


def _display(width: int, height: int, sar_text: str | None, rotation: int) -> tuple[int, int]:
    width = 2 * round(width * _sar(sar_text) / 2)
    if rotation % 180 == 90:
        return height, width
    return width, height


###########################################################################################################
###########################################################################################################
class FfmpegEngine(Engine):
    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            sink.append(await self._probe(data))
        return ctx

    async def _measured_duration(self, path: str) -> float | None:
        result = await asyncio.to_thread(
            subprocess.run,
            [PROBE_BINARY, "-v", "error", "-read_intervals", "99999999%", "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        ends = []
        for line in result.stdout.splitlines():
            pts, _, duration = line.partition(",")
            try:
                ends.append(float(pts) + (float(duration) if duration and duration != "N/A" else 0.0))
            except ValueError:
                continue
        return max(ends) if ends else None

    async def _measured_audio_bps(self, path: str, duration: float) -> int | None:
        result = await asyncio.to_thread(
            subprocess.run,
            [PROBE_BINARY, "-v", "error", "-select_streams", "a", "-show_entries", "packet=size", "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        total = sum(int(line) for line in result.stdout.splitlines() if line.isdigit())
        return int(total * 8 / duration) if total and duration else None

    async def _probe(self, source) -> VideoMetadata:
        result = await asyncio.to_thread(
            subprocess.run,
            [PROBE_BINARY, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", "-show_entries", "stream_side_data_list", source.path],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise ProbeError(source.path, result.stderr.strip())
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        if not videos:
            raise ProbeError(source.path, "no video stream")
        video = videos[0]
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        container = data.get("format", {})
        numerator, denominator = video.get("r_frame_rate", "0/0").split("/")
        rotation = next((int(float(side.get("rotation", 0))) for side in video.get("side_data_list", []) if "rotation" in side), 0) % 360
        width, height = _display(video["width"], video["height"], video.get("sample_aspect_ratio"), rotation)
        metadata = VideoMetadata(
            size=source.size,
            codec=video.get("codec_name", "unknown"),
            container=container.get("format_name"),
            width=width,
            height=height,
            rotation=rotation,
            sar=_sar(video.get("sample_aspect_ratio")),
            fps=int(numerator) / int(denominator) if int(denominator or 0) else None,
            duration=float(video.get("duration") or container.get("duration") or 0) or None,
            frame_count=int(video["nb_frames"]) if str(video.get("nb_frames", "")).isdigit() else None,
            bitrate=int(video.get("bit_rate") or container.get("bit_rate") or 0) or None,
            pix_fmt=video.get("pix_fmt"),
            color_space=video.get("color_space"),
            color_range=video.get("color_range"),
            audio=AudioMetadata(
                codec=audio.get("codec_name", "unknown"),
                bitrate=int(audio.get("bit_rate") or 0) or None,
                channels=audio.get("channels"),
                sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
            ) if audio else None,
        )
        measured = await self._measured_duration(source.path)
        if measured:
            metadata = metadata.model_copy(update={"duration": measured})
        if metadata.audio and metadata.audio.bitrate is None and metadata.duration:
            bps = await self._measured_audio_bps(source.path, metadata.duration)
            if bps:
                metadata = metadata.model_copy(update={"audio": metadata.audio.model_copy(update={"bitrate": bps})})
        return metadata

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        args = [BINARY, "-y"]
        if plan.trim_start:
            args += ["-ss", f"{plan.trim_start:g}"]
        args += ["-i", ctx.input[0].path]
        if plan.trim_end is not None:
            args += ["-t", f"{(plan.trim_end - (plan.trim_start or 0)) / plan.speed:g}"]
        filters = video_filters(plan, metadata)
        if filters:
            args += ["-vf", ",".join(filters)]
        encoder = pick_encoder(BINARY, plan.encoders)
        args += ["-c:v", encoder, "-pix_fmt", plan.pix_fmt]
        for key, value in plan.options.get(encoder, {}).items():
            args += [f"-{key}", value]
        args += rate_args(plan, encoder)
        args += self._audio_args(plan, metadata)
        if format_of(plan.format).faststart:
            args += ["-movflags", "+faststart"]
        delivered = OutputData()
        args += ["-f", plan.format, delivered.path]
        await _run(args)
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    @operation
    async def remux(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        args = [BINARY, "-y", "-i", ctx.input[0].path, "-map", "0:v:0", "-c:v", "copy"]
        if metadata.audio:
            args += ["-map", "0:a:0"]
        args += self._audio_args(plan, metadata)
        if format_of(plan.format).faststart:
            args += ["-movflags", "+faststart"]
        delivered = OutputData()
        args += ["-f", plan.format, delivered.path]
        await _run(args)
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    @operation
    async def split(self, ctx):
        format, extension = segment_format(ctx.metadata.before[0].container)
        workdir = tempfile.mkdtemp()
        try:
            pattern = os.path.join(workdir, f"chunk_%03d.{extension}")
            await _run([
                BINARY, "-y", "-i", ctx.input[0].path, "-map", "0", "-c", "copy",
                "-f", "segment", "-segment_time", str(ctx.params.chunk_seconds),
                "-segment_format", format, "-reset_timestamps", "1", pattern,
            ])
            chunks = []
            for path in sorted(glob(os.path.join(workdir, f"chunk_*.{extension}"))):
                data = OutputData()
                target = data.temp(suffix=f".{extension}")
                os.replace(path, target)
                data.path = target
                chunks.append(data)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        ctx.output += chunks
        return ctx

    #####################################################
    #####################################################
    @operation
    async def merge(self, ctx):
        sniff = await asyncio.to_thread(subprocess.run, [PROBE_BINARY, "-v", "error", "-show_entries", "format=format_name", "-of", "csv=p=0", ctx.input[0].path], capture_output=True, text=True)
        format, _ = segment_format(sniff.stdout.strip())
        delivered = OutputData()
        listing = delivered.temp(suffix=".txt")
        with open(listing, "w") as handle:
            handle.writelines(f"file '{data.path}'\n" for data in ctx.input)
        # the concat demuxer refuses non-file protocols in its listed entries unless
        # explicitly whitelisted, so a remote-URL resolver (e.g. a presigned S3 GET)
        # needs this even though ffmpeg allows the same URL directly as a top-level -i
        args = [BINARY, "-y", "-protocol_whitelist", "file,http,https,tcp,tls,crypto",
                "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy"]
        if format_of(format).faststart:
            args += ["-movflags", "+faststart"]
        args += ["-f", format, delivered.path]
        await _run(args)
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    def _audio_args(self, plan, metadata) -> list[str]:
        if metadata.audio is None:
            return ["-an"]
        if plan.audio is None or plan.audio.encoders is None:
            return ["-c:a", "copy"]
        audio = plan.audio
        args = ["-c:a", pick_encoder(BINARY, audio.encoders)]
        tempo = audio_filters(plan)
        if tempo:
            args += ["-af", ",".join(tempo)]
        if audio.bitrate:
            args += ["-b:a", str(audio.bitrate)]
        if audio.channels:
            args += ["-ac", str(audio.channels)]
        if audio.sample_rate:
            args += ["-ar", str(audio.sample_rate)]
        return args
