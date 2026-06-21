"""Product capability status truth table (G-007, Phase 1).

Single operator-facing source for "which module is real, dormant, fake-local,
or operator-ready". Sourced from docs/current/PRODUCT_CAPABILITY_AUDIT.md §4.

学习型说明：
这是一个**声明式**数据模块 —— 它不查询运行时状态，只把审计基线表成结构化
数据，供 `python main.py capability-status` 渲染。保持与审计同步是 G-003
authority-consistency 检查的职责（每个 phase exit 复核）。任何 maturity 升级
必须有 real API / real trigger / operator validation 证据，不得在此口头提升。

Maturity levels (与审计一致): L0 not_started / L1 scaffolded / L2 seam_proven /
L3 fake_local_verified / L4 real_api_verified / L5 operator_ready / L6 released.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CapabilityStatus:
    """单个能力模块的成熟度与状态声明。"""

    module: str
    level: str  # L0..L6 基线级别（限定语放 detail）
    state: str  # active / dormant / fake-local / seam
    real_api_verified: bool
    operator_ready: bool
    detail: str  # 限定语 + 证据指针（脱敏，永不放 secret）


# Source: docs/current/PRODUCT_CAPABILITY_AUDIT.md §4 maturity table.
# Keep in sync via the G-003 authority-consistency check at each phase exit.
CAPABILITY_STATUSES: tuple[CapabilityStatus, ...] = (
    CapabilityStatus(
        "Core governed runtime spine", "L4", "active", True, False,
        "Real provider -> interactive CLI -> governed tool_use (write_file) -> "
        "confirmation -> execution -> evidence/checkpoint (R-series Run 12). "
        "Promote to L5 only after operator workflow + capability status close.",
    ),
    CapabilityStatus(
        "Provider/model boundary", "L4", "active", True, False,
        "Real-API verified for DeepSeek anthropic_compatible ONLY. Kimi/GLM are "
        "config-exists (~L2); GLM openai_compatible streaming is fail-closed.",
    ),
    CapabilityStatus(
        "Interactive CLI / operator workflow", "L4", "active", True, False,
        "Gating module for any L5 promotion. No consolidated troubleshooting "
        "runbook yet (Phase 1 closes this).",
    ),
    CapabilityStatus(
        "Tool runtime and registry", "L4", "active", True, False,
        "write_file + edit_file real-proven (G-010/G-015 reproducible real "
        "dogfood). ~10 governed tools registered; run_shell/fetch_url have zero "
        "real evidence. See OPERATOR_GUIDE §10.",
    ),
    CapabilityStatus(
        "Confirmation / governance / policy", "L4", "active", True, False,
        "Qualified: only the write_file approval gate real-proven once; full "
        "governance matrix is contract-only.",
    ),
    CapabilityStatus(
        "Evidence / audit / observability", "L4", "active", True, False,
        "Write-path real-recorded (Run 12/14); inspection path is L3 (one manual "
        "logs read, fake/unit tests). No module-level browsing yet.",
    ),
    CapabilityStatus(
        "Checkpoint / session / resume", "L3", "active", False, False,
        "Resume = contract + subprocess test; no real interrupted-session resume "
        "dogfood; Ctrl+C mid-flight not PTY-validated.",
    ),
    CapabilityStatus(
        "Durable task ledger / recovery", "L3", "active", False, False,
        "S5 closed (TD-011 resolved). Safe-summary, not canonical state; no real "
        "recovery trial.",
    ),
    CapabilityStatus(
        "Memory", "L4", "active", True, False,
        "Real-trigger verified (G-019 reproducible real DeepSeek memory dogfood: "
        "MEMORY_REMEMBER_REQUEST -> memory_confirmation approval -> stored -> "
        "list_records recall). Consolidation frozen across 6 modules (LLM "
        "consolidation default-off).",
    ),
    CapabilityStatus(
        "Skill system", "L3", "active", False, False,
        "Registry/lifecycle/invocation fake/local-tested; demo-note-maker. No "
        "real external skill dir / operator install-use flow.",
    ),
    CapabilityStatus(
        "MCP config / bridge", "L3", "dormant", False, False,
        "Default-off via env-gate (config cannot flip). Opt-in real npx flight "
        "smoke exists but skip-by-default. Full ecosystem deferred (TD-009).",
    ),
    CapabilityStatus(
        "SubAgent", "L3", "fake-local", False, False,
        "Live delegation path is inline-L0 execution_mode=local_fake. L1/L2 "
        "frozen (no handler). Triple-gated; ambient env cannot flip to real.",
    ),
    CapabilityStatus(
        "Scheduler / action-planning", "L2", "dormant", False, False,
        "Registered-not-routed; chat() action_scheduler=None; main.py never "
        "passes the kwarg. Dormant by design (TD-008).",
    ),
    CapabilityStatus(
        "Security / config diagnostics", "L4", "active", True, False,
        "Real-config hardened: main.py status redaction real-config-verified "
        "(G-004). Broad diagnostic-output hardening tracked as G-036.",
    ),
    CapabilityStatus(
        "TUI / visual shell", "L2", "seam", False, False,
        "Separate Node/TS companion app; minimal unit tests; not the product "
        "surface. Gate behind capability-truth stability (Phase 5).",
    ),
    CapabilityStatus(
        "Fake / local deterministic support", "L3", "fake-local", False, False,
        "FakeProvider default (factory.py). Underpins CI/contracts/demos. Not a "
        "real capability ceiling — never read as real-API readiness.",
    ),
    CapabilityStatus(
        "Planning / task orchestration", "L3", "active", False, False,
        "Task state + dispatch spine active/tested; narrow real loop. Bounded "
        "to current runtime; broader autonomy deferred (G-035 guardrail).",
    ),
)


def render_capability_status() -> str:
    """渲染人类可读的能力真相表。永不输出 secret。"""
    lines: list[str] = []
    lines.append("FirstAgent Product Capability Status")
    lines.append("Source: docs/current/PRODUCT_CAPABILITY_AUDIT.md (baseline)")
    lines.append("")
    header = (
        f"{'Module':<38} {'Level':<6} {'State':<11} "
        f"{'RealAPI':<8} {'OpReady':<8} Detail"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for cs in CAPABILITY_STATUSES:
        lines.append(
            f"{cs.module:<38} {cs.level:<6} {cs.state:<11} "
            f"{'yes' if cs.real_api_verified else 'no':<8} "
            f"{'yes' if cs.operator_ready else 'no':<8} {cs.detail}"
        )
    lines.append("")
    lines.append("Levels: L0 not_started / L1 scaffolded / L2 seam_proven /")
    lines.append("        L3 fake_local_verified / L4 real_api_verified /")
    lines.append("        L5 operator_ready / L6 released")
    lines.append(
        "Note: no module is L5/L6. Real-API verification is opt-in (no CI gate)."
    )
    return "\n".join(lines) + "\n"


def capability_status_json() -> str:
    """渲染 JSON 形式（供脚本消费）。永不输出 secret。"""
    return json.dumps(
        {
            "source": "docs/current/PRODUCT_CAPABILITY_AUDIT.md",
            "capabilities": [asdict(cs) for cs in CAPABILITY_STATUSES],
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"
