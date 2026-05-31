"""skill.selection.entered / skill.candidates.built probe handler。

这两个 action 是每 turn 无条件执行的 probe event——只记录 selection phase 的
输入和输出 metadata，不执行任何业务逻辑。handler 将 request payload 透传至
evidence，确保 dogfood/harness 能从 action_log 中提取 candidate_count、
candidate_names 等字段，而不是依赖 `not_supported`（无 handler）的空白 evidence。
"""

from __future__ import annotations

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


class SkillSelectionProbeHandler:
    """skill.selection.entered 和 skill.candidates.built 的轻量 handler。

    只做 evidence 记录，不执行任何 invoke_registered_target。
    probe 不需要 L3 trusted target proof——它们本身只是 selection phase
    的 metadata trace，不产生用户可见的业务效果。
    """

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        payload = dict(request.payload)
        evidence_extra = dict(payload)

        return context.success(
            handler_name=type(self).__name__,
            target_module="SkillSelection",
            payload=payload,
            observed_call=None,
            evidence_extra=evidence_extra,
        )
