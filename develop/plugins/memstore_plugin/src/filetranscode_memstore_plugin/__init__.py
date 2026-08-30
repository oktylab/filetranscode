from urllib.parse import urlsplit

from filetranscode import Node, param
from filetranscode.builtin.toolkit.cli import ModelCommand
from pydantic import BaseModel
from filetranscode.builtin.toolkit.input_resolve import InputData, InputResolver
from filetranscode.builtin.toolkit.output_resolve import OutputResolver
from filetranscode.registry import registry

STORE: dict[str, bytes] = {}


def _key(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}"


class MemInputResolver(InputResolver):
    accepts = str

    async def __call__(self, ctx):
        ctx.input = [InputData(raw_bytes=STORE[_key(param(ctx, "input"))])]
        return ctx


class MemOutputResolver(OutputResolver):
    accepts = str

    async def __call__(self, ctx):
        url = param(ctx, "output")
        STORE[_key(url)] = ctx.output[0].bytes_
        ctx.out = url
        return ctx


for pipeline in ("video", "photo"):
    registry.get(f"{pipeline}.resolve").add("mem", MemInputResolver())
    registry.get(f"{pipeline}.output").add("mem", MemOutputResolver())


class MemList(Node):
    help = "list objects held by the in-memory store"

    async def __call__(self, ctx):
        ctx.out = "\n".join(f"mem://{key} ({len(data)} bytes)" for key, data in sorted(STORE.items())) or "(empty)"
        return ctx


registry.register("cli.mem.ls", MemList())


class MemPut(BaseModel):
    key: str
    file: str


class MemGet(BaseModel):
    key: str
    output: str


async def _put(params: MemPut) -> str:
    STORE[params.key] = open(params.file, "rb").read()
    return f"mem://{params.key} ({len(STORE[params.key])} bytes)"


async def _get(params: MemGet) -> str:
    with open(params.output, "wb") as handle:
        handle.write(STORE[params.key])
    return params.output


registry.register("cli.mem.put", ModelCommand(MemPut, _put, positional=("key", "file"), prog="filetranscode mem put", help="store a file under mem://KEY"))
registry.register("cli.mem.get", ModelCommand(MemGet, _get, positional=("key",), prog="filetranscode mem get", help="write mem://KEY to --output PATH"))


class MemPage(Node):
    help = "browse the in-memory store"

    async def __call__(self, ctx):
        rows = "".join(f"<tr><td>mem://{key}</td><td>{len(data)}</td></tr>" for key, data in sorted(STORE.items()))
        ctx.html = f"<h2>mem store</h2><table><tr><th>url</th><th>bytes</th></tr>{rows or '<tr><td colspan=2>(empty)</td></tr>'}</table>"
        return ctx


registry.register("web.mem.store", MemPage())
