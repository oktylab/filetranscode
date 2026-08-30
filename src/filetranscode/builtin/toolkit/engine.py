from ...core.core import Node, Registry
from .introspect import param
from ...exceptions import EngineError


###########################################################################################################
###########################################################################################################
def operation(fn):
    fn._is_operation = True
    return fn


###########################################################################################################
###########################################################################################################
class Engine:
    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.operations():
            raise TypeError(f"{cls.__name__} defines no @operation methods")

    @classmethod
    def operations(cls) -> list[str]:
        seen: dict[str, bool] = {}
        for klass in cls.__mro__:
            for name, attr in vars(klass).items():
                if callable(attr) and getattr(attr, "_is_operation", False):
                    seen[name] = True
        return sorted(seen)


###########################################################################################################
###########################################################################################################
class EngineOperationStep(Node):
    def __init__(self, registry: Registry, prefix: str, operation_name: str) -> None:
        self._registry = registry
        self._prefix = prefix
        self._operation_name = operation_name

    async def __call__(self, ctx):
        name = self._engine_name(ctx)
        engine = self._registry.get(f"{self._prefix}.{name}")
        operation = getattr(engine, self._operation_name, None)
        if operation is None:
            raise EngineError(f"engine {name!r} does not support {self._operation_name!r}, only: {type(engine).operations()}")
        return await operation(ctx)

    def _engine_name(self, ctx) -> str:
        roles = getattr(type(ctx.params), "roles", {}) if getattr(ctx, "params", None) is not None else {}
        if "engine" in roles:
            return getattr(ctx.params, roles["engine"])
        config = param(ctx, "config")
        return getattr(config, "engine", None) or ""


###########################################################################################################
###########################################################################################################
def probing(ctx) -> tuple[list, list]:
    return (ctx.input if ctx.probe == "before" else ctx.output), getattr(ctx.metadata, ctx.probe)


###########################################################################################################
###########################################################################################################
def validate_engine(registry: Registry, prefix: str, name: str) -> str:
    available = [n.removeprefix(f"{prefix}.") for n in registry.names(f"{prefix}.")]
    if name not in available:
        raise ValueError(f"unknown engine {name!r} for {prefix!r}, available: {available}")
    return name
