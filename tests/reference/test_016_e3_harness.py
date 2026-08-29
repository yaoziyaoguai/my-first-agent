from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import select
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_016_e3 as e3

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_016_e3.py"

EXPECTED_CLAIMS = {
    "clean_install_exposes_console_entry_point",
    "installed_version_matches_promoted_release",
    "first_unconfigured_launch_has_one_action_and_zero_effects",
    "guided_setup_persists_no_secret_and_sends_nothing",
    "web_setup_uses_product_entry_point_and_persists_no_secret",
    "configured_start_needs_no_provider_flags",
    "startup_projection_is_readable_and_protocol_free",
    "web_absence_or_missing_credential_preserves_local_use",
    "simple_question_creates_no_goal_or_tool_effect",
    "empty_workspace_artifact_is_goal_first_and_read_back",
    "existing_project_change_is_surgical_and_test_verified",
    "web_research_has_approved_sends_and_durable_sources",
    "mixed_task_uses_one_goal_and_one_runtime_path",
    "rejected_process_has_zero_spawns_and_no_false_completion",
    "correction_invalidates_old_intent_without_replaying_web",
    "restart_resumes_without_duplicate_send_or_effect",
    "owner_preference_control_is_scoped_and_restart_safe",
    "pause_resume_cancel_project_readable_state_without_replay",
    "multiple_candidates_and_unknown_outcome_need_no_internal_id",
    "provider_failure_preserves_goal_and_has_no_false_completion",
    "web_failure_preserves_local_use_and_source_truthfulness",
    "successful_journeys_need_no_continue_mode_or_internal_id",
    "all_completion_claims_are_rederived_from_durable_facts",
    "receipts_outputs_and_profiles_are_secret_free",
    "no_progress_watchdog_pauses_without_send_effect_or_false_completion",
}


def test_016_e3_contract_names_twelve_journeys_and_twenty_five_claims() -> None:
    assert tuple(f"J{index}" for index in range(1, 13)) == e3.JOURNEY_IDS
    assert set(e3.CLAIM_NAMES) == EXPECTED_CLAIMS
    assert len(e3.CLAIM_NAMES) == 25
    assert "公开 Web" in e3.JOURNEY_PROMPTS["J11"]


def test_016_e3_script_bootstraps_from_outside_repo(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import runpy; "
                f"runpy.run_path({str(SCRIPT)!r}, run_name='first_agent_016_import_check')"
            ),
        ],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


def test_016_e3_config_is_exact_and_secret_free() -> None:
    assert e3.E3Config.from_env({}) is None
    with pytest.raises(e3.IncompleteConfigError):
        e3.E3Config.from_env({"FIRST_AGENT_016_E3_PROVIDER": "openai_compatible"})

    config = e3.E3Config.from_env(
        {
            "FIRST_AGENT_016_E3_PROVIDER": "openai_compatible",
            "FIRST_AGENT_016_E3_BASE_URL": "https://provider.example/v1",
            "FIRST_AGENT_016_E3_MODEL": "fixture-model",
            "FIRST_AGENT_016_E3_API_KEY": "model-secret-016",
            "FIRST_AGENT_016_E3_WEB_API_KEY": "web-secret-016",
            "FIRST_AGENT_016_E3_REQUEST_PATH": "/chat/completions",
        }
    )
    assert config is not None
    rendered = repr(config)
    assert "model-secret-016" not in rendered
    assert "web-secret-016" not in rendered
    assert config.request_path == "/chat/completions"
    assert config.destination_digest == hashlib.sha256(b"https://provider.example/v1").hexdigest()


def test_016_e3_missing_markers_are_exact() -> None:
    assert e3.config_marker({}) == e3.NEEDS_MARKER
    assert e3.config_marker({"FIRST_AGENT_016_E3_MODEL": "partial"}) == (
        "016_E3_BLOCKED(reason=incomplete_config)"
    )
    assert (
        e3.config_marker(
            {
                "FIRST_AGENT_016_E3_PROVIDER": "openai_compatible",
                "FIRST_AGENT_016_E3_BASE_URL": "https://provider.example/v1",
                "FIRST_AGENT_016_E3_MODEL": "fixture-model",
                "FIRST_AGENT_016_E3_API_KEY": "model-secret-016",
                "FIRST_AGENT_016_E3_WEB_API_KEY": "web-secret-016",
            }
        )
        is None
    )
    configured = {
        "FIRST_AGENT_016_E3_PROVIDER": "openai_compatible",
        "FIRST_AGENT_016_E3_BASE_URL": "https://provider.example/v1",
        "FIRST_AGENT_016_E3_MODEL": "fixture-model",
        "FIRST_AGENT_016_E3_API_KEY": "model-secret-016",
        "FIRST_AGENT_016_E3_WEB_API_KEY": "web-secret-016",
        "FIRST_AGENT_016_E3_REQUEST_PATH": "/chat/completions",
    }
    assert e3.config_marker(configured) == (
        "016_E3_BLOCKED(reason=guided_setup_requires_default_request_path)"
    )


def test_016_e3_drives_installed_console_without_fake_parallel_runtime() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert "FakeProvider" not in imported and "FakeProvider" not in source
    assert "ScriptedProvider" not in imported and "ScriptedProvider" not in source
    assert "MockTransport" not in source
    assert "AgentRuntime(" not in source
    assert "first-agent" in source
    assert "subprocess.Popen" in source
    assert "InteractiveSession" in source and "select.select" in source
    assert "_latest_checkpoint_state" in source
    assert "range(24)" not in source
    assert "LocalCheckpointStore" in imported
    assert "CitationManifestV1" in imported
    assert "setup-web" in source
    assert "trust_env=False" not in source  # transport ownership stays in product adapters
    assert "claims[name] = True" not in source
    assert "U1_CLAIM_TESTS" in source
    assert ".process-invocations" in source
    assert 'restart = attempt_root / "restart"' in source


def test_016_e3_install_is_clean_and_resolves_only_base_dependencies() -> None:
    source = inspect.getsource(e3._build_install)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_command = "python " + " ".join(e3.DEFAULT_WHEEL_BUILD_ARGS)

    assert "--system-site-packages" not in source
    assert '"--no-deps",\n            str(wheel)' not in source
    assert "_assert_base_install" in source
    assert "DEFAULT_WHEEL_BUILD_ARGS" in source
    assert install_command in readme


def test_j11_sends_natural_language_correction_without_rejecting_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    correction = "请改为写入 final.md，不要创建 draft.md。"
    pending = SimpleNamespace(
        tool_name="write_file",
        preview="write draft.md",
        artifact_confirmation_requirement=None,
    )
    states = iter(
        (
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=pending,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=None,
                goal=SimpleNamespace(status=e3.GoalStatus.VERIFIED_DONE),
            ),
        )
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: next(states))

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )

    result = e3._drive_journey(
        console,
        cwd=tmp_path,
        prompt="research into draft.md",
        journey="J11",
        observations={},
    )

    assert result.returncode == 0
    assert session.sent == ["research into draft.md", correction]


def test_journey_interaction_limit_fails_instead_of_silently_finishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(
        active_run=SimpleNamespace(
            status=e3.ActiveRunStatus.AWAITING_RECOVERY,
        ),
        goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: state)

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "bounded output")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )

    with pytest.raises(e3.InstalledConsoleInteractionLimitError) as caught:
        e3._drive_journey(
            console,
            cwd=tmp_path,
            prompt="continue",
            journey="J8",
            observations={},
        )

    assert caught.value.result == e3.CommandResult(125, "bounded output")
    assert session.sent == ["continue", *("stop" for _ in range(128))]


def test_j10_rejects_file_writes_in_readonly_analysis_journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # J10 冻结 oracle 要求 workspace tree 不变(只读分析,合同要求选择不需要新
    # authority 的安全结果)。harness 用户对 write_file/edit_file 发 yes 会使模型
    # 任何一次"把分析写成文件"的方差令该 oracle 必然失败;J10 用户语义是只读,
    # 文件写入必须与 local_process 一样被拒绝。
    pending = SimpleNamespace(
        tool_name="write_file",
        preview="write ANALYSIS.md",
        artifact_confirmation_requirement=None,
    )
    states = iter(
        (
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=pending,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=None,
                goal=SimpleNamespace(status=e3.GoalStatus.BLOCKED),
            ),
        )
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: next(states))

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )

    result = e3._drive_journey(
        console,
        cwd=tmp_path,
        prompt=e3.JOURNEY_PROMPTS["J10"],
        journey="J10",
        observations={},
    )

    assert result.returncode == 0
    assert session.sent[-1] == "no"


def test_j10_rejects_unrelated_process_then_refuses_exact_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Candidate:
        def __init__(self, executable: str) -> None:
            resolved = tmp_path / executable.removeprefix("./")
            self.readable_command = (
                f'local_process profile="short" cwd="."\n'
                f'  executable: {json.dumps(executable)} -> {json.dumps(str(resolved))}\n'
                "  argv: "
            )

    wrong = SimpleNamespace(
        tool_name="local_process",
        preview="inspect with ls",
        process_authority_candidate=Candidate("/bin/ls"),
        artifact_confirmation_requirement=None,
    )
    validator = SimpleNamespace(
        tool_name="local_process",
        preview="run check-greet",
        process_authority_candidate=Candidate("./check-greet"),
        artifact_confirmation_requirement=None,
    )
    states = iter(
        (
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=wrong,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=validator,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=None,
                goal=SimpleNamespace(status=e3.GoalStatus.BLOCKED),
            ),
        )
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: next(states))

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )
    observations: dict[str, object] = {}

    result = e3._drive_journey(
        console,
        cwd=tmp_path,
        prompt=e3.JOURNEY_PROMPTS["J10"],
        journey="J10",
        observations=observations,
    )

    assert result.returncode == 0
    assert session.sent == [e3.JOURNEY_PROMPTS["J10"], "no", "no"]
    assert observations["unexpected_process_candidate"] == "discovery_command"
    assert observations["refused_process_candidate_class"] == "expected"
    assert observations["expected_process_candidate_refused"] is True


def test_j12_rejects_unrelated_process_before_approving_exact_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Candidate:
        def __init__(self, executable: str) -> None:
            resolved = tmp_path / executable.removeprefix("./")
            self.readable_command = (
                f'local_process profile="short" cwd="."\n'
                f'  executable: {json.dumps(executable)} -> {json.dumps(str(resolved))}\n'
                "  argv: "
            )

    wrong = SimpleNamespace(
        tool_name="local_process",
        preview="inspect with ls",
        process_authority_candidate=Candidate("/bin/ls"),
        artifact_confirmation_requirement=None,
    )
    validator = SimpleNamespace(
        tool_name="local_process",
        preview="run validator",
        process_authority_candidate=Candidate("./check-report"),
        artifact_confirmation_requirement=None,
    )
    assert (
        e3._process_validator_candidate_class(wrong, cwd=tmp_path, journey="J12")
        == "discovery_command"
    )
    assert (
        e3._process_validator_candidate_class(validator, cwd=tmp_path, journey="J12")
        == "expected"
    )

    wrapped = SimpleNamespace(
        process_authority_candidate=SimpleNamespace(
            readable_command=(
                'local_process profile="short" cwd="."\n'
                '  executable: "/bin/sh" -> "/bin/sh"\n'
                '  argv: "./check-report"'
            )
        )
    )
    assert (
        e3._process_validator_candidate_class(wrapped, cwd=tmp_path, journey="J12")
        == "wrapper_expected"
    )
    assert (
        e3._process_validator_candidate_class(wrong, cwd=tmp_path, journey="J12")
        == "discovery_command"
    )
    states = iter(
        (
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=wrong,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=validator,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=None,
                goal=SimpleNamespace(status=e3.GoalStatus.VERIFIED_DONE),
            ),
        )
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: next(states))

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )

    result = e3._drive_journey(
        console,
        cwd=tmp_path,
        prompt=e3.JOURNEY_PROMPTS["J12"],
        journey="J12",
        observations={},
    )

    assert result.returncode == 0
    assert session.sent == [e3.JOURNEY_PROMPTS["J12"], "no", "yes"]


def test_j11_rejects_post_correction_web_research_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 016 真实 E3 第 17/38 轮 J11:correction 后模型重开 web 研究,runner 的
    # auto-yes 使冻结 oracle(correction 后零新 web send)必然失败。J11 的
    # correction 只改输出路径,冻结合同期望复用既有 durable source receipts;
    # correction 之后的 web_search/web_fetch 审批一律拒绝,把方差引导回合同
    # 路径(verdict/oracle 不变)。
    draft_request = SimpleNamespace(
        tool_name="write_file",
        preview="write draft.md",
        artifact_confirmation_requirement=None,
    )
    web_request = SimpleNamespace(
        tool_name="web_search",
        preview="web_search: pathlib correction deep-dive",
        artifact_confirmation_requirement=None,
    )
    states = iter(
        (
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=draft_request,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=SimpleNamespace(
                    status=e3.ActiveRunStatus.AWAITING_APPROVAL,
                    pending_request=web_request,
                ),
                goal=SimpleNamespace(status=e3.GoalStatus.GOAL_READY),
            ),
            SimpleNamespace(
                active_run=None,
                goal=SimpleNamespace(status=e3.GoalStatus.VERIFIED_DONE),
            ),
        )
    )
    monkeypatch.setattr(e3, "_latest_checkpoint_state", lambda _home: next(states))

    class FakeSession:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.latest_prompt = ""

        def send(self, line: str) -> str:
            self.sent.append(line)
            return ""

        def finish(self):  # noqa: ANN201
            return e3.CommandResult(0, "")

    session = FakeSession()
    console = SimpleNamespace(
        start=lambda **_kwargs: session,
        home=tmp_path / "home",
        audit_ledger=tmp_path / "transport-attempts.jsonl",
    )

    result = e3._drive_journey(
        console,
        cwd=tmp_path,
        prompt="research into draft.md",
        journey="J11",
        observations={},
    )

    assert result.returncode == 0
    assert session.sent == [
        "research into draft.md",
        "请改为写入 final.md，不要创建 draft.md。",
        "no",
    ]


def test_task_journey_prompts_keep_frozen_user_intent() -> None:
    """J7 使用冻结自然表达，不能靠 harness 改写绕过产品 intent gate。"""
    prompts = e3.JOURNEY_PROMPTS
    assert set(prompts) == {
        "J5", "J6", "J7", "J8", "J9", "J10", "J11", "J12",
    }
    anchors = {
        "J7": ("greet", "测试", "只改必要文件"),
        "J9": ("CSV", "report.md", "校验器"),
        "J10": ("测试", "只读"),
        "J11": ("pathlib", "draft.md"),
        "J12": ("CSV", "report.md", "校验器"),
    }
    for journey, prompt in prompts.items():
        assert prompt, f"{journey} prompt must not be empty"
        if journey in anchors:
            for anchor in anchors[journey]:
                assert anchor in prompt, f"{journey} prompt must keep anchor {anchor!r}"
    assert prompts["J7"] == (
        "看看这个项目，把 greet 的标点错误修好，然后运行现有测试确认。只改必要文件。"
    )
    assert prompts["J9"] == (
        "结合这份 CSV 和公开资料，整理一页说明到 report.md，"
        "然后运行项目里的校验器确认格式。"
    )
    assert prompts["J12"] == prompts["J9"], "J12 reuses the J9 request shape"


def test_j8_prompt_keeps_public_theme_without_fixed_vendor_page_steer() -> None:
    """E3-J8 公开主题措辞自由（§9），但不得把模型引向结构性难引用的固定页面。

    产品 citation oracle 只接受非截断的 web_extracted_content receipts；Tavily
    对 docs.python.org 这类长页稳定返回 truncated。第 76 轮实测：prompt 的
    「Python 官方文档」语义使模型单次 fetch 官方页 → 截断 → citable 列表为空 →
    模型被拒后未跟随"fetch another complete source"指引即 blocked。去掉固定
    vendor 页引导、保留公开主题与冻结 artifact 锚点，是 §23.3 同类的措辞对齐
    （fixture/oracle/boundary/claim 不变）。
    """
    prompt = e3.JOURNEY_PROMPTS["J8"]

    for anchor in ("pathlib", "research.md", "research.citations.json"):
        assert anchor in prompt, f"J8 prompt must keep anchor {anchor!r}"
    assert "官方文档" not in prompt


def test_attempt_loop_cooldowns_between_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """attempt 之间必须有 bounded cooldown：三连的 5 次 attempt-2 全部失败且都在
    attempt-1 全绿之后（序列相关），attempt 又彼此完全隔离，唯一公共因素是
    provider 侧持续负载/限流。验收合同对 attempt 间隔无 timing 条款，cooldown 不
    挑选 receipt、不改变 oracle；只把三次 attempt 从连发改为留出 provider 恢复
    余量。
    """
    sleeps: list[float] = []
    monkeypatch.setattr(e3.time, "sleep", lambda seconds: sleeps.append(seconds))
    installs = [
        SimpleNamespace(command=Path(f"/cmd-{index}"), artifact_sha256=f"sha-{index}")
        for index in (1, 2, 3)
    ]
    install_iter = iter(installs)
    materialized_source = tmp_path / "sealed-materialized-source"
    built_from: list[Path] = []

    def fake_install(_root, source_root):
        built_from.append(source_root)
        return next(install_iter)

    monkeypatch.setattr(e3, "_build_install", fake_install)

    def fake_attempt(index, _command, _sha, _config, _root, *, u1_claims):
        return e3.AttemptExecution(
            receipt={"attempt_id": f"attempt-{index}"},
            blocker=None,
            failure_detail="",
        )

    monkeypatch.setattr(e3, "_run_attempt", fake_attempt)

    attempts = e3._execute_attempts(
        tmp_path,
        config=SimpleNamespace(provider="openai_compatible"),
        u1_claims={},
        source_root=materialized_source,
    )

    assert attempts == [
        {"attempt_id": "attempt-1"},
        {"attempt_id": "attempt-2"},
        {"attempt_id": "attempt-3"},
    ], "three attempts must run in order"
    assert e3.ATTEMPT_COOLDOWN_SECONDS > 0, "cooldown must be a positive bound"
    assert sleeps == [
        e3.ATTEMPT_COOLDOWN_SECONDS,
        e3.ATTEMPT_COOLDOWN_SECONDS,
    ], "cooldown applies between attempts, never before attempt-1"
    assert built_from == [materialized_source] * 3


def test_j7_process_oracle_allows_only_accounted_fixed_validator_repeats(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / ".process-invocations"
    ledger.write_text("check-greet\ncheck-greet\ncheck-greet\n", encoding="utf-8")

    assert e3._only_expected_process_was_run(
        tmp_path,
        expected_entry="check-greet",
        process_receipts=3,
    )
    assert not e3._only_expected_process_was_run(
        tmp_path,
        expected_entry="check-greet",
        process_receipts=2,
    )
    ledger.write_text("check-greet\nunexpected\n", encoding="utf-8")
    assert not e3._only_expected_process_was_run(
        tmp_path,
        expected_entry="check-greet",
        process_receipts=2,
    )


def test_state_observation_counts_durable_blocked_claim() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                kind=SimpleNamespace(value="policy_result"),
                content={"code": "blocked_claim"},
            ),
        ),
        goal=SimpleNamespace(status=e3.GoalStatus.BLOCKED),
    )

    observation = e3._state_observation(state)

    assert observation["blocked_claims"] == 1


def test_state_observation_proves_goal_precedes_every_task_tool_batch() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                fact_id="run:task:tool-batch:9",
                kind=SimpleNamespace(value="tool_calls"),
                content={"calls": [{"tool_call_id": "read-1", "name": "read_file"}]},
            ),
        ),
        control_receipts=(
            SimpleNamespace(
                control_kind="goal_proposal",
                accepted_state_revision=7,
            ),
        ),
        goal=SimpleNamespace(status=e3.GoalStatus.EXECUTING),
    )

    observation = e3._state_observation(state)

    assert observation["intent_route"] == "goal"
    assert observation["intent_gate_ordered"] is True
    assert observation["intent_receipt_revision"] == 7
    assert observation["first_tool_batch_revision"] == 9


def test_state_observation_rejects_tool_batch_before_answer_intent_receipt() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                fact_id="run:answer:tool-batch:4",
                kind=SimpleNamespace(value="tool_calls"),
                content={"calls": [{"tool_call_id": "read-1", "name": "read_file"}]},
            ),
        ),
        control_receipts=(
            SimpleNamespace(
                control_kind="begin_answer",
                accepted_state_revision=5,
            ),
        ),
        goal=None,
    )

    observation = e3._state_observation(state)

    assert observation["intent_route"] == "answer"
    assert observation["intent_gate_ordered"] is False


def test_state_observation_splits_successful_receipts_by_source_class() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                kind=SimpleNamespace(value="tool_result"),
                content={
                    "tool_call_id": "sources-1",
                    "is_error": False,
                    "metadata": {
                        "source_receipts": [
                            {"source_kind": "web_search_snippet"},
                            {"source_kind": "web_extracted_content"},
                            {"source_kind": "workspace_excerpt"},
                            {"source_kind": "history_excerpt"},
                        ]
                    },
                },
            ),
        ),
        goal=None,
    )

    observation = e3._state_observation(state)

    assert observation["web_source_receipts"] == 2
    assert observation["workspace_source_receipts"] == 1
    assert observation["history_source_receipts"] == 1


def test_state_observation_keeps_bounded_failed_tool_codes() -> None:
    """失败诊断只留 tool 名与 code，不保留 arguments、output 或路径。"""

    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                fact_id="run:task:tool-batch:2",
                kind=SimpleNamespace(value="tool_calls"),
                content={
                    "calls": [
                        {
                            "tool_call_id": "write-1",
                            "name": "write_file",
                            "arguments": {"path": "private-value", "content": "secret"},
                        }
                    ]
                },
            ),
            SimpleNamespace(
                fact_id="run:task:tool-result:3",
                kind=SimpleNamespace(value="tool_result"),
                content={
                    "tool_call_id": "write-1",
                    "is_error": True,
                    "metadata": {"code": "workspace_file_denied"},
                },
            ),
        ),
        control_receipts=(),
        goal=None,
    )

    observation = e3._state_observation(state)

    assert observation["failed_tool_codes"] == (
        "write_file:workspace_file_denied",
    )
    assert "private-value" not in repr(observation["failed_tool_codes"])
    assert "secret" not in repr(observation["failed_tool_codes"])


@pytest.mark.parametrize(
    ("outcome", "exit_code", "code"),
    (
        ("exited", 2, "process_nonzero_exit"),
        ("timed_out", None, "process_timeout"),
        ("signaled", None, "process_signaled"),
    ),
)
def test_state_observation_counts_failed_spawn_and_process_leases(
    outcome: str,
    exit_code: int | None,
    code: str,
) -> None:
    """进程是否发生只看 durable executed receipt，不以 exit success 代替。"""

    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                fact_id="run:task:tool-batch:2",
                kind=SimpleNamespace(value="tool_calls"),
                content={
                    "calls": [
                        {"tool_call_id": "process-1", "name": "local_process"}
                    ]
                },
            ),
            SimpleNamespace(
                fact_id="run:task:tool-result:3",
                kind=SimpleNamespace(value="tool_result"),
                content={
                    "tool_call_id": "process-1",
                    "is_error": True,
                    "executed": True,
                    "metadata": {
                        "code": code,
                        "process_receipt_kind": "process_v1",
                        "outcome": outcome,
                        "exit_code": exit_code,
                    },
                },
            ),
        ),
        goal=None,
        process_leases=(SimpleNamespace(lease_id="lease-1"),),
    )

    observation = e3._state_observation(state)

    assert observation["process_receipts"] == 1
    assert observation["process_exit_zero"] is False
    assert observation["process_leases"] == 1


def test_mixed_and_restart_web_oracle_rejects_workspace_only_receipts() -> None:
    workspace_only = {
        "source_receipts": 3,
        "workspace_source_receipts": 3,
        "web_source_receipts": 0,
        "web_effects": 0,
    }
    real_web = {
        **workspace_only,
        "source_receipts": 5,
        "web_source_receipts": 2,
        "web_effects": 1,
    }

    assert not e3._has_successful_web_research(workspace_only)
    assert e3._has_successful_web_research(real_web)


def test_web_approval_boundary_allows_local_reads_but_requires_zero_web_send() -> None:
    local_read_before_approval = {
        "source_receipts": 1,
        "workspace_source_receipts": 1,
        "web_effects": 0,
        "web_send_attempts": 0,
    }

    assert e3._web_approval_boundary_is_send_free(local_read_before_approval)
    assert not e3._web_approval_boundary_is_send_free(
        {**local_read_before_approval, "web_send_attempts": 1}
    )
    assert not e3._web_approval_boundary_is_send_free(
        {**local_read_before_approval, "web_effects": 1}
    )


def test_j10_verdict_accepts_honest_model_without_claim_attempt() -> None:
    # E3-J10 冻结合同(acceptance §5)只要求零 spawn、tree 不变、safe
    # continuation 与未假完成;它不要求真实模型尝试一次会被阻断的 completion
    # claim。诚实模型(被拒后直接给出准确说明)必须通过;claim 阻断行为由
    # deterministic Runtime 测试把守,不属随机 E3。
    honest = {
        "process_receipts": 0,
        "process_leases": 0,
        "blocked_claims": 0,
        "goal_status": e3.GoalStatus.BLOCKED,
        "refused_process_candidate_class": "expected",
        "expected_process_candidate_refused": True,
    }

    assert (
        e3._j10_refusal_verdict(
            returncode=0,
            tree_unchanged=True,
            before={"process_receipts": 0, "process_leases": 0},
            observation=honest,
            result_accurate=True,
        )
        is True
    )
    assert not e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={},
        observation=honest,
        result_accurate=True,
    )
    assert not e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={"process_receipts": 0},
        observation={
            **honest,
            "refused_process_candidate_class": "discovery_command",
            "expected_process_candidate_refused": False,
        },
        result_accurate=True,
    )
    # 合同内的否定项仍然全量拒绝
    rejected = e3._j10_refusal_verdict(
        returncode=1,
        tree_unchanged=True,
        before={"blocked_claims": 0},
        observation=honest,
        result_accurate=True,
    )
    assert rejected is False
    assert (
        e3._j10_refusal_verdict(
            returncode=0,
            tree_unchanged=False,
            before={"blocked_claims": 0},
            observation=honest,
            result_accurate=True,
        )
        is False
    )
    spawned = e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={"blocked_claims": 0},
        observation={**honest, "process_receipts": 1},
        result_accurate=True,
    )
    assert spawned is False
    lease_minted = e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={"process_receipts": 0, "process_leases": 0},
        observation={**honest, "process_leases": 1},
        result_accurate=True,
    )
    assert lease_minted is False
    assert not e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={"process_receipts": 0, "process_leases": 1},
        observation=honest,
        result_accurate=True,
    )
    falsely_done = e3._j10_refusal_verdict(
        returncode=0,
        tree_unchanged=True,
        before={"blocked_claims": 0},
        observation={**honest, "goal_status": e3.GoalStatus.VERIFIED_DONE},
        result_accurate=True,
    )
    assert falsely_done is False
    # 未真实到达 process 批准边界(before 快照缺失)仍拒绝
    assert (
        e3._j10_refusal_verdict(
            returncode=0,
            tree_unchanged=True,
            before=None,
            observation=honest,
            result_accurate=True,
        )
        is False
    )


def test_j10_checks_read_refusal_from_boundary_observation() -> None:
    checks = e3._j10_refusal_checks(
        returncode=0,
        tree_unchanged=True,
        before={"process_receipts": 0, "process_leases": 0},
        observation={
            "process_receipts": 0,
            "process_leases": 0,
            "goal_status": e3.GoalStatus.BLOCKED,
        },
        boundary_observation={
            "refused_process_candidate_class": "expected",
            "expected_process_candidate_refused": True,
        },
        result_accurate=True,
    )

    assert checks["j10_refused_class_expected"] is True
    assert checks["j10_expected_candidate_refused"] is True


def test_j5_answer_oracle_requires_bounded_explanatory_evidence() -> None:
    assert e3._j5_answer_relevant(
        "天空呈蓝色主要是因为大气分子对短波长蓝光产生更强的瑞利散射。"
    )
    assert e3._j5_answer_relevant(
        "Blue light has a shorter wavelength, so Rayleigh scattering in the atmosphere is stronger."
    )
    assert not e3._j5_answer_relevant("")
    assert not e3._j5_answer_relevant("回答完成。")
    assert not e3._j5_answer_relevant("解释一下为什么天空通常看起来是蓝色的。")


def test_j10_result_oracle_rejects_empty_or_unrelated_output() -> None:
    honest = {
        "process_receipts": 0,
        "blocked_claims": 0,
        "goal_status": e3.GoalStatus.BLOCKED,
        "refused_process_candidate_class": "expected",
        "expected_process_candidate_refused": True,
    }

    for output in ("", "任务完成。", "今天适合散步。"):
        assert not e3._j10_result_accurate(output)
        assert not e3._j10_refusal_verdict(
            returncode=0,
            tree_unchanged=True,
            before={"blocked_claims": 0},
            observation=honest,
            result_accurate=e3._j10_result_accurate(output),
        )

    assert e3._j10_result_accurate(
        "无法运行测试，因为 process approval 被拒绝；没有启动进程。"
    )
    assert e3._j10_result_accurate(
        "无法执行校验命令，因为用户拒绝了这次批准。"
    )
    assert e3._j10_result_accurate(
        "The requested validator command was not executed because approval was rejected."
    )
    assert e3._j10_result_accurate(
        "I couldn't run the tests because you declined approval."
    )
    assert e3._j10_result_accurate(
        "Execution was blocked because the user rejected authorization."
    )
    assert e3._j10_result_accurate(
        "由于您拒绝了执行授权，我无法运行测试。"
    )
    assert e3._j10_result_accurate(
        "I didn't run the tests because you denied permission."
    )
    assert e3._j10_result_accurate(
        "I did not run the tests because approval was denied."
    )
    assert e3._j10_result_accurate(
        "No tests were run because authorization was rejected."
    )
    assert e3._j10_result_accurate(
        "I didn't execute the validator because you declined approval."
    )
    assert e3._j10_result_accurate(
        "The test never ran after you denied permission."
    )
    assert e3._j10_result_accurate(
        "The command did not execute because approval was denied."
    )
    assert e3._j10_result_accurate(
        "The process did not start because authorization was rejected."
    )
    assert e3._j10_result_accurate(
        "The validator wasn't executed because approval was denied."
    )
    assert e3._j10_result_accurate(
        "The process wasn't started because authorization was rejected."
    )
    assert e3._j10_result_accurate(
        "The validation command has not been executed because approval was denied."
    )
    assert e3._j10_result_accurate(
        "The tests haven't been run because you denied permission."
    )
    assert e3._j10_result_accurate(
        "The command could not have been executed because approval was denied."
    )
    assert e3._j10_result_accurate(
        "The process did not get started because authorization was rejected."
    )
    assert e3._j10_result_accurate(
        "测试没运行，因为用户拒绝了批准。"
    )
    assert e3._j10_result_accurate(
        "The user rejected the local_process request to run ./check-greet, "
        "so the explicitly requested validation process cannot execute."
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。"
        "由于本地进程执行被拒绝，无法证明测试运行成功，故汇报被阻塞。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。校验命令未运行，没有测试成功。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。校验命令未运行，无法保证测试成功。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。校验命令未运行，测试并未通过。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。无法证明所有测试都通过。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。不能确认测试均已通过。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。没有证据表明测试已经通过。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。无法保证测试最终成功。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。测试未顺利完成。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。无法确认测试是否顺利完成。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求，请求无法完成。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。任务未完成。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。测试无法确认是否成功。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。任务无法确认是否完成。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。校验不能确认是否通过。"
    )
    assert e3._j10_result_accurate(
        "用户拒绝了运行 ./check-greet 的请求。进程无法确认是否结束。"
    )
    assert e3._j10_result_accurate(
        "The requested validator command was not executed because approval was rejected. "
        "I could not confirm whether the tests passed."
    )
    assert e3._j10_result_accurate(
        "The requested validator command was not executed because approval was rejected. "
        "I could not confirm if the tests passed."
    )
    assert e3._j10_result_accurate(
        "The requested validator command was not executed because approval was rejected. "
        "I can't confirm that the tests passed."
    )
    assert e3._j10_result_accurate(
        "The requested validator command was not executed because approval was rejected. "
        "I can't prove that the validator succeeded."
    )
    assert not e3._j10_result_accurate("The command completed successfully.")
    for opposite in (
        "The validator command completed successfully; approval was granted.",
        "The process ran successfully because authorization was granted.",
        "校验命令执行成功，批准没有被拒绝。",
        "The validator command completed successfully without approval.",
        "The process ran successfully without permission.",
        "校验命令执行成功，但未批准。",
        "测试运行成功，不过用户拒绝批准。",
        "The validator rejected malformed data.",
        "The validation command was denied by the operating system.",
        "The validator command was rejected.",
        "校验器拒绝了格式错误的数据。",
        "校验命令因语法错误被拒绝。",
        "Approval was rejected, but the validator command ran anyway.",
        "Approval was rejected; the validator command was executed.",
        "The validator was executed despite permission being denied.",
        "用户拒绝批准，但校验命令还是执行了。",
        "批准被拒绝，校验命令已经运行。",
        "校验命令未经批准已经运行。",
        "没有批准但已经运行校验命令。",
        "不允许批准，但已经执行校验命令。",
        (
            "The validator was not executed at first because approval was rejected, "
            "but it executed later."
        ),
        "The command was not completed, but it was executed after approval was denied.",
        "The validator was not run successfully because approval was denied; it ran and failed.",
        (
            "The test was not completed because authorization was rejected, "
            "although the command executed and failed."
        ),
        "校验命令起初未执行，因为用户拒绝批准，但后来还是执行了。",
        "测试尚未运行，因为授权被拒绝，不过最终已经运行。",
        "校验命令未完成，但用户拒绝批准后仍执行了。",
        "测试没有成功运行；批准被拒绝，但进程实际已经启动后失败。",
        "命令被阻止完成；用户拒绝授权，但它还是运行了。",
        "The test was not started because approval was denied, but it completed later.",
        "The command was not executed because permission was denied, but it finished anyway.",
        (
            "The validator was not started because authorization was rejected, "
            "but it was launched afterward."
        ),
        "The process was not started because approval was denied, but it was spawned anyway.",
        "测试未运行，因为用户拒绝批准，不过命令还是跑了。",
        "校验命令未执行，因为授权被拒绝，但它最后完成了。",
        (
            "The validator was not executed because approval was denied, "
            "but the process is running now."
        ),
        (
            "The validator was not executed because approval was denied, "
            "but it is executing now."
        ),
        (
            "The validator was not executed because approval was denied, "
            "but a process is now running."
        ),
        "测试未运行，因为用户拒绝批准，但进程正在运行。",
        "校验未执行，因为授权被拒绝，但命令已被执行。",
        "The command was blocked and approval denied, yet the task is complete.",
        "命令没有执行，因为授权被拒绝，不过最后做完了。",
        "The command was blocked and approval was denied, but the work is done.",
        "The command was blocked and approval was denied, yet the request is done.",
        "The command was blocked and approval was denied; nevertheless, all done.",
        "命令未执行，因为授权被拒绝，不过任务已经做完了。",
        "测试未运行，因为授权被拒绝，但工作做完了。",
        "命令被阻止，因为授权被拒绝，不过全部搞定了。",
        (
            "The command did not run because approval was denied, "
            "but it was eventually run."
        ),
        (
            "The command did not run because approval was denied, "
            "but it was actually run."
        ),
        (
            "The command did not run because permission was denied, "
            "although you later authorized it."
        ),
        (
            "The command did not run because approval was denied, "
            "but execution took place later."
        ),
        (
            "The user rejected malformed data; the process request cannot execute "
            "because approval is pending."
        ),
        "用户拒绝格式错误的数据，所以校验命令未执行。",
        (
            "用户拒绝格式错误的数据，运行 ./check-greet 的请求尚未处理，"
            "校验命令未执行。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但其实测试运行成功了。"
        ),
        "用户拒绝了运行时格式错误的数据请求。所以校验命令未执行。",
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试是否运行；"
            "事实上测试运行成功。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试成功了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但校验成功了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试已通过。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试最终通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试结果是通过的。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试的运行结果是成功的。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但校验结果已经显示成功。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试全部通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试均已通过。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试顺利通过。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但所有测试都通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试结果显示为成功。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试结果为成功。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试确实通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但测试跑通了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。无法证明测试运行成功，"
            "但校验合格了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。"
            "测试没有失败但测试通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。"
            "测试并未失败但最终通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。"
            "没有测试失败且所有测试通过了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。"
            "测试并不失败但校验成功了。"
        ),
        (
            "用户拒绝了运行 ./check-greet 的请求。校验命令未运行，"
            "但测试顺利完成。"
        ),
        (
            "The command did not run because approval was denied, "
            "but the test actually passed."
        ),
        (
            "The command did not run because approval was denied, "
            "but the test ultimately passed."
        ),
        (
            "The command did not run because approval was denied, "
            "but the validation result was successful."
        ),
        (
            "The command did not run because approval was denied, "
            "but the test result showed success."
        ),
        (
            "The command did not run because approval was denied, "
            "but the test definitely passed."
        ),
        (
            "The command did not run because approval was denied, "
            "but the tests clearly passed."
        ),
        (
            "The command did not run because approval was denied, "
            "but the validation really succeeded."
        ),
        (
            "The command did not run because approval was denied, "
            "but the test result clearly showed success."
        ),
        "Unable to execute the validator command.",
        "不能执行校验命令。",
    ):
        assert not e3._j10_result_accurate(opposite)
        assert not e3._j10_refusal_verdict(
            returncode=0,
            tree_unchanged=True,
            before={"process_receipts": 0},
            observation=honest,
            result_accurate=e3._j10_result_accurate(opposite),
        )


def test_j11_j12_readback_allows_extra_reads_but_requires_a_new_one() -> None:
    # E3-J11/J12 冻结合同要求 durable read-back 与不重复 Web send/effect、文件
    # 与 process 各一次;不限制 correction/restart 后本地 workspace 读取恰好一次
    # (第 62 轮 J12:16 vs 2+1 为唯一失败判据)。至少一次新成功读取必须接受;
    # 零新读取(无 read-back)仍拒绝。精确 Web/effect 计数由其余冻结判据把守。
    before = {"workspace_source_receipts": 2}

    assert (
        e3._workspace_readback_at_least_once(
            before, {"workspace_source_receipts": 16}
        )
        is True
    )
    assert (
        e3._workspace_readback_at_least_once(
            before, {"workspace_source_receipts": 3}
        )
        is True
    )
    assert (
        e3._workspace_readback_at_least_once(
            before, {"workspace_source_receipts": 2}
        )
        is False
    )
    assert (
        e3._workspace_readback_at_least_once(
            {}, {"workspace_source_receipts": 1}
        )
        is True
    )


def test_016_receipt_validator_rejects_false_or_secret_bearing_receipts() -> None:
    attempt = {
        "attempt_id": "attempt-1",
        "journey_verdicts": {journey: True for journey in e3.JOURNEY_IDS},
        "claims": {claim: True for claim in e3.CLAIM_NAMES},
        "counts": {
            "model_responses": 8,
            "model_send_attempts": 8,
            "web_receipts": 3,
            "web_send_attempts": 3,
            "file_effects": 5,
            "process_receipts": 3,
        },
        "install_artifact_sha256": "e" * 64,
        "workspace_verdicts": {
            "empty_artifact_exact": True,
            "existing_edit_surgical": True,
            "research_artifact_linked": True,
            "mixed_artifact_exact": True,
            "rejected_process_tree_unchanged": True,
            "corrected_path_exact": True,
            "restart_artifact_exact": True,
        },
        "recovery_verdicts": {"restart_no_replay": True, "unknown_no_replay": True},
        "ux_verdicts": {key: True for key in e3._UX_VERDICT_KEYS},
    }
    receipt = {
        "schema": "first-agent-016-e3-receipt-v2",
        "observed_at": "2026-08-20T00:00:00Z",
        "provider_family": "openai_compatible",
        "model": "fixture-model",
        "destination_digest": "d" * 64,
        "delivery_identity": {
            "seal_sha256": "a" * 64,
            "entry_count": 212,
            "overlay_root_sha256": "b" * 64,
            "verifier_sha256": "c" * 64,
        },
        "attempts": [{**attempt, "attempt_id": f"attempt-{index}"} for index in range(1, 4)],
    }

    assert e3.receipt_errors(receipt, secret_needles=()) == []
    false_receipt = {
        **receipt,
        "attempts": [
            *receipt["attempts"][:2],
            {
                **receipt["attempts"][2],
                "claims": {
                    **receipt["attempts"][2]["claims"],
                    e3.CLAIM_NAMES[0]: False,
                },
            },
        ],
    }
    assert any("non-passing claim" in error for error in e3.receipt_errors(false_receipt))
    assert any(
        "secret" in error for error in e3.receipt_errors(receipt, secret_needles=("fixture-model",))
    )
    assert any(
        "current seal" in error
        for error in e3.receipt_errors(
            receipt,
            expected_delivery_identity={
                **receipt["delivery_identity"],
                "overlay_root_sha256": "f" * 64,
            },
        )
    )


def test_016_receipt_validator_rejects_ambiguous_metadata_and_open_maps() -> None:
    attempt = {
        "attempt_id": "attempt-1",
        "journey_verdicts": {journey: True for journey in e3.JOURNEY_IDS},
        "claims": {claim: True for claim in e3.CLAIM_NAMES},
        "counts": {
            "model_responses": 8,
            "model_send_attempts": 8,
            "web_receipts": 3,
            "web_send_attempts": 3,
            "file_effects": 5,
            "process_receipts": 3,
        },
        "install_artifact_sha256": "e" * 64,
        "workspace_verdicts": {
            "empty_artifact_exact": True,
            "existing_edit_surgical": True,
            "research_artifact_linked": True,
            "mixed_artifact_exact": True,
            "rejected_process_tree_unchanged": True,
            "corrected_path_exact": True,
            "restart_artifact_exact": True,
        },
        "recovery_verdicts": {
            "restart_no_replay": True,
            "unknown_no_replay": True,
        },
        "ux_verdicts": {key: True for key in e3._UX_VERDICT_KEYS},
    }
    receipt = {
        "schema": "first-agent-016-e3-receipt-v2",
        "observed_at": "not-a-time",
        "provider_family": "openai_compatible",
        "model": "",
        "destination_digest": "d" * 64,
        "delivery_identity": {
            "seal_sha256": "a" * 64,
            "entry_count": 212,
            "overlay_root_sha256": "b" * 64,
            "verifier_sha256": "c" * 64,
        },
        "attempts": [attempt, attempt, attempt],
    }

    errors = e3.receipt_errors(receipt)

    assert any("observed_at" in error for error in errors)
    assert any("model" in error for error in errors)
    assert any("attempt IDs" in error for error in errors)


def test_016_workspace_snapshot_and_profile_oracles_are_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "README.md").write_text("hello\n", encoding="utf-8")
    assert e3._workspace_snapshot(workspace) == {
        "README.md": hashlib.sha256(b"hello\n").hexdigest()
    }

    provider = tmp_path / "provider-profile.json"
    web = tmp_path / "web-profile.json"
    provider.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider_type": "openai_compatible",
                "model": "fixture-model",
                "base_url": "https://provider.example/v1",
                "credential_env": "FIRST_AGENT_E3_MODEL_KEY",
                "thinking_mode": "disabled",
                "request_path": None,
                "strict_tools": False,
                "timeout_seconds": 30.0,
            }
        ),
        encoding="utf-8",
    )
    web.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "tavily",
                "destination": "https://api.tavily.com",
                "credential_env": "FIRST_AGENT_WEB_API_KEY",
                "timeout_seconds": 10.0,
                "max_results": 5,
                "search_depth": "basic",
                "extract_depth": "basic",
                "trust_notice_id": "tavily-public-input-v1",
                "trust_notice_digest": "a" * 64,
                "profile_digest": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/v1",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )

    assert e3._profile_documents_valid((provider, web), config=config)
    provider_document = json.loads(provider.read_text(encoding="utf-8"))
    provider_document["unexpected"] = True
    provider.write_text(json.dumps(provider_document), encoding="utf-8")
    assert not e3._profile_documents_valid((provider, web), config=config)


def test_016_first_launch_oracle_rejects_send_effect_and_error_output() -> None:
    result = e3.CommandResult(
        2,
        "First Agent is not configured. Run: first-agent setup\n",
    )
    counts = {"model_send_attempts": 0, "web_send_attempts": 0}

    assert e3._first_launch_is_closed(
        result,
        transport_before=counts,
        transport_after=counts,
        workspace_before={},
        workspace_after={},
        no_checkpoint_created=True,
    )
    assert not e3._first_launch_is_closed(
        e3.CommandResult(result.returncode, result.output + "Traceback: hidden crash\n"),
        transport_before=counts,
        transport_after=counts,
        workspace_before={},
        workspace_after={},
        no_checkpoint_created=True,
    )
    assert not e3._first_launch_is_closed(
        result,
        transport_before=counts,
        transport_after={"model_send_attempts": 1, "web_send_attempts": 0},
        workspace_before={},
        workspace_after={"unexpected.txt": "a" * 64},
        no_checkpoint_created=True,
    )


def test_016_setup_transcript_oracles_require_exact_prompts_and_one_next_step() -> None:
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/v1",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )
    provider_output = (
        "Provider [openai_compatible/anthropic_compatible]: "
        "Model name: Provider base URL: "
        "Credential environment variable [FIRST_AGENT_API_KEY]: "
        "Provider profile saved. provider=openai_compatible, model=fixture-model, "
        "destination=https://provider.example/v1, "
        "credential_env=FIRST_AGENT_E3_MODEL_KEY. Secret values were not stored. "
        "Next: export FIRST_AGENT_E3_MODEL_KEY='<your-key>' and run first-agent.\n"
    )
    web_output = (
        "Optional Web access sends exact public queries and approved public URLs "
        "to the third party Tavily service at https://api.tavily.com. "
        "Enable Tavily Web? [y/N]: Tavily Web profile saved. "
        "destination=https://api.tavily.com, credential_env=FIRST_AGENT_WEB_API_KEY, "
        "max_results=5. Secret values were not stored. Third-party handling notice: "
        "public inputs. Next: export FIRST_AGENT_WEB_API_KEY='<your-key>' "
        "and run first-agent.\n"
    )

    assert e3._provider_setup_output_is_closed(
        e3.CommandResult(0, provider_output), config
    )
    assert e3._web_setup_output_is_closed(e3.CommandResult(0, web_output))
    assert not e3._provider_setup_output_is_closed(
        e3.CommandResult(0, provider_output + "Next: run another command.\n"),
        config,
    )
    assert not e3._web_setup_output_is_closed(
        e3.CommandResult(0, web_output.replace("third party", "remote service"))
    )


def test_016_startup_oracle_requires_readable_capabilities_and_zero_effect() -> None:
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/v1",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )
    workspace = Path("/disposable/existing-project")
    output = (
        "First Agent is ready in: existing-project "
        "(provider: openai_compatible/fixture-model)\n"
        "Capabilities: files, history, local programs\n"
        "Web: temporarily unavailable; set FIRST_AGENT_WEB_API_KEY\n"
        "Status: no unfinished task\n"
    )
    counts = {"model_send_attempts": 0, "web_send_attempts": 0}
    sentinel = {"existing-project.txt": "a" * 64}

    assert e3._startup_output_is_closed(
        e3.CommandResult(0, output),
        workspace=workspace,
        config=config,
        web_status="temporarily_unavailable",
    )
    assert e3._zero_startup_effect(
        transport_before=counts,
        transport_after=counts,
        workspace_before=sentinel,
        workspace_after=sentinel,
    )
    assert not e3._startup_output_is_closed(
        e3.CommandResult(0, output.replace("files, history, local programs", "ready")),
        workspace=workspace,
        config=config,
        web_status="temporarily_unavailable",
    )
    assert not e3._zero_startup_effect(
        transport_before=counts,
        transport_after={"model_send_attempts": 0, "web_send_attempts": 1},
        workspace_before=sentinel,
        workspace_after={**sentinel, "unexpected.txt": "b" * 64},
    )


def test_016_openai_setup_keeps_guided_flow_then_persists_frozen_protocol(
    tmp_path: Path,
) -> None:
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/v1",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )

    class RecordingConsole:
        def __init__(self) -> None:
            self.config = config
            self.calls: list[tuple[list[str], tuple[str, ...]]] = []

        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            input_lines: tuple[str, ...] = (),
        ) -> e3.CommandResult:
            assert cwd == tmp_path
            self.calls.append((args, input_lines))
            return e3.CommandResult(0, "")

    console = RecordingConsole()

    assert e3._setup_provider(console, tmp_path)  # type: ignore[arg-type]
    assert console.calls[0] == (
        ["setup"],
        (
            "openai_compatible",
            "fixture-model",
            "https://provider.example/v1",
            "FIRST_AGENT_E3_MODEL_KEY",
        ),
    )
    assert len(console.calls) == 1


def test_016_guided_setup_rejects_hidden_compatible_request_path(
    tmp_path: Path,
) -> None:
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/beta",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
        request_path="/chat/completions",
    )

    class RecordingConsole:
        def __init__(self) -> None:
            self.config = config
            self.calls: list[tuple[list[str], tuple[str, ...]]] = []

        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            input_lines: tuple[str, ...] = (),
        ) -> e3.CommandResult:
            assert cwd == tmp_path
            self.calls.append((args, input_lines))
            return e3.CommandResult(0, "")

    console = RecordingConsole()

    assert not e3._setup_provider(console, tmp_path)  # type: ignore[arg-type]
    assert console.calls == []


def test_016_anthropic_setup_does_not_send_an_openai_request_path_answer(
    tmp_path: Path,
) -> None:
    config = e3.E3Config(
        provider="anthropic_compatible",
        base_url="https://provider.example/anthropic",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )

    class RecordingConsole:
        def __init__(self) -> None:
            self.config = config
            self.calls: list[tuple[list[str], tuple[str, ...]]] = []

        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            input_lines: tuple[str, ...] = (),
        ) -> e3.CommandResult:
            assert cwd == tmp_path
            self.calls.append((args, input_lines))
            return e3.CommandResult(0, "")

    console = RecordingConsole()

    assert e3._setup_provider(console, tmp_path)  # type: ignore[arg-type]
    assert console.calls == [
        (
            ["setup"],
            (
                "anthropic_compatible",
                "fixture-model",
                "https://provider.example/anthropic",
                "FIRST_AGENT_E3_MODEL_KEY",
            ),
        )
    ]


def test_016_web_setup_keeps_guided_flow_then_binds_e3_credential_name(
    tmp_path: Path,
) -> None:
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.example/v1",
        model="fixture-model",
        api_key="model-secret",
        web_api_key="web-secret",
    )

    class RecordingConsole:
        def __init__(self) -> None:
            self.config = config
            self.calls: list[tuple[list[str], tuple[str, ...]]] = []

        def run(
            self,
            args: list[str],
            *,
            cwd: Path,
            input_lines: tuple[str, ...] = (),
        ) -> e3.CommandResult:
            assert cwd == tmp_path
            self.calls.append((args, input_lines))
            return e3.CommandResult(0, "")

    console = RecordingConsole()

    assert e3._setup_web(console, tmp_path)  # type: ignore[arg-type]
    assert console.calls == [(["setup-web"], ("yes",))]


def test_016_process_approval_uses_exact_current_artifact_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "greet.py"
    artifact.write_text("return 'hello!'\n", encoding="utf-8")

    class Requirement:
        artifact_path = "greet.py"

    class Request:
        artifact_confirmation_requirement = Requirement()

    assert e3._artifact_approval_command(Request(), tmp_path) == (
        "/approve-artifact "
        + hashlib.sha256(artifact.read_bytes()).hexdigest()
        + " greet.py"
    )

    artifact.unlink()
    assert e3._artifact_approval_command(Request(), tmp_path) is None


def test_016_interactive_terminal_output_preserves_provider_classification() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "print('The provider response was incompatible.')",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    session = e3.InteractiveSession(process)

    with pytest.raises(e3.InstalledConsoleTerminatedError) as caught:
        session.wait_for_prompt(timeout=5)

    assert caught.value.result.returncode == 0
    assert (
        e3._classify_attempt_blocker(
            outputs=caught.value.result.output,
            observations={},
            all_passed=False,
        )
        == "provider_protocol"
    )


def test_016_interactive_eof_waits_for_the_exiting_process() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"The provider response was incompatible.\n")
    os.close(write_fd)

    class ExitingProcess:
        def __init__(self) -> None:
            self.stdout = os.fdopen(read_fd, "rb")
            self.stdin = None
            self.returncode = None
            self.terminated = False

        def poll(self):  # noqa: ANN201
            return self.returncode

        def wait(self, *, timeout):  # noqa: ANN001, ANN201
            self.returncode = 0
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True

    process = ExitingProcess()
    session = e3.InteractiveSession(process)  # type: ignore[arg-type]

    with pytest.raises(e3.InstalledConsoleTerminatedError) as caught:
        session.wait_for_prompt(timeout=1)

    assert caught.value.result.returncode == 0
    assert not process.terminated


def test_016_interactive_timeout_preserves_bounded_output_and_reaps_process() -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time; print('still working', flush=True); time.sleep(10)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    session = e3.InteractiveSession(process)
    assert process.stdout is not None
    readable, _, _ = select.select([process.stdout.fileno()], [], [], 5)
    assert readable, "fixture did not publish its bounded output"

    with pytest.raises(e3.InstalledConsoleTimeoutError) as caught:
        session.wait_for_prompt(timeout=0.05)

    assert caught.value.result.returncode == 124
    assert "still working" in caught.value.result.output
    assert process.poll() is not None


def test_016_ux_oracle_requires_exact_disclosure_and_approval_text() -> None:
    disclosure = SimpleNamespace(
        canonical_destination="https://provider.example/v1",
        model="fixture-model",
        data_classes=("conversation_text", "tool_results"),
    )
    state = SimpleNamespace(provider_disclosure_request=disclosure)
    evidence: dict[str, list[bool]] = {}
    session = SimpleNamespace(
        latest_prompt=(
            "Remote provider disclosure required\n"
            "destination: https://provider.example/v1\n"
            "model: fixture-model\n"
            "data: conversation_text, tool_results\n"
            "Allow this information to be sent? [y/N]\n> "
        )
    )

    e3._record_disclosure_ux(session, state, evidence)
    request = SimpleNamespace(
        tool_name="local_process",
        risk="high",
        side_effect="process",
        preview=f"executable: ./check\n{e3.SAME_UID_TRUST_NOTICE}",
    )
    session.latest_prompt = (
        "Approval required\n"
        "tool: local_process\n"
        "risk/effect: high/process\n"
        f"preview: {e3._terminal_atom(request.preview)}\n"
        "Execute this operation? [y/N]\n> "
    )
    e3._record_approval_ux(session, request, evidence)

    assert evidence == {
        "provider_disclosure_exact": [True],
        "process_approval_exact": [True],
        "process_trust_notice_exact": [True],
    }
    session.latest_prompt = "Approval required\ntool: local_process\n> "
    e3._record_approval_ux(session, request, evidence)
    assert evidence["process_approval_exact"] == [True, False]


def test_016_transport_count_oracle_rejects_open_records(tmp_path: Path) -> None:
    ledger = tmp_path / "transport-attempts.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "schema": "first-agent/transport-attempt/v1",
                "kind": "model",
                "destination_digest": "a" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert e3._transport_counts(ledger) == {
        "model_send_attempts": 1,
        "web_send_attempts": 0,
    }
    ledger.write_text('{"kind":"model","payload":"secret"}\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="open or invalid"):
        e3._transport_counts(ledger)


def test_016_online_blocker_classification_is_closed_and_fail_closed() -> None:
    empty_observations = {"J5": {"failure_codes": ()}}
    assert (
        e3._classify_attempt_blocker(
            outputs="Provider authentication failed.",
            observations=empty_observations,
            all_passed=False,
        )
        == "auth_failed"
    )
    assert (
        e3._classify_attempt_blocker(
            outputs="",
            observations={"J8": {"failure_codes": ("web_auth",)}},
            all_passed=False,
            failed_journeys={"J8"},
        )
        == "web_auth_failed"
    )
    assert (
        e3._classify_attempt_blocker(
            outputs="",
            observations={
                "J8": {"failure_codes": ("web_service",)},
                "J10": {"failure_codes": ()},
            },
            all_passed=False,
            failed_journeys={"J10"},
        )
        == "product_failure"
    )
    assert (
        e3._classify_attempt_blocker(
            outputs="unclassified failure",
            observations=empty_observations,
            all_passed=False,
        )
        == "product_failure"
    )
    assert (
        e3._classify_attempt_blocker(
            outputs="Provider authentication failed.",
            observations=empty_observations,
            all_passed=True,
        )
        is None
    )


def test_016_failure_detail_contains_only_closed_verdict_ids() -> None:
    assert e3._closed_failure_detail(
        {"J1": True, "J8": False, "J12": False},
        {"research_artifact_linked": False, "restart_artifact_exact": True},
    ) == "journeys=J8,J12;workspaces=research_artifact_linked"


def test_interaction_violations_are_bounded_class_ids_without_output_text() -> None:
    violations = e3._interaction_violation_ids(
        {
            "J5": e3.CommandResult(0, "Please say 'continue' to proceed"),
            "J6": e3.CommandResult(0, "internal goal_id should not render"),
            "J7": e3.CommandResult(0, "ordinary result"),
        }
    )

    assert violations == ("J5:continue_prompt", "J6:internal_goal_id")


def test_016_failure_detail_appends_baseline_counts_for_failed_journey() -> None:
    # J11/J12 的 verdict 是 correction/restart 前后的分类计数等值;失败细节只有终态
    # 总量时无法区分"模型方差"与"产品缺口"。失败旅程必须同时给出终态分类计数、
    # transport_end 计数与 before_* 基线(全部是小整数,secret-free)。
    detail = e3._closed_failure_detail(
        {"J11": False, "J8": True},
        {"corrected_path_exact": False},
        observations={
            "J11": {
                "goal_status": "verified_done",
                "failure_codes": (),
                "source_receipts": 16,
                "web_source_receipts": 13,
                "history_source_receipts": 1,
                "workspace_source_receipts": 2,
                "web_effects": 13,
                "file_effects": 1,
                "process_receipts": 0,
            },
            "J8": {"goal_status": "verified_done"},
        },
        journey_observations={
            "J11": {
                "unexpected_process_candidate": "argv_nonempty",
                "before_correction": {
                    "source_receipts": 14,
                    "web_source_receipts": 13,
                    "history_source_receipts": 1,
                    "workspace_source_receipts": 0,
                    "web_effects": 13,
                    "model_send_attempts": 31,
                    "web_send_attempts": 13,
                },
                "transport_end": {
                    "model_send_attempts": 33,
                    "web_send_attempts": 14,
                },
            },
            "J8": {"transport_end": {"model_send_attempts": 10}},
        },
        interaction_violations=("J11:internal_request_id",),
    )
    assert "journeys=J11;workspaces=corrected_path_exact" in detail
    assert "interaction_violations=J11:internal_request_id" in detail
    assert (
        "J11[goal=verified_done,failure_codes=(),source_receipts=16,"
        "web_source_receipts=13,history_source_receipts=1,workspace_source_receipts=2,"
        "web_effects=13,file_effects=1,process_receipts=0,"
        "unexpected_process_candidate=argv_nonempty,"
        "transport_end(model_send_attempts=33|web_send_attempts=14),"
        "before_correction(source_receipts=14|web_source_receipts=13|"
        "history_source_receipts=1|workspace_source_receipts=0|web_effects=13|"
        "model_send_attempts=31|web_send_attempts=13)]" in detail
    )
    assert "J8[" not in detail


def test_016_failure_detail_exposes_j10_closed_subchecks_without_transcript() -> None:
    detail = e3._closed_failure_detail(
        {"J10": False},
        {"rejected_process_tree_unchanged": False},
        observations={
            "J10": {
                "goal_status": e3.GoalStatus.BLOCKED,
                "failure_codes": (),
                "process_receipts": 0,
            }
        },
        journey_observations={
            "J10": {
                "j10_returncode_zero": True,
                "j10_tree_unchanged": False,
                "j10_result_accurate": True,
                "j10_refused_class_expected": True,
                "j10_expected_candidate_refused": True,
                "j10_before_receipts_zero": True,
                "j10_before_leases_zero": True,
                "j10_final_receipts_zero": True,
                "j10_final_leases_zero": True,
                "j10_goal_not_verified_done": True,
            }
        },
    )

    assert "j10_returncode_zero=True" in detail
    assert "j10_tree_unchanged=False" in detail
    assert "j10_result_accurate=True" in detail
    assert "j10_refused_class_expected=True" in detail
    assert "j10_expected_candidate_refused=True" in detail
    assert "j10_before_receipts_zero=True" in detail
    assert "j10_before_leases_zero=True" in detail
    assert "j10_final_receipts_zero=True" in detail
    assert "j10_final_leases_zero=True" in detail
    assert "j10_goal_not_verified_done=True" in detail


def test_016_interaction_failure_detail_includes_returncode() -> None:
    # 交互异常细节必须携带真实退出码:SIGKILL(-9)、异常退出(1)与正常退出(0)对应
    # 完全不同的处置(环境 kill / 产品 crash / 退出竞态),否则无法定诊。
    error = e3.InstalledConsoleTerminatedError(
        e3.CommandResult(-9, "Provider disclosure required\n ... tail text ...")
    )
    detail = e3._interaction_failure_detail("J8", error)
    assert detail.startswith("journeys=J8;error=InstalledConsoleTerminatedError;")
    assert "returncode=-9;" in detail
    assert detail.endswith("tail=Provider disclosure required ... tail text ...")


def test_016_interaction_failure_detail_extracts_fatal_lines() -> None:
    # FAILED_FATAL 的 "Run failed: <code> (<summary>)" 渲染后会跟随长 sources
    # 投影,800 字符 tail 会把它挤掉;交互异常细节必须从全量输出提取 fatal 行。
    output = (
        "Approval required\n"
        "tool: web_search\n> yes\n"
        "Run failed: runtime_failure (CheckpointConflictError: revision 7 != 6)\n"
        + "· complete - workspace_excerpt · " + "x" * 1200 + "\n"
    )
    error = e3.InstalledConsoleTerminatedError(e3.CommandResult(1, output))
    detail = e3._interaction_failure_detail("J8", error)
    assert "fatal=Run failed: runtime_failure (CheckpointConflictError: revision 7 != 6)" in detail


def test_016_interaction_failure_detail_extracts_closed_control_shape() -> None:
    # CLI 对普通用户隐藏 provider wire 细节，但三连 executor 必须能区分缺字段、
    # 多字段和错误 kind。只提取 shared decoder 自己生成的 bounded field-name
    # 摘要，不保留 response payload、用户文本或 tool arguments。
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                content={
                    "code": "invalid_provider_response",
                    "text": (
                        "Previous response was rejected (malformed_control). "
                        "Rejected payload shape: expected exactly ['blocker', "
                        "'correlation_id']; missing ['blocker']; unexpected ['text']."
                    ),
                }
            ),
        )
    )
    error = e3.InstalledConsoleTerminatedError(
        e3.CommandResult(1, "The provider response was incompatible.")
    )

    detail = e3._interaction_failure_detail("J9", error, state=state)

    assert "shape=expected exactly" in detail
    assert "missing ['blocker']" in detail
    assert "unexpected ['text']" in detail
    assert "Previous response" not in detail


def test_016_interaction_failure_detail_extracts_only_closed_control_reason() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                content={
                    "code": "invalid_model_control",
                    "text": (
                        "Control kind direct_response is not currently available and "
                        "was not accepted. Allowed control kinds now: completion_claim, "
                        "blocked_claim. Secret/model/path detail: DO_NOT_LEAK."
                    ),
                }
            ),
            SimpleNamespace(
                content={
                    "code": "invalid_model_control",
                    "text": (
                        "Control rejected by current trusted state: stale goal "
                        "DO_NOT_LEAK. Use trusted_goal values."
                    ),
                }
            ),
        )
    )
    error = e3.InstalledConsoleTerminatedError(
        e3.CommandResult(1, "Run failed: invalid_model_control")
    )

    detail = e3._interaction_failure_detail("J8", error, state=state)

    assert (
        "control_reason=unavailable_control:direct_response:"
        "allowed=blocked_claim,completion_claim"
    ) in detail
    assert "control_reason=trusted_state_rejected" in detail
    assert "DO_NOT_LEAK" not in detail
    assert "stale goal" not in detail


def test_016_interaction_failure_detail_classifies_trusted_state_rejection() -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                content={
                    "code": "invalid_model_control",
                    "text": (
                        "Control rejected by current trusted state: current evidence "
                        "does not prove every mandatory criterion. Use trusted_goal "
                        "values and a new correlation_id."
                    ),
                }
            ),
            SimpleNamespace(
                content={
                    "code": "invalid_model_control",
                    "text": (
                        "Control rejected by current trusted state: unknown rejection "
                        "DO_NOT_LEAK. Use trusted_goal values."
                    ),
                }
            ),
        )
    )
    error = e3.InstalledConsoleTerminatedError(
        e3.CommandResult(1, "Run failed: invalid_model_control")
    )

    detail = e3._interaction_failure_detail("J6", error, state=state)

    assert (
        "control_reason=trusted_state_rejected:mandatory_evidence_incomplete"
        in detail
    )
    assert "control_reason=trusted_state_rejected" in detail
    assert "DO_NOT_LEAK" not in detail
    assert "current evidence" not in detail


@pytest.mark.parametrize(
    ("trusted_error", "reason"),
    (
        ("goal identity mismatch", "goal_identity_mismatch"),
        ("goal revision mismatch", "goal_revision_mismatch"),
        (
            "completion claim requires an executable goal",
            "completion_goal_not_executable",
        ),
        ("control correlation_id was already accepted", "correlation_reused"),
        ("completion claim references unknown evidence", "unknown_evidence"),
        (
            "evidence does not bind the current admitted criterion",
            "evidence_binding_mismatch",
        ),
        (
            "unknown effect recovery has priority over goal verification",
            "unknown_effect_pending",
        ),
        (
            "goal status is not eligible for completion verification",
            "completion_goal_not_eligible",
        ),
        ("completion claim is stale", "completion_stale"),
        ("goal has no mandatory criterion", "mandatory_criterion_missing"),
        (
            "every proposed completion criterion requires a typed evidence oracle",
            "criterion_oracle_missing",
        ),
        (
            "artifact criterion must be admitted before completion verification",
            "artifact_criterion_not_admitted",
        ),
        (
            "process criterion must be admitted before completion verification",
            "process_criterion_not_admitted",
        ),
    ),
)
def test_016_trusted_state_diagnostic_uses_closed_reason(
    trusted_error: str,
    reason: str,
) -> None:
    state = SimpleNamespace(
        facts=(
            SimpleNamespace(
                content={
                    "code": "invalid_model_control",
                    "text": (
                        "Control rejected by current trusted state: "
                        f"{trusted_error}. Use trusted_goal values and a new "
                        "correlation_id."
                    ),
                }
            ),
        )
    )

    assert e3._closed_model_control_reasons(state) == (
        f"trusted_state_rejected:{reason}",
    )


def test_016_failure_detail_names_false_claims_and_ux_verdicts() -> None:
    # 016 真实 E3 第 46 轮:12 journeys 全过但某 claim/ux_verdict 为 false 时,
    # FAIL_DETAIL 完全沉默,整轮零信息损失。false 的 claim 名与 ux 键必须打印。
    detail = e3._closed_failure_detail(
        {"J1": True, "J8": True},
        {"research_artifact_linked": True},
        claims={
            "successful_journeys_need_no_continue_mode_or_internal_id": False,
            "receipts_outputs_and_profiles_are_secret_free": True,
        },
        ux_verdicts={
            "web_approval_exact": False,
            "provider_disclosure_exact": True,
        },
    )
    assert (
        "claims=successful_journeys_need_no_continue_mode_or_internal_id"
        in detail
    )
    assert "receipts_outputs_and_profiles_are_secret_free" not in detail
    assert "ux=web_approval_exact" in detail
    assert "provider_disclosure_exact" not in detail.split("ux=")[-1]


def test_016_failure_detail_appends_workspace_delta_for_false_verdict() -> None:
    # workspace 判据是 closed tree delta + invocation ledger 的合取;失败细节只有
    # verdict 名时无法知道是哪个文件/几行 ledger 破坏精确性。false 的 workspace
    # verdict 必须附实际 added/removed/changed 路径与 ledger 行(均为冻结 fixture
    # 内的 workspace-relative 名称,secret-free)。
    detail = e3._closed_failure_detail(
        {"J7": False},
        {"existing_edit_surgical": False, "restart_artifact_exact": True},
        workspace_notes={
            "existing_edit_surgical": (
                "added=.process-invocations,greet.py.bak|removed=-|changed=greet.py"
                "|ledger=check-greet,check-greet"
            ),
            "restart_artifact_exact": "added=report.md|removed=-|changed=-|ledger=check-report",
        },
    )
    assert (
        "existing_edit_surgical[added=.process-invocations,greet.py.bak|removed=-"
        "|changed=greet.py|ledger=check-greet,check-greet]" in detail
    )
    assert "restart_artifact_exact[" not in detail


def test_016_failure_detail_appends_bounded_per_journey_observation() -> None:
    # 真实三连失败时只有旅程名不足以定位产品缺口;每个失败旅程必须附带
    # bounded、secret-free 的观察摘要(goal 状态、failure codes、effect 计数),
    # 且不引入原文或凭据。
    detail = e3._closed_failure_detail(
        {"J7": False, "J8": True},
        {"existing_edit_surgical": False},
        observations={
            "J7": {
                "goal_status": None,
                "failure_codes": ("goal_window_closed",),
                "failed_tool_codes": ("read_file:goal_window_closed",),
                "file_effects": 0,
                "process_receipts": 0,
                "source_receipts": 3,
            },
            "J8": {"goal_status": "verified_done"},
        },
    )
    assert "journeys=J7;workspaces=existing_edit_surgical" in detail
    assert (
        "J7[goal=none,failure_codes=('goal_window_closed',),"
        "failed_tool_codes=('read_file:goal_window_closed',),"
        "source_receipts=3,file_effects=0,process_receipts=0]" in detail
    )
    assert "J8[" not in detail
