import inspect
from types import UnionType
from typing import Any, Generic, TypeVar, Union, get_args, get_origin
from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model
from ...core.core import Call, Node, Registry
from ...registry import registry as default_registry
from .cli import OpCommand
from .introspect import Role
from .engine import EngineOperationStep
from .web import DiagramPage, GraphEndpoint, OpEndpoint, page_for
from .extend import extend_model


###########################################################################################################
###########################################################################################################
def node(name: str, *, public: bool = False):
    if not isinstance(name, str):
        raise TypeError("@node requires an explicit name: @node(\"resolve\"), not bare @node")

    def wrap(fn):
        fn._node_name = name
        fn._node_public = public
        return fn
    return wrap


###########################################################################################################
###########################################################################################################
def engine_node(name: str):
    return node(f"engine.{name}")


###########################################################################################################
###########################################################################################################
def _signature_fields(fn) -> dict[str, tuple[type, Any]]:
    fields = {}
    for pname, param in inspect.signature(fn).parameters.items():
        if pname == "self":
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else Any
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[pname] = (annotation, default)
    return fields


###########################################################################################################
###########################################################################################################
def _input_model(op_name: str, fn, config_cls: type) -> type[BaseModel]:
    config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    model = create_model(f"{op_name.capitalize()}Params", __config__=config, **_signature_fields(fn))
    model.roles = _roles_of(fn, config_cls)
    return model


###########################################################################################################
###########################################################################################################
def _role_of(annotation, config_cls: type) -> str | None:
    args = get_args(annotation)
    if isinstance(annotation, type) and not args and issubclass(annotation, config_cls):
        return "config"
    role = next((meta for meta in args if isinstance(meta, Role)), None)
    if role is None and get_origin(annotation) in (Union, UnionType):
        role = next((found for arg in args if (found := _role_of(arg, config_cls))), None)
    return role


def _roles_of(fn, config_cls: type) -> dict[str, str]:
    return {role: pname for pname, (annotation, _) in _signature_fields(fn).items() if (role := _role_of(annotation, config_cls))}


M = TypeVar("M")


###########################################################################################################
###########################################################################################################
class Probed(BaseModel, Generic[M]):
    before: list[M] = []
    after: list[M] = []


###########################################################################################################
###########################################################################################################
class Out(Node):
    def __init__(self, field: str) -> None:
        self.field = field

    async def __call__(self, ctx):
        value = ctx
        for part in self.field.split("."):
            value = getattr(value, part)
        ctx.out = value
        return ctx


###########################################################################################################
###########################################################################################################
class UseMetadata(Node):
    async def __call__(self, ctx):
        ctx.metadata.before = [ctx.params.metadata]
        return ctx


def metadata_route(ctx) -> str:
    params = ctx.params
    if getattr(params, "metadata", None) is not None:
        return "metadata"
    if hasattr(params, "metadata") and getattr(params, "input", None) is None:
        raise ValueError("provide either an input file or its metadata")
    return "file"


###########################################################################################################
###########################################################################################################
def _out_adapter(fn) -> TypeAdapter | None:
    annotation = inspect.signature(fn).return_annotation
    if annotation is inspect.Signature.empty or annotation is None:
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return TypeAdapter(annotation)
    return TypeAdapter(annotation, config=ConfigDict(arbitrary_types_allowed=True))


###########################################################################################################
###########################################################################################################
def _public_caller(op_name: str, input_model: type[BaseModel], out_adapter: TypeAdapter | None):
    async def caller(self, **kwargs):
        params = input_model(**kwargs)
        ctx = self.context_cls(params=params)
        try:
            ctx = await self._registry.get(f"{self.name}.{op_name}")(ctx)
            return out_adapter.validate_python(ctx.out) if out_adapter else ctx
        finally:
            for value in ctx.__dict__.values():
                for item in value if isinstance(value, list) else (value,):
                    if hasattr(item, "cleanup"):
                        item.cleanup()
    return caller


###########################################################################################################
###########################################################################################################
class Pipeline:
    name: str
    config_cls: type[BaseModel]
    context_cls: type[BaseModel]
    media: str = "file"

    #####################################################
    #####################################################
    def __init__(self, registry: Registry | None = None) -> None:
        self._registry = registry or default_registry

    #####################################################
    #####################################################
    def ref(self, node_name: str) -> Node:
        return Call(self._registry, f"{self.name}.{node_name}")

    #####################################################
    #####################################################
    def engine_operation(self, operation_name: str) -> Node:
        return EngineOperationStep(self._registry, f"{self.name}.engine", operation_name)

    #####################################################
    #####################################################
    async def run(self, operation: str, **kwargs):
        ctx = self.context_cls(**kwargs)
        return await self._registry.get(f"{self.name}.{operation}")(ctx)

    #####################################################
    #####################################################
    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)

        node_fns = [attr for attr in vars(cls).values() if callable(attr) and hasattr(attr, "_node_name")]
        if not node_fns:
            return
        instance = cls()

        params_types: set[type] = set()

        for fn in node_fns:
            placeholders = {pname: None for pname in _signature_fields(fn)}
            default_registry.register(f"{cls.name}.{fn._node_name}", getattr(instance, fn.__name__)(**placeholders))
            if not fn._node_public:
                continue

            input_model = _input_model(fn._node_name, fn, cls.config_cls)
            params_types.add(input_model)
            setattr(cls, fn.__name__, _public_caller(fn._node_name, input_model, _out_adapter(fn)))
            default_registry.register(f"cli.{cls.name}.{fn._node_name}", OpCommand(cls, fn.__name__, fn._node_name, input_model))
            default_registry.register(f"api.{cls.name}.{fn._node_name}", OpEndpoint(cls, fn.__name__, fn._node_name, input_model))
            default_registry.register(f"web.{cls.name}.{fn._node_name}", page_for(cls, fn, fn._node_name, input_model, default_registry))

        if params_types:
            annotation = params_types.pop() if len(params_types) == 1 else Union[tuple(params_types)]
            mixin = create_model(f"{cls.__name__}Params", __config__=ConfigDict(arbitrary_types_allowed=True), params=(annotation | None, None))
            cls.extend_context(mixin)
            default_registry.register(f"api.{cls.name}.graph", GraphEndpoint(cls.name, default_registry))
            default_registry.register(f"web.{cls.name}.graph", DiagramPage(cls.name, default_registry))

    #####################################################
    #####################################################
    @classmethod
    def extend_config(cls, mixin: type[BaseModel]) -> None:
        extend_model(cls.config_cls, mixin)

    #####################################################
    #####################################################
    @classmethod
    def extend_context(cls, mixin: type[BaseModel]) -> None:
        extend_model(cls.context_cls, mixin)
