import io
import os
import tempfile
from contextlib import suppress
from typing import IO, Annotated, Any, ClassVar, Union
from urllib.parse import urlsplit
from urllib.request import url2pathname

from pydantic import BaseModel, ConfigDict, PrivateAttr

from ...core.core import Node, Registry
from .introspect import Role, param


###########################################################################################################
###########################################################################################################
def _is_local(path: str | os.PathLike[str]) -> bool:
    return urlsplit(os.fspath(path)).scheme not in ("http", "https")


###########################################################################################################
###########################################################################################################
class InputData(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw_path: str | os.PathLike[str] | None = None
    raw_stream: Any = None
    raw_bytes: bytes | None = None

    _cached_path: str | None = PrivateAttr(default=None)
    _cached_stream: Any = PrivateAttr(default=None)
    _temps: list[str] = PrivateAttr(default_factory=list)

    #####################################################
    #####################################################
    def temp(self, suffix: str = "") -> str:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        self._temps.append(tmp_path)
        return tmp_path

    #####################################################
    #####################################################
    def cleanup(self) -> None:
        for tmp_path in self._temps:
            with suppress(OSError):
                os.remove(tmp_path)
        self._temps.clear()

    #####################################################
    #####################################################
    @property
    def size(self) -> int:
        if self.raw_bytes is not None:
            return len(self.raw_bytes)
        if self.raw_path is not None and _is_local(self.raw_path):
            return os.path.getsize(self.raw_path)
        if self.raw_stream is not None:
            return self.raw_stream.seek(0, os.SEEK_END)
        raise ValueError(f"{type(self).__name__} has no local path, stream, or bytes to size")

    #####################################################
    #####################################################
    @property
    def bytes_(self) -> bytes:
        if self.raw_bytes is not None:
            return self.raw_bytes
        if self.raw_path is not None and _is_local(self.raw_path):
            with open(self.raw_path, "rb") as f:
                return f.read()
        if self.raw_stream is not None:
            self.raw_stream.seek(0)
            return self.raw_stream.read()
        if self.raw_path is not None:
            with open(self.raw_path, "rb") as f:
                return f.read()
        raise ValueError(f"{type(self).__name__} has no path, stream, or bytes set")

    #####################################################
    #####################################################
    @bytes_.setter
    def bytes_(self, value: bytes) -> None:
        self._reset(raw_bytes=value)

    @property
    def path(self) -> str:
        if self.raw_path is not None:
            return os.fspath(self.raw_path)
        if self._cached_path is None:
            self._cached_path = self.temp()
            with open(self._cached_path, "wb") as f:
                f.write(self.bytes_)
        return self._cached_path

    #####################################################
    #####################################################
    @path.setter
    def path(self, value: str | os.PathLike[str]) -> None:
        self._reset(raw_path=value)

    #####################################################
    #####################################################
    @property
    def stream(self) -> IO[bytes]:
        if self.raw_stream is not None:
            self.raw_stream.seek(0)
            return self.raw_stream
        if self._cached_stream is None:
            self._cached_stream = io.BytesIO(self.bytes_)
        self._cached_stream.seek(0)
        return self._cached_stream

    #####################################################
    #####################################################
    @stream.setter
    def stream(self, value: IO[bytes]) -> None:
        self._reset(raw_stream=value)

    #####################################################
    #####################################################
    def _reset(self, *, raw_path=None, raw_stream=None, raw_bytes=None) -> None:
        self.raw_path, self.raw_stream, self.raw_bytes = raw_path, raw_stream, raw_bytes
        self._cached_path = None
        self._cached_stream = None


###########################################################################################################
###########################################################################################################
class InputResolver(Node):
    accepts: type

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "accepts" not in vars(cls):
            raise TypeError(f"{cls.__name__} must declare 'accepts' (the type of input it resolves)")


###########################################################################################################
###########################################################################################################
class InputPathResolver(InputResolver):
    accepts = str

    async def __call__(self, ctx):
        value = param(ctx, "input")
        parts = urlsplit(value)
        ctx.input = [InputData(raw_path=url2pathname(parts.path) if parts.scheme == "file" else value)]
        return ctx


###########################################################################################################
###########################################################################################################
class InputBytesResolver(InputResolver):
    accepts = bytes

    async def __call__(self, ctx):
        ctx.input = [InputData(raw_bytes=param(ctx, "input"))]
        return ctx


###########################################################################################################
###########################################################################################################
class InputStreamResolver(InputResolver):
    accepts = Any

    async def __call__(self, ctx):
        ctx.input = [InputData(raw_stream=param(ctx, "input"))]
        return ctx


###########################################################################################################
###########################################################################################################
def input_type(*resolvers: type[InputResolver]) -> type:
    types = {r.accepts for r in resolvers}
    return Annotated[types.pop() if len(types) == 1 else Union[tuple(types)], Role("input")]


###########################################################################################################
###########################################################################################################
def input_list_type(*resolvers: type[InputResolver]) -> type:
    types = {r.accepts for r in resolvers}
    return Annotated[list[types.pop() if len(types) == 1 else Union[tuple(types)]], Role("inputs")]


###########################################################################################################
###########################################################################################################
class _ListItemParams(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: Any
    roles: ClassVar[dict[str, str]] = {"input": "value"}


class InputListResolver(Node):
    """Resolves each item of an `inputs` list through the same per-pipeline `resolve`
    branch a single `input` goes through, so a plugin-registered scheme (e.g. `s3://`)
    works for every item without any list-specific plugin code."""

    def __init__(self, registry: Registry, branch_name: str) -> None:
        self.registry = registry
        self.branch_name = branch_name

    async def __call__(self, ctx):
        resolve = self.registry.get(self.branch_name)
        resolved: list[InputData] = []
        for value in param(ctx, "inputs"):
            if isinstance(value, bytes):
                resolved.append(InputData(raw_bytes=value))
            elif hasattr(value, "read"):
                resolved.append(InputData(raw_stream=value))
            else:
                item_ctx = ctx.model_copy(update={"params": _ListItemParams(value=value)})
                item_ctx = await resolve(item_ctx)
                resolved.append(item_ctx.input[0])
        ctx.input = resolved
        return ctx


###########################################################################################################
###########################################################################################################
def scheme_of(ctx) -> str:
    value = param(ctx, "input")
    if value is None:
        raise AttributeError("input resolve requires the calling operation to declare a parameter annotated with input_type(...)")
    if isinstance(value, bytes):
        return "bytes"
    if hasattr(value, "read"):
        return "stream"
    scheme = urlsplit(value).scheme
    return scheme if scheme and scheme != "file" else "default"
