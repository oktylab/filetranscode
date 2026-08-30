from importlib.util import find_spec
from typing import Annotated, Any

from ...core.core import Branch, Node, Noop, Sequence, Set
from ...registry import registry
from ..toolkit.input_resolve import InputBytesResolver, InputListResolver, InputPathResolver, InputStreamResolver, input_list_type, input_type, scheme_of
from ..toolkit.output_resolve import OutputBytesResolver, OutputEach, OutputPathResolver, OutputStreamResolver, output_scheme_of, output_type
from ..toolkit.introspect import param
from ..toolkit.pipeline import Out, Pipeline, Role, UseMetadata, engine_node, metadata_route, node
from .color import COMPENSATIONS, CodecColor
from .config import VideoConfig
from .context import VideoContext
from .engines.ffmpeg import FfmpegEngine

PYAV = find_spec("av") is not None
MOVIEPY = find_spec("moviepy") is not None
if PYAV:
    from .engines.pyav import PyAvEngine
if MOVIEPY:
    from .engines.moviepy import MoviePyEngine
from .fanout import AdoptPlan, FanOutExport
from .models import ExportPlan, VideoMetadata, VideoPreset
from .planner import Copy, PlanAction, PlanAudio, PlanCodec, PlanCrop, PlanEdits, PlanFrameRate, PlanGeometry, PlanLimits
from .presets import PRESETS, Preset, PresetIndex
from .rate import CodecRate, GENERIC, SizeRetry, TRAITS

InputLike = input_type(InputPathResolver, InputBytesResolver, InputStreamResolver)
InputsLike = input_list_type(InputPathResolver, InputBytesResolver, InputStreamResolver)
OutputLike = output_type(OutputPathResolver, OutputBytesResolver, OutputStreamResolver)
EngineChoice = Annotated[str, Role("engine")]


###########################################################################################################
###########################################################################################################
def codec_route(name: str):
    def selector(ctx) -> str:
        codec = ctx.plan.codec
        return codec if codec in registry.get(name).children else "default"
    return selector


###########################################################################################################
###########################################################################################################
class VideoPipeline(Pipeline):
    name = "video"
    media = "video"
    config_cls = VideoConfig
    context_cls = VideoContext

    #####################################################
    #####################################################
    @node("resolve")
    def resolve(self) -> Node:
        return Branch(
            selector=scheme_of,
            default=InputPathResolver(),
            bytes=InputBytesResolver(),
            stream=InputStreamResolver(),
        )

    #####################################################
    #####################################################
    @node("output")
    def output(self) -> Node:
        return Branch(
            selector=output_scheme_of,
            default=OutputPathResolver(),
            bytes=OutputBytesResolver(),
            stream=OutputStreamResolver(),
        )

    #####################################################
    #####################################################
    @engine_node("ffmpeg")
    def ffmpeg(self) -> Node:
        return FfmpegEngine()

    if PYAV:
        @engine_node("pyav")
        def pyav(self) -> Node:
            return PyAvEngine()

    if MOVIEPY:
        @engine_node("moviepy")
        def moviepy(self) -> Node:
            return MoviePyEngine()

    #####################################################
    #####################################################
    @node("preset")
    def preset(self) -> Node:
        return Branch(selector=lambda ctx: param(ctx, "config").preset or "none", none=Noop(), **{name: Preset(spec) for name, spec in PRESETS.items()})

    #####################################################
    #####################################################
    @node("rate")
    def rate(self) -> Node:
        return Branch(selector=codec_route("video.rate"), default=CodecRate(GENERIC), **{codec: CodecRate(traits) for codec, traits in TRAITS.items()})

    #####################################################
    #####################################################
    @node("color")
    def color(self) -> Node:
        return Branch(selector=codec_route("video.color"), default=CodecColor(), **{codec: CodecColor(compensation) for codec, compensation in COMPENSATIONS.items()})

    #####################################################
    #####################################################
    @node("planner")
    def planner(self) -> Node:
        return Sequence(PlanCodec(), PlanCrop(), PlanGeometry(), PlanFrameRate(), PlanEdits(), PlanAudio(), PlanLimits(), PlanAction())

    #####################################################
    #####################################################
    @node("prepare")
    def prepare(self) -> Node:
        return Sequence(
            Branch(selector=metadata_route, metadata=Noop(), file=self.ref("resolve")),
            Branch(
                selector=lambda ctx: "given" if getattr(ctx.params, "plan", None) else "compute",
                given=Sequence(self.engine_operation("probe"), AdoptPlan()),
                compute=Sequence(
                    self.ref("preset"),
                    Branch(selector=metadata_route, metadata=UseMetadata(), file=self.engine_operation("probe")),
                    self.ref("planner"),
                    Branch(
                        selector=lambda ctx: ctx.plan.action,
                        encode=Sequence(self.ref("rate"), self.ref("color")),
                        copy=Noop(),
                        remux=Noop(),
                    ),
                ),
            ),
        )

    #####################################################
    #####################################################
    @node("execute")
    def execute(self) -> Node:
        return Branch(
            selector=lambda ctx: ctx.plan.action,
            copy=Copy(),
            remux=self.engine_operation("remux"),
            encode=SizeRetry(self.engine_operation("encode")),
        )

    #####################################################
    #####################################################
    @node("probe", public=True)
    def probe(self, input: InputLike, engine: EngineChoice = "ffmpeg") -> list[VideoMetadata]:
        return Sequence(self.ref("resolve"), self.engine_operation("probe"), Out("metadata.before"))

    #####################################################
    #####################################################
    @node("plan", public=True)
    def plan(self, config: VideoConfig, input: InputLike | None = None, metadata: VideoMetadata | None = None) -> ExportPlan:
        return Sequence(self.ref("prepare"), Out("plan"))

    #####################################################
    #####################################################
    @node("export", public=True)
    def export(self, input: InputLike, output: OutputLike, config: VideoConfig, plan: ExportPlan | None = None) -> Any:
        return Sequence(self.ref("prepare"), self.ref("execute"), Set(probe="after"), self.engine_operation("probe"), self.ref("output"))

    #####################################################
    #####################################################
    @node("fanout", public=True)
    def fanout(self, input: InputLike, output: OutputLike, config: VideoConfig, chunk_seconds: float = 60.0, plan: ExportPlan | None = None) -> Any:
        return Sequence(
            self.ref("prepare"),
            SizeRetry(Sequence(self.engine_operation("split"), FanOutExport(self), self.engine_operation("merge"))),
            Set(probe="after"),
            self.engine_operation("probe"),
            self.ref("output"),
        )

    #####################################################
    #####################################################
    @node("split", public=True)
    def split(self, input: InputLike, output: OutputLike, config: VideoConfig, chunk_seconds: float = 60.0) -> list[Any]:
        return Sequence(self.ref("resolve"), self.engine_operation("probe"), self.engine_operation("split"), Set(probe="after"), self.engine_operation("probe"), OutputEach(self.ref("output")))

    #####################################################
    #####################################################
    @node("merge", public=True)
    def merge(self, inputs: InputsLike, output: OutputLike, engine: EngineChoice = "ffmpeg") -> Any:
        return Sequence(InputListResolver(self._registry, f"{self.name}.resolve"), self.engine_operation("merge"), Set(probe="after"), self.engine_operation("probe"), self.ref("output"))

    #####################################################
    #####################################################
    @node("presets", public=True)
    def presets(self) -> dict[str, VideoPreset]:
        return PresetIndex(self._registry)
