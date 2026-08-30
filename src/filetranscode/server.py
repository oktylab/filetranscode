from collections import OrderedDict
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile

from .builtin.toolkit.web import STATIC, WebContext, layout
from .core.errors import NodeNotFound, NoBranchMatched
from .exceptions import EngineError, ProbeError, UnsatisfiableError
from .registry import registry


###########################################################################################################
###########################################################################################################
def _accumulate(values: dict[str, str], key: str, value: str) -> None:
    text = value.strip()
    if not text:
        values.setdefault(key, "")
    else:
        values[key] = f"{values[key]} {text}".strip() if values.get(key) else text


###########################################################################################################
###########################################################################################################
def create_app() -> FastAPI:
    app = FastAPI(title="filetranscode", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    parts_store: OrderedDict[str, bytes] = OrderedDict()
    trace_store: OrderedDict[str, dict] = OrderedDict()

    def stash_trace(ctx: WebContext) -> None:
        if ctx.trace is None:
            return
        trace_id = uuid4().hex
        trace_store[trace_id] = ctx.trace
        ctx.headers["X-Trace"] = f"/api/traces/{trace_id}"
        while len(trace_store) > 64:
            trace_store.popitem(last=False)

    @app.get("/api/traces/{trace_id}")
    async def trace(trace_id: str) -> Response:
        data = trace_store.get(trace_id)
        if data is None:
            return Response("unknown trace", status_code=404, media_type="text/plain")
        return JSONResponse(data)

    @app.get("/api/parts/{part_id}")
    async def part(part_id: str) -> Response:
        data = parts_store.get(part_id)
        if data is None:
            return Response("unknown part", status_code=404, media_type="text/plain")
        return Response(data)

    ############################################################
    ############################################################
    @app.get("/")
    async def index() -> Response:
        groups: dict[str, list[str]] = {}
        for name in registry.names("web."):
            _, group, page = name.split(".", 2)
            groups.setdefault(group, []).append(page)
        if not groups:
            return Response("no web pages registered", media_type="text/plain")
        group = max(groups, key=lambda name: len(groups[name]))
        return RedirectResponse(f"/{group}/{sorted(groups[group])[0]}")

    ############################################################
    ############################################################
    @app.get("/{group}/{page}", response_class=HTMLResponse)
    async def render_page(group: str, page: str) -> HTMLResponse:
        try:
            node = registry.get(f"web.{group}.{page}")
        except NodeNotFound:
            return HTMLResponse(layout(registry, group, page, f"<h2>unknown page: {group}/{page}</h2>"), status_code=404)
        ctx = await node(WebContext(group=group))
        return HTMLResponse(layout(registry, group, page, ctx.html or ""))

    ############################################################
    ############################################################
    @app.get("/api/{group}/{name}")
    @app.post("/api/{group}/{name}")
    async def api(group: str, name: str, request: Request) -> Response:
        try:
            node = registry.get(f"api.{group}.{name}")
        except NodeNotFound:
            return Response(f"unknown endpoint: {group}/{name}", status_code=404, media_type="text/plain")
        ctx = WebContext(group=group)
        for key, value in request.query_params.multi_items():
            _accumulate(ctx.values, key, str(value))
        if request.method == "POST":
            form = await request.form()
            for key, item in form.multi_items():
                if isinstance(item, UploadFile):
                    if item.filename:
                        ctx.files.setdefault(key, []).append(await item.read())
                else:
                    _accumulate(ctx.values, key, str(item))
        try:
            ctx = await node(ctx)
        except (EngineError, ProbeError, UnsatisfiableError, NodeNotFound, NoBranchMatched, ValueError, KeyError, FileNotFoundError) as error:
            stash_trace(ctx)
            detail = f"unknown key: {error.args[0]}" if isinstance(error, KeyError) and error.args else str(error)
            return Response(detail, status_code=422, media_type="text/plain", headers=ctx.headers)
        stash_trace(ctx)
        if ctx.parts is not None and ctx.values.get("parts"):
            urls = []
            for data in ctx.parts:
                part_id = uuid4().hex
                parts_store[part_id] = data
                urls.append(f"/api/parts/{part_id}")
            while len(parts_store) > 64:
                parts_store.popitem(last=False)
            return JSONResponse({"parts": urls}, headers=ctx.headers)
        if ctx.body is not None:
            return Response(ctx.body, media_type=ctx.content_type, headers=ctx.headers)
        return JSONResponse(ctx.result, headers=ctx.headers)

    return app
