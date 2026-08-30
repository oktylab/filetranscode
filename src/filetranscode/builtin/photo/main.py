import shutil
from typing import Any, Annotated

from ...core.core import Branch, Node, Noop, Sequence, Set
from ...registry import registry
from ..toolkit.input_resolve import InputBytesResolver, InputPathResolver, InputStreamResolver, input_type, scheme_of
from ..toolkit.introspect import param
from ..toolkit.output_resolve import OutputBytesResolver, OutputPathResolver, OutputStreamResolver, output_scheme_of, output_type
from ..toolkit.pipeline import Out, Pipeline, Role, UseMetadata, engine_node, metadata_route, node
from .color import COMPENSATIONS, FormatColor
from .config import PhotoConfig
from .context import PhotoContext
from .engines.pillow import PillowEngine

IMAGEMAGICK = shutil.which("magick") is not None
if IMAGEMAGICK:
    from .engines.imagemagick import ImageMagickEngine
from .formats import FORMATS
from .models import ExportPlan, PhotoMetadata, PhotoPreset
from .planner import Copy, PlanAction, PlanAlpha, PlanColorSpace, PlanCrop, PlanFormat, PlanGeometry, PlanLimits
from .presets import PRESETS, Preset, PresetIndex
from .quality import FormatQuality, SizeRetry

InputLike = input_type(InputPathResolver, InputBytesResolver, InputStreamResolver)
OutputLike = output_type(OutputPathResolver, OutputBytesResolver, OutputStreamResolver)
EngineChoice = Annotated[str, Role("engine")]


###########################################################################################################
###########################################################################################################
def format_route(name: str):
    def selector(ctx) -> str:
        format = ctx.plan.format
        return format if format in registry.get(name).children else "default"
    return selector


###########################################################################################################
###########################################################################################################
class PhotoPipeline(Pipeline):
    name = "photo"
    media = "image"
    config_cls = PhotoConfig
    context_cls = PhotoContext

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
    @engine_node("pillow")
    def pillow(self) -> Node:
        return PillowEngine()

    if IMAGEMAGICK:
        @engine_node("imagemagick")
        def imagemagick(self) -> Node:
            return ImageMagickEngine()

    #####################################################
    #####################################################
    @node("preset")
    def preset(self) -> Node:
        return Branch(selector=lambda ctx: param(ctx, "config").preset or "none", none=Noop(), **{name: Preset(spec) for name, spec in PRESETS.items()})

    #####################################################
    #####################################################
    @node("quality")
    def quality(self) -> Node:
        return Branch(selector=format_route("photo.quality"), default=FormatQuality(), **{name: FormatQuality(traits) for name, traits in FORMATS.items()})

    #####################################################
    #####################################################
    @node("color")
    def color(self) -> Node:
        return Branch(selector=format_route("photo.color"), default=FormatColor(), **{name: FormatColor(compensation) for name, compensation in COMPENSATIONS.items()})

    #####################################################
    #####################################################
    @node("planner")
    def planner(self) -> Node:
        return Sequence(PlanFormat(), PlanCrop(), PlanGeometry(), PlanColorSpace(), PlanAlpha(), PlanLimits(), PlanAction())

    #####################################################
    #####################################################
    @node("prepare")
    def prepare(self) -> Node:
        return Sequence(
            Branch(selector=metadata_route, metadata=Noop(), file=self.ref("resolve")),
            self.ref("preset"),
            Branch(selector=metadata_route, metadata=UseMetadata(), file=self.engine_operation("probe")),
            self.ref("planner"),
            Branch(
                selector=lambda ctx: ctx.plan.action,
                encode=Sequence(self.ref("quality"), self.ref("color")),
                copy=Noop(),
            ),
        )

    #####################################################
    #####################################################
    @node("execute")
    def execute(self) -> Node:
        return Branch(
            selector=lambda ctx: ctx.plan.action,
            copy=Copy(),
            encode=SizeRetry(self.engine_operation("encode")),
        )

    #####################################################
    #####################################################
    @node("probe", public=True)
    def probe(self, input: InputLike, engine: EngineChoice = "pillow") -> list[PhotoMetadata]:
        return Sequence(self.ref("resolve"), self.engine_operation("probe"), Out("metadata.before"))

    #####################################################
    #####################################################
    @node("plan", public=True)
    def plan(self, config: PhotoConfig, input: InputLike | None = None, metadata: PhotoMetadata | None = None) -> ExportPlan:
        return Sequence(self.ref("prepare"), Out("plan"))

    #####################################################
    #####################################################
    @node("export", public=True)
    def export(self, input: InputLike, output: OutputLike, config: PhotoConfig) -> Any:
        return Sequence(self.ref("prepare"), self.ref("execute"), Set(probe="after"), self.engine_operation("probe"), self.ref("output"))

    #####################################################
    #####################################################
    @node("presets", public=True)
    def presets(self) -> dict[str, PhotoPreset]:
        return PresetIndex(self._registry)
