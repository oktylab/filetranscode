from ..toolkit.web import ui
from .models import AudioConstraints, Model, VideoConstraints


###########################################################################################################
###########################################################################################################
class FormatTraits(Model):
    format: str
    extension: str
    faststart: bool = False
    audio_default: str | None = None
    audio_codecs: set[str] | None = None


###########################################################################################################
###########################################################################################################
class AudioCodecTraits(Model):
    codec: str
    encoders: list[str]
    extension: str
    samplerates: list[int] | None = None
    bitrates: list[int] | None = None
    max_bitrate: int | None = None
    lossless: bool = False


###########################################################################################################
###########################################################################################################
FORMATS: dict[str, FormatTraits] = {}
AUDIO_CODECS: dict[str, AudioCodecTraits] = {}


def register_format(traits: FormatTraits) -> None:
    FORMATS[traits.format] = traits


def register_audio_codec(traits: AudioCodecTraits) -> None:
    AUDIO_CODECS[traits.codec] = traits


def format_of(name: str) -> FormatTraits:
    return FORMATS.get(name) or FormatTraits(format=name, extension=name)


def format_for_extension(extension: str) -> str | None:
    return next((traits.format for traits in FORMATS.values() if traits.extension == extension), None)


def audio_codec_of(codec: str) -> AudioCodecTraits:
    return AUDIO_CODECS.get(codec) or AudioCodecTraits(codec=codec, encoders=[codec], extension=codec)


###########################################################################################################
###########################################################################################################
def container_holds(container: str | None, format: str) -> bool:
    return container is not None and format in container.split(",")


###########################################################################################################
###########################################################################################################
def segment_format(container: str | None) -> tuple[str, str]:
    tokens = set((container or "").split(","))
    for name, traits in FORMATS.items():
        if name in tokens:
            return name, traits.extension
    return "matroska", "mkv"


###########################################################################################################
###########################################################################################################
for traits in (
    FormatTraits(format="mp4", extension="mp4", faststart=True, audio_default="aac", audio_codecs={"aac", "mp3", "ac3", "eac3", "alac"}),
    FormatTraits(format="mov", extension="mov", faststart=True, audio_default="aac", audio_codecs={"aac", "mp3", "ac3", "alac", "pcm_s16le"}),
    FormatTraits(format="matroska", extension="mkv"),
    FormatTraits(format="webm", extension="webm", audio_default="opus", audio_codecs={"opus", "vorbis"}),
    FormatTraits(format="mpeg", extension="mpg", audio_default="mp2", audio_codecs={"mp2", "mp3", "ac3"}),
    FormatTraits(format="mpegts", extension="ts", audio_default="aac", audio_codecs={"aac", "mp2", "mp3", "ac3"}),
    FormatTraits(format="avi", extension="avi", audio_default="aac", audio_codecs={"aac", "mp3", "mp2", "ac3", "pcm_s16le"}),
    FormatTraits(format="ogg", extension="ogv", audio_default="vorbis", audio_codecs={"vorbis", "opus", "flac"}),
):
    register_format(traits)

for audio_traits in (
    AudioCodecTraits(
        codec="aac",
        encoders=["aac"],
        extension="m4a",
        samplerates=[96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000],
        max_bitrate=512_000,
    ),
    AudioCodecTraits(
        codec="opus",
        encoders=["libopus", "opus"],
        extension="ogg",
        samplerates=[48000, 24000, 16000, 12000, 8000],
        max_bitrate=510_000,
    ),
    AudioCodecTraits(
        codec="vorbis",
        encoders=["libvorbis", "vorbis"],
        extension="ogg",
        max_bitrate=480_000,
    ),
    AudioCodecTraits(
        codec="mp3",
        encoders=["libmp3lame"],
        extension="mp3",
        samplerates=[48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000],
        max_bitrate=320_000,
    ),
    AudioCodecTraits(
        codec="mp2",
        encoders=["mp2"],
        extension="mp2",
        samplerates=[48000, 44100, 32000, 24000, 22050, 16000],
        bitrates=[32_000, 48_000, 56_000, 64_000, 80_000, 96_000, 112_000, 128_000, 160_000, 192_000, 224_000, 256_000, 320_000, 384_000],
        max_bitrate=384_000,
    ),
    AudioCodecTraits(
        codec="ac3",
        encoders=["ac3"],
        extension="ac3",
        samplerates=[48000, 44100, 32000],
        bitrates=[32_000, 40_000, 48_000, 56_000, 64_000, 80_000, 96_000, 112_000, 128_000, 160_000, 192_000, 224_000, 256_000, 320_000, 384_000, 448_000, 512_000, 576_000, 640_000],
        max_bitrate=640_000,
    ),
    AudioCodecTraits(codec="eac3", encoders=["eac3"], extension="eac3"),
    AudioCodecTraits(codec="flac", encoders=["flac"], extension="flac", lossless=True),
    AudioCodecTraits(codec="alac", encoders=["alac"], extension="m4a", lossless=True),
    AudioCodecTraits(codec="pcm_s16le", encoders=["pcm_s16le"], extension="wav", lossless=True),
):
    register_audio_codec(audio_traits)

AudioConstraints.model_fields["codecs"].json_schema_extra = ui(choices=lambda: list(AUDIO_CODECS))
VideoConstraints.model_fields["formats"].json_schema_extra = ui(choices=lambda: list(FORMATS))
