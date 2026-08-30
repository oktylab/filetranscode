import math
import os

from moviepy import VideoFileClip, afx, concatenate_videoclips, vfx
from moviepy.config import FFMPEG_BINARY
from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos

from .....exceptions import ProbeError
from ....toolkit.engine import Engine, operation, probing
from ....toolkit.output_resolve import OutputData
from ...formats import audio_codec_of, format_for_extension, format_of, segment_format
from ...models import AudioMetadata, VideoMetadata
from ...css import transform
from ...rate import traits_of
from ..ffmpeg.rate import rate_args
from ..encoders import pick_encoder


###########################################################################################################
###########################################################################################################
class MoviePyEngine(Engine):
    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            sink.append(self._probe(data))
        return ctx

    def _probe(self, data) -> VideoMetadata:
        path = data.path
        try:
            infos = ffmpeg_parse_infos(path)
        except (OSError, ValueError, KeyError) as error:
            raise ProbeError(path, str(error))
        if not infos.get("video_found"):
            raise ProbeError(path, "no video stream")
        width, height = infos["video_size"]
        extension = os.path.splitext(str(data.raw_path or ""))[1].lstrip(".").lower()
        return VideoMetadata(
            size=data.size,
            codec=infos.get("video_codec_name") or "unknown",
            container=format_for_extension(extension),
            width=width,
            height=height,
            fps=infos.get("video_fps"),
            duration=infos.get("video_duration") or infos.get("duration"),
            frame_count=infos.get("video_n_frames") or None,
            bitrate=(infos.get("video_bitrate") or 0) * 1000 or None,
            audio=AudioMetadata(
                codec=infos.get("audio_codec_name") or "unknown",
                bitrate=(infos.get("audio_bitrate") or 0) * 1000 or None,
                sample_rate=infos.get("audio_fps") if isinstance(infos.get("audio_fps"), int) else None,
            ) if infos.get("audio_found") else None,
        )

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        with VideoFileClip(ctx.input[0].path) as clip:
            out = clip
            if plan.trim_start is not None or plan.trim_end is not None:
                out = out.subclipped(plan.trim_start or 0, plan.trim_end or clip.duration)
            if plan.crop:
                out = out.cropped(x1=plan.crop.x, y1=plan.crop.y, width=plan.crop.width, height=plan.crop.height)
            if plan.speed != 1.0:
                out = out.with_effects([vfx.MultiplySpeed(factor=plan.speed)])
            if plan.volume != 1.0 and out.audio is not None:
                out = out.with_effects([afx.MultiplyVolume(plan.volume)])
            if (plan.width, plan.height) != (metadata.width, metadata.height):
                out = out.resized((plan.width, plan.height))
            if plan.fps and plan.fps != metadata.fps:
                out = out.with_fps(plan.fps)
            if plan.color and not plan.color.identity():
                out = out.image_transform(transform(plan.color))
            delivered = OutputData()
            path = delivered.temp(suffix=f".{format_of(plan.format).extension}")
            out.write_videofile(path, logger=None, **self._write_kwargs(delivered, plan, metadata))
        delivered.path = path
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    @operation
    async def split(self, ctx):
        metadata = ctx.metadata.before[0]
        format, extension = segment_format(metadata.container)
        seconds = ctx.params.chunk_seconds
        encoder = pick_encoder(FFMPEG_BINARY, traits_of(metadata.codec).encoders)
        chunks: list[OutputData] = []
        with VideoFileClip(ctx.input[0].path) as clip:
            count = max(1, math.ceil(clip.duration / seconds))
            for index in range(count):
                data = OutputData()
                path = data.temp(suffix=f".{extension}")
                section = clip.subclipped(index * seconds, min((index + 1) * seconds, clip.duration))
                section.write_videofile(path, codec=encoder, logger=None)
                data.path = path
                chunks.append(data)
        ctx.output += chunks
        return ctx

    #####################################################
    #####################################################
    @operation
    async def merge(self, ctx):
        infos = ffmpeg_parse_infos(ctx.input[0].path)
        extension = os.path.splitext(str(ctx.input[0].raw_path or ""))[1].lstrip(".").lower()
        format = format_for_extension(extension) or "mp4"
        encoder = pick_encoder(FFMPEG_BINARY, traits_of(infos.get("video_codec_name") or "h264").encoders)
        clips = [VideoFileClip(data.path) for data in ctx.input]
        merged = concatenate_videoclips(clips)
        delivered = OutputData()
        path = delivered.temp(suffix=f".{format_of(format).extension}")
        merged.write_videofile(path, codec=encoder, logger=None)
        for clip in clips:
            clip.close()
        delivered.path = path
        ctx.output.append(delivered)
        return ctx

    #####################################################
    #####################################################
    def _write_kwargs(self, delivered, plan, metadata) -> dict:
        encoder = pick_encoder(FFMPEG_BINARY, plan.encoders)
        params = ["-pix_fmt", plan.pix_fmt]
        for key, value in plan.options.get(encoder, {}).items():
            params += [f"-{key}", value]
        if format_of(plan.format).faststart:
            params += ["-movflags", "+faststart"]
        params += rate_args(plan, encoder)
        kwargs = {"codec": encoder, "ffmpeg_params": params}
        if metadata.audio is None:
            kwargs["audio"] = False
            return kwargs
        audio = plan.audio
        if audio and audio.encoders:
            traits = audio_codec_of(audio.codec or metadata.audio.codec)
            kwargs["audio_codec"] = pick_encoder(FFMPEG_BINARY, audio.encoders)
            kwargs["temp_audiofile"] = delivered.temp(suffix=f".{traits.extension}")
            if audio.bitrate:
                kwargs["audio_bitrate"] = str(audio.bitrate)
            if audio.sample_rate:
                kwargs["audio_fps"] = audio.sample_rate
        else:
            traits = audio_codec_of(metadata.audio.codec)
            kwargs["audio_codec"] = pick_encoder(FFMPEG_BINARY, traits.encoders)
            kwargs["temp_audiofile"] = delivered.temp(suffix=f".{traits.extension}")
        return kwargs
