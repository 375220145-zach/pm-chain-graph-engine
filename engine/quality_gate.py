"""Quality gate engine: validation rules + gate node execution.

Phase 2 adds two things to the core engine:
1. Quality gate nodes — sit between task nodes and validate their outputs
2. Branch-level retry — if a gate finds a problem, only the failing branch retries

Gate node JSON structure:
{
  "id": "gate_mkt",
  "name": "Quality Gate - Market Research",
  "type": "gate",
  "config": {
    "max_retries": 2,
    "rules": [
      {"type": "file_exists", "path": "${node.A.output_dir}/A.md"},
      {"type": "file_min_size", "path": "${node.A.output_dir}/A.json", "min_bytes": 50},
      {"type": "json_field_present", "path": "${node.A.output_dir}/A.json", "field": "node_id"},
      {"type": "json_field_non_empty", "path": "${node.A.output_dir}/A.json", "field": "status"}
    ]
  }
}

Built-in rule types:
- file_exists: check that a file was created
- file_min_size: check file is at least N bytes
- json_field_present: check JSON has a specific top-level field
- json_field_non_empty: check JSON field has a non-empty value
- grep_pattern_found: check a string pattern exists in a text file
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ─── Rule result types ──────────────────────────────────────────────


@dataclass
class RuleResult:
    """Result of running a single validation rule."""

    rule_type: str
    passed: bool
    detail: str = ""
    target_file: str = ""


@dataclass
class GateResult:
    """Result of running all rules in a gate."""

    passed: bool
    rule_results: list[RuleResult] = field(default_factory=list)
    failed_node_id: Optional[str] = None

    @property
    def failed_rules(self) -> list[RuleResult]:
        return [r for r in self.rule_results if not r.passed]


# ─── Rule implementations ────────────────────────────────────────────


def _rule_file_exists(path_str: str) -> RuleResult:
    path = Path(path_str)
    if path.exists():
        return RuleResult("file_exists", True, f"文件存在: {path.name}", str(path))
    return RuleResult("file_exists", False, f"文件不存在: {path_str}", str(path))


def _rule_file_min_size(path_str: str, min_bytes: int) -> RuleResult:
    path = Path(path_str)
    if not path.exists():
        return RuleResult(
            "file_min_size", False, f"文件不存在，无法检查大小: {path_str}", str(path)
        )
    size = path.stat().st_size
    if size >= min_bytes:
        return RuleResult(
            "file_min_size", True, f"文件大小 {size}B ≥ {min_bytes}B", str(path)
        )
    return RuleResult(
        "file_min_size", False, f"文件大小 {size}B < {min_bytes}B", str(path)
    )


def _rule_json_field_present(path_str: str, field: str) -> RuleResult:
    path = Path(path_str)
    if not path.exists():
        return RuleResult(
            "json_field_present", False, f"文件不存在: {path_str}", str(path)
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return RuleResult(
            "json_field_present", False, f"JSON 解析失败: {e}", str(path)
        )
    if field in data:
        return RuleResult(
            "json_field_present", True, f"字段 '{field}' 存在", str(path)
        )
    return RuleResult(
        "json_field_present", False, f"字段 '{field}' 缺失", str(path)
    )


def _rule_json_field_non_empty(path_str: str, field: str) -> RuleResult:
    path = Path(path_str)
    if not path.exists():
        return RuleResult(
            "json_field_non_empty", False, f"文件不存在: {path_str}", str(path)
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return RuleResult(
            "json_field_non_empty", False, f"JSON 解析失败: {e}", str(path)
        )
    value = data.get(field)
    if value is not None and value != "" and value != [] and value != {}:
        return RuleResult(
            "json_field_non_empty", True, f"字段 '{field}' 有值", str(path)
        )
    return RuleResult(
        "json_field_non_empty", False, f"字段 '{field}' 为空", str(path)
    )


def _rule_grep_pattern(path_str: str, pattern: str) -> RuleResult:
    path = Path(path_str)
    if not path.exists():
        return RuleResult(
            "grep_pattern", False, f"文件不存在: {path_str}", str(path)
        )
    content = path.read_text(encoding="utf-8")
    if re.search(pattern, content):
        return RuleResult(
            "grep_pattern", True, f"找到匹配 '{pattern}'", str(path)
        )
    return RuleResult(
        "grep_pattern", False, f"未找到匹配 '{pattern}'", str(path)
    )


# Registry of built-in rule types
RULE_HANDLERS = {
    "file_exists": lambda **kw: _rule_file_exists(kw["path"]),
    "file_min_size": lambda **kw: _rule_file_min_size(kw["path"], kw["min_bytes"]),
    "json_field_present": lambda **kw: _rule_json_field_present(kw["path"], kw["field"]),
    "json_field_non_empty": lambda **kw: _rule_json_field_non_empty(kw["path"], kw["field"]),
    "grep_pattern": lambda **kw: _rule_grep_pattern(kw["path"], kw["pattern"]),
}


# ─── Variable interpolation ──────────────────────────────────────────

# Gate rules can reference node outputs using template variables:
#   ${node.<node_id>.output_dir}    → the output_dir from that node's config
#   ${node.<node_id>.config.<key>}  → any config value
# This lets rule paths be relative to each upstream node's output.

def _resolve_variables(template: str, node_configs: dict[str, dict]) -> str:
    """Replace ${node.X.Y} with actual config values from node X."""
    def _replace(match):
        full = match.group(0)
        parts = match.group(1).split(".")
        # Expected: node.<id>.<key1>.<key2...>
        if len(parts) < 3 or parts[0] != "node":
            return full
        nid = parts[1]
        key_path = parts[2:]
        config = node_configs.get(nid, {})
        value = config
        for k in key_path:
            if isinstance(value, dict):
                value = value.get(k, full)
            else:
                return full
        return str(value) if value is not None else full
    return re.sub(r'\$\{([^}]+)\}', _replace, template)


# ─── Gate runner ─────────────────────────────────────────────────────


class GateRunner:
    """Runs validation rules for a gate node.

    Usage:
        runner = GateRunner()
        result = runner.check(gate_node, upstream_outputs)
        if not result.passed:
            print(f"Failed: {result.failed_rules}")
    """

    def check(
        self,
        gate_node: Any,  # Node from graph_loader
        node_configs: dict[str, dict],
    ) -> GateResult:
        """Run all validation rules in the gate config.

        Args:
            gate_node: The gate Node object with config.rules and config.max_retries.
            node_configs: Dict of {node_id: config_dict} for variable resolution.
                          Should include the gate's upstream nodes.

        Returns:
            GateResult with pass/fail and per-rule details.
        """
        rules = gate_node.config.get("rules", [])
        if not rules:
            return GateResult(passed=True, rule_results=[])

        results: list[RuleResult] = []
        for rule in rules:
            rule_type = rule.get("type", "")
            if rule_type not in RULE_HANDLERS:
                results.append(
                    RuleResult(
                        rule_type, False,
                        f"未知规则类型: '{rule_type}'",
                        ""
                    )
                )
                continue

            # Resolve variables in rule params
            resolved = {}
            for key, value in rule.items():
                if key == "type":
                    continue
                if isinstance(value, str):
                    resolved[key] = _resolve_variables(value, node_configs)
                else:
                    resolved[key] = value

            try:
                result = RULE_HANDLERS[rule_type](**resolved)
                results.append(result)
            except Exception as e:
                results.append(
                    RuleResult(
                        rule_type, False,
                        f"规则执行异常: {e}",
                        resolved.get("path", "")
                    )
                )

        all_passed = all(r.passed for r in results)
        return GateResult(passed=all_passed, rule_results=results)


    def identify_failing_branch(
        self,
        result: GateResult,
        upstream_node_ids: list[str],
        raw_rules: list[dict] | None = None,
    ) -> Optional[str]:
        """Guess which upstream node caused the failure.

        Strategy (in priority order):
        1. Check failed rules' resolved target_file paths for node IDs
        2. If not found, check raw rule templates for ${node.<id>...} patterns
        3. Fallback: return first upstream node
        """
        if result.passed:
            return None

        # Strategy 1: resolved file paths
        for nid in upstream_node_ids:
            for rule in result.failed_rules:
                if f"/{nid}." in rule.target_file or f"/{nid}/" in rule.target_file:
                    return nid

        # Strategy 2: raw rule templates (before variable resolution)
        if raw_rules:
            for nid in upstream_node_ids:
                for rule in raw_rules:
                    for value in rule.values():
                        if isinstance(value, str) and f"${{node.{nid}" in value:
                            return nid

        # Fallback
        return upstream_node_ids[0] if upstream_node_ids else None
