"""从仓库外验证 wheel 中的 D0-D4；只使用合成数据与 MockTransport。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

import agent
import main as entrypoint
from agent.composition import build_owner_preference_resources
from agent.continuity.sessions import open_workspace_session
from agent.process.tools import build_local_process_registration
from agent.provider.config import AgentProviderConfig
from agent.provider.openai_http import OpenAICompatibleProvider
from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    BudgetReport,
    ContextPack,
    ExecutionIntent,
    ProcessAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.ports import ModelAttemptBudgetExhaustedError
from agent.runtime.tools import KernelToolRuntime
from agent.tools.file_ops import build_file_tool_runtime
from agent.transport_audit import TransportAttemptLedger


def _record(cases: list[dict[str, object]], case_id: str, passed: bool, **facts: object) -> None:
    cases.append({"id": case_id, "pass": passed, **facts})


def _invoke(runtime, call: ToolCall, context: ToolPrepareContext):
    prepared = runtime.prepare(call, context)
    if not isinstance(prepared, ExecutionIntent):
        raise AssertionError(f"unexpected prepare result: {type(prepared).__name__}")
    return runtime.invoke(prepared)


def _approve(runtime, call: ToolCall, context: ToolPrepareContext):
    requested = runtime.prepare(call, context)
    if not isinstance(requested, ApprovalRequired):
        raise AssertionError(f"approval missing: {type(requested).__name__}")
    prepared = runtime.prepare(
        call,
        context,
        approval=ApprovalGrant(
            requested.request.request_id,
            requested.request.binding_digest,
        ),
    )
    if not isinstance(prepared, ExecutionIntent):
        raise AssertionError(f"approved intent missing: {type(prepared).__name__}")
    return runtime.invoke(prepared)


def _approve_process(runtime, call: ToolCall, context: ToolPrepareContext):
    requested = runtime.prepare(call, context)
    if not isinstance(requested, ApprovalRequired):
        raise AssertionError(f"process approval missing: {type(requested).__name__}")
    candidate = requested.request.process_authority_candidate
    if candidate is None:
        raise AssertionError("process authority candidate missing")
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity=requested.request.request_id,
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )
    prepared = runtime.prepare(
        call,
        ToolPrepareContext(
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            state_revision=context.state_revision,
            goal_id=context.goal_id,
            goal_revision=context.goal_revision,
            workspace_identity_digest=context.workspace_identity_digest,
            process_leases=(lease,),
        ),
    )
    if not isinstance(prepared, ExecutionIntent):
        raise AssertionError(f"approved process missing: {type(prepared).__name__}")
    return runtime.invoke(prepared)


def _manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.json"))
    }


def _model_config(model: str) -> AgentProviderConfig:
    return AgentProviderConfig(
        provider_type="openai_compatible",
        model=model,
        base_url="https://provider.invalid",
        credential="synthetic",
    )


def _probe_budget(root: Path, cases: list[dict[str, object]]) -> None:
    secure = root / "budget"
    secure.mkdir(mode=0o700)
    ledger_path = secure / "attempts.jsonl"
    TransportAttemptLedger(ledger_path, max_model_attempts=1).record(
        "model", "https://provider.invalid"
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "unused"}}]})

    context = ContextPack(
        system="policy",
        messages=(),
        tools=(),
        budget=BudgetReport(
            input_limit=2_000,
            estimated_input_tokens=100,
            output_reserve=200,
        ),
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            config=_model_config("budget-model"),
            http_client=client,
            attempt_recorder=TransportAttemptLedger(
                ledger_path, max_model_attempts=1
            ).record,
        )
        try:
            provider.generate(context)
        except ModelAttemptBudgetExhaustedError:
            blocked = True
        else:
            blocked = False
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    _record(
        cases,
        "D0-installed-cumulative-budget",
        blocked and requests == [] and len(lines) == 1,
        blocked_before_dispatch=blocked and requests == [],
        ledger_model_attempts=len(lines),
    )


def _probe_paths_and_directory(root: Path, cases: list[dict[str, object]]) -> None:
    workspace = root / "workspace-files"
    config = workspace / "config"
    config.mkdir(parents=True)
    (config / "app.yaml").write_text("export_format: csv\n", encoding="utf-8")
    (config / ".env").write_text("SECRET=synthetic\n", encoding="utf-8")
    (workspace / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    runtime = build_file_tool_runtime(
        workspace,
        project_paths=("config/app.yaml", "pytest.ini"),
    )
    context = ToolPrepareContext("conversation", "run", 1)
    app = _invoke(runtime, ToolCall("read-1", "read_file", {"path": "config/app.yaml"}), context)
    pytest_config = _invoke(
        runtime,
        ToolCall("read-2", "read_file", {"path": "pytest.ini"}),
        context,
    )
    denied = runtime.prepare(
        ToolCall("read-3", "read_file", {"path": "config/.env"}),
        context,
    )
    _record(
        cases,
        "D1-installed-project-paths",
        app.content == "export_format: csv\n"
        and "testpaths = tests" in pytest_config.content
        and isinstance(denied, ToolResult)
        and denied.is_error,
        public_values_read=True,
        sensitive_path_denied=isinstance(denied, ToolResult) and denied.is_error,
    )

    directory_result = _approve(
        runtime,
        ToolCall("mkdir-1", "make_directory", {"path": "reports"}),
        context,
    )
    file_result = _approve(
        runtime,
        ToolCall(
            "write-1",
            "write_file",
            {"path": "reports/daily.md", "content": "# Daily\nApproved fixture.\n"},
        ),
        context,
    )
    readback = _invoke(
        runtime,
        ToolCall("read-4", "read_file", {"path": "reports/daily.md"}),
        context,
    )
    _record(
        cases,
        "D2-installed-directory-then-file",
        directory_result.executed
        and file_result.executed
        and readback.content == "# Daily\nApproved fixture.\n",
        directory_mode=oct((workspace / "reports").stat().st_mode & 0o777),
        exact_readback=readback.content == "# Daily\nApproved fixture.\n",
    )


def _probe_pagination(root: Path, cases: list[dict[str, object]]) -> None:
    workspace = root / "workspace-sessions"
    workspace.mkdir()
    state_root = root / "state-sessions"
    for suffix in range(1, 34):
        open_workspace_session(
            workspace,
            state_root=state_root,
            force_new=True,
            conversation_id_factory=(
                lambda value=suffix: f"00000000-0000-4000-8000-{value:012d}"
            ),
        )
    before = _manifest(state_root)
    answers = iter(("n", "n", "1", "/exit"))
    output: list[str] = []
    code = entrypoint.main(
        [
            "--workspace",
            str(workspace),
            "--state-root",
            str(state_root),
            "--provider",
            "fake",
            "--without-owner-preferences",
        ],
        input_fn=lambda _prompt: next(answers),
        write_fn=output.append,
    )
    after = _manifest(state_root)
    _record(
        cases,
        "D3-installed-33-conversation-pages",
        code == 0 and any("Page 3 of 3" in line for line in output) and before == after,
        exit_code=code,
        reached_page_3=any("Page 3 of 3" in line for line in output),
        checkpoint_bytes_unchanged=before == after,
    )


def _probe_multihop_venv_process(root: Path, cases: list[dict[str, object]]) -> None:
    workspace = root / "workspace-process"
    workspace.mkdir()
    (workspace / "generate_report.py").write_text(
        "from pathlib import Path\n"
        'Path("generated.txt").write_text("bounded process output\\n", encoding="utf-8")\n',
        encoding="utf-8",
    )
    runtime = KernelToolRuntime(
        (
            build_local_process_registration(
                workspace=workspace,
                captured_path=os.environ.get("PATH", ""),
            ),
        )
    )
    result = _approve_process(
        runtime,
        ToolCall(
            "process-1",
            "local_process",
            {
                "executable": sys.executable,
                "argv": ["generate_report.py"],
                "cwd": ".",
                "profile": "short",
            },
        ),
        ToolPrepareContext(
            "conversation",
            "run",
            1,
            goal_id="goal",
            goal_revision=1,
            workspace_identity_digest="synthetic-workspace",
        ),
    )
    output = (workspace / "generated.txt").read_text(encoding="utf-8")
    _record(
        cases,
        "D5-installed-multihop-venv-process",
        result.executed and not result.is_error and output == "bounded process output\n",
        interpreter_is_symlink=Path(sys.executable).is_symlink(),
        exact_output=output == "bounded process output\n",
    )


def _probe_owner_preference_skip(root: Path, cases: list[dict[str, object]]) -> None:
    workspace = root / "workspace-preferences"
    workspace.mkdir()
    state_root = root / "state-preferences"
    open_workspace_session(workspace, state_root=state_root)
    preference_path = state_root / "owner-preferences.json"
    build_owner_preference_resources(
        preference_path,
        provider_trust_digest=_model_config("model-a").descriptor().identity_digest,
    )
    original = preference_path.read_bytes()
    common = [
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
        "--provider",
        "openai_compatible",
        "--model",
        "model-b",
        "--base-url",
        "https://provider.invalid",
        "--credential-env",
        "FIRST_AGENT_INSTALLED_PROBE_KEY",
    ]
    os.environ["FIRST_AGENT_INSTALLED_PROBE_KEY"] = "synthetic"
    try:
        strict_output: list[str] = []
        strict_code = entrypoint.main(
            common,
            input_fn=lambda _prompt: "/exit",
            write_fn=strict_output.append,
        )
        skip_output: list[str] = []
        skip_code = entrypoint.main(
            [*common, "--without-owner-preferences"],
            input_fn=lambda _prompt: "/exit",
            write_fn=skip_output.append,
        )
    finally:
        os.environ.pop("FIRST_AGENT_INSTALLED_PROBE_KEY", None)
    unchanged = preference_path.read_bytes() == original
    _record(
        cases,
        "D4-installed-owner-preference-skip",
        strict_code == 2
        and skip_code == 0
        and unchanged
        and any("not loaded" in line for line in skip_output),
        strict_start_rejected=strict_code == 2,
        explicit_skip_started=skip_code == 0,
        preference_bytes_unchanged=unchanged,
    )


def _probe_cli(entry: Path, root: Path, cases: list[dict[str, object]]) -> None:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    help_result = subprocess.run(
        [str(entry), "--help"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    status_workspace = root / "status-workspace"
    status_workspace.mkdir()
    status_result = subprocess.run(
        [str(entry), "--workspace", str(status_workspace), "--status"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    _record(
        cases,
        "installed-cli-surface",
        help_result.returncode == 0
        and status_result.returncode == 0
        and "No saved conversations." in status_result.stdout
        and all(
            flag in help_result.stdout
            for flag in (
                "--max-model-attempts",
                "--project-path",
                "--without-owner-preferences",
            )
        ),
        help_exit=help_result.returncode,
        status_exit=status_result.returncode,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-agent", type=Path, required=True)
    parser.add_argument("--site-root", type=Path, required=True)
    args = parser.parse_args()
    entry = args.first_agent.absolute()
    site_root = args.site_root.resolve(strict=True)
    module_paths = (Path(agent.__file__).resolve(), Path(entrypoint.__file__).resolve())
    if not all(path.is_relative_to(site_root) for path in module_paths):
        parser.error("agent/main were not imported from the requested installed site root")

    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="first-agent-v3-installed-", dir="/private/tmp") as tmp:
        root = Path(tmp).resolve(strict=True)
        _probe_cli(entry, root, cases)
        _probe_budget(root, cases)
        _probe_paths_and_directory(root, cases)
        _probe_multihop_venv_process(root, cases)
        _probe_pagination(root, cases)
        _probe_owner_preference_skip(root, cases)
    print(
        json.dumps(
            {
                "module_paths": [str(path) for path in module_paths],
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(case["pass"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
