import inspect
from pathlib import Path
from typing import Any, get_origin

from pydantic import BaseModel

from ....core.core import Node, Registry
from .context import WebContext
from .forms import form_data

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"

_env = None


def _environment():
    global _env
    if _env is None:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        _env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    return _env


def asset_version() -> int:
    return int(max(path.stat().st_mtime for path in STATIC.iterdir()))


###########################################################################################################
###########################################################################################################
def render(template: str, **context: Any) -> str:
    return _environment().get_template(template).render(**context)


###########################################################################################################
###########################################################################################################
class JsonPage(Node):
    def __init__(self, pipeline_cls: type, op_name: str, input_model: type[BaseModel], registry: Registry) -> None:
        self.pipeline_cls = pipeline_cls
        self.op_name = op_name
        self.input_model = input_model
        self.registry = registry
        self.help = f"{op_name} form with json result"

    async def __call__(self, ctx: WebContext) -> WebContext:
        form = form_data(self.pipeline_cls, self.input_model, self.registry, ctx.group)
        ctx.html = render("json.html", group=ctx.group, op=self.op_name, api=f"/api/{ctx.group}/{self.op_name}?trace=1", media="", **form)
        return ctx


###########################################################################################################
###########################################################################################################
class ExportPage(Node):
    def __init__(self, pipeline_cls: type, op_name: str, input_model: type[BaseModel], registry: Registry, media: str | None = None, multiout: bool = False) -> None:
        self.pipeline_cls = pipeline_cls
        self.op_name = op_name
        self.input_model = input_model
        self.registry = registry
        self.media = media
        self.multiout = multiout
        self.help = f"{op_name} with original/result compare"

    async def __call__(self, ctx: WebContext) -> WebContext:
        form = form_data(self.pipeline_cls, self.input_model, self.registry, ctx.group)
        roles = self.input_model.roles
        ctx.html = render(
            "export.html", group=ctx.group, op=self.op_name, api=f"/api/{ctx.group}/{self.op_name}?trace=1",
            media=self.media or getattr(self.pipeline_cls, "media", "file"),
            has_original="input" in roles or "inputs" in roles,
            multiple="inputs" in roles, multiout=self.multiout, **form,
        )
        return ctx


###########################################################################################################
###########################################################################################################
class DiagramPage(Node):
    def __init__(self, group: str, registry: Registry) -> None:
        self.group = group
        self.registry = registry
        self.help = f"{group} pipeline graph"

    async def __call__(self, ctx: WebContext) -> WebContext:
        ops = [name.rsplit(".", 1)[1] for name in self.registry.names(f"cli.{self.group}.")]
        ctx.html = render("diagram.html", group=self.group, ops=ops)
        return ctx


###########################################################################################################
###########################################################################################################
def page_for(pipeline_cls: type, fn, op_name: str, input_model: type[BaseModel], registry: Registry) -> Node:
    annotation = inspect.signature(fn).return_annotation
    roles = input_model.roles
    if "output" in roles or "inputs" in roles:
        return ExportPage(pipeline_cls, op_name, input_model, registry, multiout=get_origin(annotation) is list)
    return JsonPage(pipeline_cls, op_name, input_model, registry)


###########################################################################################################
###########################################################################################################
def layout(registry: Registry, group: str, page: str, content: str) -> str:
    groups: dict[str, list[str]] = {}
    for name in registry.names("web."):
        _, entry_group, entry_page = name.split(".", 2)
        groups.setdefault(entry_group, []).append(entry_page)
    sidebar = [{"name": entry_group, "pages": sorted(groups[entry_group])} for entry_group in sorted(groups)]
    return render("layout.html", groups=sidebar, active_group=group, active_page=page, content=content, version=asset_version())
