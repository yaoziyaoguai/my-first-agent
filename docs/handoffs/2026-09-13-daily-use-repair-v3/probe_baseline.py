"""观察当前日常使用缺口；只操作自己创建的合成临时数据，不调用真实 provider。"""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

from agent.composition import build_owner_preference_resources
from agent.continuity.sessions import (
    open_workspace_session,
    select_workspace_candidate,
)
from agent.memory.store import MemoryStoreError
from agent.provider.config import AgentProviderConfig
from agent.runtime.contracts import ToolCall, ToolPrepareContext, ToolResult
from agent.tools.file_ops import build_file_tool_runtime
from main import main as product_main


def emit(case: str, **observations: object) -> None:
    print(json.dumps({"case": case, **observations}, sort_keys=True))


def observe_file_boundaries(workspace: Path) -> None:
    context = ToolPrepareContext("conversation-audit", "run-audit", 1)
    runtime = build_file_tool_runtime(workspace)
    prepared = runtime.prepare(
        ToolCall("write-1", "write_file", {"path": "reports/daily.md", "content": "ok"}),
        context,
    )
    rejected = isinstance(prepared, ToolResult) and prepared.is_error
    emit(
        "missing_parent",
        rejected=rejected,
        code=prepared.metadata.get("code") if isinstance(prepared, ToolResult) else None,
        parent_created=(workspace / "reports").exists(),
    )

    for index, relative_path in enumerate(("config/app.yaml", "pytest.ini", "normal.txt")):
        target = workspace / relative_path
        target.parent.mkdir(exist_ok=True)
        target.write_text("public synthetic fixture\n", encoding="utf-8")
        prepared = runtime.prepare(
            ToolCall(f"read-{index}", "read_file", {"path": relative_path}),
            context,
        )
        emit(
            "ordinary_project_path",
            path=relative_path,
            rejected=isinstance(prepared, ToolResult) and prepared.is_error,
        )


def observe_conversations(workspace: Path, state_root: Path) -> None:
    conversation_ids = []
    for index in range(1, 18):
        conversation_id = f"00000000-0000-4000-8000-{index:012d}"
        conversation_ids.append(conversation_id)
        open_workspace_session(
            workspace,
            state_root=state_root,
            force_new=True,
            conversation_id_factory=lambda cid=conversation_id: cid,
        )
    selection = open_workspace_session(workspace, state_root=state_root)
    visible_ids = {item.conversation_id for item in selection.candidates}
    last_id = conversation_ids[-1]
    candidate = replace(
        selection.candidates[0],
        conversation_id=last_id,
        checkpoint_path=selection.candidates[0].checkpoint_path.with_name(f"{last_id}.json"),
    )
    try:
        select_workspace_candidate(selection, candidate)
    except ValueError:
        direct_selection = "rejected"
    else:
        direct_selection = "accepted"

    # 输入有界，分页实现后即使非法输入改为重试，也不会卡在永久返回 17 的 fixture 中。
    answers = iter(("17",))
    messages: list[str] = []
    cli_exit = product_main(
        ["--workspace", str(workspace), "--state-root", str(state_root), "--provider", "fake"],
        input_fn=lambda _: next(answers),
        write_fn=messages.append,
    )
    emit(
        "17_conversations",
        stored=selection.total_active_count,
        visible=len(visible_ids),
        last_created_visible=last_id in visible_ids,
        direct_selection=direct_selection,
        cli_choose_17_exit=cli_exit,
    )


def observe_model_switch(preferences: Path) -> None:
    first = AgentProviderConfig(
        provider_type="openai_compatible",
        model="model-a",
        base_url="https://provider.example",
    ).descriptor()
    second = AgentProviderConfig(
        provider_type="openai_compatible",
        model="model-b",
        base_url="https://provider.example",
    ).descriptor()
    build_owner_preference_resources(preferences, provider_trust_digest=first.identity_digest)
    original_bytes = preferences.read_bytes()
    try:
        build_owner_preference_resources(preferences, provider_trust_digest=second.identity_digest)
    except MemoryStoreError:
        model_switch = "rejected"
    else:
        model_switch = "accepted"
    emit(
        "same_endpoint_empty_preferences_model_switch",
        result=model_switch,
        original_bytes_preserved=preferences.read_bytes() == original_bytes,
    )


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="first-agent-v3-baseline-") as temporary_root:
        # macOS 的系统临时目录前缀可能经过 /var symlink；产品收到已解析的合成路径。
        root = Path(temporary_root).resolve(strict=True)
        workspace = root / "project"
        workspace.mkdir()
        observe_file_boundaries(workspace)
        observe_conversations(workspace, root / "state")
        observe_model_switch(root / "synthetic-owner-preferences.json")
    emit("probe_completed", scope="offline_synthetic", product_acceptance="not_evaluated")


if __name__ == "__main__":
    run()
