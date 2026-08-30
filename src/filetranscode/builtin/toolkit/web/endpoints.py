import io
import json
import zipfile
from typing import Any, get_origin

from pydantic import BaseModel

from ....core.core import Branch, Call, Node, Registry, Sequence, Wrap
from ....core.trace import brief, tracing
from ..introspect import model_of, unwrap
from ..engine import EngineOperationStep
from .context import WebContext


###########################################################################################################
###########################################################################################################
class OpEndpoint(Node):
    def __init__(self, pipeline_cls: type, method: str, op_name: str, input_model: type[BaseModel]) -> None:
        self.pipeline_cls = pipeline_cls
        self.method = method
        self.op_name = op_name
        self.input_model = input_model
        self.help = f"{pipeline_cls.name}.{op_name} over http"

    #####################################################
    #####################################################
    async def __call__(self, ctx: WebContext) -> WebContext:
        run = getattr(self.pipeline_cls(), self.method)
        reserved = "trace" in self.input_model.model_fields or "trace" in self.pipeline_cls.config_cls.model_fields
        if ctx.values.get("trace") and not reserved:
            with tracing() as trace:
                try:
                    result = await run(**self.arguments(ctx))
                finally:
                    ctx.trace = trace.root.to_dict()
        else:
            result = await run(**self.arguments(ctx))
        if isinstance(result, io.BytesIO):
            result = result.getvalue()
        if isinstance(result, (bytes, bytearray)):
            ctx.body = bytes(result)
        elif isinstance(result, list) and result and all(isinstance(chunk, (bytes, bytearray, io.BytesIO)) for chunk in result):
            ctx.parts = [chunk.getvalue() if isinstance(chunk, io.BytesIO) else bytes(chunk) for chunk in result]
            ctx.body = _zipped(ctx.parts)
            ctx.content_type = "application/zip"
            ctx.headers["X-Chunks"] = str(len(result))
        else:
            ctx.result = jsonable(result)
        return ctx

    #####################################################
    #####################################################
    def arguments(self, ctx: WebContext) -> dict[str, Any]:
        from ..output_resolve import AsBytes
        roles = self.input_model.roles
        kwargs: dict[str, Any] = {}
        for name, field in self.input_model.model_fields.items():
            if name == roles.get("input"):
                uploads = ctx.files.get(name)
                kwargs[name] = uploads[0] if uploads else ctx.values.get(name, "")
                if not kwargs[name]:
                    raise ValueError(f"{name}: provide a file or a source")
            elif name == roles.get("inputs"):
                kwargs[name] = [*ctx.files.get(name, []), *str(ctx.values.get(name, "")).split()]
                if not kwargs[name]:
                    raise ValueError(f"{name}: provide at least one file or source")
            elif name == roles.get("output"):
                kwargs[name] = ctx.values.get(name) or AsBytes()
            elif name == roles.get("config"):
                kwargs[name] = self._config(ctx.values)
            elif ctx.values.get(name, "") != "":
                kwargs[name] = _parse(ctx.values[name], field.annotation)
        return kwargs

    #####################################################
    #####################################################
    def _config(self, values: dict[str, str]):
        config_cls = self.pipeline_cls.config_cls
        data: dict[str, Any] = {}
        for name, field in config_cls.model_fields.items():
            nested = model_of(field.annotation)
            if nested:
                group = {sub: _parse(values[f"{name}_{sub}"], subfield.annotation) for sub, subfield in nested.model_fields.items() if values.get(f"{name}_{sub}", "") != ""}
                if group:
                    data[name] = group
            elif values.get(name, "") != "":
                data[name] = _parse(values[name], field.annotation)
        return config_cls(**data)


###########################################################################################################
###########################################################################################################
class GraphEndpoint(Node):
    def __init__(self, group: str, registry: Registry) -> None:
        self.group = group
        self.registry = registry
        self.help = f"inspect {group}.* node graphs"

    async def __call__(self, ctx: WebContext) -> WebContext:
        name = ctx.values.get("name") or f"{self.group}.export"
        if not name.startswith(f"{self.group}."):
            raise ValueError(f"unknown graph: {name}")
        ctx.result = inspect_node(self.registry.get(name), self.registry, {name})
        return ctx


###########################################################################################################
###########################################################################################################
def inspect_node(node: Any, registry: Registry, seen: set[str]) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": type(node).__name__}
    detail = {}
    for key, value in vars(node).items():
        label = key.lstrip("_")
        if isinstance(value, BaseModel):
            detail[label] = value.model_dump(mode="json")
        elif isinstance(value, (str, int, float, bool)):
            detail[label] = value
        elif isinstance(value, (list, tuple, set)) and all(isinstance(item, (str, int, float, bool)) for item in value):
            detail[label] = list(value)
        elif isinstance(value, dict) and all(isinstance(item, (str, int, float, bool, dict, list)) for item in value.values()) and key != "children":
            detail[label] = value
        elif callable(value) and not isinstance(value, Node):
            detail[label] = getattr(value, "__name__", repr(value))
    if isinstance(node, EngineOperationStep):
        detail["engines"] = {name.rsplit(".", 1)[1]: type(registry.get(name)).operations() for name in registry.names(f"{node._prefix}.")}
    if detail:
        data["detail"] = detail
    if isinstance(node, Sequence):
        data["children"] = [inspect_node(child, registry, seen) for child in node.children]
    elif isinstance(node, Branch):
        data["branches"] = {key: inspect_node(child, registry, seen) for key, child in node.children.items()}
    elif isinstance(node, Wrap):
        data["wraps"] = inspect_node(node.node, registry, seen)
    elif isinstance(node, Call):
        data["calls"] = node.name
        if node.name not in seen:
            data["target"] = inspect_node(registry.get(node.name), registry, seen | {node.name})
    return data


###########################################################################################################
###########################################################################################################
def _parse(value: str, annotation: Any) -> Any:
    base = unwrap(annotation)
    if model_of(annotation):
        return json.loads(value)
    if get_origin(base) in (list, set):
        return value.split()
    if base is bool:
        return value not in ("", "false", "off", "0")
    return value


def _zipped(chunks: list) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, chunk in enumerate(chunks):
            data = chunk.getvalue() if isinstance(chunk, io.BytesIO) else bytes(chunk)
            archive.writestr(f"chunk_{index:03d}", data)
    return buffer.getvalue()


def jsonable(result: Any) -> Any:
    if isinstance(result, BaseModel):
        try:
            return result.model_dump(mode="json")
        except (TypeError, ValueError):
            return brief(result)
    if isinstance(result, dict):
        return {key: jsonable(value) for key, value in result.items()}
    if isinstance(result, (list, tuple)):
        return [jsonable(value) for value in result]
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return brief(result)
