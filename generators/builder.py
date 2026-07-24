"""Graph builder: generates a graph JSON from category + scope rules.

Workflow:
  1. Start from a base template (pm-chain-full or pm-chain-quick)
  2. Apply category rules (add/remove nodes, adjust edges)
  3. Apply scope overrides (concept vs specific → human_collab)
  4. Output the final graph

Usage:
    from generators.builder import build_graph
    graph_json = build_graph(category="ai", scope="concept", mode="full")
    # graph_json is a dict ready to write to a .json file or feed to the engine
"""

import copy
import json
from pathlib import Path
from typing import Optional

from generators.category_rules import RULES, CategoryRules


# ─── Base templates ─────────────────────────────────────────────────

# These are the starting points. The generator loads them and applies
# category-specific transformations.

BASE_DIR = Path(__file__).parent.parent / "graphs"

BASE_TEMPLATES = {
    "full": "pm-chain-full.json",
    "quick": "pm-chain-quick.json",
}


def _load_base(mode: str) -> dict:
    """Load the base template graph JSON."""
    filename = BASE_TEMPLATES.get(mode)
    if not filename:
        raise ValueError(f"未知模式: '{mode}'。可选: full, quick")
    path = BASE_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"基础模板不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Transform functions ─────────────────────────────────────────────

def _apply_category_rules(graph: dict, category: str) -> dict:
    """Apply category-specific node/edge changes to the graph."""
    rules = RULES.get(category)
    if not rules:
        print(f"  ⚠ 品类 '{category}' 无专属规则，使用通用模板")
        return graph

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_ids = {n["id"] for n in nodes}

    # Add extra nodes
    for extra in rules.extra_nodes:
        if extra["id"] not in node_ids:
            nodes.append(copy.deepcopy(extra))
            node_ids.add(extra["id"])

    # Add extra edges (only if both nodes exist in the graph)
    existing_edges = {(e["from"], e["to"]) for e in edges}
    for extra in rules.extra_edges:
        key = (extra["from"], extra["to"])
        if key not in existing_edges:
            # Check both nodes exist (quick mode may have removed them)
            if extra["from"] in node_ids and extra["to"] in node_ids:
                edges.append(copy.deepcopy(extra))
                existing_edges.add(key)

    # Remove nodes (and edges referencing them)
    for remove_id in rules.remove_nodes:
        nodes[:] = [n for n in nodes if n["id"] != remove_id]
        edges[:] = [e for e in edges if e["from"] != remove_id and e["to"] != remove_id]

    # Apply human_collab overrides
    for node in nodes:
        if node["id"] in rules.human_overrides:
            node["config"]["human_collab"] = rules.human_overrides[node["id"]]

    # Append extra gate rules
    for gate_id, extra_rules in rules.extra_gate_rules.items():
        for node in nodes:
            if node["id"] == gate_id and "rules" in node.get("config", {}):
                node["config"]["rules"].extend(extra_rules)

    graph["nodes"] = nodes
    graph["edges"] = edges
    return graph


def _apply_scope_overrides(graph: dict, scope: str) -> dict:
    """Apply scope-based adjustments.

    concept (概念版): Product doesn't exist yet. Go/No-Go decisions
                     are critical → market and brainstorm set to pause.
    specific (具体版): Product exists. Most stages are auto/flag.
    """
    if scope == "concept":
        overrides = {
            "market": "pause",       # 概念验证→市场数据决定要不要做
            "brainstorm": "pause",   # 头脑风暴→需要方向决策
            "risk": "pause",         # 风险评估→概念阶段必须人工看
        }
    elif scope == "specific":
        overrides = {
            "market": "flag",        # 已有产品→市场数据可抽查
            "brainstorm": "auto",    # 优化方向→自动
            "risk": "flag",          # 风险评估→抽查
        }
    else:
        raise ValueError(f"未知维度: '{scope}'。可选: concept, specific")

    for node in graph.get("nodes", []):
        if node["id"] in overrides:
            # Only override if currently "auto" — don't downgrade
            # an already-set "pause" to "flag"
            current = node.get("config", {}).get("human_collab", "auto")
            target = overrides[node["id"]]
            # Keep the stronger setting
            priority = {"auto": 0, "flag": 1, "pause": 2}
            if priority.get(target, 0) > priority.get(current, 0):
                node["config"]["human_collab"] = target

    return graph


# ─── Public API ──────────────────────────────────────────────────────

def build_graph(
    category: str,
    scope: str = "concept",
    mode: str = "full",
    name: Optional[str] = None,
) -> dict:
    """Build a graph JSON for a given product category and scope.

    Args:
        category: One of ai, consumer_electronics, saas, physical_goods,
                  content, marketplace, service.
        scope: "concept" (产品未上线) or "specific" (产品已上线).
        mode: "full" (完整报告) or "quick" (快速摸底).
        name: Optional custom graph name. Auto-generated if not provided.

    Returns:
        A dict representing the complete graph JSON, ready to:
        - Write to a .json file
        - Feed directly to engine.graph_loader.GraphLoader

    Example:
        >>> graph = build_graph("ai", "concept", "full")
        >>> import json
        >>> json.dump(graph, open("my-graph.json", "w"), ensure_ascii=False, indent=2)
    """
    # Load base
    graph = _load_base(mode)

    # Customize name
    cat_label = RULES.get(category, CategoryRules(category_name=category)).category_name
    scope_label = "概念版" if scope == "concept" else "具体版"
    mode_label = "完整报告" if mode == "full" else "快速摸底"
    graph["name"] = name or f"{cat_label} — {scope_label} — {mode_label}"
    graph["description"] = (
        f"品类: {cat_label} | 维度: {scope_label} | 模式: {mode_label}"
    )

    # Apply transforms
    # Category rules only apply to full mode — quick mode is always
    # the same market+competitive parallel scan regardless of category.
    if mode == "full":
        graph = _apply_category_rules(graph, category)
    graph = _apply_scope_overrides(graph, scope)

    # Update node count in description
    graph["description"] += f" | 节点: {len(graph['nodes'])}, 边: {len(graph['edges'])}"

    return graph


def build_and_save(
    category: str,
    scope: str = "concept",
    mode: str = "full",
    output_path: Optional[str] = None,
) -> str:
    """Build and save a graph JSON to disk.

    Returns the file path.
    """
    graph = build_graph(category, scope, mode)

    if output_path is None:
        output_path = str(
            BASE_DIR / f"generated-{category}-{scope}-{mode}.json"
        )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return str(path)
