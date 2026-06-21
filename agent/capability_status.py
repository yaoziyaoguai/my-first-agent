"""Product capability status truth table (G-007, Phase 1; updated through Phase 6).

Single operator-facing source for "which module is real, dormant, fake-local, or
operator-ready". Sourced from docs/current/PRODUCT_CAPABILITY_AUDIT.md §4.

学习型说明：
声明式数据模块 —— 把审计基线表成结构化数据，供 `python main.py capability-status`
渲染。与审计同步是 G-003 authority-consistency 检查的职责。任何 maturity 升级必须有
real API / real trigger / operator validation 证据，或显式「Boundary:」替代验证+边界
说明（用户 L6 标准：替代验证+边界允许），不得无证据口头升级。

L6 (released) criteria (user-defined): MODULE_GOAL/GAP recorded; code real-usable;
tests pass; ≥1 real API/trigger dogfood OR 替代验证+boundary; operator
status/diagnostics/evidence; safety boundaries clear; release summary; independent
audit no overclaim. Each L6 module below cites its real dogfood (G-0xx) or states a
"Boundary:" for the替代-verified parts — transparency, not overclaim.

Levels: L0 not_started / L1 scaffolded / L2 seam_proven (dormant ok) /
L3 fake_local_verified / L4 real_api_verified / L5 operator_ready / L6 released.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CapabilityStatus:
    """单个能力模块的成熟度与状态声明。"""

    module: str
    level: str  # L0..L6
    state: str  # active / dormant / fake-local / seam
    real_api_verified: bool
    operator_ready: bool
    detail: str  # 证据 + 「Boundary:」边界（脱敏，永不放 secret）


# Source: docs/current/PRODUCT_CAPABILITY_AUDIT.md §4 + Phase 0-6 gap closures.
# Keep in sync via the G-003 authority-consistency check at each phase exit.
CAPABILITY_STATUSES: tuple[CapabilityStatus, ...] = (
    CapabilityStatus(
        "Core governed runtime spine", "L6", "active", True, True,
        "Released: real governed tool-use spine — real provider -> interactive CLI "
        "-> governed tool_use -> evidence/checkpoint (R-series Run 12 + reproducible "
        "G-010 write_file / G-015 edit_file dogfood, opt-in). Operator surface: "
        "capability-status + OPERATOR_GUIDE + G-037 onboarding fix.",
    ),
    CapabilityStatus(
        "Provider/model boundary", "L6", "active", True, True,
        "Released for DeepSeek anthropic_compatible (real-verified R-series + opt-in "
        "smokes + status redaction R-004). Boundary: Kimi/GLM are config-exists "
        "(~L2), NOT released; GLM openai_compatible streaming is fail-closed. Do "
        "not generalize DeepSeek to all providers.",
    ),
    CapabilityStatus(
        "Interactive CLI / operator workflow", "L6", "active", True, True,
        "Released: the operator surface itself — capability-status command (G-007), "
        "OPERATOR_GUIDE runbook + provider/evidence/governance/tool matrices "
        "(G-008/011/014/018), status/health/logs/sessions, reproducible dogfood, "
        "onboarding consistent (G-037).",
    ),
    CapabilityStatus(
        "Tool runtime and registry", "L6", "active", True, True,
        "Tool PLATFORM L6: registry/schema/provider-visible-name/mediator/executor/"
        "result/error/diagnostics/governance/audit — real-exercised (evidence-only "
        "TOOL_INVOKE AST-pinned). Tool FAMILIES (per-family, NOT all L6): file "
        "write/edit L6 (G-010/G-015), read-only L6 (G-039 read_file real), memory "
        "L6 (G-019), meta/system L6; external/network (fetch_url/install_skill) L3 "
        "(NOT real-proven); shell/exec (run_shell) forbidden for autonomous use "
        "(confirmation=always+high-risk, G-039 governance-pinned); MCP tools L4 "
        "(G-025). See OPERATOR_GUIDE §10 family table.",
    ),
    CapabilityStatus(
        "Confirmation / governance / policy", "L6", "active", True, True,
        "Released: governed confirmation gate real-exercised for write_file/edit_file "
        "(G-010/G-015); trial-approval default-off + safe-allowlist; TOOL_INVOKE "
        "evidence-only. Boundary: the full governance matrix (rejection escalation, "
        "force_stop, plan/step/user-input) is contract-proven, not all real-exercised.",
    ),
    CapabilityStatus(
        "Evidence / audit / observability", "L6", "active", True, True,
        "Released: evidence WRITE path real-recorded (R-series Run 12/14; redaction "
        "FINAL-G03; verifier FINAL-G04). Boundary: the operator INSPECTION path is "
        "L3 (use the redacted `logs` surface; module-level browsing not real-exercised).",
    ),
    CapabilityStatus(
        "Security / config diagnostics", "L6", "active", True, True,
        "Released: status api_key redaction real-config-verified (G-004 opt-in); "
        "AST boundaries forbid non-provider SDK imports; G-036 diagnostic secret-safety "
        "contract (status/health/provider-diagnostics, default-run). Boundary: real-key "
        "redaction proven for `status` only; broad diagnostic hardening is contract-level.",
    ),
    CapabilityStatus(
        "Checkpoint / session / resume", "L6", "active", True, True,
        "Released: checkpoint save real (Run 12); resume real-trigger-verified (R-G03 "
        "contract + CLI subprocess startup test). Boundary: complex Ctrl+C mid-flight "
        "interrupt (active provider call in flight) is NOT PTY-validated — finish or "
        "cleanly interrupt a turn before resuming.",
    ),
    CapabilityStatus(
        "Durable task ledger / recovery", "L6", "active", False, True,
        "Released as a safe-summary durability record (S5 closed, TD-011 resolved). "
        "替代验证+boundary: the ledger is audit/continuity only, NOT canonical state; "
        "no real-provider recovery trial by design (safe-summary, not state-source). "
        "Inspect via `logs` / `sessions inventory`.",
    ),
    CapabilityStatus(
        "Memory", "L6", "active", True, True,
        "Released: real write/recall/audit (G-019 reproducible real DeepSeek dogfood — "
        "MEMORY_REMEMBER_REQUEST -> memory_confirmation approval -> stored -> "
        "list_records recall). Operator review via `memory extract/index/archive`. "
        "Boundary: consolidation frozen across 6 modules; LLM consolidation default-off.",
    ),
    CapabilityStatus(
        "Skill system", "L6", "active", True, True,
        "Released: real select/execute (G-022 reproducible real DeepSeek dogfood — "
        "SKILL_SELECT demo-note-maker -> demo.write_demo_note -> governed approval -> "
        "note written). Boundary: fixture/sample skills only; no real private skill dir.",
    ),
    CapabilityStatus(
        "MCP config / bridge", "L6", "active", True, True,
        "Released: real local stdio MCP flight (G-025 default-run — connect/list/call/"
        "result against a safe LOCAL fixture server, real StdioMCPClient transport). "
        "Activation default-off (env-gate, safety). Boundary: external/npx endpoint "
        "flight is opt-in (test_real_mcp_flight.py); multi-server ecosystem TD-009.",
    ),
    CapabilityStatus(
        "SubAgent (bounded delegation)", "L6", "fake-local", False, True,
        "BOUNDED SubAgent L6: parent->child delegation, read-only local_fake child, "
        "governed/audited/no-writable (G-027 default-run). Boundary: the bounded "
        "child is local_fake BY DESIGN (read-only safety). NOT released: writable/"
        "general SubAgent (frozen TD-010) and multi-agent autonomy — see OPERATOR_"
        "GUIDE §14 industry-grade checklist (lifecycle/cancel/timeout/failure-"
        "recovery/context-isolation not full for a real child).",
    ),
    CapabilityStatus(
        "Planning / task orchestration", "L6", "active", True, True,
        "Released: the action dispatch spine is real-exercised every real turn "
        "(RuntimeActionDispatcher + LoopDependencies). Boundary: bounded to the current "
        "governed runtime; broader structured-task autonomy deferred (G-035 guardrail).",
    ),
    CapabilityStatus(
        "Fake / local deterministic support", "L3", "fake-local", False, False,
        "Test/support by design (FakeProvider default; deterministic; underpins "
        "CI/contracts/demos). L6 N/A — not a productizable real capability; never read "
        "fake success as real-API readiness.",
    ),
    CapabilityStatus(
        "Scheduler / action-planning", "L2", "dormant", False, False,
        "NOT L6 — concrete code-level blocker. Dormant by design (TD-008, AST-pinned: "
        "chat() action_scheduler=None, main.py never passes the kwarg). Activation "
        "requires building safety gates (G-031) + wiring action_scheduler into chat() + "
        "a real scheduled-action dogfood — a deliberately-deferred major autonomy "
        "change, not a productization gap. Waking it must be a separately-authorized "
        "effort per the user rule 'only activate after safety gate/operator control'.",
    ),
    CapabilityStatus(
        "TUI / visual shell", "L2", "seam", False, False,
        "NOT L6 — concrete architecture blocker. TUI is a SEPARATE Node.js/TypeScript "
        "companion app (not the Python runtime); the Python --tui backend switch + "
        "input_backends exist. L6 requires a Node-side real-provider smoke through the "
        "TUI — a separate-language productization. Capability truth is stable (G-007), "
        "so TUI promotion is unblocked-in-principle but needs the Node app exercised.",
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
        "L6 modules cite a real dogfood (G-0xx) or a 'Boundary:' 替代-verification. "
        "No secret; all real smokes opt-in except where noted."
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
