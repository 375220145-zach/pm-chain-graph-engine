"""Scheduler: topological sort + wave grouping.

Takes a validated Graph and produces an execution plan:
1. Topological sort: linear ordering that respects all dependencies
2. Wave grouping: group nodes into "waves" where all nodes in a wave
   can run in parallel (no dependencies between them)

Example:
    A → B, A → C, B → D, C → D
    Wave 0: [A]       (no unfinished dependencies)
    Wave 1: [B, C]    (A finished, B and C can run together)
    Wave 2: [D]       (B and C both finished)
"""

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from engine.graph_loader import Graph


@dataclass
class ExecutionPlan:
    """The execution plan produced by the scheduler.

    waves: list of lists — each inner list is a wave of node IDs
           that can run in parallel.
    sorted_order: flat topological order of all node IDs.
    """

    waves: list[list[str]] = field(default_factory=list)
    sorted_order: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        lines = [f"ExecutionPlan ({len(self.waves)} waves):"]
        for i, wave in enumerate(self.waves):
            lines.append(f"  Wave {i}: {wave}")
        return "\n".join(lines)


class Scheduler:
    """Produces an ExecutionPlan from a validated Graph.

    Usage:
        scheduler = Scheduler()
        plan = scheduler.plan(graph)
        print(plan)  # see the wave structure
    """

    def plan(self, graph: Graph) -> ExecutionPlan:
        """Create an execution plan from a graph.

        Args:
            graph: A validated Graph from GraphLoader.

        Returns:
            ExecutionPlan with waves and sorted order.
        """
        G = graph.to_networkx()

        # Handle empty graph
        if len(G.nodes) == 0:
            return ExecutionPlan(waves=[], sorted_order=[])

        # Topological sort: flat list respecting all dependencies
        sorted_ids = list(nx.topological_sort(G))

        # Group into waves using topological generations
        # nx.topological_generations() groups nodes by their "layer"
        # — all nodes in one layer have zero indegree from remaining nodes
        waves = []
        for generation in nx.topological_generations(G):
            waves.append(sorted(generation))

        return ExecutionPlan(waves=waves, sorted_order=sorted_ids)
