"""Graph loader: reads and validates graph JSON files.

A graph JSON file defines a DAG (Directed Acyclic Graph) with:
- nodes: tasks to execute (each has id, name, type, skill_name, config)
- edges: dependencies between nodes (from -> to)

The loader validates:
- JSON syntax
- Required fields on every node
- All edge references point to existing nodes
- No circular dependencies (graph must be a DAG)
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx


@dataclass
class Node:
    """A single node in the graph — one step in the workflow.

    id: unique identifier within the graph (e.g. "mkt", "comp")
    name: human-readable label (e.g. "市场调研")
    type: node type — "skill" (Phase 1), "gate" (Phase 2), "human" (Phase 3)
    skill_name: which skill to invoke (e.g. "market-research")
    config: node-specific settings (output dir, timeout, retries, human_collab)
    """

    id: str
    name: str
    type: str = "skill"
    skill_name: str = "mock"
    config: dict = field(default_factory=dict)


@dataclass
class Edge:
    """A directed edge: from_node must finish before to_node can start."""

    from_node: str
    to_node: str


@dataclass
class Graph:
    """A validated graph ready for scheduling.

    name: graph name (for logging)
    description: what this graph is for
    nodes: list of Node objects
    edges: list of Edge objects
    """

    name: str
    description: str
    nodes: list[Node]
    edges: list[Edge]

    def to_networkx(self) -> nx.DiGraph:
        """Convert this graph to a networkx DiGraph for scheduling."""
        G = nx.DiGraph()
        G.add_nodes_from([(n.id, {"node": n}) for n in self.nodes])
        G.add_edges_from([(e.from_node, e.to_node) for e in self.edges])
        return G


class GraphLoader:
    """Reads a graph JSON file and produces a validated Graph object.

    Usage:
        loader = GraphLoader()
        graph = loader.load("graphs/my-workflow.json")
    """

    REQUIRED_NODE_FIELDS = {"id", "name"}
    VALID_NODE_TYPES = {"skill", "gate", "human"}

    def load(self, filepath: str) -> Graph:
        """Load and validate a graph JSON file.

        Args:
            filepath: Path to the graph JSON file.

        Returns:
            A validated Graph object.

        Raises:
            FileNotFoundError: File doesn't exist.
            ValueError: Invalid graph structure (bad JSON, missing fields, cycles).
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"找不到图文件: {filepath}")

        raw = json.loads(path.read_text(encoding="utf-8"))

        graph = self._parse(raw, filepath)
        self._validate(graph)
        return graph

    def _parse(self, raw: dict, filepath: str) -> Graph:
        """Parse raw JSON dict into Graph object."""
        try:
            name = raw["name"]
            description = raw.get("description", "")
        except KeyError as e:
            raise ValueError(f"图文件缺少顶层字段: {e} — 文件: {filepath}")

        nodes = []
        for i, n in enumerate(raw.get("nodes", [])):
            try:
                nodes.append(
                    Node(
                        id=n["id"],
                        name=n["name"],
                        type=n.get("type", "skill"),
                        skill_name=n.get("skill_name", "mock"),
                        config=n.get("config", {}),
                    )
                )
            except KeyError as e:
                raise ValueError(
                    f"节点 #{i} 缺少必填字段 {e} — 文件: {filepath}"
                )

        edges = []
        for i, e in enumerate(raw.get("edges", [])):
            try:
                edges.append(Edge(from_node=e["from"], to_node=e["to"]))
            except KeyError as err:
                raise ValueError(
                    f"边 #{i} 缺少必填字段 {err} — 文件: {filepath}"
                )

        return Graph(name=name, description=description, nodes=nodes, edges=edges)

    def _validate(self, graph: Graph) -> None:
        """Run all validation checks. Raises ValueError on any failure."""
        self._validate_node_ids_unique(graph)
        self._validate_node_types(graph)
        self._validate_edge_references(graph)
        self._validate_no_cycles(graph)

    def _validate_node_ids_unique(self, graph: Graph) -> None:
        ids = [n.id for n in graph.nodes]
        seen = set()
        for nid in ids:
            if nid in seen:
                raise ValueError(f"节点 ID 重复: '{nid}' — 每个节点 ID 必须唯一")
            seen.add(nid)

    def _validate_node_types(self, graph: Graph) -> None:
        for node in graph.nodes:
            if node.type not in self.VALID_NODE_TYPES:
                raise ValueError(
                    f"节点 '{node.id}' 类型无效: '{node.type}' — "
                    f"有效类型: {', '.join(sorted(self.VALID_NODE_TYPES))}"
                )

    def _validate_edge_references(self, graph: Graph) -> None:
        node_ids = {n.id for n in graph.nodes}
        for edge in graph.edges:
            if edge.from_node not in node_ids:
                raise ValueError(
                    f"边引用了不存在的来源节点: '{edge.from_node}' — "
                    f"有效节点: {sorted(node_ids)}"
                )
            if edge.to_node not in node_ids:
                raise ValueError(
                    f"边引用了不存在的目标节点: '{edge.to_node}' — "
                    f"有效节点: {sorted(node_ids)}"
                )

    def _validate_no_cycles(self, graph: Graph) -> None:
        """Build a networkx DiGraph and check for cycles."""
        G = nx.DiGraph()
        G.add_nodes_from([n.id for n in graph.nodes])
        G.add_edges_from([(e.from_node, e.to_node) for e in graph.edges])

        if not nx.is_directed_acyclic_graph(G):
            cycles = list(nx.simple_cycles(G))
            cycle_strs = [" → ".join(c) + " → " + c[0] for c in cycles]
            raise ValueError(
                f"图中存在环路（死循环）: {'; '.join(cycle_strs)}"
            )

