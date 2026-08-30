from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Iterator


#############################################################
#############################################################
@dataclass
class Step:
    kind: str
    label: str = ""
    took_ms: float = 0.0
    state: dict[str, Any] = field(default_factory=dict)
    changed: list[str] = field(default_factory=list)
    error: str | None = None
    children: list[Step] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "took_ms": round(self.took_ms, 2),
            "state": self.state,
            "changed": self.changed,
            "error": self.error,
            "children": [child.to_dict() for child in self.children],
        }


#############################################################
#############################################################
@dataclass
class Trace:
    snapshot: Callable[[Any], dict[str, Any]]
    root: Step = field(default_factory=lambda: Step(kind="run"))


ACTIVE: ContextVar[Trace | None] = ContextVar("filetranscode_trace", default=None)
PARENT: ContextVar[Step | None] = ContextVar("filetranscode_trace_parent", default=None)


#############################################################
#############################################################
def brief(value: Any, depth: int = 0, limit: int = 8) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if depth >= limit:
        return f"<{type(value).__name__}>" if isinstance(value, (dict, list, tuple, set)) else repr(value)[:120]
    if isinstance(value, dict):
        return {str(key): brief(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [brief(item, depth + 1) for item in value]
    if hasattr(value, "model_dump"):
        try:
            return brief(value.model_dump(), depth + 1)
        except (TypeError, ValueError):
            return repr(value)[:120]
    if hasattr(value, "getvalue"):
        try:
            return f"<stream {len(value.getvalue())} bytes>"
        except (TypeError, ValueError):
            return repr(value)[:120]
    return repr(value)[:120]


def default_snapshot(ctx: Any) -> dict[str, Any]:
    state = vars(ctx) if hasattr(ctx, "__dict__") else {}
    return {name: brief(value) for name, value in state.items()}


#############################################################
#############################################################
def diff_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        paths = []
        for key in before.keys() | after.keys():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths += diff_paths(before.get(key), after.get(key), path)
        return paths
    return [] if before == after else [prefix]


#############################################################
#############################################################
@contextmanager
def tracing(snapshot: Callable[[Any], dict[str, Any]] = default_snapshot) -> Iterator[Trace]:
    trace = Trace(snapshot=snapshot)
    active_token = ACTIVE.set(trace)
    parent_token = PARENT.set(trace.root)
    try:
        yield trace
    finally:
        ACTIVE.reset(active_token)
        PARENT.reset(parent_token)


#############################################################
#############################################################
async def traced(node: Any, ctx: Any, label: str = "") -> Any:
    trace = ACTIVE.get()
    if trace is None:
        return await node(ctx)
    parent = PARENT.get() or trace.root
    step = Step(kind=type(node).__name__, label=label)
    parent.children.append(step)
    token = PARENT.set(step)
    before = trace.snapshot(ctx)
    start = perf_counter()
    try:
        ctx = await node(ctx)
        return ctx
    except BaseException as error:
        step.error = f"{type(error).__name__}: {error}"
        raise
    finally:
        step.took_ms = (perf_counter() - start) * 1000
        step.state = trace.snapshot(ctx)
        step.changed = diff_paths(before, step.state)
        PARENT.reset(token)


#############################################################
#############################################################
@contextmanager
def span(kind: str, label: str = "") -> Iterator[None]:
    trace = ACTIVE.get()
    if trace is None:
        yield
        return
    parent = PARENT.get() or trace.root
    step = Step(kind=kind, label=label)
    parent.children.append(step)
    token = PARENT.set(step)
    start = perf_counter()
    try:
        yield
    finally:
        step.took_ms = (perf_counter() - start) * 1000
        PARENT.reset(token)
