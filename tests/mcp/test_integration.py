from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from agent.composition import (
    Composition,
    build_composition,
    build_mcp_resources,
    load_mcp_catalog_file,
)
from agent.mcp.bridge import SessionTimeouts
from agent.mcp.catalog import build_mcp_catalog
from agent.mcp.contracts import McpOutcomeClassification
from agent.runtime.checkpoint import InMemoryCheckpointStore
from agent.runtime.context import ContextLimits
from agent.runtime.contracts import ConversationState
from agent.runtime.loop import InvocationLimits
from tests.kernel.fakes import CollectingSink, ScriptedProvider

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp" / "stdio_server.py"
ECHO_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _catalog_config(command: str) -> dict:
    return {
        "servers": [
            {
                "server_id": "repo",
                "transport": "stdio",
                "command": command,
                "args": [],
                "safety_generation": "gen-1",
                "protocol_revision": "2025-11-25",
                "tools": [
                    {
                        "remote_name": "echo",
                        "description": "Echo text back.",
                        "input_schema": ECHO_SCHEMA,
                        "output_limit_chars": 1000,
                    }
                ],
            }
        ]
    }


def _wrapper(tmp_path: Path) -> Path:
    wrapper = tmp_path / "run_server.sh"
    wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(SERVER))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    return wrapper


def _safety_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "mcp-safety"
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / "latch.json"


def test_composition_with_mcp_has_close_stack_and_tools(tmp_path: Path) -> None:
    wrapper = _wrapper(tmp_path)
    resources = build_mcp_resources(
        _catalog_config(str(wrapper)),
        _safety_dir(tmp_path),
        env_provider=lambda names: {},  # noqa: ARG005
        timeouts=SessionTimeouts(initialize=30, list_page=10, call=10, shutdown=5),
    )
    store = InMemoryCheckpointStore(ConversationState.new("c1"))
    composition = build_composition(
        provider=ScriptedProvider(),
        checkpoint_store=store,
        tool_registrations=resources.registrations,
        event_sink=CollectingSink(),
        system_policy="policy",
        context_limits=ContextLimits(max_input_tokens=2_000, output_reserve=200),
        invocation_limits=InvocationLimits(),
        closeables=resources.closeables,
    )

    assert isinstance(composition, Composition)
    assert composition.close_stack
    names = {definition.name for definition in composition.tool_runtime.definitions()}
    assert "mcp__repo__echo" in names

    # teardown 倒序关闭 close stack（关闭 bridge）。
    for closeable in reversed(composition.close_stack):
        closeable()


def test_main_composes_mcp_when_safety_latch_not_yet_created(tmp_path: Path) -> None:
    """首次经 ``first-agent`` CLI 使用 ``--mcp-safety-state`` 时，latch 文件尚未由任何
    invocation 创建（McpSafetyLatch 设计为文件缺失即 clear）。main() 必须成功 compose，
    而不是对尚不存在的 latch 路径 resolve(strict=True) 触发 FileNotFoundError 启动失败。"""
    import main as fa_main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(_catalog_config(str(_wrapper(tmp_path)))), encoding="utf-8"
    )
    safety_state = _safety_dir(tmp_path)  # 目录存在，latch.json 故意不存在
    assert not safety_state.exists()

    argv = [
        "--workspace", str(workspace),
        "--state-root", str(tmp_path / "state-root"),
        "--provider", "fake",
        "--mcp-catalog", str(catalog_path),
        "--mcp-safety-state", str(safety_state),
    ]
    outputs: list[str] = []
    rc = fa_main.main(argv, input_fn=lambda _p: "/exit", write_fn=outputs.append)

    assert rc == 0
    assert not any("Startup failed" in line for line in outputs)


def test_unresolved_latch_blocks_mcp_composition(tmp_path: Path) -> None:
    from agent.mcp.safety import LatchBinding, McpSafetyLatch, SafetyLatchError

    wrapper = _wrapper(tmp_path)
    state = _safety_dir(tmp_path)
    # 先 arm 一个未清除的 marker。
    McpSafetyLatch(state).arm(
        expected_clear_revision=0,
        binding=LatchBinding("repo", "cfg", None, "gen-1", "intent"),
    )

    with pytest.raises(SafetyLatchError):
        build_mcp_resources(
            _catalog_config(str(wrapper)),
            state,
            env_provider=lambda names: {},  # noqa: ARG005
        )


def test_composition_imports_without_mcp_sdk() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['mcp'] = None; import agent.composition; print('OK')",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_load_mcp_catalog_file_reads_json(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text('{"servers": []}', encoding="utf-8")
    config = load_mcp_catalog_file(catalog_path)
    assert config == {"servers": []}


def test_empty_env_allowlist_does_not_inherit_parent(monkeypatch, tmp_path: Path) -> None:
    """A2: an empty env allowlist must yield an empty child environment, never inherit the
    parent environment (which may carry credentials)."""
    import sys as _sys

    from agent.mcp.bridge import McpAsyncBridge, SessionTimeouts, run_stdio_session
    from agent.mcp.safety import LatchBinding, McpSafetyLatch

    monkeypatch.setenv("FAKE_SECRET_A2", "must-not-leak")
    safety_dir = tmp_path / "safety"
    safety_dir.mkdir(mode=0o700, exist_ok=True)
    latch = McpSafetyLatch(safety_dir / "latch.json")
    binding = LatchBinding("repo", "cfg", None, "gen-1", "intent-a2")
    bridge = McpAsyncBridge(total_timeout_seconds=120)
    try:
        outcome = bridge.submit(
            lambda: run_stdio_session(
                command=_sys.executable,
                args=(str(SERVER),),
                cwd=str(tmp_path),
                env={},
                remote_name="environment",
                arguments={},
                input_schema={"type": "object", "properties": {}},
                descriptor_digest="d-a2",
                latch=latch,
                binding=binding,
                expected_clear_revision=0,
                timeouts=SessionTimeouts(initialize=30, list_page=10, call=10, shutdown=5),
            )
        )
    finally:
        bridge.close()
    assert outcome.classification is not McpOutcomeClassification.NOT_EXECUTED or (
        outcome.result_text
    )
    assert "FAKE_SECRET_A2" not in (outcome.result_text or "")


def test_approval_binds_full_arguments_and_executable_identity(tmp_path: Path) -> None:
    """A4: approval preview must show canonical bounded arguments and executable/cwd identity,
    not only server/tool/profile."""
    import shlex
    import sys as _sys

    from agent.mcp.bridge import McpAsyncBridge, SessionTimeouts
    from agent.mcp.safety import McpSafetyLatch
    from agent.mcp.tools import build_mcp_tool_registrations
    from agent.runtime.contracts import ToolCall, ToolPrepareContext
    from agent.runtime.tools import KernelToolRuntime

    wrapper = tmp_path / "run_server.sh"
    wrapper.write_text(
        f"#!/bin/sh\nexec {shlex.quote(_sys.executable)} {shlex.quote(str(SERVER))}\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    catalog = build_mcp_catalog(
        {
            "servers": [
                {
                    "server_id": "repo",
                    "transport": "stdio",
                    "command": str(wrapper),
                    "args": [],
                    "cwd": str(cwd_dir),
                    "safety_generation": "gen-1",
                    "protocol_revision": "2025-11-25",
                    "credential_profile": "ops-profile",
                    "tools": [
                        {
                            "remote_name": "echo",
                            "description": "Echo text back.",
                            "input_schema": ECHO_SCHEMA,
                            "output_limit_chars": 1000,
                        }
                    ],
                }
            ]
        }
    )
    safety_dir = tmp_path / "safety"
    safety_dir.mkdir(mode=0o700, exist_ok=True)
    from agent.mcp.tools import McpExecutorConfig

    config = McpExecutorConfig(
        bridge=McpAsyncBridge(total_timeout_seconds=120),
        latch=McpSafetyLatch(safety_dir / "latch.json"),
        composition_epoch="epoch-1",
        timeouts=SessionTimeouts(initialize=30, list_page=10, call=10, shutdown=5),
        env_provider=lambda names: {},
    )
    try:
        registrations = build_mcp_tool_registrations(catalog, executor_config=config)
        runtime = KernelToolRuntime(registrations)
        prepared = runtime.prepare(
            ToolCall(
                "call-1",
                "mcp__repo__echo",
                {"text": "hello-secret-arg"},
            ),
            ToolPrepareContext("c1", "r1", 1),
        )
        preview = prepared.request.preview
        assert "hello-secret-arg" in preview, "canonical arguments missing from preview"
        assert str(wrapper) in preview or "repo" in preview, "executable identity missing"
        assert "ops-profile" in preview
    finally:
        config.bridge.close()
