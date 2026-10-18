"""A small, explicit calculation dependency graph.

The simulation engine is written as a set of *nodes*. Each node declares the
line items it reads (``deps``), the line items it produces (``outputs``), and a
plain-language formula for each output. The graph is topologically sorted and
evaluated once per scenario run. Because every screen reads results produced
by this single graph, there is exactly one authoritative calculation layer.

The same metadata powers the dependency viewer and the "show formula"
inspector in the user interface, so documentation cannot drift from the code
that actually runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class LineItem:
    key: str
    label: str
    formula: str
    unit: str = "currency"
    node: str = ""
    inputs: list[str] = field(default_factory=list)  # assumption paths read
    nature: str = "context"  # revenue | expense | context | balance


@dataclass
class Node:
    name: str
    func: Callable
    deps: list[str]
    outputs: dict[str, LineItem]
    description: str


class GraphError(RuntimeError):
    pass


class CalcGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.items: dict[str, LineItem] = {}

    def node(self, name: str, deps: list[str], outputs: list[LineItem], description: str = ""):
        def deco(func: Callable) -> Callable:
            if name in self.nodes:
                raise GraphError(f"Duplicate node {name}")
            out = {}
            for li in outputs:
                if li.key in self.items:
                    raise GraphError(f"Line item {li.key} produced twice ({self.items[li.key].node}, {name})")
                li.node = name
                out[li.key] = li
                self.items[li.key] = li
            self.nodes[name] = Node(name, func, deps, out, description)
            return func

        return deco

    def producer(self, item: str) -> Node:
        return self.nodes[self.items[item].node]

    def order(self) -> list[Node]:
        """Topological order; raises GraphError on missing inputs or cycles."""
        produced_by = {k: li.node for k, li in self.items.items()}
        for n in self.nodes.values():
            for d in n.deps:
                if d not in produced_by:
                    raise GraphError(f"Node {n.name} depends on unknown line item {d}")
        visited: dict[str, int] = {}
        result: list[Node] = []

        def visit(nname: str, stack: list[str]) -> None:
            state = visited.get(nname, 0)
            if state == 2:
                return
            if state == 1:
                raise GraphError("Cycle: " + " → ".join(stack + [nname]))
            visited[nname] = 1
            for d in self.nodes[nname].deps:
                visit(produced_by[d], stack + [nname])
            visited[nname] = 2
            result.append(self.nodes[nname])

        for nname in self.nodes:
            visit(nname, [])
        return result

    def upstream(self, item: str) -> list[str]:
        """Line items an item depends on (direct)."""
        return list(self.producer(item).deps)

    def downstream(self, item: str) -> list[str]:
        """Line items whose producing node reads ``item`` (direct)."""
        out = []
        for n in self.nodes.values():
            if item in n.deps:
                out.extend(n.outputs.keys())
        return out

    def evaluate(self, ctx) -> dict:
        values: dict = {}
        for n in self.order():
            produced = n.func(ctx, values)
            missing = set(n.outputs) - set(produced)
            if missing:
                raise GraphError(f"Node {n.name} did not produce {sorted(missing)}")
            values.update(produced)
        return values
