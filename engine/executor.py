"""Executor: async execution engine.

Takes an ExecutionPlan and runs it wave by wave:
- Within each wave, all nodes run concurrently (asyncio.gather)
- Between waves, execution is sequential (wave N+1 only after wave N completes)
- Gate nodes validate upstream outputs; on failure, retry only the failing branch

Phase 1: tasks are mock functions (simulated skill calls).
Phase 2: gate nodes with validation rules + branch-level retry.
"""

import asyncio
from pathlib import Path
from typing import Any, Callable, Optional

from engine.graph_loader import Graph, Node
from engine.scheduler import ExecutionPlan
from engine.logger import ExecutionLogger
from engine.quality_gate import GateRunner, GateResult
from nodes.human_node import HumanCollabHandler


# Type for a task handler: takes a Node and returns a dict (output)
TaskHandler = Callable[[Node], dict[str, Any]]


async def _mock_skill(node: Node) -> dict[str, Any]:
    """Mock skill: simulates work by sleeping, then writes placeholder output.

    Supports a 'fail_mode' config to simulate failures for gate testing:
      fail_mode: "first" → fails on first run, succeeds on retry
      fail_mode: "always" → always fails
    """
    duration = node.config.get("duration_seconds", 2)
    output_dir = node.config.get("output_dir", "./output")

    await asyncio.sleep(duration)

    # Check fail mode
    fail_mode = node.config.get("fail_mode", "")
    attempt = node.config.get("_attempt", 0)

    if fail_mode == "always":
        raise RuntimeError(f"节点 {node.id} 配置为始终失败")
    if fail_mode == "first" and attempt == 0:
        raise RuntimeError(f"节点 {node.id} 第 1 次执行故意失败（将在重试时成功）")

    # Create placeholder output directory + files
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    md_file = out_path / f"{node.id}.md"
    json_file = out_path / f"{node.id}.json"

    md_content = f"# {node.name}\n\nMock output for node '{node.id}'.\n"
    json_content = f'{{"node_id": "{node.id}", "name": "{node.name}", "status": "success"}}'

    md_file.write_text(md_content, encoding="utf-8")
    json_file.write_text(json_content, encoding="utf-8")

    return {
        "files": [str(md_file), str(json_file)],
        "duration_seconds": duration,
        "output_dir": output_dir,
    }


class Executor:
    """Runs a graph execution plan wave by wave.

    Usage:
        executor = Executor(logger)
        success = await executor.execute(plan, graph)
    """

    def __init__(self, logger: ExecutionLogger, task_handler: TaskHandler = None):
        self.logger = logger
        self._handler = task_handler or _mock_skill
        self._gate_runner = GateRunner()
        self._human = HumanCollabHandler()
        # Tracks node outputs for gate inspection: {node_id: output_dict}
        self._node_outputs: dict[str, dict[str, Any]] = {}

    async def execute(self, plan: ExecutionPlan, graph: Graph) -> bool:
        """Execute the full plan. Returns True if all nodes succeeded.

        Args:
            plan: ExecutionPlan from Scheduler.
            graph: The original Graph (needed for node configs).

        Returns:
            True if all nodes completed successfully, False if any failed.
        """
        node_map = {n.id: n for n in graph.nodes}
        self._node_outputs = {}

        total_waves = len(plan.waves)

        for wave_idx, wave in enumerate(plan.waves):
            if total_waves > 1:
                gate_count = sum(1 for nid in wave if node_map.get(nid) and node_map[nid].type == "gate")
                skill_count = len(wave) - gate_count
                label_parts = [f"{skill_count} 任务"] if skill_count > 0 else []
                if gate_count > 0:
                    label_parts.append(f"{gate_count} 门禁")
                label = ", ".join(label_parts)
                print(f"\n── Wave {wave_idx}/{total_waves - 1} ({label}) ──")

            # Split wave into skill nodes and gate nodes
            skill_nodes = []
            gate_nodes = []
            for node_id in wave:
                node = node_map.get(node_id)
                if node is None:
                    print(f"  ⚠ 跳过未知节点: {node_id}")
                    continue
                if node.type == "gate":
                    gate_nodes.append(node)
                else:
                    skill_nodes.append(node)

            # Step 1: Run all skill nodes in parallel (allow exceptions)
            skill_errors = []
            if skill_nodes:
                tasks = [self._run_skill_node(n, wave_idx) for n in skill_nodes]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for node, result in zip(skill_nodes, results):
                    if isinstance(result, Exception):
                        self.logger.log_fail(node.id, str(result))
                        self._node_outputs[node.id] = {"_error": str(result)}
                        print(f"  ❌ {node.name} ({node.id}) — {result}")
                        skill_errors.append(node.id)

            # Step 1.5: Human collaboration check for completed skill nodes
            # Runs sequentially after skills finish so user isn't bombarded
            # with multiple prompts at once.
            for node in skill_nodes:
                if node.id in skill_errors:
                    continue  # failed nodes handled by gates
                decision = await self._check_human_collab(node)
                if decision == "abort":
                    print(f"  🛑 用户中止流程")
                    return False
                elif decision == "retry":
                    # Re-run the node and re-check
                    await self._retry_skill_for_human(node, wave_idx)

            # Step 2: Run gate nodes (if any)
            # Gates can retry failed upstream nodes, so don't halt on skill
            # failure — let gates decide whether to retry or abort.
            for gate_node in gate_nodes:
                gate_ok = await self._run_gate_node(gate_node, node_map, wave_idx)
                if not gate_ok:
                    return False
            # Note: skill failures without a gate to catch them will cause
            # downstream nodes to fail naturally. Gate failures (after retries)
            # are the only hard stop.

        return True

    # ─── Skill node execution ──────────────────────────────────────

    async def _run_skill_node(self, node: Node, wave_idx: int) -> None:
        """Run a single skill node and log the result."""
        self.logger.log_start(
            node_id=node.id,
            node_name=node.name,
            node_type=node.type,
            skill_name=node.skill_name,
            wave=wave_idx,
        )

        output = await self._handler(node)
        self.logger.log_complete(node.id, output)
        self._node_outputs[node.id] = output
        dur = output.get("duration_seconds", "?")
        print(f"  ✅ {node.name} ({node.id}) — {dur:.1f}s")

    # ─── Human collaboration (Phase 3) ─────────────────────────────

    async def _check_human_collab(self, node: Node) -> str:
        """Check human_collab setting and interact if needed.

        Returns: "continue" | "retry" | "abort"
        """
        mode = node.config.get("human_collab", "auto")
        if mode == "auto":
            return "continue"

        output = self._node_outputs.get(node.id, {})
        return await self._human.handle(node, output)

    async def _retry_skill_for_human(self, node: Node, wave_idx: int) -> None:
        """Re-run a skill node because the user requested retry."""
        print(f"  🔄 重新执行: {node.name} ({node.id})")
        node.config["_attempt"] = node.config.get("_attempt", 0) + 1

        self.logger.log_retry(node.id, node.config["_attempt"], "用户手动触发重试")

        try:
            output = await self._handler(node)
            self._node_outputs[node.id] = output
            # Update existing NodeLog output — don't double-count
            nl = self.logger.run_log.get_node(node.id) if self.logger.run_log else None
            if nl:
                nl.output = output
            dur = output.get("duration_seconds", "?")
            print(f"  ✅ 重试完成: {node.name} ({node.id}) — {dur:.1f}s")
        except Exception as e:
            self.logger.log_fail(node.id, str(e))
            print(f"  ❌ 重试失败: {node.name} ({node.id}) — {e}")

    # ─── Gate node execution ────────────────────────────────────────

    async def _run_gate_node(
        self, gate_node: Node, node_map: dict[str, Node], wave_idx: int
    ) -> bool:
        """Run a gate node: validate upstream outputs, retry failing branches.

        Returns True if gate passes (or passes after retries).
        Returns False if gate fails after exhausting all retries.
        """
        max_retries = gate_node.config.get("max_retries", 2)

        # Find upstream nodes (nodes that have edges pointing TO this gate)
        upstream_ids = self._get_upstream_nodes(gate_node.id, node_map)

        # Build node configs dict for variable resolution in validation rules
        node_configs = {
            nid: node_map[nid].config for nid in node_map
        }

        # Run gate → retry loop
        for attempt in range(max_retries + 1):  # 0 = first attempt, 1..N = retries
            self.logger.log_start(
                node_id=gate_node.id,
                node_name=gate_node.name,
                node_type="gate",
                skill_name=f"gate (attempt {attempt + 1}/{max_retries + 1})",
                wave=wave_idx,
            )

            result = self._gate_runner.check(gate_node, node_configs)
            self.logger.log_gate_result(gate_node.id, result, attempt)

            if result.passed:
                dur = 0.0  # gates are instant
                print(f"  ✅ {gate_node.name} ({gate_node.id}) — 通过")
                self.logger.log_complete(gate_node.id, {
                    "gate_result": "passed",
                    "attempt": attempt,
                    "rules_checked": len(result.rule_results),
                })
                return True

            # Gate failed — show what went wrong
            failed_rules_str = "; ".join(
                f"{r.rule_type}: {r.detail}" for r in result.failed_rules[:3]
            )
            print(f"  🔴 {gate_node.name} ({gate_node.id}) — {len(result.failed_rules)} 条规则不通过")
            for r in result.failed_rules:
                print(f"     ❌ {r.rule_type}: {r.detail}")

            # If retries left, find the failing branch and retry it
            if attempt < max_retries:
                raw_rules = gate_node.config.get("rules", [])
                failing_id = self._gate_runner.identify_failing_branch(
                    result, upstream_ids, raw_rules
                )
                if failing_id and failing_id in node_map:
                    print(f"  🔄 重试节点: {node_map[failing_id].name} ({failing_id}) — 第 {attempt + 1} 次重试")
                    retry_node = node_map[failing_id]

                    # Bump attempt counter in config so mock skill can change behavior
                    retry_node.config["_attempt"] = retry_node.config.get("_attempt", 0) + 1

                    # Re-run the failing skill node
                    self.logger.log_retry(failing_id, attempt + 1, str(result.failed_rules[0].detail) if result.failed_rules else "unknown")
                    try:
                        output = await self._handler(retry_node)
                        self._node_outputs[failing_id] = output
                        self.logger.log_complete(failing_id, output)
                        dur = output.get("duration_seconds", "?")
                        print(f"  ✅ 重试成功: {retry_node.name} ({failing_id}) — {dur:.1f}s")
                    except Exception as e:
                        self.logger.log_fail(failing_id, str(e))
                        print(f"  ❌ 重试失败: {retry_node.name} ({failing_id}) — {e}")
                        # Don't return yet — the gate will fail on next iteration
                        # if max_retries exhausted
                else:
                    print(f"  ⚠ 无法确定哪个上游节点失败，跳过重试")
            else:
                # Max retries exhausted
                print(f"  ❌ {gate_node.name}: 已达最大重试次数 ({max_retries})，流程中止")
                self.logger.log_fail(
                    gate_node.id,
                    f"门禁失败: {len(result.failed_rules)} 条规则不通过, {max_retries} 次重试已用尽"
                )
                return False

        return False

    def _get_upstream_nodes(
        self, gate_id: str, node_map: dict[str, Node]
    ) -> list[str]:
        """Find nodes that have edges pointing to this gate.

        Walks backward through node_map by checking which nodes'
        outputs the gate rules reference. Since we don't have the
        original Graph edges here, we infer upstream from rule paths.
        """
        # Simple approach: check which node IDs appear in gate rule paths
        gate_node = node_map.get(gate_id)
        if not gate_node:
            return []

        upstream = []
        rules = gate_node.config.get("rules", [])
        for rule in rules:
            for key, value in rule.items():
                if isinstance(value, str):
                    # Look for ${node.X...} patterns
                    import re
                    for match in re.finditer(r'\$\{node\.(\w+)', value):
                        nid = match.group(1)
                        if nid not in upstream and nid in node_map:
                            upstream.append(nid)

        return upstream
