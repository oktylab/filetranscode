from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from .errors import NodeNotFound, NoBranchMatched
from .trace import traced

C = TypeVar("C")


#############################################################
#############################################################
@dataclass
class NodeDescription:
    kind: str
    children: list[NodeDescription] | dict[str, NodeDescription] | None = None


#############################################################
#############################################################
class Node(ABC, Generic[C]):
    @abstractmethod
    async def __call__(self, ctx: C) -> C: ...

    def describe(self) -> NodeDescription:
        return NodeDescription(kind=type(self).__name__)


#############################################################
#############################################################
class Noop(Node[C]):
    async def __call__(self, ctx: C) -> C:
        return ctx


#############################################################
#############################################################
class Set(Node[C]):
    def __init__(self, **values: object) -> None:
        self.values = values

    async def __call__(self, ctx: C) -> C:
        for name, value in self.values.items():
            setattr(ctx, name, value)
        return ctx

    def describe(self) -> NodeDescription:
        return NodeDescription(kind=f"Set({', '.join(self.values)})")


#############################################################
#############################################################
class Sequence(Node[C]):
    def __init__(self, *children: Node[C]) -> None:
        self.children = children

    async def __call__(self, ctx: C) -> C:
        for child in self.children:
            ctx = await traced(child, ctx)
        return ctx

    def describe(self) -> NodeDescription:
        return NodeDescription(kind="Sequence", children=[c.describe() for c in self.children])


#############################################################
#############################################################
class Parallel(Node[C]):
    def __init__(self, *children: Node[C], merge: Callable[[C, list[C]], C]) -> None:
        self.children = children
        self.merge = merge

    async def __call__(self, ctx: C) -> C:
        results = await asyncio.gather(*(traced(child, ctx) for child in self.children))
        return self.merge(ctx, list(results))

    def describe(self) -> NodeDescription:
        return NodeDescription(kind="Parallel", children=[c.describe() for c in self.children])


#############################################################
#############################################################
class Branch(Node[C]):
    def __init__(self, selector: Callable[[C], str], **children: Node[C]) -> None:
        self.selector = selector
        self.children = children

    async def __call__(self, ctx: C) -> C:
        key = self.selector(ctx)
        child = self.children.get(key)
        if child is None:
            raise NoBranchMatched(key, tuple(self.children))
        return await traced(child, ctx, label=key)

    def add(self, name: str, node: Node[C]) -> None:
        self.children[name] = node

    def describe(self) -> NodeDescription:
        return NodeDescription(
            kind="Branch",
            children={name: child.describe() for name, child in self.children.items()},
        )


#############################################################
#############################################################
class Wrap(Node[C]):
    def __init__(self, node: Node[C], handler: Callable[[Node[C], C], Awaitable[C]]) -> None:
        self.node = node
        self.handler = handler

    async def __call__(self, ctx: C) -> C:
        return await self.handler(self.node, ctx)

    def describe(self) -> NodeDescription:
        return NodeDescription(kind="Wrap", children=[self.node.describe()])


#############################################################
#############################################################
class Call(Node[C]):
    def __init__(self, registry: Registry[C], name: str) -> None:
        self.registry = registry
        self.name = name

    async def __call__(self, ctx: C) -> C:
        return await traced(self.registry.get(self.name), ctx, label=self.name)

    def describe(self) -> NodeDescription:
        return NodeDescription(kind=f"Call({self.name})")


#############################################################
#############################################################
class Registry(Generic[C]):
    def __init__(self) -> None:
        self._nodes: dict[str, Node[C]] = {}

    def register(self, name: str, node: Node[C]) -> None:
        self._nodes[name] = node

    def get(self, name: str) -> Node[C]:
        node = self._nodes.get(name)
        if node is None:
            raise NodeNotFound(name)
        return node

    def names(self, prefix: str = "") -> list[str]:
        return sorted(name for name in self._nodes if name.startswith(prefix))
