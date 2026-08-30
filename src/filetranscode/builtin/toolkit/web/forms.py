from typing import Any, get_origin

from pydantic import BaseModel

from ....core.core import Registry
from ..introspect import model_of, unwrap
from .context import ui_of


###########################################################################################################
###########################################################################################################
def choices_of(hints: dict[str, Any], registry: Registry) -> list[str] | None:
    if "choices" in hints:
        source = hints["choices"]
        return list(source() if callable(source) else source)
    if "choices_branch" in hints:
        exclude = set(hints.get("exclude", []))
        try:
            return [key for key in registry.get(hints["choices_branch"]).children if key not in exclude]
        except Exception:
            return None
    if "choices_prefix" in hints:
        prefix = hints["choices_prefix"]
        return [name.removeprefix(f"{prefix}.") for name in registry.names(f"{prefix}.")]
    return None


###########################################################################################################
###########################################################################################################
def form_data(pipeline_cls: type, input_model: type[BaseModel], registry: Registry, group: str) -> dict[str, Any]:
    roles = input_model.roles
    params: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    for name, field in input_model.model_fields.items():
        if name == roles.get("input"):
            params.append(_entry("file", name, multiple=False, placeholder=_destinations(registry, f"{group}.resolve")))
        elif name == roles.get("inputs"):
            params.append(_entry("file", name, multiple=True, placeholder=_destinations(registry, f"{group}.resolve")))
        elif name == roles.get("output"):
            params.append(_entry("output", name, placeholder=_destinations(registry, f"{group}.output")))
        elif name == roles.get("engine"):
            engines = choices_of({"choices_prefix": f"{group}.engine"}, registry) or []
            params.append(_entry("select", name, options=engines, selected=field.default if isinstance(field.default, str) else ""))
        elif name == roles.get("config"):
            sections, primary = _sections(pipeline_cls.config_cls, registry)
            params += primary
        elif model_of(field.annotation):
            params.append(_entry("model", name, placeholder=f"{model_of(field.annotation).__name__} json"))
        else:
            params.append(_field(name, field, registry))
    return {"params": params, "sections": sections}


###########################################################################################################
###########################################################################################################
def _sections(config_cls: type[BaseModel], registry: Registry) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    primary: list[dict[str, Any]] = []
    for name, field in config_cls.model_fields.items():
        hints = ui_of(field)
        if hints.get("primary"):
            primary.append({**_field(name, field, registry), "span2": True})
            continue
        section = groups.setdefault(hints.get("group", "settings"), [])
        nested = model_of(field.annotation)
        if nested:
            section += _rows(nested.model_fields, registry, prefix=f"{name}_")
        else:
            section += _rows({name: field}, registry)
    return [{"legend": legend, "fields": rows} for legend, rows in groups.items() if rows], primary


###########################################################################################################
###########################################################################################################
def _rows(fields: dict[str, Any], registry: Registry, prefix: str = "") -> list[dict[str, Any]]:
    def ranged(*names: str) -> bool:
        return all(name in fields and ui_of(fields[name]).get("widget") == "range" for name in names)

    paired = {name[4:] for name in fields if name.startswith("min_") and ranged(name, f"max_{name[4:]}")}
    spanned = {name[:-6] for name in fields if name.endswith("_start") and ranged(name, f"{name[:-6]}_end")}
    rows = []
    for name, field in fields.items():
        hints = ui_of(field)
        if (name.startswith("max_") and name[4:] in paired) or (name.endswith("_end") and name[:-4] in spanned):
            continue
        if name.startswith("min_") and name[4:] in paired:
            stem = name[4:]
            rows.append(_entry("dual", f"{prefix}{stem}", label=stem.replace("_", " "), min_name=f"{prefix}min_{stem}", max_name=f"{prefix}max_{stem}",
                               low=hints.get("low", 0), high=hints.get("high", 100), step=hints.get("step", 1)))
            continue
        if name.endswith("_start") and name[:-6] in spanned:
            stem = name[:-6]
            rows.append(_entry("dual", f"{prefix}{stem}", label=stem.replace("_", " "), min_name=f"{prefix}{stem}_start", max_name=f"{prefix}{stem}_end",
                               low=hints.get("low", 0), high=hints.get("high", 100), step=hints.get("step", 1)))
            continue
        rows.append(_field(f"{prefix}{name}", field, registry))
    return rows


###########################################################################################################
###########################################################################################################
def _field(name: str, field, registry: Registry) -> dict[str, Any]:
    hints = ui_of(field)
    if hints.get("widget") == "aspect":
        return _entry("aspect", name, options=hints.get("choices", []))
    base = unwrap(field.annotation)
    choices = choices_of(hints, registry)
    if choices and get_origin(base) in (list, set):
        return _entry("chips", name, options=choices)
    if choices:
        return _entry("select", name, options=choices, selected=field.default if isinstance(field.default, str) else "")
    if hints.get("widget") == "range":
        default = field.default if isinstance(field.default, (int, float)) else hints.get("low", 0)
        return _entry("range", name, low=hints.get("low", 0), high=hints.get("high", 100), step=hints.get("step", 1), default=f"{default:g}", css=hints.get("css", ""))
    if base is bool:
        return _entry("checkbox", name)
    if base in (int, float):
        return _entry("number", name)
    if get_origin(base) in (list, set):
        return _entry("text", name, placeholder="space separated")
    return _entry("text", name, placeholder="")


def _entry(kind: str, name: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "name": name, "label": extra.pop("label", name.replace("_", " ")), **extra}


def _destinations(registry: Registry, branch: str) -> str:
    try:
        children = registry.get(branch).children
    except Exception:
        return "a path"
    schemes = [f"{key}://" for key in children if key not in ("default", "bytes", "stream")]
    return " or ".join(["a path", *schemes])
