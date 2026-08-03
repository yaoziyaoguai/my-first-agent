"""013 日常 workspace 的 scripted E2 reference journeys。"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from agent.cli.app import run_repl
from agent.cli.render import TerminalRenderer
from agent.composition import build_composition
from agent.runtime.checkpoint import LocalCheckpointStore
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import (
    CompletionClaim,
    ConversationState,
    GoalProposal,
    GoalStatus,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    ProposedCriterion,
    canonical_json_digest,
)
from agent.runtime.loop import InvocationLimits
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_registrations
from main import EVERYDAY_SYSTEM_POLICY
from tests.continuity.test_contracts import _goal
from tests.kernel.fakes import ScriptedProvider


def _composition(provider, store, workspace: Path, output: list[str]):
    renderer = TerminalRenderer(output.append)
    composition = build_composition(
        provider=provider,
        checkpoint_store=store,
        tool_registrations=build_file_tool_registrations(workspace),
        event_sink=renderer,
        system_policy=EVERYDAY_SYSTEM_POLICY,
        context_limits=ContextLimits(max_input_tokens=8_000, output_reserve=400),
        invocation_limits=InvocationLimits(),
        workspace_scope_digest="workspace-1",
    )
    return composition.runtime, renderer


def _authority_snapshot(workspace: Path) -> str:
    definitions = KernelToolRuntime(build_file_tool_registrations(workspace)).definitions()
    return canonical_json_digest(
        {
            "version": "fixed-composition-v1",
            "workspace_identity_digest": "workspace-1",
            "provider_descriptor_digest": "local-unbound",
            "tools": [
                {
                    "name": definition.name,
                    "input_schema": definition.input_schema,
                    "side_effect": definition.side_effect.value,
                }
                for definition in definitions
            ],
        }
    )


def _artifact_goal(
    *,
    source_fact_id: str,
    goal_id: str,
    path: str,
    outcome: str,
    authority_snapshot: str,
):
    criterion_id = f"criterion:{goal_id}:content"
    return replace(
        _goal(),
        goal_id=goal_id,
        created_from_fact_ids=(source_fact_id,),
        workspace_identity_digest="workspace-1",
        user_outcome=outcome,
        targets=(path,),
        proposed_criteria=(
            ProposedCriterion(criterion_id, f"{path} reads back with the requested content"),
        ),
        admitted_criteria=(),
        authority_snapshot=authority_snapshot,
    )


def test_everyday_policy_keeps_discussion_goal_free_and_forbids_progress_loops() -> None:
    assert "Discussion, explanation, comparison, and brainstorming are answer-only" in (
        EVERYDAY_SYSTEM_POLICY
    )
    assert "Only an explicit request to create, write, edit, or save" in EVERYDAY_SYSTEM_POLICY
    assert "goal_progress never substitutes for a product tool call" in EVERYDAY_SYSTEM_POLICY


def test_discussion_stays_goal_free_until_explicit_artifact_then_verifies(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes").mkdir()
    store = LocalCheckpointStore.initialize(
        tmp_path / "state" / "conversation.json",
        ConversationState.new("conversation-013-discussion"),
    )
    content = "# Idea\n\nKeep the first version small.\n"
    goal_id = "goal-013-idea"
    criterion_id = f"criterion:{goal_id}:content"
    evidence_id = f"evidence:{goal_id}:1:{criterion_id}"
    provider = ScriptedProvider(
        ModelResponse(
            (ModelTextBlock("A small local-first scope is the strongest starting point."),)
        ),
        ModelResponse(
            (),
            control=GoalProposal(
                "proposal-013-idea",
                _artifact_goal(
                    source_fact_id="action:2:user",
                    goal_id=goal_id,
                    path="notes/idea.md",
                    outcome="Write the discussion conclusion to notes/idea.md",
                    authority_snapshot=_authority_snapshot(workspace),
                ),
            ),
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "write-013-idea",
                    "write_file",
                    {"path": "notes/idea.md", "content": content},
                ),
            )
        ),
        ModelResponse(
            (ModelToolCall("read-013-idea", "read_file", {"path": "notes/idea.md"}),)
        ),
        ModelResponse(
            (),
            control=CompletionClaim(
                # 真实 DeepSeek 曾复用 GoalProposal 的 correlation_id；Runtime 必须
                # 在同一 run 内要求一次有界修复，不能把用户的任务打成 fatal。
                correlation_id="proposal-013-idea",
                goal_id=goal_id,
                goal_revision=1,
                criterion_evidence_refs=(evidence_id,),
            ),
        ),
        ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="completion-013-idea",
                goal_id=goal_id,
                goal_revision=1,
                criterion_evidence_refs=(evidence_id,),
            ),
        ),
    )
    output: list[str] = []
    runtime, renderer = _composition(provider, store, workspace, output)
    inputs = iter(
        (
            "我们讨论一下这个 agent 最初应该多大范围",
            "把刚才结论写成 notes/idea.md",
            "是",
            "/exit",
        )
    )

    exit_code = run_repl(
        runtime,
        store,
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        renderer=renderer,
        run_id_factory=iter(("run-discuss", "run-artifact")).__next__,
    )

    assert exit_code == 0, store.load().state.last_safe_result
    assert (workspace / "notes" / "idea.md").read_text(encoding="utf-8") == content
    final = store.load().state
    assert final.goal is not None and final.goal.status is GoalStatus.VERIFIED_DONE
    assert final.goal.created_from_fact_ids == ("action:2:user",)
    assert "read-013-idea" in final.evidence_records[0].source_fact_ids[-1]
    rendered = "\n".join(output)
    assert "A small local-first scope" in rendered
    assert "Execute this operation? [y/N]" in rendered
    assert "proposal-013-idea" not in rendered
    assert "write-013-idea" not in rendered
    assert "continue" not in rendered.lower()


def test_empty_workspace_can_discover_root_and_create_verified_artifact(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "empty-workspace"
    workspace.mkdir()
    store = LocalCheckpointStore.initialize(
        tmp_path / "state-empty" / "conversation.json",
        ConversationState.new("conversation-013-empty"),
    )
    content = "A bounded first artifact.\n"
    goal_id = "goal-013-empty"
    criterion_id = f"criterion:{goal_id}:content"
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalProposal(
                "proposal-013-empty",
                _artifact_goal(
                    source_fact_id="action:1:user",
                    goal_id=goal_id,
                    path="idea.md",
                    outcome="Create idea.md in the empty workspace",
                    authority_snapshot=_authority_snapshot(workspace),
                ),
            ),
        ),
        ModelResponse((ModelToolCall("list-013-empty", "list_files", {"path": "."}),)),
        ModelResponse(
            (
                ModelToolCall(
                    "write-013-empty",
                    "write_file",
                    {"path": "idea.md", "content": content},
                ),
            )
        ),
        ModelResponse(
            (ModelToolCall("read-013-empty", "read_file", {"path": "idea.md"}),)
        ),
        ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="completion-013-empty",
                goal_id=goal_id,
                goal_revision=1,
                criterion_evidence_refs=(
                    f"evidence:{goal_id}:1:{criterion_id}",
                ),
            ),
        ),
    )
    output: list[str] = []
    runtime, renderer = _composition(provider, store, workspace, output)
    inputs = iter(("在这个空目录创建 idea.md，内容是 A bounded first artifact.", "yes", "/exit"))

    exit_code = run_repl(
        runtime,
        store,
        input_fn=lambda _: next(inputs),
        write_fn=output.append,
        renderer=renderer,
        run_id_factory=lambda: "run-empty",
    )

    assert exit_code == 0, store.load().state.last_safe_result
    assert (workspace / "idea.md").read_text(encoding="utf-8") == content
    final = store.load().state
    assert final.goal is not None and final.goal.status is GoalStatus.VERIFIED_DONE
    assert {path.name for path in workspace.iterdir()} == {"idea.md"}
    assert "list-013-empty" not in "\n".join(output)


def test_existing_workspace_restart_changes_only_target_and_preserves_sentinels(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "README.md"
    target.write_text("Title\nOld summary\n", encoding="utf-8")
    sentinels = {
        workspace / "config.txt": "configuration stays\n",
        workspace / "notes.txt": "unrelated notes stay\n",
    }
    for path, content in sentinels.items():
        path.write_text(content, encoding="utf-8")
    sentinel_digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sentinels
    }
    checkpoint = tmp_path / "state" / "conversation.json"
    store = LocalCheckpointStore.initialize(
        checkpoint,
        ConversationState.new("conversation-013-existing"),
    )
    goal_id = "goal-013-readme"
    criterion_id = f"criterion:{goal_id}:content"
    evidence_id = f"evidence:{goal_id}:1:{criterion_id}"
    provider = ScriptedProvider(
        ModelResponse(
            (),
            control=GoalProposal(
                "proposal-013-readme",
                _artifact_goal(
                    source_fact_id="action:1:user",
                    goal_id=goal_id,
                    path="README.md",
                    outcome="Replace only the README summary line",
                    authority_snapshot=_authority_snapshot(workspace),
                ),
            ),
        ),
        ModelResponse(
            (
                ModelToolCall(
                    "edit-013-readme",
                    "edit_file",
                    {
                        "path": "README.md",
                        "old_text": "Old summary",
                        "new_text": "New bounded summary",
                    },
                ),
            )
        ),
        ModelResponse(
            (ModelToolCall("read-013-readme", "read_file", {"path": "README.md"}),)
        ),
        ModelResponse(
            (),
            control=CompletionClaim(
                correlation_id="completion-013-readme",
                goal_id=goal_id,
                goal_revision=1,
                criterion_evidence_refs=(evidence_id,),
            ),
        ),
    )

    first_output: list[str] = []
    first_runtime, first_renderer = _composition(provider, store, workspace, first_output)
    first_inputs = iter(("只把 README.md 的 Old summary 改成 New bounded summary",))
    first_exit = run_repl(
        first_runtime,
        store,
        input_fn=lambda _: next(first_inputs),
        write_fn=first_output.append,
        renderer=first_renderer,
        run_id_factory=lambda: "run-existing",
    )

    assert first_exit == 0, store.load().state.last_safe_result
    before_restart = store.load().state
    assert before_restart.goal is not None
    assert before_restart.goal.goal_id == goal_id
    assert target.read_text(encoding="utf-8") == "Title\nOld summary\n"
    assert "Execute this operation? [y/N]" in "\n".join(first_output)
    calls_before_restart = len(provider.calls)

    restarted_store = LocalCheckpointStore(checkpoint)
    second_output: list[str] = []
    second_runtime, second_renderer = _composition(
        provider, restarted_store, workspace, second_output
    )
    assert len(provider.calls) == calls_before_restart
    second_inputs = iter(("yes", "/exit"))
    second_exit = run_repl(
        second_runtime,
        restarted_store,
        input_fn=lambda _: next(second_inputs),
        write_fn=second_output.append,
        renderer=second_renderer,
        run_id_factory=lambda: "must-not-create-a-new-run",
    )

    after_restart = restarted_store.load().state
    assert second_exit == 0, (
        second_output,
        after_restart.last_safe_result,
        after_restart.goal,
        after_restart.evidence_records,
        len(provider.calls),
    )
    assert target.read_text(encoding="utf-8") == "Title\nNew bounded summary\n"
    final = restarted_store.load().state
    assert final.goal is not None and final.goal.goal_id == goal_id
    assert final.goal.status is GoalStatus.VERIFIED_DONE
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sentinels
    } == sentinel_digests
    rendered = "\n".join((*first_output, *second_output))
    assert "proposal-013-readme" not in rendered
    assert "edit-013-readme" not in rendered
    assert "continue" not in rendered.lower()
