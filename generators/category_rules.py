"""Category-specific rules for graph generation.

Each category defines:
- extra_nodes: additional skill nodes to insert (e.g., BOM analysis for hardware)
- remove_nodes: nodes to skip (e.g., no brand strategy for quick scans)
- extra_edges: dependency edges for added nodes
- human_overrides: per-node human_collab overrides

Categories:
  ai                    — AI 原生产品（Agent / AI 应用 / AI Skill）
  consumer_electronics  — 消费电子 / 硬件（智能硬件 / IoT）
  saas                  — SaaS / 软件（B2B/B2C SaaS / Web 应用）
  physical_goods        — 实体商品（服装 / 配饰 / 家居）
  content               — 内容 / 知识产品（课程 / 付费社区）
  marketplace           — 双边市场 / 平台
  service               — 服务（B2B 咨询 / B2C 服务）
"""

from dataclasses import dataclass, field


@dataclass
class CategoryRules:
    """Rules for transforming the base graph for a specific category."""

    category_name: str
    extra_nodes: list[dict] = field(default_factory=list)
    remove_nodes: list[str] = field(default_factory=list)
    extra_edges: list[dict] = field(default_factory=list)
    human_overrides: dict[str, str] = field(default_factory=dict)
    # Additional gate rules to append
    extra_gate_rules: dict[str, list[dict]] = field(default_factory=dict)


# ─── Category definitions ──────────────────────────────────────────

RULES: dict[str, CategoryRules] = {
    # ── AI 原生产品 ──────────────────────────────────────────────
    "ai": CategoryRules(
        category_name="AI 原生产品",
        extra_nodes=[
            {
                "id": "inference",
                "name": "推理成本建模",
                "type": "skill",
                "skill_name": "mock-inference-cost",
                "config": {"duration_seconds": 2, "human_collab": "auto"},
            },
            {
                "id": "model_select",
                "name": "模型选型对比",
                "type": "skill",
                "skill_name": "mock-model-selection",
                "config": {"duration_seconds": 2, "human_collab": "auto"},
            },
        ],
        extra_edges=[
            {"from": "prd", "to": "inference"},
            {"from": "inference", "to": "model_select"},
            {"from": "model_select", "to": "gtm"},
        ],
        human_overrides={
            "sentiment": "flag",   # AI 产品舆论敏感度高
            "risk": "pause",       # AI 风险需要人工确认
        },
    ),

    # ── 消费电子 / 硬件 ──────────────────────────────────────────
    "consumer_electronics": CategoryRules(
        category_name="消费电子 / 硬件",
        extra_nodes=[
            {
                "id": "bom",
                "name": "BOM 成本分析",
                "type": "skill",
                "skill_name": "mock-bom-analysis",
                "config": {"duration_seconds": 3, "human_collab": "pause"},
            },
            {
                "id": "certification",
                "name": "认证与合规检查",
                "type": "skill",
                "skill_name": "mock-certification",
                "config": {"duration_seconds": 2, "human_collab": "flag", "flag_timeout": 10},
            },
        ],
        extra_edges=[
            {"from": "prd", "to": "bom"},
            {"from": "bom", "to": "certification"},
            {"from": "certification", "to": "gtm"},
        ],
        human_overrides={
            "market": "pause",  # 硬件市场调研关键决策
            "brand": "flag",    # 硬件品牌策略建议审查但不必阻塞
        },
    ),

    # ── SaaS / 软件 ──────────────────────────────────────────────
    "saas": CategoryRules(
        category_name="SaaS / 软件",
        extra_nodes=[
            {
                "id": "unit_economics",
                "name": "单位经济学分析",
                "type": "skill",
                "skill_name": "mock-unit-economics",
                "config": {"duration_seconds": 2, "human_collab": "pause"},
            },
        ],
        extra_edges=[
            {"from": "prd", "to": "unit_economics"},
            {"from": "unit_economics", "to": "gtm"},
        ],
        human_overrides={
            "gtm": "flag",  # SaaS GTM 定价策略建议审查
        },
    ),

    # ── 实体商品 ──────────────────────────────────────────────────
    "physical_goods": CategoryRules(
        category_name="实体商品",
        extra_nodes=[
            {
                "id": "supply_chain",
                "name": "供应链分析",
                "type": "skill",
                "skill_name": "mock-supply-chain",
                "config": {"duration_seconds": 2, "human_collab": "pause"},
            },
            {
                "id": "sku_strategy",
                "name": "SKU 策略",
                "type": "skill",
                "skill_name": "mock-sku-strategy",
                "config": {"duration_seconds": 2, "human_collab": "auto"},
            },
        ],
        extra_edges=[
            {"from": "competitive", "to": "supply_chain"},
            {"from": "supply_chain", "to": "sku_strategy"},
            {"from": "sku_strategy", "to": "brainstorm"},
        ],
        human_overrides={
            "competitive": "flag",  # 实体竞品容易买错版本，建议抽查
        },
    ),

    # ── 内容 / 知识产品 ──────────────────────────────────────────
    "content": CategoryRules(
        category_name="内容 / 知识产品",
        remove_nodes=["architecture", "prototype"],  # 内容产品通常不需要架构图和原型
        human_overrides={
            "market": "pause",  # 课程市场验证关键
        },
    ),

    # ── 双边市场 / 平台 ──────────────────────────────────────────
    "marketplace": CategoryRules(
        category_name="双边市场 / 平台",
        extra_nodes=[
            {
                "id": "cold_start",
                "name": "冷启动策略（双边）",
                "type": "skill",
                "skill_name": "mock-cold-start",
                "config": {"duration_seconds": 3, "human_collab": "pause"},
            },
            {
                "id": "liquidity",
                "name": "流动性建模",
                "type": "skill",
                "skill_name": "mock-liquidity",
                "config": {"duration_seconds": 2, "human_collab": "auto"},
            },
        ],
        extra_edges=[
            {"from": "gtm", "to": "cold_start"},
            {"from": "cold_start", "to": "liquidity"},
            {"from": "liquidity", "to": "brand"},
        ],
        human_overrides={
            "gtm": "pause",  # 双边市场 GTM 需要人工确认
        },
    ),

    # ── 服务 ──────────────────────────────────────────────────────
    "service": CategoryRules(
        category_name="服务",
        extra_nodes=[
            {
                "id": "sop",
                "name": "服务 SOP 设计",
                "type": "skill",
                "skill_name": "mock-sop-design",
                "config": {"duration_seconds": 2, "human_collab": "flag", "flag_timeout": 10},
            },
        ],
        extra_edges=[
            {"from": "prd", "to": "sop"},
            {"from": "sop", "to": "gtm"},
        ],
        human_overrides={
            "risk": "pause",  # 服务业风险评估需人工确认
        },
    ),
}
