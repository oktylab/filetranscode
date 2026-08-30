import asyncio
import sys

from pydantic import BaseModel

from .builtin.toolkit.cli import CliContext, ModelCommand, render
from .core.errors import NodeNotFound
from .registry import registry


###########################################################################################################
###########################################################################################################
class RegistryQuery(BaseModel):
    prefix: str = ""


async def _registry_names(params: RegistryQuery) -> list[str]:
    return registry.names(params.prefix)


registry.register("cli.registry.ls", ModelCommand(RegistryQuery, _registry_names, prog="filetranscode registry ls", help="list registered node names, optionally by --prefix"))


###########################################################################################################
###########################################################################################################
class ServerOptions(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False


async def _serve(params: ServerOptions) -> None:
    try:
        import uvicorn
        from .server import create_app
    except ImportError:
        raise RuntimeError("the web server needs the optional cli extra: pip install 'filetranscode[cli]'")
    print(f"serving on http://{params.host}:{params.port}" + (" (auto-reload)" if params.reload else ""))
    if params.reload:
        import os
        from pathlib import Path
        os.execv(sys.executable, [
            sys.executable, "-m", "uvicorn", "filetranscode.server:create_app", "--factory",
            "--host", params.host, "--port", str(params.port), "--log-level", "warning",
            "--reload", "--reload-dir", str(Path(__file__).parent),
        ])
    server = uvicorn.Server(uvicorn.Config(create_app(), host=params.host, port=params.port, log_level="warning"))
    await server.serve()


registry.register("cli.server.start", ModelCommand(ServerOptions, _serve, prog="filetranscode server start", help="run the web ui"))


###########################################################################################################
###########################################################################################################
def usage() -> str:
    groups: dict[str, list[tuple[str, str]]] = {}
    for name in registry.names("cli."):
        _, group, command = name.split(".", 2)
        groups.setdefault(group, []).append((command, getattr(registry.get(name), "help", "")))
    lines = ["usage: filetranscode <group> <command> [options]", "       filetranscode <group> <command> --help", ""]
    for group in sorted(groups):
        for command, help in sorted(groups[group]):
            lines.append(f"  {f'{group} {command}':22} {help}")
    return "\n".join(lines)


###########################################################################################################
###########################################################################################################
def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] in ("-h", "--help"):
        print(usage())
        return 0
    if len(arguments) < 2:
        print(usage(), file=sys.stderr)
        return 2
    try:
        command = registry.get(f"cli.{arguments[0]}.{arguments[1]}")
    except NodeNotFound:
        print(f"unknown command: {arguments[0]} {arguments[1]}\n\n{usage()}", file=sys.stderr)
        return 2
    ctx = CliContext(argv=arguments[2:])
    try:
        ctx = asyncio.run(command(ctx))
    except SystemExit as exit_:
        return int(exit_.code or 0)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if ctx.out is not None:
        print(render(ctx.out))
    return 0
