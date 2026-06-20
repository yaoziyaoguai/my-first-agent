"""S4-G11: optional audit observability（人读 audit 视图，P3 增强）。

把 replay chain（G02，previews 已在投影点经 G03 redaction）渲染成**人可读的、redacted 的**
审计摘要，便于人工/合规快速浏览 agent 做了什么。增强 AC-2/AC-5，非必达、不阻塞 release。

边界：本模块只渲染既有 chain（只读），不重新采集、不持久化、不做外部上报；preview 已 redacted，
渲染安全（注入的 fake secret 不会出现，由 G03 保证 + 本模块测试断言）。
"""

from __future__ import annotations

from agent.evidence_redaction import redact_text
from agent.task_replay_chain import ReplayChain


def render_replay_summary(chain: ReplayChain) -> str:
    """把 replay chain 渲染成人读的、redacted 的审计摘要（每事件一行 + preview）。

    参数:
        chain: ReplayChain（previews 已在 build_replay_chain 经 G03 redaction）。

    返回:
        多行人读字符串；不含 raw secret（preview 经 redact_text 二次保险）。
    """
    lines = [
        f"Replay summary: scope={chain.task_scope_id} lifecycle={chain.lifecycle} "
        f"events={len(chain.events)}"
    ]
    if not chain.events:
        lines.append("  (empty — no governed events projected)")
        return "\n".join(lines)
    for e in chain.events:
        lines.append(
            f"  [{e.seq}] step={e.step_index} {e.kind}: {e.name} "
            f"status={e.status} policy={e.policy_outcome}"
        )
        preview = e.output_preview or e.input_preview
        if preview:
            # preview 已在 chain 投影点 redacted；此处再过一次 redact_text 作 defense-in-depth。
            lines.append(f"      preview: {redact_text(preview)}")
    return "\n".join(lines)


def replay_summary_stats(chain: ReplayChain) -> dict[str, int]:
    """replay chain 的结构化计数摘要（人读/机读双用，全为整数，无 content 泄漏）。"""
    return {
        "total_events": len(chain.events),
        "decision_events": len(chain.decision_events),
        "tool_events": len(chain.tool_events),
        "delegation_events": len(chain.delegation_events),
    }
