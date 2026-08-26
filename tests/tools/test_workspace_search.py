from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import agent.tools.path_safety as path_safety
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import (
    BeginAnswer,
    ConversationState,
    ExecutionIntent,
    ModelResponse,
    ModelTextBlock,
    ModelToolCall,
    RunStatus,
    SubmitMessage,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.loop import AgentRuntime, InvocationLimits
from agent.runtime.tools import IntentConflictError, KernelToolRuntime
from agent.tools.file_ops import build_file_tool_registrations, build_file_tool_runtime
from tests.kernel.fakes import (
    CollectingSink,
    InMemoryCheckpointStore,
    ScriptedProvider,
)


def _invoke(runtime, call: ToolCall):  # noqa: ANN001
    prepared = runtime.prepare(
        call,
        ToolPrepareContext("conversation-1", "run-workspace-search", 1),
    )
    assert isinstance(prepared, ExecutionIntent)
    return runtime.invoke(prepared)


def test_workspace_search_tools_are_in_the_single_file_capability_factory(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    definitions = {definition.name: definition for definition in runtime.definitions()}

    assert set(definitions) == {
        "read_file",
        "list_files",
        "search_paths",
        "search_text",
        "read_file_chunk",
        "write_file",
        "edit_file",
    }
    for name in (
        "read_file",
        "list_files",
        "search_paths",
        "search_text",
        "read_file_chunk",
    ):
        assert definitions[name].side_effect.value == "read_only"


def test_path_search_is_deterministic_and_excludes_private_or_aliased_entries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "docs").mkdir()
    (workspace / "docs" / "alpha-plan.md").write_text("plan", encoding="utf-8")
    (workspace / "z-alpha.txt").write_text("visible", encoding="utf-8")
    (workspace / "sessions").mkdir()
    (workspace / "sessions" / "alpha-secret.txt").write_text(
        "secret", encoding="utf-8"
    )
    outside = tmp_path / "outside-alpha.txt"
    outside.write_text("outside", encoding="utf-8")
    (workspace / "alpha-link.txt").symlink_to(outside)
    os.link(outside, workspace / "alpha-hardlink.txt")
    runtime = build_file_tool_runtime(workspace)

    result = _invoke(
        runtime,
        ToolCall("paths-1", "search_paths", {"query": "alpha", "root": "."}),
    )
    payload = json.loads(result.content)

    assert [item["path"] for item in payload["results"]] == [
        "docs/alpha-plan.md",
        "z-alpha.txt",
    ]
    assert payload["truncated"] is False
    assert "secret" not in result.content
    assert "outside" not in result.content
    receipts = result.metadata["source_receipts"]
    assert {receipt["source_kind"] for receipt in receipts} == {"workspace_path"}
    assert all(not receipt["origin_locator"].startswith("/") for receipt in receipts)


def test_text_search_handles_unicode_replacement_and_skips_binary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "unicode.txt").write_text(
        "第一行\nneedle 与 Unicode\n第三行\n", encoding="utf-8"
    )
    (workspace / "invalid.txt").write_bytes(b"prefix needle \xff suffix\n")
    (workspace / "binary.bin").write_bytes(b"\x00needle\x01")
    runtime = build_file_tool_runtime(workspace)

    result = _invoke(
        runtime,
        ToolCall("text-1", "search_text", {"query": "needle", "root": "."}),
    )
    payload = json.loads(result.content)

    assert [item["path"] for item in payload["results"]] == [
        "invalid.txt",
        "unicode.txt",
    ]
    assert payload["results"][0]["encoding"] == "utf-8-replacement"
    assert payload["results"][1]["line"] == 2
    assert "binary.bin" not in result.content
    assert all(
        receipt["source_kind"] == "workspace_excerpt"
        for receipt in result.metadata["source_receipts"]
    )


def test_read_file_chunk_returns_exact_lines_and_snapshot_receipt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text(
        "one\ntwo\nthree\nfour\n", encoding="utf-8"
    )
    runtime = build_file_tool_runtime(workspace)

    result = _invoke(
        runtime,
        ToolCall(
            "chunk-1",
            "read_file_chunk",
            {"path": "notes.txt", "start_line": 2, "max_lines": 2},
        ),
    )
    payload = json.loads(result.content)

    assert payload == {
        "content": "two\nthree\n",
        "encoding": "utf-8",
        "end_line": 3,
        "path": "notes.txt",
        "start_line": 2,
        "truncated": True,
    }
    receipt = result.metadata["source_receipts"][0]
    assert receipt["origin_locator"] == "notes.txt#L2-L3"
    assert receipt["truncated"] is True
    assert receipt["truncation_reason"] == "line_window"


def test_scan_output_and_byte_caps_are_reported_separately(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for index in range(8):
        (workspace / f"match-{index}.txt").write_text(
            "needle " + "x" * 30,
            encoding="utf-8",
        )
    runtime = build_file_tool_runtime(
        workspace,
        max_scan_entries=5,
        max_search_matches=2,
        max_search_bytes=80,
    )

    paths = _invoke(
        runtime,
        ToolCall("paths-cap", "search_paths", {"query": "match", "root": "."}),
    )
    text = _invoke(
        runtime,
        ToolCall("text-cap", "search_text", {"query": "needle", "root": "."}),
    )
    path_payload = json.loads(paths.content)
    text_payload = json.loads(text.content)

    assert path_payload["truncated"] is True
    assert path_payload["truncation_reason"] in {"scan_entries", "matches"}
    assert len(path_payload["results"]) <= 2
    assert text_payload["truncated"] is True
    assert text_payload["truncation_reason"] in {
        "scan_entries",
        "matches",
        "total_bytes",
    }
    assert len(text_payload["results"]) <= 2


def test_depth_and_deadline_are_independent_traversal_caps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    nested = workspace / "level-one" / "level-two"
    nested.mkdir(parents=True)
    (nested / "target.txt").write_text("needle", encoding="utf-8")
    depth_runtime = build_file_tool_runtime(workspace, max_search_depth=1)

    depth_result = _invoke(
        depth_runtime,
        ToolCall("depth-cap", "search_text", {"query": "needle", "root": "."}),
    )
    depth_payload = json.loads(depth_result.content)

    assert depth_payload["results"] == []
    assert depth_payload["truncated"] is True
    assert depth_payload["truncation_reason"] == "depth"

    monotonic_calls = iter((0.0, 1.0))
    monkeypatch.setattr(path_safety.time, "monotonic", lambda: next(monotonic_calls))
    deadline_runtime = build_file_tool_runtime(
        workspace,
        search_deadline_seconds=0.5,
    )

    deadline_result = _invoke(
        deadline_runtime,
        ToolCall(
            "deadline-cap",
            "search_paths",
            {"query": "target", "root": "."},
        ),
    )
    deadline_payload = json.loads(deadline_result.content)

    assert deadline_payload["results"] == []
    assert deadline_payload["truncated"] is True
    assert deadline_payload["truncation_reason"] == "deadline"


def test_sensitive_tree_is_rejected_before_open_during_recursive_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = workspace / "sessions"
    private.mkdir()
    (private / "NEVER_OPEN_SENTINEL.txt").write_text("needle", encoding="utf-8")
    (workspace / "visible.txt").write_text("needle", encoding="utf-8")
    opened_names: list[str] = []
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):  # noqa: ANN001
        opened_names.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    runtime = build_file_tool_runtime(workspace)

    result = _invoke(
        runtime,
        ToolCall("text-private", "search_text", {"query": "needle", "root": "."}),
    )

    assert "visible.txt" in result.content
    assert "NEVER_OPEN_SENTINEL" not in result.content
    assert "sessions" not in opened_names


def test_nested_private_tree_is_hidden_from_read_list_and_search(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = workspace / "subproject" / ".claude"
    private.mkdir(parents=True)
    private_file = private / "settings.json"
    private_file.write_text("NESTED_PRIVATE_SENTINEL", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall(
            "read-nested-private",
            "read_file",
            {"path": "subproject/.claude/settings.json"},
        ),
        ToolPrepareContext("conversation-1", "run-private", 1),
    )
    listed = _invoke(
        runtime,
        ToolCall("list-nested-private", "list_files", {"path": "subproject"}),
    )
    paths = _invoke(
        runtime,
        ToolCall(
            "paths-nested-private",
            "search_paths",
            {"query": "settings", "root": "."},
        ),
    )
    text = _invoke(
        runtime,
        ToolCall(
            "text-nested-private",
            "search_text",
            {"query": "NESTED_PRIVATE_SENTINEL", "root": "."},
        ),
    )

    assert denied.is_error is True and denied.executed is False
    assert ".claude" not in listed.content
    assert "settings.json" not in paths.content
    assert "NESTED_PRIVATE_SENTINEL" not in text.content
    assert json.loads(paths.content)["results"] == []
    assert json.loads(text.content)["results"] == []


def test_existing_read_and_list_now_emit_workspace_source_receipts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("visible content", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)

    listed = _invoke(runtime, ToolCall("list-source", "list_files", {"path": "."}))
    read = _invoke(
        runtime,
        ToolCall("read-source", "read_file", {"path": "visible.txt"}),
    )

    assert listed.metadata["source_receipts"][0]["source_kind"] == "workspace_path"
    read_receipt = read.metadata["source_receipts"][0]
    assert read_receipt["source_kind"] == "workspace_excerpt"
    assert read_receipt["origin_locator"] == "visible.txt"
    assert read_receipt["data_class"] == "workspace_excerpt"


def test_search_revalidates_root_identity_after_prepare(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docs = workspace / "docs"
    docs.mkdir()
    (docs / "inside.txt").write_text("needle", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle OUTSIDE_SENTINEL", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall("swap-1", "search_text", {"query": "needle", "root": "docs"})
    prepared = runtime.prepare(
        call,
        ToolPrepareContext("conversation-1", "run-swap", 1),
    )
    assert isinstance(prepared, ExecutionIntent)
    docs.rename(workspace / "docs-old")
    docs.symlink_to(outside, target_is_directory=True)

    with pytest.raises(IntentConflictError, match="preconditions changed"):
        runtime.invoke(prepared)


def test_text_search_rejects_file_identity_swap_between_scan_and_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    visible = workspace / "visible.txt"
    visible.write_text("public needle", encoding="utf-8")
    replacement = workspace / "replacement.txt"
    replacement.write_text("PRIVATE_SWAP_SENTINEL needle", encoding="utf-8")
    boundary = path_safety.WorkspaceBoundary(workspace)
    real_open_regular = boundary._open_regular  # noqa: SLF001
    swapped = False

    def swap_then_open(parent_fd, name, *, expected=None, mutation=False):  # noqa: ANN001
        nonlocal swapped
        if name == "visible.txt" and not swapped:
            swapped = True
            os.replace(replacement, visible)
        return real_open_regular(
            parent_fd,
            name,
            expected=expected,
            mutation=mutation,
        )

    monkeypatch.setattr(boundary, "_open_regular", swap_then_open)

    with pytest.raises(path_safety.WorkspaceSecurityError, match="identity changed"):
        boundary.search_text(
            "needle",
            root=".",
            max_results=5,
            limits=path_safety.TraversalLimits(),
        )


def test_workspace_search_result_enters_next_model_context_as_untrusted_source(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "decision.md").write_text(
        "The durable choice is local-first.", encoding="utf-8"
    )
    provider = ScriptedProvider(
        ModelResponse((), control=BeginAnswer("begin-workspace-search")),
        ModelResponse(
            (
                ModelToolCall(
                    "search-e2",
                    "search_text",
                    {"query": "local-first", "root": "."},
                ),
            )
        ),
        ModelResponse((ModelTextBlock("The workspace says local-first."),)),
    )
    store = InMemoryCheckpointStore(ConversationState.new("conversation-1"))
    runtime = AgentRuntime(
        provider=provider,
        context_manager=KernelContextManager(
            system_policy="policy",
            limits=ContextLimits(max_input_tokens=8_000, output_reserve=500),
        ),
        tool_runtime=KernelToolRuntime(build_file_tool_registrations(workspace)),
        checkpoint_store=store,
        event_sink=CollectingSink(),
        limits=InvocationLimits(),
    )
    action = SubmitMessage(
        conversation_id="conversation-1",
        action_seq=1,
        expected_revision=0,
        run_id="run-workspace-e2",
        message="What did this workspace decide?",
    )

    result = runtime.run_turn(action, store.load())

    assert result.status is RunStatus.COMPLETED
    assert len(provider.calls) == 3
    assert "workspace_excerpt" in provider.calls[2].data_classes
    source_blocks = [
        block
        for message in provider.calls[2].messages
        for block in message.content
        if block.get("type") == "tool_result"
    ]
    assert source_blocks and source_blocks[0]["untrusted"] is True
    assert source_blocks[0]["metadata"]["source_receipts"][0]["source_kind"] == (
        "workspace_excerpt"
    )
