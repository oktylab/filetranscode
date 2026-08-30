import os
import shutil
from typing import Annotated, Union
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ...core.core import Node
from .input_resolve import InputData
from .introspect import Role, param


###########################################################################################################
###########################################################################################################
class AsBytes:
    pass


class AsStream:
    pass


###########################################################################################################
###########################################################################################################
class OutputData(InputData):
    @property
    def path(self) -> str:
        if self.raw_path is None and self.raw_stream is None and self.raw_bytes is None:
            self.raw_path = self.temp()
        return super().path

    @path.setter
    def path(self, value: str | os.PathLike[str]) -> None:
        self._reset(raw_path=value)


###########################################################################################################
###########################################################################################################
class OutputResolver(Node):
    accepts: type

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "accepts" not in vars(cls):
            raise TypeError(f"{cls.__name__} must declare 'accepts' (the type of output destination it delivers to)")


###########################################################################################################
###########################################################################################################
class OutputPathResolver(OutputResolver):
    accepts = str

    async def __call__(self, ctx):
        value = param(ctx, "output")
        parts = urlsplit(value)
        destination = url2pathname(parts.path) if parts.scheme == "file" else value
        os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
        shutil.move(ctx.output[0].path, destination)
        ctx.output[0].path = destination
        ctx.out = destination
        return ctx


###########################################################################################################
###########################################################################################################
class OutputBytesResolver(OutputResolver):
    accepts = AsBytes

    async def __call__(self, ctx):
        ctx.out = ctx.output[0].bytes_
        return ctx


###########################################################################################################
###########################################################################################################
class OutputStreamResolver(OutputResolver):
    accepts = AsStream

    async def __call__(self, ctx):
        ctx.out = ctx.output[0].stream
        return ctx


###########################################################################################################
###########################################################################################################
class OutputEach(Node):
    def __init__(self, output: Node) -> None:
        self.output = output

    async def __call__(self, ctx):
        destination = param(ctx, "output")
        role_param = type(ctx.params).roles.get("output")
        params = ctx.params
        items = list(ctx.output)
        delivered = []
        for index, data in enumerate(items):
            ctx.output = [data]
            if isinstance(destination, str):
                ctx.params = params.model_copy(update={role_param: _indexed(destination, index)})
            ctx = await self.output(ctx)
            delivered.append(ctx.out)
        ctx.params = params
        ctx.output = items
        ctx.out = delivered
        return ctx


###########################################################################################################
###########################################################################################################
def _indexed(destination: str, index: int) -> str:
    if "{index" in destination:
        return destination.format(index=index)
    root, extension = os.path.splitext(destination)
    return f"{root}_{index:03d}{extension}"


###########################################################################################################
###########################################################################################################
def output_type(*resolvers: type[OutputResolver]) -> type:
    types = {r.accepts for r in resolvers}
    return Annotated[types.pop() if len(types) == 1 else Union[tuple(types)], Role("output")]


###########################################################################################################
###########################################################################################################
def output_scheme_of(ctx) -> str:
    value = param(ctx, "output")
    if value is None:
        raise AttributeError("output requires the calling operation to declare a parameter annotated with output_type(...)")
    if isinstance(value, AsBytes):
        return "bytes"
    if isinstance(value, AsStream):
        return "stream"
    scheme = urlsplit(value).scheme
    return scheme if scheme and scheme != "file" else "default"
