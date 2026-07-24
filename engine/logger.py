"""Logger: structured execution log generation.

Tracks every node execution: start time, end time, status, output, errors.
Produces a structured JSON log at the end of the run.

Log format mirrors pm-chain's execution-log.json structure so downstream
tools (report credibility dashboard) can consume it without changes.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


@dataclass
class NodeLog:
    """Execution record for a single node."""

    node_id: str
    node_name: str
    node_type: str
    skill_name: str
    wave: int
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "pending"  # pending | running | success | failed | skipped
    error: Optional[str] = None
    output: dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.status = "running"

    def complete(self, output: dict | None = None) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.status = "success"
        if output:
            self.output = output
        # Calculate duration
        if self.started_at:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.completed_at)
            self.duration_seconds = (end - start).total_seconds()

    def fail(self, error: str) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.status = "failed"
        self.error = error
        if self.started_at:
            start = datetime.fromisoformat(self.started_at)
            end = datetime.fromisoformat(self.completed_at)
            self.duration_seconds = (end - start).total_seconds()


@dataclass
class RunLog:
    """Complete execution log for one graph run."""

    run_id: str
    graph_name: str
    started_at: str
    completed_at: str = ""
    total_duration_seconds: float = 0.0
    total_nodes: int = 0
    success_count: int = 0
    failed_count: int = 0
    node_logs: list[NodeLog] = field(default_factory=list)

    def get_node(self, node_id: str) -> Optional[NodeLog]:
        for nl in self.node_logs:
            if nl.node_id == node_id:
                return nl
        return None

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "graph_name": self.graph_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_seconds": self.total_duration_seconds,
            "total_nodes": self.total_nodes,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
        }

    def to_json(self) -> str:
        data = {
            "run_id": self.run_id,
            "graph_name": self.graph_name,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration_seconds": self.total_duration_seconds,
            "total_nodes": self.total_nodes,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "nodes": [
                {
                    "node_id": nl.node_id,
                    "node_name": nl.node_name,
                    "node_type": nl.node_type,
                    "skill_name": nl.skill_name,
                    "wave": nl.wave,
                    "started_at": nl.started_at,
                    "completed_at": nl.completed_at,
                    "duration_seconds": nl.duration_seconds,
                    "status": nl.status,
                    "error": nl.error,
                }
                for nl in self.node_logs
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


class ExecutionLogger:
    """Creates and manages the run log.

    Usage:
        logger = ExecutionLogger()
        logger.start_run("my-graph", node_count=5)
        logger.log_start("mkt", "market-research", "skill", wave=0)
        # ... node runs ...
        logger.log_complete("mkt", output={"file": "mkt.md"})
        logger.finish_run()
        logger.save("output/execution-log.json")
    """

    def __init__(self) -> None:
        self.run_log: Optional[RunLog] = None

    def start_run(self, graph_name: str, node_count: int) -> RunLog:
        """Begin a new run."""
        self.run_log = RunLog(
            run_id=str(uuid.uuid4())[:8],
            graph_name=graph_name,
            started_at=datetime.now(timezone.utc).isoformat(),
            total_nodes=node_count,
        )
        return self.run_log

    def log_start(
        self, node_id: str, node_name: str, node_type: str, skill_name: str, wave: int
    ) -> None:
        """Record a node starting execution."""
        if not self.run_log:
            return
        nl = NodeLog(
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            skill_name=skill_name,
            wave=wave,
        )
        nl.start()
        self.run_log.node_logs.append(nl)

    def log_complete(self, node_id: str, output: dict | None = None) -> None:
        """Record a node completing successfully.

        If this node previously failed (retry scenario), update the
        failure count back down.
        """
        if not self.run_log:
            return
        nl = self.run_log.get_node(node_id)
        if nl:
            was_failed = nl.status == "failed"
            nl.complete(output)
            self.run_log.success_count += 1
            if was_failed:
                self.run_log.failed_count -= 1

    def log_fail(self, node_id: str, error: str) -> None:
        """Record a node failing."""
        if not self.run_log:
            return
        nl = self.run_log.get_node(node_id)
        if nl:
            nl.fail(error)
            self.run_log.failed_count += 1

    def finish_run(self) -> None:
        """Mark the run as complete and compute totals."""
        if not self.run_log:
            return
        self.run_log.completed_at = datetime.now(timezone.utc).isoformat()
        start = datetime.fromisoformat(self.run_log.started_at)
        end = datetime.fromisoformat(self.run_log.completed_at)
        self.run_log.total_duration_seconds = (end - start).total_seconds()

    def save(self, filepath: str) -> None:
        """Write the run log to a JSON file."""
        if not self.run_log:
            return
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.run_log.to_json(), encoding="utf-8")

    def log_gate_result(self, node_id: str, result: Any, attempt: int) -> None:
        """Record gate validation result in the node's log entry."""
        if not self.run_log:
            return
        nl = self.run_log.get_node(node_id)
        if nl:
            gate_info = {
                "gate_passed": result.passed,
                "attempt": attempt,
                "rules_total": len(result.rule_results),
                "rules_passed": len([r for r in result.rule_results if r.passed]),
                "rules_failed": len(result.failed_rules),
                "failed_details": [
                    {"type": r.rule_type, "detail": r.detail, "file": r.target_file}
                    for r in result.failed_rules[:10]
                ],
            }
            nl.output.update(gate_info)

    def log_retry(self, node_id: str, attempt: int, reason: str) -> None:
        """Record a retry event in the run log."""
        if not self.run_log:
            return
        nl = self.run_log.get_node(node_id)
        if nl:
            retries = nl.output.get("retries", [])
            retries.append({
                "attempt": attempt,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            nl.output["retries"] = retries

    def terminal_summary(self) -> str:
        """Return a one-line terminal summary of the run."""
        if not self.run_log:
            return "无执行记录"
        rl = self.run_log
        status_icon = "✅" if rl.failed_count == 0 else "⚠️"
        return (
            f"{status_icon} {rl.graph_name}: "
            f"{rl.success_count}/{rl.total_nodes} 成功, "
            f"{rl.failed_count} 失败, "
            f"耗时 {rl.total_duration_seconds:.1f}s"
        )
