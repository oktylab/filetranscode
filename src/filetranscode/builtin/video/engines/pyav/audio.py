import av

from .codecs import pick_encoder, supported_rate


###########################################################################################################
###########################################################################################################
def audio_out(sink, plan, audio_in):
    if audio_in is None:
        return None, None, None
    if plan is None or plan.audio is None or plan.audio.encoders is None:
        return sink.add_stream_from_template(audio_in), None, None
    encoder = pick_encoder(plan.audio.encoders)
    codec = av.Codec(encoder, "w")
    rate = supported_rate(codec, plan.audio.sample_rate or audio_in.codec_context.sample_rate)
    layout = "mono" if (plan.audio.channels or 2) == 1 else "stereo"
    out = sink.add_stream(encoder, rate=rate)
    out.codec_context.layout = layout
    if plan.audio.bitrate:
        out.codec_context.bit_rate = plan.audio.bitrate
    format = codec.audio_formats[0].name if codec.audio_formats else "fltp"
    out.codec_context.format = format
    return out, av.AudioResampler(format=format, layout=layout, rate=rate), av.AudioFifo()


###########################################################################################################
###########################################################################################################
def transcode_audio(sink, out, resampler, fifo, frame) -> None:
    for resampled in resampler.resample(frame):
        resampled.pts = None
        fifo.write(resampled)
    size = out.codec_context.frame_size or 0
    if size == 0:
        chunk = fifo.read()
        if chunk is not None:
            sink.mux(out.encode(chunk))
        return
    while fifo.samples >= size:
        sink.mux(out.encode(fifo.read(size)))
    if frame is None and fifo.samples:
        sink.mux(out.encode(fifo.read(fifo.samples, partial=True)))
