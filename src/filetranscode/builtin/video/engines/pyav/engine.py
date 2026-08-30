import io
from fractions import Fraction

import av
import av.error

from .....exceptions import ProbeError
from ....toolkit.engine import Engine, operation, probing
from ....toolkit.output_resolve import OutputData
from ...formats import segment_format
from ...models import AudioMetadata, VideoMetadata
from .audio import audio_out, transcode_audio
from .codecs import pick_encoder, rate_options
from .filters import audio_graph, build_graph, drain_graph, filtered, video_steps


###########################################################################################################
###########################################################################################################
def _open(data):
    try:
        return av.open(data.stream)
    except (av.error.FFmpegError, OSError, ValueError) as error:
        raise ProbeError(str(data.raw_path or "<memory>"), str(error))


###########################################################################################################
###########################################################################################################
def _decode(packet):
    try:
        return packet.decode()
    except av.error.InvalidDataError:
        return []


###########################################################################################################
###########################################################################################################
def _rotation(container, video) -> int:
    try:
        for frame in container.decode(video):
            rotation = int(frame.rotation or 0) % 360
            container.seek(0)
            return rotation
    except (av.error.FFmpegError, StopIteration, TypeError, ValueError):
        pass
    return 0


###########################################################################################################
###########################################################################################################
def _measured_duration(container) -> float | None:
    try:
        container.seek(container.duration - 1 if container.duration else (1 << 60))
        ends = [float((packet.pts + (packet.duration or 0)) * packet.time_base)
                for packet in container.demux() if packet.pts is not None]
        return max(ends) if ends else None
    except (av.error.FFmpegError, OSError, ValueError):
        return None


###########################################################################################################
###########################################################################################################
def _measured_audio_bps(data, duration: float) -> int | None:
    try:
        with _open(data) as container:
            if not container.streams.audio:
                return None
            total = sum(packet.size for packet in container.demux(container.streams.audio[0]) if packet.size)
        return int(total * 8 / duration) if total else None
    except (av.error.FFmpegError, OSError, ValueError):
        return None


###########################################################################################################
###########################################################################################################
def _tempo(graph, frame):
    if graph is None:
        return [frame] if frame is not None else []
    if frame is not None:
        frame.pts = None
        graph.push(frame)
    else:
        graph.push(None)
    stretched = []
    while True:
        try:
            stretched.append(graph.pull())
        except (av.error.BlockingIOError, av.error.EOFError):
            break
    return stretched


###########################################################################################################
###########################################################################################################
def _outside(frame, start: float, end: float | None) -> bool:
    if frame.time is None:
        return False
    return frame.time < start or (end is not None and frame.time >= end)


def _outside_packet(packet, start: float, end: float | None) -> bool:
    if packet.pts is None:
        return False
    time = float(packet.pts * packet.time_base)
    return time < start or (end is not None and time >= end)


def _rebase(frame, start: float) -> None:
    if start and frame.pts is not None and frame.time_base:
        frame.pts = frame.pts - int(round(start / frame.time_base))


###########################################################################################################
###########################################################################################################
def _rate(plan, video) -> Fraction:
    if plan.fps:
        return Fraction(plan.fps).limit_denominator(1001000)
    return video.average_rate or Fraction(30, 1)


###########################################################################################################
###########################################################################################################
def _audio_metadata(audio) -> AudioMetadata | None:
    if audio is None:
        return None
    context = audio.codec_context
    return AudioMetadata(
        codec=context.name,
        bitrate=audio.bit_rate or None,
        channels=context.layout.nb_channels if context.layout else None,
        sample_rate=context.sample_rate,
    )


###########################################################################################################
###########################################################################################################
class PyAvEngine(Engine):
    #####################################################
    #####################################################
    @operation
    async def probe(self, ctx):
        datas, sink = probing(ctx)
        for data in datas:
            sink.append(self._probe(data))
        return ctx

    def _probe(self, data) -> VideoMetadata:
        with _open(data) as container:
            if not container.streams.video:
                raise ProbeError(str(data.raw_path or "<memory>"), "no video stream")
            video = container.streams.video[0]
            audio = container.streams.audio[0] if container.streams.audio else None
            sar = float(video.sample_aspect_ratio) if video.sample_aspect_ratio else 1.0
            rotation = _rotation(container, video)
            width = 2 * round(video.codec_context.width * sar / 2)
            height = video.codec_context.height
            if rotation % 180 == 90:
                width, height = height, width
            metadata = VideoMetadata(
                size=data.size,
                codec=video.codec_context.name,
                container=container.format.name,
                width=width,
                height=height,
                rotation=rotation,
                sar=sar,
                fps=float(video.average_rate) if video.average_rate else None,
                duration=container.duration / av.time_base if container.duration else None,
                frame_count=video.frames or None,
                bitrate=video.bit_rate or container.bit_rate or None,
                pix_fmt=video.codec_context.pix_fmt,
                audio=_audio_metadata(audio),
            )
            measured = _measured_duration(container)
            if measured:
                metadata = metadata.model_copy(update={"duration": measured})
        if metadata.audio and metadata.audio.bitrate is None and metadata.duration:
            bps = _measured_audio_bps(data, metadata.duration)
            if bps:
                metadata = metadata.model_copy(update={"audio": metadata.audio.model_copy(update={"bitrate": bps})})
        return metadata

    #####################################################
    #####################################################
    @operation
    async def encode(self, ctx):
        plan, metadata = ctx.plan, ctx.metadata.before[0]
        buffer = io.BytesIO()
        with _open(ctx.input[0]) as source, av.open(buffer, "w", format=plan.format) as sink:
            video_in = source.streams.video[0]
            encoder = pick_encoder(plan.encoders)
            video_out = sink.add_stream(encoder, rate=_rate(plan, video_in), options={**plan.options.get(encoder, {}), **rate_options(plan, encoder)})
            video_out.width, video_out.height = plan.width, plan.height
            video_out.pix_fmt = plan.pix_fmt
            if plan.rate and plan.rate.mode == "abr" and plan.rate.bitrate:
                video_out.codec_context.bit_rate = plan.rate.bitrate
            audio_in = source.streams.audio[0] if source.streams.audio else None
            audio_stream, resampler, fifo = audio_out(sink, plan, audio_in)
            tempo = audio_graph(audio_in, plan) if resampler is not None else None
            graph = build_graph(video_in, [*video_steps(plan, metadata), ("format", plan.pix_fmt)])
            start, end = plan.trim_start or 0.0, plan.trim_end
            if start:
                source.seek(int(start * av.time_base))
            for packet in source.demux([stream for stream in (video_in, audio_in) if stream is not None]):
                if packet.dts is None:
                    continue
                if end is not None and packet.pts is not None and float(packet.pts * packet.time_base) > end + 2:
                    break
                if packet.stream is video_in:
                    for frame in _decode(packet):
                        if _outside(frame, start, end):
                            continue
                        for graded in filtered(graph, frame):
                            graded.pict_type = 0
                            _rebase(graded, start)
                            sink.mux(video_out.encode(graded))
                elif resampler is None:
                    if _outside_packet(packet, start, end):
                        continue
                    if start:
                        packet.pts -= int(start / packet.time_base)
                        packet.dts = packet.pts
                    packet.stream = audio_stream
                    sink.mux(packet)
                else:
                    for frame in _decode(packet):
                        if _outside(frame, start, end):
                            continue
                        if start:
                            frame.pts = None
                        for stretched in _tempo(tempo, frame):
                            transcode_audio(sink, audio_stream, resampler, fifo, stretched)
            if graph is not None:
                graph.push(None)
                for frame in drain_graph(graph):
                    frame.pict_type = 0
                    sink.mux(video_out.encode(frame))
            sink.mux(video_out.encode())
            if resampler is not None:
                for stretched in _tempo(tempo, None):
                    transcode_audio(sink, audio_stream, resampler, fifo, stretched)
                transcode_audio(sink, audio_stream, resampler, fifo, None)
                sink.mux(audio_stream.encode())
        ctx.output.append(OutputData(raw_stream=buffer))
        return ctx

    #####################################################
    #####################################################
    @operation
    async def remux(self, ctx):
        plan = ctx.plan
        buffer = io.BytesIO()
        with _open(ctx.input[0]) as source, av.open(buffer, "w", format=plan.format) as sink:
            video_in = source.streams.video[0]
            video_out = sink.add_stream_from_template(video_in)
            audio_in = source.streams.audio[0] if source.streams.audio else None
            audio_stream, resampler, fifo = audio_out(sink, plan, audio_in)
            shaper = audio_graph(audio_in, plan) if resampler is not None else None
            for packet in source.demux([stream for stream in (video_in, audio_in) if stream is not None]):
                if packet.dts is None:
                    continue
                if packet.stream is video_in:
                    packet.stream = video_out
                    sink.mux(packet)
                elif resampler is None:
                    packet.stream = audio_stream
                    sink.mux(packet)
                else:
                    for frame in _decode(packet):
                        for shaped in _tempo(shaper, frame):
                            transcode_audio(sink, audio_stream, resampler, fifo, shaped)
            if resampler is not None:
                for shaped in _tempo(shaper, None):
                    transcode_audio(sink, audio_stream, resampler, fifo, shaped)
                transcode_audio(sink, audio_stream, resampler, fifo, None)
                sink.mux(audio_stream.encode())
        ctx.output.append(OutputData(raw_stream=buffer))
        return ctx

    #####################################################
    #####################################################
    @operation
    async def split(self, ctx):
        format, extension = segment_format(ctx.metadata.before[0].container)
        seconds = ctx.params.chunk_seconds
        chunks: list[OutputData] = []
        with _open(ctx.input[0]) as source:
            video = source.streams.video[0]
            streams = [video, *source.streams.audio[:1]]
            sink = None
            mapping: dict = {}
            offsets: dict = {}
            boundary = 0.0
            for packet in source.demux(streams):
                if packet.dts is None:
                    continue
                if packet.stream is video and packet.is_keyframe and (sink is None or float(packet.dts * packet.time_base) >= boundary):
                    if sink is not None:
                        sink.close()
                    boundary = float(packet.dts * packet.time_base) + seconds
                    data = OutputData()
                    path = data.temp(suffix=f".{extension}")
                    data.path = path
                    chunks.append(data)
                    sink = av.open(path, "w", format=format)
                    mapping = {stream: sink.add_stream_from_template(stream) for stream in streams}
                    offsets = {}
                    segment_start = (packet.pts if packet.pts is not None else packet.dts) * packet.time_base
                if sink is None:
                    continue
                offset = offsets.setdefault(packet.stream, int(segment_start / packet.stream.time_base))
                packet.pts = packet.pts - offset if packet.pts is not None else None
                packet.dts -= offset
                packet.stream = mapping[packet.stream]
                sink.mux(packet)
            if sink is not None:
                sink.close()
        ctx.output += chunks
        return ctx

    #####################################################
    #####################################################
    @operation
    async def merge(self, ctx):
        with av.open(io.BytesIO(ctx.input[0].bytes_)) as first:
            format, _ = segment_format(first.format.name)
        delivered = OutputData()
        listing = delivered.temp(suffix=".txt")
        with open(listing, "w") as handle:
            handle.writelines(f"file '{data.path}'\n" for data in ctx.input)
        buffer = io.BytesIO()
        with av.open(listing, format="concat", options={"safe": "0"}) as source, av.open(buffer, "w", format=format) as sink:
            streams = [stream for stream in source.streams if stream.type in ("video", "audio")]
            mapping = {stream.index: sink.add_stream_from_template(stream) for stream in streams}
            for packet in source.demux(streams):
                if packet.dts is None:
                    continue
                packet.stream = mapping[packet.stream.index]
                sink.mux(packet)
        delivered.stream = buffer
        ctx.output.append(delivered)
        return ctx
