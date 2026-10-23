"""公开、离线的确认负担探针；只用内存状态/ScriptedProvider，不读取真实会话。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from agent.runtime.contracts import (  # noqa: E402
    AcknowledgeProviderDisclosure,
    ConversationState,
    ModelResponse,
    ModelTextBlock,
    PauseGoal,
    ResumeGoal,
    RunStatus,
    SubmitMessage,
)
from tests.cli.test_contextual_decisions import (  # noqa: E402
    _goal_scoped_approval_state,
    _run,
)
from tests.kernel.fakes import (  # noqa: E402
    conversation_with_active_goal,
    goal_noop_response,
)
from tests.provider.test_remote_disclosure import (  # noqa: E402
    _descriptor,
    _runtime,
    _submit,
)


def acknowledge(runtime, store):  # noqa: ANN001, ANN201
    state = store.state
    request = state.provider_disclosure_request
    assert request is not None
    return runtime.run_turn(
        AcknowledgeProviderDisclosure(
            conversation_id=state.conversation_id,
            action_seq=state.next_action_seq,
            expected_revision=state.revision,
            request_digest=request.request_digest,
            acknowledged_at="2026-10-21T00:00:00Z",
        ),
        store.load(),
    )


def file_choices() -> dict:
    """适配层对照；不是完整文件效果证明，完整链由已有 Runtime 测试证明。"""
    state = _goal_scoped_approval_state()
    choices = {}
    for answer in ("yes", "/approve-goal-target"):
        runtime, output, exit_code = _run(state, answer, "/exit")
        action = runtime.actions[0]
        choices[answer] = {
            "approved": action.approved,
            "reuse_file": action.authorize_goal_target,
            "reuse_directory": action.authorize_goal_directory,
            "exit_code": exit_code,
            "prompt_mentions_shortcut": "/approve-goal-target" in output[0],
        }
    return choices


def plain_conversation() -> dict:
    """真实 Runtime 的三轮普通对话；provider 为零网络的脚本替身。"""
    runtime, store, provider = _runtime(
        ConversationState.new("synthetic-consent-friction"),
        _descriptor(),
        responses=tuple(
            ModelResponse((ModelTextBlock("synthetic answer"),)) for _ in range(3)
        ),
    )
    confirmations = []
    for index in range(3):
        state = store.state
        result = runtime.run_turn(
            SubmitMessage(
                conversation_id=state.conversation_id,
                action_seq=state.next_action_seq,
                expected_revision=state.revision,
                run_id=f"run-{index}",
                message=f"synthetic question {index}",
            ),
            store.load(),
        )
        for _ in range(8):
            if result.status is not RunStatus.AWAITING_DISCLOSURE:
                break
            request = store.state.provider_disclosure_request
            assert request is not None
            confirmations.append(
                {"turn": index + 1, "data_classes": list(request.data_classes)}
            )
            result = acknowledge(runtime, store)
        assert result.status is RunStatus.COMPLETED, result.status
    return {
        "user_turns": 3,
        "provider_calls": len(provider.calls),
        "confirmations": confirmations,
    }


def category_set_transition() -> dict:
    """仅检查生产 request builder 的摘要身份；不冒充完整 compaction 旅程。"""
    runtime, _, _ = _runtime(ConversationState.new("category-set"), _descriptor())
    a = ("system_policy", "user_messages")
    b = (*a, "conversation_history")
    previous = None
    changed = []
    for data_classes in (a, b, a, b, b):
        request = runtime._required_disclosure(SimpleNamespace(data_classes=data_classes))
        assert request is not None
        changed.append(request.request_digest != previous)
        previous = request.request_digest
    return {"sequence": ["A", "B", "A", "B", "B"], "digest_requires_new_ack": changed}


def resumed_disclosure() -> dict:
    """复制已有公开 fixture 的暂停/恢复窗口，记录每次确认后的新增打断。"""
    runtime, store, provider = _runtime(
        conversation_with_active_goal(),
        _descriptor(),
        responses=(
            ModelResponse((ModelTextBlock("sent"),)),
            goal_noop_response("synthetic-resume-2"),
        ),
    )
    runtime.run_turn(_submit(store.state), store.load())
    request = store.state.provider_disclosure_request
    assert request is not None
    stages = [{"stage": "before_pause", "data_classes": list(request.data_classes)}]
    for action_type in (PauseGoal, ResumeGoal):
        state = store.state
        goal = state.goal
        assert goal is not None
        runtime.run_turn(
            action_type(
                conversation_id=state.conversation_id,
                action_seq=state.next_action_seq,
                expected_revision=state.revision,
                goal_id=goal.goal_id,
                goal_revision=goal.revision,
            ),
            store.load(),
        )
    for index in range(2):
        result = acknowledge(runtime, store)
        request = store.state.provider_disclosure_request
        assert request is not None
        stages.append(
            {
                "stage": f"after_resume_ack_{index + 1}",
                "status": result.status.value,
                "data_classes": list(request.data_classes),
                "provider_calls": len(provider.calls),
            }
        )
    return {"stages": stages, "scope": "bounded prefix, not a completed task"}


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "schema": "my-first-agent/consent-ux-baseline/v1",
                "source_head": "97f5c584e9e266930fbcf283aa3199b3609e8178",
                "network_calls": 0,
                "private_sessions_read": False,
                "file_choices": file_choices(),
                "plain_conversation": plain_conversation(),
                "category_set_transition": category_set_transition(),
                "resumed_disclosure": resumed_disclosure(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
