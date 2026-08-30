import argparse
import json
import sys
from typing import Any, Awaitable, Callable, get_origin

from pydantic import BaseModel, ConfigDict

from ...core.core import Node
from ...core.trace import Step, tracing
from .introspect import model_of, unwrap


###########################################################################################################
###########################################################################################################
class CliContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    argv: list[str] = []
    out: Any = None


###########################################################################################################
###########################################################################################################
class OpCommand(Node):
    def __init__(self, pipeline_cls: type, method: str, op_name: str, input_model: type[BaseModel]) -> None:
        self.pipeline_cls = pipeline_cls
        self.method = method
        self.op_name = op_name
        self.input_model = input_model
        self.help = f"{pipeline_cls.name}.{op_name} as a command"

    #####################################################
    #####################################################
    async def __call__(self, ctx: CliContext) -> CliContext:
        values = vars(self.parser().parse_args(ctx.argv))
        wants_trace = values.pop("_trace", False)
        run = getattr(self.pipeline_cls(), self.method)
        if wants_trace:
            with tracing() as trace:
                try:
                    ctx.out = await run(**self.arguments(values))
                finally:
                    _print_steps(trace.root)
        else:
            ctx.out = await run(**self.arguments(values))
        return ctx

    #####################################################
    #####################################################
    def parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=f"filetranscode {self.pipeline_cls.name} {self.op_name}", argument_default=argparse.SUPPRESS)
        if "trace" not in self.input_model.model_fields and "trace" not in self.pipeline_cls.config_cls.model_fields:
            parser.add_argument("--trace", dest="_trace", action="store_true", default=False)
        roles = self.input_model.roles
        for name, field in self.input_model.model_fields.items():
            if name == roles.get("input"):
                parser.add_argument(name, metavar=name.upper())
            elif name == roles.get("inputs"):
                parser.add_argument(name, nargs="+", metavar=name.upper())
            elif name == roles.get("config"):
                self._config_arguments(parser)
            else:
                _argument(parser, name, field.annotation)
        return parser

    #####################################################
    #####################################################
    def arguments(self, values: dict[str, Any]) -> dict[str, Any]:
        for name, field in self.input_model.model_fields.items():
            if name in values and model_of(field.annotation):
                values[name] = json.loads(values[name])
        config_param = self.input_model.roles.get("config")
        if not config_param:
            return values
        config_cls = self.pipeline_cls.config_cls
        data: dict[str, Any] = {}
        for name, field in config_cls.model_fields.items():
            nested = model_of(field.annotation)
            if nested:
                group = {sub: values.pop(f"{name}_{sub}") for sub in nested.model_fields if f"{name}_{sub}" in values}
                if group:
                    data[name] = group
            elif name in values:
                data[name] = values.pop(name)
        values[config_param] = config_cls(**data)
        return values

    #####################################################
    #####################################################
    def _config_arguments(self, parser: argparse.ArgumentParser) -> None:
        for name, field in self.pipeline_cls.config_cls.model_fields.items():
            nested = model_of(field.annotation)
            if nested:
                for sub, subfield in nested.model_fields.items():
                    _argument(parser, f"{name}_{sub}", subfield.annotation)
            else:
                _argument(parser, name, field.annotation)


###########################################################################################################
###########################################################################################################
def _print_steps(step: Step, depth: int = 0) -> None:
    label = f"[{step.label}] " if step.label else ""
    wrote = f" -> {', '.join(sorted({path.split('.')[0] for path in step.changed}))}" if step.changed else ""
    error = f" !! {step.error}" if step.error else ""
    if depth:
        sys.stderr.write(f"{'  ' * (depth - 1)}{label}{step.kind} {step.took_ms:.0f}ms{wrote}{error}\n")
    for child in step.children:
        _print_steps(child, depth + 1)


###########################################################################################################
###########################################################################################################
class ModelCommand(Node):
    def __init__(self, model: type[BaseModel], run: Callable[[BaseModel], Awaitable[Any]], *, positional: tuple[str, ...] = (), prog: str = "", help: str = "") -> None:
        self.model = model
        self.run = run
        self.positional = positional
        self.prog = prog
        self.help = help

    #####################################################
    #####################################################
    async def __call__(self, ctx: CliContext) -> CliContext:
        values = vars(self.parser().parse_args(ctx.argv))
        ctx.out = await self.run(self.model(**values))
        return ctx

    #####################################################
    #####################################################
    def parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.prog, description=self.help, argument_default=argparse.SUPPRESS)
        for name, field in self.model.model_fields.items():
            _argument(parser, name, field.annotation, positional=name in self.positional)
        return parser


###########################################################################################################
###########################################################################################################
def _argument(parser: argparse.ArgumentParser, name: str, annotation: Any, positional: bool = False) -> None:
    base = unwrap(annotation)
    if positional:
        if get_origin(base) in (list, set):
            parser.add_argument(name, nargs="+", metavar=name.upper())
        else:
            parser.add_argument(name, metavar=name.upper())
        return
    flag = f"--{name.replace('_', '-')}"
    if base is bool:
        parser.add_argument(flag, dest=name, action=argparse.BooleanOptionalAction)
    elif get_origin(base) in (list, set):
        parser.add_argument(flag, dest=name, nargs="*")
    else:
        parser.add_argument(flag, dest=name)


###########################################################################################################
###########################################################################################################


###########################################################################################################
###########################################################################################################
def render(result: Any) -> str:
    if isinstance(result, BaseModel):
        return result.model_dump_json(indent=2)
    if isinstance(result, dict):
        return json.dumps({key: value.model_dump() if isinstance(value, BaseModel) else value for key, value in result.items()}, indent=2, default=str)
    if isinstance(result, list):
        return "\n".join(str(value) for value in result)
    return str(result)
