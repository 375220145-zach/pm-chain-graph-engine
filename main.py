#!/usr/bin/env python3
"""PM Graph Engine — CLI entry point.

Usage:
    python main.py run <graph-file.json>
    python main.py run <graph-file.json> --output-dir ./output

Examples:
    python main.py run graphs/test-simple.json
    python main.py run graphs/test-diamond.json --output-dir ~/Desktop/pm-output/test
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from engine.graph_loader import GraphLoader
from engine.scheduler import Scheduler
from engine.executor import Executor
from engine.logger import ExecutionLogger


def main():
    parser = argparse.ArgumentParser(
        description="PM Graph Engine — DAG-based workflow execution engine",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Run a graph")
    run_parser.add_argument("graph_file", help="Path to graph JSON file")
    run_parser.add_argument(
        "--output-dir",
        default="./output",
        help="Output directory for node artifacts (default: ./output)",
    )

    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate a graph from category + scope")
    gen_parser.add_argument(
        "--category", "-c",
        required=True,
        choices=["ai", "consumer_electronics", "saas", "physical_goods", "content", "marketplace", "service"],
        help="Product category",
    )
    gen_parser.add_argument(
        "--scope", "-s",
        default="concept",
        choices=["concept", "specific"],
        help="Analysis scope (default: concept)",
    )
    gen_parser.add_argument(
        "--mode", "-m",
        default="full",
        choices=["full", "quick"],
        help="Pipeline mode (default: full)",
    )
    gen_parser.add_argument(
        "--output", "-o",
        default=None,
        help="Save graph to file (default: graphs/generated-{cat}-{scope}-{mode}.json)",
    )
    gen_parser.add_argument(
        "--run",
        action="store_true",
        help="Run the generated graph immediately",
    )
    gen_parser.add_argument(
        "--run-output-dir",
        default="./output",
        help="Output dir if --run is used",
    )

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_graph(args))
    elif args.command == "generate":
        handle_generate(args)
    else:
        parser.print_help()


async def run_graph(args):
    """Load, schedule, and execute a graph."""
    # Step 1: Load the graph
    print(f"📂 加载图: {args.graph_file}")
    loader = GraphLoader()
    try:
        graph = loader.load(args.graph_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 加载失败: {e}")
        sys.exit(1)

    # Step 2: Inject output dir into all nodes
    for node in graph.nodes:
        node.config["output_dir"] = args.output_dir

    print(f"📋 图: {graph.name}")
    print(f"   节点数: {len(graph.nodes)}, 边数: {len(graph.edges)}")

    # Step 3: Schedule
    scheduler = Scheduler()
    try:
        plan = scheduler.plan(graph)
    except Exception as e:
        print(f"❌ 调度失败: {e}")
        sys.exit(1)

    print(f"\n{plan}")

    # Step 4: Set up logging
    logger = ExecutionLogger()
    logger.start_run(graph.name, len(graph.nodes))

    # Step 5: Execute
    print(f"\n🚀 开始执行...")
    executor = Executor(logger)
    success = await executor.execute(plan, graph)

    # Step 6: Finish and save log
    logger.finish_run()
    log_path = Path(args.output_dir) / "execution-log.json"
    logger.save(str(log_path))
    print(f"\n{logger.terminal_summary()}")
    print(f"📄 执行日志: {log_path}")

    if not success:
        sys.exit(1)


def handle_generate(args):
    """Generate a graph from category + scope, optionally run it."""
    from generators.builder import build_and_save

    path = build_and_save(args.category, args.scope, args.mode, args.output)
    print(f"📄 图已生成: {path}")

    if args.run:
        print()
        # Build args-like object for run_graph
        class RunArgs:
            graph_file = path
            output_dir = args.run_output_dir
        asyncio.run(run_graph(RunArgs()))


if __name__ == "__main__":
    main()
