"""Skill capability 的 Product gate reference task。

候选 reference task（见 roadmap）：给定一个 operator-approved 本地 Skill 及一个
resource，让 Agent 显式激活后按其中规则完成一次领域回答。证据：tool trace、完整未裁剪
guidance、回答中可核对的规则应用。

这里用 FakeProvider 脚本化模型行为，证明 wiring 真实成立：skill body 与 resource 内容
都未裁剪地进入模型上下文，最终回答包含可核对的、仅能从 Skill 获得的产物。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RunStatus,
    SubmitMessage,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from agent.skill.catalog import build_skill_catalog
from agent.skill.tools import build_skill_tool_registrations
from tests.kernel.fakes import CollectingSink, InMemoryCheckpointStore, ScriptedProvider

SKILL_BODY = (
    "Summarize the release for the operator.\n"
    "Rule: the summary MUST end with the literal token READY.\n"
)
VERSION_RESOURCE = "version: 1.2.3\n"
FINAL_ANSWER = "Release 1.2.3 ships the new file tools. READY"


def _context_blob(pack) -> str:
    return json.dumps([list(message.content) for message in pack.messages])


def _build_skill_tree(tmp_path: Path) -> Path:
    root = tmp_path / "roots"
    skill_dir = root / "release-notes"
    references = skill_dir / "references"
    references.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\nname: release-notes\ndescription: Summarize a release.\n"
        f"---\n{SKILL_BODY}",
        encoding="utf-8",
    )
    references.joinpath("version.txt").write_text(VERSION_RESOURCE, encoding="utf-8")
    return root


def test_skill_reference_task_applies_guidance_and_resource(tmp_path: Path) -> None:
    root = _build_skill_tree(tmp_path)
    catalog = build_skill_catalog([root])
    max_tool_result_chars = 8_000
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    provider = ScriptedProvider(
        ModelResponse((ModelToolCall("call-1", "skill__release-notes", {}),)),
        ModelResponse(
            (
                ModelToolCall(
                    "call-2",
                    "skill__read_resource",
                    {"skill_name": "release-notes", "path": "references/version.txt"},
                ),
            )
        ),
        ModelResponse((ModelTextBlock(FINAL_ANSWER),)),
    )
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(
                max_input_tokens=12_000,
                output_reserve=200,
                max_tool_result_chars=max_tool_result_chars,
            ),
        ),
        tool_runtime=KernelToolRuntime(
            build_skill_tool_registrations(
                catalog, max_tool_result_chars=max_tool_result_chars
            )
        ),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
        invocation_id_factory=lambda: "invocation-1",
    )

    result = runtime.run_turn(
        SubmitMessage(
            conversation_id="conversation-1",
            action_seq=1,
            expected_revision=0,
            run_id="run-1",
            message="summarize the release using the skill",
        ),
        store.load(),
    )

    # 一次 logical run 经历 3 次 provider 调用：激活 -> 读资源 -> 终态回答。
    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 3
    assert result.message == FINAL_ANSWER

    # 完整未裁剪 guidance（skill body）进入第二次 provider 调用的上下文。
    assert "the summary MUST end with the literal token READY" in _context_blob(
        provider.calls[1]
    )
    # 资源内容进入第三次 provider 调用的上下文。
    assert "version: 1.2.3" in _context_blob(provider.calls[2])

    # 可核对的规则应用：最终回答同时包含仅能从 resource 获得的版本号与 skill 规则要求的 READY 收尾。
    assert "1.2.3" in result.message
    assert result.message.endswith("READY")
