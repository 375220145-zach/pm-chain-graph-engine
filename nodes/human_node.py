"""Human collaboration: auto / flag / pause node behaviors.

Phase 3 adds three human-interaction modes to any skill or gate node,
configured via node.config.human_collab:

  "auto"  — runs silently, no interruption (default, same as Phase 1-2)
  "flag"  — runs, shows summary, waits N seconds. User can type 'stop'
            to pause and inspect, or do nothing to auto-continue.
  "pause" — runs, shows output, HALTS until user makes a decision.
            User picks from structured options (not open-ended).

Usage:
    handler = HumanCollabHandler()
    decision = await handler.handle(node, output)
    # decision: "continue" | "retry" | "abort"
"""

import asyncio
import sys
from typing import Any


class HumanCollabHandler:
    """Manages auto/flag/pause interaction for a completed node.

    Called by the executor after a skill node finishes, before moving
    to the next node/wave.
    """

    async def handle(self, node: Any, output: dict[str, Any]) -> str:
        """Run the appropriate interaction mode for this node.

        Args:
            node: The Node dataclass (has .config with human_collab setting).
            output: The node's output dict from the task handler.

        Returns:
            "continue" — proceed to next node
            "retry"   — re-run this node
            "abort"   — halt the entire run
        """
        mode = node.config.get("human_collab", "auto")

        if mode == "auto":
            return "continue"

        elif mode == "flag":
            return await self._handle_flag(node, output)

        elif mode == "pause":
            return await self._handle_pause(node, output)

        else:
            print(f"  ⚠ 未知 human_collab 模式: '{mode}'，按 auto 处理")
            return "continue"

    # ─── Flag mode: summary + timeout ────────────────────────────

    async def _handle_flag(self, node: Any, output: dict[str, Any]) -> str:
        timeout = node.config.get("flag_timeout", 10)

        dur = output.get("duration_seconds", "?")
        files = output.get("files", [])
        file_list = ", ".join([f.split("/")[-1] for f in files[:3]]) if files else "无文件"

        print(f"  📋 {node.name} ({node.id}) — {dur:.1f}s | {file_list}")
        print(f"     {timeout}秒后自动继续，输入 'stop' 暂停检查...")

        # Race: user types 'stop' vs timeout expires
        try:
            user_input = await asyncio.wait_for(
                asyncio.to_thread(sys.stdin.readline),
                timeout=timeout,
            )
            if user_input and user_input.strip().lower() == "stop":
                print(f"  ⏸ 已暂停 — 进入检查模式")
                try:
                    return await self._interactive_review(node, output)
                except EOFError:
                    print("  (无输入，默认继续)")
                    return "continue"
        except asyncio.TimeoutError:
            pass  # timeout → auto-continue
        except EOFError:
            pass  # non-interactive → auto-continue

        return "continue"

    # ─── Pause mode: halt until user decides ──────────────────────

    async def _handle_pause(self, node: Any, output: dict[str, Any]) -> str:
        prompt = node.config.get("pause_prompt", "请选择下一步操作")
        options = node.config.get("pause_options", [
            {"key": "c", "label": "继续 — 接受当前结果，进入下一步"},
            {"key": "r", "label": "重试 — 重新执行此节点"},
            {"key": "a", "label": "中止 — 停止整个流程"},
        ])

        print(f"\n  ⏸  [{node.name}] {prompt}")
        for opt in options:
            print(f"     [{opt['key']}] {opt['label']}")

        while True:
            try:
                response = await asyncio.to_thread(input, "  选择 > ")
            except EOFError:
                print("  (无输入，默认继续)")
                return "continue"
            cmd = response.strip().lower()
            for opt in options:
                if cmd == opt["key"]:
                    if cmd == "r":
                        return "retry"
                    elif cmd == "a":
                        return "abort"
                    else:
                        return "continue"
            print(f"  无效选项 '{cmd}'，请重试")

    # ─── Interactive review (entered via flag→stop) ───────────────

    async def _interactive_review(self, node: Any, output: dict[str, Any]) -> str:
        """Interactive mode: user can inspect files, retry, continue, or abort."""
        print(f"  检查模式 — 节点: {node.name} ({node.id})")
        print(f"  命令: [c]继续 [r]重试 [a]中止 [i]查看输出")

        while True:
            try:
                response = await asyncio.to_thread(input, "  检查 > ")
            except EOFError:
                print("  (无输入，默认继续)")
                return "continue"
            cmd = response.strip().lower()

            if cmd in ("c", "continue"):
                return "continue"
            elif cmd in ("r", "retry"):
                return "retry"
            elif cmd in ("a", "abort"):
                return "abort"
            elif cmd in ("i", "inspect"):
                files = output.get("files", [])
                if files:
                    print(f"  产出文件:")
                    for f in files:
                        print(f"    - {f}")
                else:
                    print(f"  输出: {output}")
            else:
                print(f"  未知命令: {cmd}. 可用: c/r/a/i")
