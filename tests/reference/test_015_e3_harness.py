"""015 E3 harness 的离线结构合同测试。

证明 ``scripts/run_015_e3.py`` 是 real runner（非 stub）：config-present path 调 production
adapter（AST）、harness core provider-injected、26 claims closed boolean 从 durable facts
重算、owner-only fixtures、secret-free receipt、三连逻辑、partial/missing config marker。
**Fake/scripted provider 仅作离线结构测试，不作 E3 pass 证据**；real mode 走真实 adapter。
"""

from __future__ import annotations

import ast
import json
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_015_e3 as e3  # noqa: E402
import verify_015_materialized_tree as v015  # noqa: E402

SCRIPT = ROOT / "scripts" / "run_015_e3.py"


def test_015_e3_harness_has_26_closed_boolean_claims() -> None:
    assert len(e3.CLAIM_NAMES) == 26
    assert len(set(e3.CLAIM_NAMES)) == 26  # unique


def test_015_e3_receipt_is_detached_from_overlay_and_strictly_verified() -> None:
    receipt_path = "docs/acceptance/015_GOVERNED_LOCAL_ACTION_E3_RECEIPTS.json"
    assert receipt_path in v015.CONTROL_PATHS
    seal = {"entry_count": 200, "overlay_root_sha256": "0" * 64}
    fixture_digest = "1" * 64
    attempt = {
        "attempt_id": "attempt-1",
        "started_at": "2026-08-16T00:00:00Z",
        "ended_at": "2026-08-16T00:01:00Z",
        "journey_verdicts": {},
        "claims": {name: True for name in e3.CLAIM_NAMES},
        "model_send_count": 21,
        "process_receipt_digest": "2" * 64,
        "process_output_digests": [],
        "artifact_digest": "3" * 64,
        "fixture_invocation_count": 7,
    }
    receipt = {
        "contract_version": "015-e3/v1",
        "acceptance_status": "accepted",
        "provider_family": "openai_compatible",
        "model": "fixture-model",
        "destination_digest": "4" * 64,
        "delivery_seal_sha256": "5" * 64,
        "fixture_identity_digest": fixture_digest,
        "materialized_identity": {
            "entry_count": 200,
            "overlay_root_sha256": "0" * 64,
            "composition_under_install": True,
            "install_root_digest": "6" * 64,
        },
        "reviewer_handoff": "015-fresh-reviewer/v1",
        "attempts": [{**attempt, "attempt_id": f"attempt-{i}"} for i in range(1, 4)],
    }

    assert v015._attestation_errors(
        receipt,
        seal=seal,
        seal_digest="5" * 64,
        fixture_identity_digest=fixture_digest,
    ) == []

    stale = {**receipt, "delivery_seal_sha256": "7" * 64}
    assert any(
        "seal digest drift" in error
        for error in v015._attestation_errors(
            stale,
            seal=seal,
            seal_digest="5" * 64,
            fixture_identity_digest=fixture_digest,
        )
    )
    false_claim = json.loads(json.dumps(receipt))
    false_claim["attempts"][1]["claims"][e3.CLAIM_NAMES[0]] = False
    assert any(
        "non-passing claim" in error
        for error in v015._attestation_errors(
            false_claim,
            seal=seal,
            seal_digest="5" * 64,
            fixture_identity_digest=fixture_digest,
        )
    )


def test_015_e3_fixtures_are_owner_only_executables(tmp_path: Path) -> None:
    fixtures = e3.FixtureSet.create(tmp_path / "root")
    assert set(fixtures.paths) == {
        "write-artifact",
        "echo-argv",
        "count-run",
        "hang-tree",
        "print-env-keys",
    }
    for name in fixtures.paths:
        path = fixtures.workspace / name
        assert path.exists()
        info = path.stat()
        assert stat.S_ISREG(info.st_mode)
        assert info.st_mode & stat.S_IXUSR  # owner-only executable


def test_015_every_fixture_updates_independent_invocation_ledger(tmp_path: Path) -> None:
    """echo/env 类无业务 artifact 的 fixture 也必须可证明 preapproval spawn。"""

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    subprocess.run(
        [str(fixtures.workspace / "echo-argv"), "probe"],
        cwd=fixtures.workspace,
        check=True,
        capture_output=True,
    )
    from agent.runtime.contracts import ConversationState

    snapshot = e3._approval_snapshot(
        "mutation",
        ConversationState.new("conversation-ledger"),
        fixtures,
        fingerprint="f" * 64,
        counter_baseline=0,
        artifact_baseline=False,
        ledger_baseline=0,
    )
    assert snapshot["fixture_ledger_delta"] == 1
    assert snapshot["receipt_count"] == 0
    assert snapshot["unreceipted_side_effect"] is True


def test_015_e3_config_from_env_markers(tmp_path: Path) -> None:
    # 四项全缺 → None（caller 输出 NEEDS）。
    assert e3.E3Config.from_env({}) is None
    # 部分缺失 → _IncompleteConfigError（caller 输出 incomplete_config）。
    with pytest.raises(e3._IncompleteConfigError) as exc:
        e3.E3Config.from_env(
            {
                "FIRST_AGENT_015_E3_PROVIDER": "openai_compatible",
                "FIRST_AGENT_015_E3_BASE_URL": "https://provider.invalid",
            }
        )
    assert "FIRST_AGENT_015_E3_MODEL" in exc.value.missing
    # 齐全 → config（不回显 key 到这里；config 仅持有 value，receipt 不写它）。
    config = e3.E3Config.from_env(
        {
            "FIRST_AGENT_015_E3_PROVIDER": "openai_compatible",
            "FIRST_AGENT_015_E3_BASE_URL": "https://provider.invalid",
            "FIRST_AGENT_015_E3_MODEL": "fixture-model",
            "FIRST_AGENT_015_E3_API_KEY": "fixture-key",
        }
    )
    assert config is not None
    assert config.model == "fixture-model"


def test_015_e3_main_returns_nonzero_when_real_evidence_is_blocked(monkeypatch) -> None:
    monkeypatch.setattr(e3, "offline_gates_green", lambda: True)
    for name in (
        "FIRST_AGENT_015_E3_PROVIDER",
        "FIRST_AGENT_015_E3_BASE_URL",
        "FIRST_AGENT_015_E3_MODEL",
        "FIRST_AGENT_015_E3_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert e3.main([]) != 0

    monkeypatch.setenv("FIRST_AGENT_015_E3_PROVIDER", "openai_compatible")
    assert e3.main([]) != 0


def test_015_e3_receipt_is_secret_free(tmp_path: Path) -> None:
    del tmp_path  # receipt 不需要 fixture，仅证明 secret-free 序列化
    observation = e3.AttemptObservation(
        attempt_id="attempt-0",
        claims={name: True for name in e3.CLAIM_NAMES},
        model_send_count=4,
        process_receipt_digest="d" * 64,
        fixture_invocation_count=1,
        secret_hits=(),
    )
    result = e3.ThreeConsecutiveResult(
        passed=True, attempts=[observation, observation, observation], blocker=""
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid",
        model="fixture-model",
        api_key="secret-canary-key",
    )
    receipt = e3.write_receipt(result, config)
    serialized = json.dumps(receipt, sort_keys=True)
    for forbidden in (
        "secret-canary-key",
        "Authorization",
        "Bearer ",
        "FIRST_AGENT_015_E3_API_KEY",
    ):
        assert forbidden not in serialized
    assert receipt["acceptance_status"] == "accepted"
    assert len(receipt["attempts"]) == 3


def test_015_final_receipt_projection_rejects_api_key() -> None:
    observation = e3.AttemptObservation(
        attempt_id="secret-canary-key",
        claims={name: True for name in e3.CLAIM_NAMES},
        model_send_count=1,
        process_receipt_digest=None,
        fixture_invocation_count=0,
        secret_hits=(),
    )
    result = e3.ThreeConsecutiveResult(
        passed=True,
        attempts=[observation, observation, observation],
        blocker="",
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid",
        model="fixture-model",
        api_key="secret-canary-key",
    )

    with pytest.raises(ValueError, match="secret oracle"):
        e3.write_receipt(result, config)


def test_015_secret_oracle_scans_rendered_results_and_fails_closed_on_read_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fixtures = e3.FixtureSet.create(tmp_path / "root")
    checkpoint = fixtures.state_root / "checkpoint.json"
    checkpoint.write_text("{}", encoding="utf-8")
    observed = {
        "event_sinks": [],
        "journeys": {},
        "rendered_results": [
            "visible " + e3.SYNTHETIC_CANARY_ENV["FIRST_AGENT_015_E3_CANARY"]
        ],
    }
    original_read_bytes = Path.read_bytes

    def fail_checkpoint_read(path: Path) -> bytes:
        if path == checkpoint:
            raise OSError("fixture read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_checkpoint_read)
    e3._record_canary_hits(observed, fixtures)

    assert "rendered_result" in observed["secret_hits"]
    assert "checkpoint_scan_error" in observed["secret_hits"]


def test_015_receipt_binds_section8_identity(tmp_path: Path) -> None:
    """F7（P2 review finding / E3 §8）：receipt 必须绑定 tree/seal/fixture/materialized
    identity + 每 attempt 时间/journey verdict/stdout-stderr digest+truncation/artifact
    digest + reviewer handoff——当前精简 JSON 与树无法密码学对账。secret-free 不变。"""

    observation = e3.AttemptObservation(
        attempt_id="attempt-f7",
        claims={name: True for name in e3.CLAIM_NAMES},
        model_send_count=4,
        process_receipt_digest="d" * 64,
        fixture_invocation_count=3,
        secret_hits=(),
        attempt_started_at="2026-08-15T00:00:00Z",
        attempt_ended_at="2026-08-15T00:02:00Z",
        journey_verdicts={"j1": "verified_done", "j3": "goal_ready"},
        process_output_digests=[
            {
                "stdout_digest": "a" * 64,
                "stderr_digest": "b" * 64,
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        ],
        artifact_digest="c" * 64,
        materialized_drive={
            "entry_count": 184,
            "overlay_root_sha256": "0" * 64,
            "composition_under_install": True,
            "install_root": "/tmp/015-install-fixture",
        },
    )
    result = e3.ThreeConsecutiveResult(
        passed=True, attempts=[observation] * 3, blocker=""
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid",
        model="fixture-model",
        api_key="secret-canary-key",
    )
    receipt = e3.write_receipt(result, config)
    # §8 identity 绑定。
    assert receipt["delivery_seal_sha256"]
    assert receipt["fixture_identity_digest"]
    assert receipt["materialized_identity"]["entry_count"] == 184
    assert receipt["materialized_identity"]["overlay_root_sha256"] == "0" * 64
    assert receipt["materialized_identity"]["composition_under_install"] is True
    assert receipt["reviewer_handoff"]
    attempt = receipt["attempts"][0]
    assert attempt["started_at"] == "2026-08-15T00:00:00Z"
    assert attempt["ended_at"] == "2026-08-15T00:02:00Z"
    assert attempt["journey_verdicts"]["j1"] == "verified_done"
    assert attempt["process_output_digests"][0]["stdout_digest"] == "a" * 64
    assert attempt["process_output_digests"][0]["stderr_truncated"] is False
    assert attempt["artifact_digest"] == "c" * 64
    serialized = json.dumps(receipt, sort_keys=True)
    for forbidden in ("secret-canary-key", "Authorization", "Bearer "):
        assert forbidden not in serialized
    # F3（P2 review finding / E3 §8）：不得保存 absolute temp path——
    # materialized identity 只保留 digest/count/under-install，不携带宿主路径。
    identity = receipt["materialized_identity"]
    assert "install_root" not in identity
    assert "site_dir" not in identity
    for key, value in identity.items():
        assert not (isinstance(value, str) and value.startswith(("/", "/private/", "/tmp/"))), (
            f"materialized identity must not carry host paths: {key}={value!r}"
        )


def test_015_fixture_invocation_count_recomputed_from_receipts(tmp_path: Path) -> None:
    """F7：fixture_invocation_count 必须从 durable process receipts 重算（此前
    `_record_fixture_invocation` 零调用点 → 恒 0，与真实执行矛盾）。scripted
    offline attempt 有多个 local_process receipt → count == receipt 总数且 > 0。"""

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers[journey_name](fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        return provider, ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )

    observation = e3.drive_attempt(
        factory, fixtures, attempt_id="inv", clock=None
    )
    raw = observation.raw_observed
    from agent.runtime.contracts import FactKind

    total_receipts = sum(
        1
        for state in raw["journeys"].values()
        for f in state.facts
        if f.kind is FactKind.TOOL_RESULT
        and isinstance(f.content.get("metadata"), dict)
        and f.content["metadata"].get("process_receipt_kind") == "process_v1"
    )
    assert total_receipts > 0, "scripted attempt must run local_process fixtures"
    assert observation.fixture_invocation_count == total_receipts, (
        f"fixture_invocation_count must equal durable process receipts "
        f"({total_receipts}), got {observation.fixture_invocation_count}"
    )


def test_015_e3_three_consecutive_failure_breaks_continuity(tmp_path: Path) -> None:
    """失败 attempt 打断三连连续性；不写 accepted receipt。"""

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def failing_factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers.get(journey_name, e3._J1JourneyProvider)(fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )
        return provider, descriptor

    # 注入一个 force-fail：把 claims 全置 False 模拟 attempt 失败。
    original = e3.drive_attempt

    def failing_drive(factory, fx, *, attempt_id, clock, **_):  # noqa: ANN001, ANN202
        observation = original(factory, fx, attempt_id=attempt_id, clock=clock)
        observation.claims = {name: False for name in e3.CLAIM_NAMES}
        return observation

    e3.drive_attempt = failing_drive
    try:
        result = e3.drive_three_consecutive(failing_factory, attempts=3)
    finally:
        e3.drive_attempt = original
    assert result.passed is False
    assert result.blocker == "product_no_progress"
    assert len(result.attempts) == 1  # 失败立即打断，不等三连


def test_015_e3_script_uses_production_adapter_not_stub() -> None:
    """AST：run_015_e3 调 production build_model_provider + drive_three_consecutive（非 stub）。"""

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "build_model_provider" in source, "real mode 必须装配 production HTTP adapter"
    assert "def drive_three_consecutive" in source
    assert "def drive_attempt" in source
    # 26 claim names 出现在源码（closed claim set）。
    for claim in (
        "process_receipt_kernel_minted",
        "executing_checkpoint_precedes_spawn",
        "closed_environment_secret_free",
    ):
        assert claim in source


def test_015_e3_drive_attempt_runs_real_local_process(tmp_path: Path) -> None:
    """drive_attempt 经 production composition + 真实 POSIX runner 执行 fixture。

    scripted provider（offline 结构测试）驱动同一 production composition；real local_process
    执行由 KernelToolRuntime.invoke 经 runner 完成。这是结构证明，**不是** E3 pass 证据。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers[journey_name](fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )
        return provider, descriptor

    observation = e3.drive_attempt(factory, fixtures, attempt_id="attempt-smoke", clock=None)
    # Core structural claims — always True regardless of process timing.
    assert observation.claims["process_receipt_kernel_minted"] is True
    assert observation.claims["kernel_tool_runtime_used"] is True
    assert observation.claims["typed_same_uid_execution_authority_bound"] is True
    assert observation.claims["production_composition_used"] is True
    assert observation.claims["single_runtime_loop_preserved"] is True
    assert observation.claims["durable_goal_before_process"] is True
    assert observation.claims["zero_spawn_before_approval"] is True
    assert observation.claims["approval_preview_exact_and_informed"] is True
    assert observation.claims["lease_goal_revision_workspace_bound"] is True
    assert observation.claims["output_bounded_and_untrusted"] is True
    assert observation.claims["closed_resource_profile_bound"] is True
    assert observation.claims["no_false_sandbox_claim"] is True
    # claim 22：J1 经 process receipt + filesystem read-back 双 evidence 达成 VERIFIED_DONE。
    assert (
        observation.claims["artifact_requires_process_and_readback_evidence"] is True
    )
    assert observation.process_receipt_digest  # 真实 receipt digest
    # Timing-sensitive claims (J3 timeout, J4 crash, J5 shell, J2 lease reuse)
    # are proven by dedicated tests; here we only assert that the harness
    # completed without error and drove >= 4 model turns.
    assert observation.model_send_count >= 4


def test_015_real_provider_factory_sends_http_via_injectable_transport() -> None:
    """real_provider_factory 经既有 http_client seam 装配真实 adapter 并发 HTTP request。

    证明 config-present path 用 production adapter（非 fake core）：注入 recording transport，
    provider.generate 实际向其发 request。AST/source-string presence 不是充分证据，这是 runtime
    证明。
    """

    import httpx

    from agent.provider.openai_http import OpenAICompatibleProvider
    from agent.provider.protocol import ProviderHTTPRetryableError
    from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage

    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(500)

    client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1/chat/completions",
        model="fixture-model",
        api_key="fixture-key",
    )
    factory = e3.real_provider_factory(config, http_client=client)
    provider, _descriptor = factory(None, None)
    # 真实 production adapter wrapped in counting proxy (parity with scripted .calls)
    assert isinstance(provider, e3._CountingProvider)
    assert isinstance(provider._delegate, OpenAICompatibleProvider)
    context = ContextPack(
        system="probe",
        messages=(ModelMessage(role="user", content=({"type": "text", "text": "probe"},),),),
        tools=(),
        budget=BudgetReport(input_limit=100, estimated_input_tokens=10, output_reserve=10),
    )
    with pytest.raises(ProviderHTTPRetryableError):
        provider.generate(context)
    # 真实 adapter 经 injectable transport 发了恰好一个 HTTP request。
    assert len(recorded) == 1
    assert recorded[0].url.host == "provider.invalid"
    assert recorded[0].headers.get("authorization")  # real adapter auth header（key 不回显）


def test_015_counting_seam_records_send_through_real_adapter() -> None:
    """goal A：真实 production adapter 经 _CountingProvider 记录 generate/send。

    用 production adapter + recording transport（不发真实网）证明 counting seam：
    - 成功 generate 计恰好一次 send；
    - 失败/异常 generate 也计一次（语义＝实际调用 delegate.generate，attempt counted，
      J4 restart 才能可靠探测重复 model 调用）；
    - 未实现 send_count seam 的 provider 显式失败（fail-closed，绝不默认 0）；
    - counting observation 只持久化整数 send_count，不存完整 prompt/context。
    """

    import httpx

    from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage

    def _context() -> ContextPack:
        return ContextPack(
            system="probe",
            messages=(
                ModelMessage(role="user", content=({"type": "text", "text": "probe"},),),
            ),
            tools=(),
            budget=BudgetReport(
                input_limit=100, estimated_input_tokens=10, output_reserve=10
            ),
        )

    def _provider(handler) -> object:
        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
            trust_env=False,
        )
        config = e3.E3Config(
            provider="openai_compatible",
            base_url="https://provider.invalid/v1/chat/completions",
            model="fixture-model",
            api_key="fixture-key",
        )
        return e3.real_provider_factory(config, http_client=client)(None, None)[0]

    # 成功：200 合法响应 → send_count 恰好 1。
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    from agent.provider.protocol import ProviderHTTPRetryableError

    ok_provider = _provider(ok_handler)
    assert isinstance(ok_provider, e3._CountingProvider)
    assert ok_provider.send_count == 0
    ok_provider.generate(_context())
    assert ok_provider.send_count == 1  # 成功计一次 send

    # 失败：500 → generate raise，但 send_count 仍计一次（实际调用了 delegate.generate）。
    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    fail_provider = _provider(fail_handler)
    with pytest.raises(ProviderHTTPRetryableError):
        fail_provider.generate(_context())
    assert fail_provider.send_count == 1  # 失败也计一次 send（attempt counted）

    # fail-closed：未实现 send_count seam 的 provider 显式失败，绝不默认 0。
    with pytest.raises(TypeError):
        e3._provider_send_count(object())

    class _BareProvider:  # 有 generate 但无 send_count seam
        def generate(self, context):  # noqa: ANN001, ANN201
            return None

    with pytest.raises(TypeError):
        e3._provider_send_count(_BareProvider())

    # counting observation 不持久化完整 prompt/context：_CountingProvider 自身可审计状态
    # 只有 send_count（整数）+ delegate 引用 + response_shapes（secret-free 诊断：control
    # kind / tool 名 / text 长度，无内容）+ 不可信 frame 计数，不复制 ContextPack。
    assert not hasattr(ok_provider, "calls")  # 不存 ContextPack 列表
    own_state = {k: v for k, v in vars(ok_provider).items() if not k.startswith("__")}
    assert set(own_state) == {
        "_delegate",
        "send_count",
        "response_shapes",
        "untrusted_process_receipt_digests_seen",
    }
    assert isinstance(own_state["untrusted_process_receipt_digests_seen"], set)


def test_015_j4_count_comes_from_unified_send_count_seam(tmp_path: Path) -> None:
    """goal A：J4 两阶段（crash/restart）的 model send count 必须从统一 _provider_send_count
    seam 取得，不从 provider 私有 .calls 或旁路读取。claim 19 restart_zero_duplicate 依赖它。"""

    fixtures = e3.FixtureSet.create(tmp_path / "root")

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = e3._J4JourneyProvider(fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )
        return provider, descriptor

    observed: dict = {}
    # J4 经 _drive_j4_crash_journey 驱动；它内部用 _provider_send_count 读 pre/post count。
    j4_state, total_sends = e3._drive_j4_crash_journey(factory, fixtures, None, observed)
    # pre/post count 都经统一 seam 写入 observed（键存在且为 int）。
    assert isinstance(observed.get("j4_pre_crash_send_count"), int)
    assert isinstance(observed.get("j4_post_restart_send_count"), int)
    # restart 后 model send count 不增（claim 19 的可审计基础）。
    assert observed["j4_post_restart_send_count"] == 0
    assert total_sends == observed["j4_pre_crash_send_count"]
    assert j4_state is not None


def test_015_j4_phase1_recovery_does_not_lose_observations(tmp_path: Path) -> None:
    """真实 E3 §3.35 后 FAIL_DETAIL：response_shapes.j4 空 + runtime_identity 无 j4 +
    j4 4 claims 连锁崩——j4 phase-1 循环不处理 AWAITING_RECOVERY（如真实 invoke 抛
    IntentConflictError → recovery），`else: break` 静默早退并丢失全部 j4 observation。

    Red：monkeypatch j4 crash wrapper 为普通 Exception（→ runtime 既有 recovery 路径），
    断言 observed 仍记录 response_shapes["j4"] / runtime_identity["j4"] / j4_crash_happened
    ——诚实 False 可见，而非证据蒸发。Green 后 phase-1 用 MARK_FAILED 继续（模型可重试
    local_process 触发真实 crash 路径）。不放宽 frozen journey：crash 未发生时相关 claims
    仍由 durable facts 诚实计算为 False。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    import agent.composition as comp_mod
    from agent.runtime.tools import RegisteredTool

    real_regs = comp_mod.build_tool_registrations
    state = {"raised": False}

    def regs_with_regular_failure(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        regs = list(real_regs(*a, **kw))
        wrapped = []
        for reg in regs:
            if reg.spec.name == "local_process":
                def raise_once(intent, _orig=reg.func):  # noqa: ANN001, ANN202
                    result = _orig(intent)
                    if not state["raised"]:
                        state["raised"] = True
                        raise ValueError("synthetic pre-crash invoke failure")
                    return result

                wrapped.append(
                    RegisteredTool(
                        spec=reg.spec, func=raise_once, prepare_binding=reg.prepare_binding
                    )
                )
            else:
                wrapped.append(reg)
        return wrapped

    comp_mod.build_tool_registrations = regs_with_regular_failure
    try:
        observed: dict = {
            "fixture_invocations": {},
            "secret_hits": [],
            "journeys": {},
        }
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )

        def factory(_name, _ws):  # noqa: ANN001, ANN202
            return e3._J4JourneyProvider(fixtures), descriptor

        e3._drive_j4_crash_journey(factory, fixtures, None, observed)
    finally:
        comp_mod.build_tool_registrations = real_regs
    assert "j4_crash_happened" in observed, (
        "j4 crash flag must always be recorded (honest False), not silently dropped"
    )
    assert "j4" in observed.get("response_shapes", {}), (
        "j4 response shapes must always be recorded for diagnosis"
    )
    assert "j4" in observed.get("runtime_identity", {}), (
        "j4 runtime identity must always be recorded for claim 3"
    )


def test_015_drive_attempt_observes_real_adapter_and_materialized_flags(
    tmp_path: Path,
) -> None:
    """claims real_model_adapter_used / materialized_source_parity 必须从 durable observation
    重算，不能恒 False（否则真实 E3 必然 product_no_progress）。drive_attempt 接受
    real_adapter_used / materialized_verified 观察标志；real mode（main 经 real_provider_factory
    且 offline gates 全绿）置 True，offline scripted 默认 False（诚实：scripted 非 real adapter）。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers[journey_name](fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )
        return provider, descriptor

    flagged = e3.drive_attempt(
        factory,
        fixtures,
        attempt_id="flag-probe",
        clock=None,
        real_adapter_used=True,
        materialized_verified=True,
    )
    assert flagged.claims["real_model_adapter_used"] is True
    # F2（review finding）：caller flag 不再单独冒充 materialized 驱动——没有
    # in-attempt 的 install-origin 观察时 claim 26 必须为 False。
    assert flagged.claims["materialized_source_parity"] is False

    # 不传 flag（offline scripted 默认）→ 两条 claim 保持 False（诚实）。
    offline = e3.drive_attempt(factory, fixtures, attempt_id="flag-off", clock=None)
    assert offline.claims["real_model_adapter_used"] is False
    assert offline.claims["materialized_source_parity"] is False


def test_015_materialized_drive_claim_requires_install_observation(tmp_path: Path) -> None:
    """F2（P1 review finding）：claim 26 必须由 in-attempt 的 install-origin 观察支撑。

    mutation：gates flag True 但 drive observation 缺失 / under_install False →
    claim 26 必须 False；只有 flag AND under_install=True 才 True。
    """

    import copy

    # 最小 observed：直接构造 claim 26 依赖的两个 observation 键做 mutation 矩阵。
    base_observed = {
        "fixture_invocations": {},
        "secret_hits": [],
        "journeys": {},
        "materialized_verified": True,
        "materialized_drive": {
            "install_root": "/tmp/015-install",
            "composition_under_install": True,
        },
    }
    claims = e3._compute_claims("mat-drive", base_observed).claims
    assert claims["materialized_source_parity"] is True

    def mutated(mutate):  # noqa: ANN001, ANN202
        observed = copy.deepcopy(base_observed)
        mutate(observed)
        return e3._compute_claims("mat-drive-mut", observed).claims[
            "materialized_source_parity"
        ]

    # mutation 1：drive observation 缺失（flag 单独）→ False。
    assert mutated(lambda o: o.pop("materialized_drive")) is False
    # mutation 2：composition 未解析自 install → False。
    assert (
        mutated(
            lambda o: o["materialized_drive"].update(composition_under_install=False)
        )
        is False
    )
    # mutation 3：gates flag False → False。
    assert mutated(lambda o: o.update(materialized_verified=False)) is False


def test_015_real_e3_adapter_forces_strict_typed_control_channel() -> None:
    """real E3 production adapter 必须启用 strict control channel。

    ``real_provider_factory`` 必须以 ``strict_tools=True`` 构建 config，且 ``_build_e3_composition``
    必须传 ``strict_control_schema=True``（二者耦合，匹配 production ``--strict-tools``）。这样真实
    adapter 在 control_schema 存在、goal_bootstrap 缺失的首轮强制 ``tool_choice="required"``，真实
    model 才会被迫发完整 typed control（GoalProposal → ... → CompletionClaim）。否则真实 model 不被
    强制 → 发 prose → 无 GoalProposal → product_no_progress。offline scripted 不经 adapter
    故不受影响。
    context_control §111-112 明确：real model 必须能从 wire schema 独立构造完整 control，
    strict 是必要条件。
    """

    import httpx

    from agent.runtime.context_control import reserved_control_schema
    from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage

    control_schema = reserved_control_schema(strict=True)
    context = ContextPack(
        system="s",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "x"},),),
        ),
        tools=(),
        budget=BudgetReport(
            input_limit=100, estimated_input_tokens=10, output_reserve=10
        ),
        control_schema=control_schema,
        goal_bootstrap=None,
    )
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "x"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1/chat/completions",
        model="fixture-model",
        api_key="fixture-key",
    )
    provider, _descriptor = e3.real_provider_factory(config, http_client=client)(None, None)
    provider.generate(context)
    import json as _json

    body = _json.loads(recorded[0].content)
    assert body.get("tool_choice") == "required", (
        "real E3 adapter must force typed control via tool_choice=required; "
        f"got {body.get('tool_choice')!r}"
    )


def test_015_failing_attempt_emits_secret_free_diagnostics(tmp_path: Path) -> None:
    """real E3 失败时必须输出 secret-free 诊断，否则 ``product_no_progress`` 不透明
    （3 次真实 E3 仅返回 reason、无细节，无法定位）。``AttemptObservation`` 携带
    ``false_claims`` + ``diagnostic``（哪些 claim false + 每-journey goal_status /
    process_receipts / evidence_records + send_count + J4 facts），全 secret-free。
    """

    import json as _json

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers[journey_name](fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        descriptor = ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )
        return provider, descriptor

    # 不带 real/materialized flag → claims 2/26 false（offline scripted 诚实：非 real adapter）。
    observation = e3.drive_attempt(
        factory, fixtures, attempt_id="diag", clock=None
    )
    assert "real_model_adapter_used" in set(observation.false_claims)
    assert "materialized_source_parity" in set(observation.false_claims)
    # diagnostic 含 secret-free 每-journey summary + send_count。
    assert "send_count" in observation.diagnostic
    assert "journeys" in observation.diagnostic
    for _jname, jsummary in observation.diagnostic["journeys"].items():
        assert "goal_status" in jsummary
        assert "process_receipts" in jsummary
        assert "evidence_records" in jsummary
    # 诊断必须 JSON 可序列化（secret-free projection）。
    serialized = _json.dumps(observation.diagnostic, sort_keys=True, default=str)
    for forbidden in ("fixture-key", "Authorization", "Bearer ", "FIRST_AGENT_015_E3_API_KEY"):
        assert forbidden not in serialized


def test_015_real_adapter_forces_control_on_proposal_turn() -> None:
    """real E3 根因（真实 FAIL_DETAIL：send_count=5、5 journey 全 goal_status=null、
    approvals=0）：真实 model 在每个 journey 首轮发 prose，不构造 GoalProposal。

    首轮（无 goal）``goal_bootstrap`` **present**（提供 workspace_identity_digest 让 model
    构造 GoalProposal），但 ``openai_http`` 的 ``tool_choice="required"`` 条件含
    ``goal_bootstrap is None`` → 首轮不强制 → model 发 prose → 无 GoalProposal → 全 journey
    无 goal → product_no_progress。strict agent 必须在每个 control_schema 存在的轮次都强制
    typed control（收紧，非放宽）。本测试用 production adapter + recording transport 证明
    首轮 request 必含 ``tool_choice="required"``。
    """

    import httpx

    from agent.runtime.context_control import reserved_control_schema
    from agent.runtime.contracts import (
        BudgetReport,
        ContextPack,
        GoalBootstrap,
        ModelMessage,
    )

    control_schema = reserved_control_schema(strict=True)
    # 首轮：goal_bootstrap present（model 应 propose），control_schema present。
    bootstrap = GoalBootstrap(
        source_fact_id="fact:user:1",
        workspace_identity_digest="d" * 64,
        authority_snapshot="a" * 64,
    )
    context = ContextPack(
        system="s",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "do task"},),),
        ),
        tools=(),
        budget=BudgetReport(
            input_limit=100, estimated_input_tokens=10, output_reserve=10
        ),
        control_schema=control_schema,
        goal_bootstrap=bootstrap,
    )
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "x"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1/chat/completions",
        model="fixture-model",
        api_key="fixture-key",
    )
    provider, _descriptor = e3.real_provider_factory(config, http_client=client)(None, None)
    provider.generate(context)
    import json as _json

    body = _json.loads(recorded[0].content)
    assert body.get("tool_choice") == "required", (
        "proposal turn (goal_bootstrap present) must force typed control; "
        f"got {body.get('tool_choice')!r}"
    )


def test_015_counting_provider_records_exception_and_derives_blocker() -> None:
    """真实 adapter 抛异常时（FAIL_DETAIL: response_shapes 全空 + send_count=5 证明
    delegate.generate 在 append 前 raise），_CountingProvider 记录 error_type 再原样抛；
    _derive_blocker 据此映射准确 blocker（非笼统 product_no_progress）。
    """

    class _RaisingDelegate:  # noqa: D106
        def generate(self, context):  # noqa: ANN001, ANN201
            raise ValueError("boom")

    cp = e3._CountingProvider(_RaisingDelegate())
    with pytest.raises(ValueError):
        cp.generate(None)
    assert cp.send_count == 1  # counted before delegate
    assert cp.response_shapes == [
        {"control": "exception", "error_type": "ValueError", "reason": "boom"}
    ]

    def _obs(error_type: str) -> e3.AttemptObservation:
        return e3.AttemptObservation(
            attempt_id="x",
            claims={"c": False},
            model_send_count=1,
            process_receipt_digest=None,
            fixture_invocation_count=0,
            secret_hits=(),
            diagnostic={
                "response_shapes": {
                    "j1": [{"control": "exception", "error_type": error_type}]
                }
            },
        )

    assert e3._derive_blocker(_obs("ProviderHTTPError")) == "model_endpoint"
    assert e3._derive_blocker(_obs("ProviderAuthError")) == "model_auth"
    assert e3._derive_blocker(_obs("ProviderTimeoutError")) == "timeout"
    assert (
        e3._derive_blocker(_obs("ProviderProtocolError"))
        == "product_invalid_model_output"
    )
    # 未知异常类型 / 无异常 → 仍 product_no_progress（不放宽）
    assert e3._derive_blocker(_obs("ValueError")) == "product_no_progress"


def test_015_real_e3_adapter_disables_thinking_for_strict_tool_choice() -> None:
    """DeepSeek V4 provider-compatibility 根因（Codex 外部 A/B 复现）：
    ``thinking_mode=None``（DeepSeek V4 默认思考）+ ``strict_tools=True``（发
    ``tool_choice="required"``）→ 稳定 ``ProviderHTTPError 400``（DeepSeek V4 thinking mode
    不接受 tool_choice）；仅设 ``thinking_mode="disabled"``（其余不变）→ HTTP 200 + 合法
    GoalProposal。``real_provider_factory`` 必须对 openai_compatible 显式设
    ``thinking_mode="disabled"``，使 strict tool_choice 与 DeepSeek 兼容。**不放宽 strict tools、
    不移除 tool_choice**。本测试用 production adapter + recording transport 证明 request 同时含
    ``tool_choice="required"``（strict 保留）与 ``thinking={"type":"disabled"}``（兼容）。
    """

    import httpx

    from agent.runtime.context_control import reserved_control_schema
    from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage

    control_schema = reserved_control_schema(strict=True)
    context = ContextPack(
        system="s",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "x"},),),
        ),
        tools=(),
        budget=BudgetReport(
            input_limit=100, estimated_input_tokens=10, output_reserve=10
        ),
        control_schema=control_schema,
        goal_bootstrap=None,
    )
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "x"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1/chat/completions",
        model="fixture-model",
        api_key="fixture-key",
    )
    provider, _descriptor = e3.real_provider_factory(config, http_client=client)(None, None)
    provider.generate(context)
    import json as _json

    body = _json.loads(recorded[0].content)
    # strict tool_choice 必须保留（不放宽 typed control）
    assert body.get("tool_choice") == "required", (
        f"strict tool_choice must remain; got {body.get('tool_choice')!r}"
    )
    # thinking 必须显式 disabled（覆盖 DeepSeek V4 默认 thinking，使其兼容 tool_choice）
    assert body.get("thinking") == {"type": "disabled"}, (
        f"thinking must be disabled for openai_compatible strict tool_choice; "
        f"got {body.get('thinking')!r}"
    )


def test_015_j1_message_proposes_goal_first_and_provides_digest(tmp_path: Path) -> None:
    """j1 journey message 必须提案-先并提供真实 sha256（真实 E3 24/26 后 j1 根因）。

    真实 model 按旧 message「先读 input.txt」→ read_file 后 source_result_since_latest_user
    =True → goal_proposal_is_available=False（context.py）→ strict decoder anyOf 不含
    goal_proposal → 模型坚持提案 → malformed_control ×3（§3.27/§3.29 FAIL_DETAIL 实测），
    j1 永不建 goal。j2-j5 提案-先全部成功。且 LLM 无法计算 sha256——runner 必须在 message
    中提供 input.txt 的真实 content digest（runtime 仍在 CompletionClaim 从 durable
    read_file fact 重算 sha256 验证，不伪造 evidence）。
    """

    import hashlib

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    j1 = e3._journey_messages(fixtures)["j1"]
    propose_idx = j1.find("1. Propose a Goal")
    read_idx = j1.find("2. Read input.txt")
    assert propose_idx != -1, "j1 message step 1 must be GoalProposal (proposal-first)"
    assert read_idx != -1, "j1 message step 2 must be the input read"
    assert propose_idx < read_idx, "GoalProposal must precede any file read"
    digest = hashlib.sha256(
        (fixtures.workspace / "input.txt").read_bytes()
    ).hexdigest()
    assert digest in j1, "j1 message must contain the real input.txt sha256"
    assert "<sha256" not in j1, "digest placeholder must be replaced by the real value"


def test_015_response_shape_captures_tool_arguments() -> None:
    """response_shape 必须捕获 tool arguments（j5 0-receipts 诊断依赖）。

    真实 E3 §3.29 FAIL_DETAIL：j5 模型调用了 local_process 但 0 process_receipts、
    goal blocked——无法看到模型实际发送的 executable/argv。捕获白名单参数
    （executable/argv/cwd/profile/path，均 fixture 路径/token，
    secret-free）使下次运行可定位 j5 为何未 spawn。
    """

    from agent.runtime.contracts import ModelResponse, ModelTextBlock, ModelToolCall

    response = ModelResponse(
        (
            ModelToolCall(
                "call-x",
                "local_process",
                {
                    "executable": "echo-argv",
                    "argv": ["a;b", "|c"],
                    "cwd": ".",
                    "profile": "short",
                    "expected_artifact": {"path": "o", "sha256": "f" * 64},
                },
            ),
            ModelTextBlock("hi"),
        )
    )
    shape = e3._response_shape(response)
    assert shape["tools"] == ["local_process"]
    assert shape["tool_args"] == [
        {
            "executable": "echo-argv",
            "argv": ["a;b", "|c"],
            "cwd": ".",
            "profile": "short",
        }
    ]
    assert shape["text_len"] == 2


def test_015_j2_driver_keeps_rejecting_rejected_fingerprint(tmp_path: Path) -> None:
    """claim 13 rejected_command_zero_spawn：用户拒绝过的命令指纹必须持续拒绝。

    真实 E3 §3.30 FAIL_DETAIL：model 的 changed-argv 命令被拒后**重试**，driver
    只拒 approval_index==2，第 3 个 approval 又批准 → rejected fingerprint 被 spawn
    → claim 13 False。frozen journey 定义用户行为：拒绝过的命令永不执行，model
    重试不改变用户决定。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")

    class _J2RetryProvider:  # noqa: D106
        def __init__(self, fixtures):  # noqa: ANN001, ANN202
            self.fixtures = fixtures
            self.calls: list = []

        @property
        def send_count(self) -> int:
            return len(self.calls)

        def generate(self, context):  # noqa: ANN001, ANN201
            from agent.runtime.contracts import (
                GoalFrame,
                GoalProposal,
                GoalStatus,
                ModelResponse,
                ModelToolCall,
                ProposedCriterion,
            )

            self.calls.append(context)
            index = len(self.calls)
            bootstrap = getattr(context, "goal_bootstrap", None)
            if index == 1 and bootstrap is not None:
                return ModelResponse(
                    (),
                    control=GoalProposal(
                        correlation_id="p-j2retry",
                        goal_frame=GoalFrame(
                            goal_id="goal-j2retry",
                            revision=1,
                            created_from_fact_ids=(bootstrap.source_fact_id,),
                            workspace_identity_digest=bootstrap.workspace_identity_digest,
                            user_outcome="Exercise lease reuse and rejection",
                            beneficiary="user",
                            targets=("count-run-counter",),
                            scope=("workspace",),
                            non_goals=(),
                            assumptions=(),
                            proposed_criteria=(
                                ProposedCriterion("c-j2retry", "count-run contract"),
                            ),
                            admitted_criteria=(),
                            authority_snapshot=bootstrap.authority_snapshot,
                            status=GoalStatus.GOAL_READY,
                            created_at="2026-08-09T00:00:00Z",
                            updated_at="2026-08-09T00:00:00Z",
                        ),
                    ),
                )
            if index in (2, 3):
                return ModelResponse(
                    (
                        ModelToolCall(
                            f"call-exact-{index}",
                            "local_process",
                            {
                                "executable": self.fixtures.paths["count-run"],
                                "argv": ["count-run-counter"],
                                "cwd": ".",
                                "profile": "short",
                            },
                        ),
                    )
                )
            if index in (4, 5):
                return ModelResponse(
                    (
                        ModelToolCall(
                            f"call-changed-{index}",
                            "local_process",
                            {
                                "executable": self.fixtures.paths["count-run"],
                                "argv": ["count-run-counter", "changed"],
                                "cwd": ".",
                                "profile": "short",
                            },
                        ),
                    )
                )
            return ModelResponse(())

    provider = _J2RetryProvider(fixtures)
    from agent.runtime.contracts import ProviderDescriptor

    descriptor = ProviderDescriptor(
        family="openai_compatible",
        model="fixture-model",
        canonical_destination="https://provider.invalid",
        trust_profile="remote-https-v1",
        remote=True,
    )
    composition = e3._build_e3_composition(
        provider=provider,
        provider_descriptor=descriptor,
        fixtures=fixtures,
        clock=None,
    )
    observed: dict = {
        "fixture_invocations": {},
        "secret_hits": [],
        "journeys": {},
    }
    _final, _sends = e3._drive_journey(
        "j2", composition, provider, fixtures, observed
    )
    rejected = observed.get("j2_rejected_fingerprint")
    fingerprints = observed.get("j2_receipt_fingerprints", ())
    assert rejected is not None, "changed command must be rejected once"
    assert rejected not in fingerprints, (
        "a user-rejected command fingerprint must NEVER spawn, "
        "even when the model retries it"
    )


def test_015_journey_messages_exclude_expected_artifact_for_non_artifact_journeys(
    tmp_path: Path,
) -> None:
    """j2/j3/j4/j5 message 必须显式禁止 expected_artifact（真实 E3 §3.30 实测）。

    model 给 count-run/hang-tree/echo-argv 加 bogus expected_artifact（全零 sha256 /
    空 path）——空 path 被 admission 正确 fail-closed 拒绝（j3 0 receipts、timeout
    claims False），全零 sha256 改变 fingerprint。expected_artifact 仅用于产出
    artifact 的命令。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    messages = e3._journey_messages(fixtures)
    for journey in ("j2", "j3", "j4", "j5"):
        assert (
            "The tool schema only accepts executable/argv/cwd/profile"
            in messages[journey]
        ), f"{journey} message must state the closed 4-field schema"
        assert "expected_artifact=" not in messages[journey], (
            f"{journey} message must not instruct the model to pass expected_artifact"
        )
    # j1（产出 artifact 的 journey）也必须走用户确认 digest，非模型自供。
    assert "expected_artifact=" not in messages["j1"]


def test_015_transport_error_cause_is_captured() -> None:
    """transport 失败诊断必须含底层 cause 类型（真实 E3 §3.31：全 journey 首个 send
    即 ProviderTransportError，reason 仅 "provider_transport"，无法区分 connect
    refused / DNS / TLS / reset——DeepSeek 服务 vs 出口问题）。

    provider 层 `raise ... from None` 是 deliberate contract（tests/provider 锁定
    `__cause__ is None`，错误分类不泄漏 httpx 内部）——但 `from None` 仍保留
    `__context__`。`_CountingProvider` 从 `__context__` 取 cause **类型名**
    （如 ConnectError/ConnectTimeout/ReadError，不含 URL/message，secret-free）。
    """

    import httpx

    from agent.provider.protocol import ProviderTransportError

    def connect_fail_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("all connection attempts failed")

    client = httpx.Client(
        transport=httpx.MockTransport(connect_fail_handler),
        follow_redirects=False,
        trust_env=False,
    )
    config = e3.E3Config(
        provider="openai_compatible",
        base_url="https://provider.invalid/v1/chat/completions",
        model="fixture-model",
        api_key="fixture-key",
    )
    provider, _descriptor = e3.real_provider_factory(config, http_client=client)(
        None, None
    )
    from agent.runtime.contracts import BudgetReport, ContextPack, ModelMessage

    context = ContextPack(
        system="probe",
        messages=(
            ModelMessage(role="user", content=({"type": "text", "text": "x"},),),
        ),
        tools=(),
        budget=BudgetReport(
            input_limit=100, estimated_input_tokens=10, output_reserve=10
        ),
    )
    with pytest.raises(ProviderTransportError):
        provider.generate(context)
    assert provider.send_count == 1
    shape = provider.response_shapes[0]
    assert shape["error_type"] == "ProviderTransportError"
    assert shape["cause"] == "ConnectError", (
        "underlying transport cause class must be captured "
        f"(from __context__, secret-free); got {shape.get('cause')!r}"
    )


def test_015_claims_real_evidence_and_mutation(tmp_path: Path) -> None:
    """Codex 预审：claim 3/5/6/7/14/15 必须从真实 observation 证明，且 mutation 令其 False。

    - claim 3：runtime identity（type + 每 journey 单一 runtime 对象），非 run_id==run_id 恒真。
    - claim 5/6/7：首个 approval 时刻快照——goal 已存在、process receipts=0、fixture
      side-effects=0（count-run counter/artifact.out 未产生）。
    - claim 14：J5 echo-argv 输出按 NUL 分割后与 frozen 完整有序 token 列表**精确相等**。
    - claim 15：J5 真实执行 print-env-keys；synthetic 非 secret canary 的 key 不在
      child env key 输出中、canary value 不出现在任何 process 输出；secret_hits 空。
    - mutation：删/篡改任一 load-bearing observation → 对应 claim False。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        provider = providers[journey_name](fixtures)
        from agent.runtime.contracts import ProviderDescriptor

        return provider, ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )

    observation = e3.drive_attempt(
        factory,
        fixtures,
        attempt_id="mut",
        clock=None,
        real_adapter_used=True,
        materialized_verified=True,
    )
    # 基线：收紧后的 claims 离线（scripted 全 journey，含 J5 print-env-keys + canary）——
    # 25/26 True；claim 26（materialized_source_parity）F2 后需要 in-attempt install
    # 观察，offline scripted 驱动没有 → 诚实 False（其 mutation 由专门测试覆盖）。
    raw = observation.raw_observed
    false_claims = [n for n in e3.CLAIM_NAMES if not observation.claims[n]]
    assert false_claims == ["materialized_source_parity"], (
        f"offline baseline must be 25/26 with only materialized claim false; "
        f"false: {false_claims}; "
        f"j2_receipt_fingerprints={raw.get('j2_receipt_fingerprints')}; "
        f"approvals={len(raw.get('approval_previews', []))}"
    )

    def claim_after(name: str, mutate) -> bool:  # noqa: ANN001, ANN202
        # observed 内含 frozen JSON 对象（journey state facts）不可整体 deepcopy；
        # 只复制被 mutation 触碰的 plain 顶层键。
        mutated = dict(raw)
        mutated["runtime_identity"] = dict(raw.get("runtime_identity", {}))
        mutated["pre_first_approval"] = dict(raw.get("pre_first_approval", {}))
        mutated["j5_process_outputs"] = list(raw.get("j5_process_outputs", []))
        mutate(mutated)
        return e3._compute_claims("mutated", mutated).claims[name]

    # claim 3：runtime identity 证据被删除 → False。
    assert not claim_after(
        "single_runtime_loop_preserved",
        lambda o: o["runtime_identity"].clear(),
    )
    assert not claim_after(
        "single_runtime_loop_preserved",
        lambda o: o["runtime_identity"].update(
            {"j1": {"type": "SomeOtherLoop", "distinct": 1}}
        ),
    )
    # claim 5：首个 approval 时刻 goal 缺失 → False。
    assert not claim_after(
        "durable_goal_before_process",
        lambda o: o["pre_first_approval"].update(goal_present=False),
    )
    # claim 6/7：首个 approval 前已有 process receipt → False。
    def bump_receipts(o):  # noqa: ANN001, ANN202
        o["pre_first_approval"]["process_receipts"] = 1

    assert not claim_after("zero_spawn_before_approval", bump_receipts)
    assert not claim_after(
        "zero_process_side_effect_before_approval", bump_receipts
    )
    # claim 7：首个 approval 前已有 fixture side-effect → False。
    assert not claim_after(
        "zero_process_side_effect_before_approval",
        lambda o: o["pre_first_approval"].update(fixture_side_effects=1),
    )
    # claim 14：argv token 顺序/内容不精确相等 → False。
    assert not claim_after(
        "shell_metacharacters_literal",
        lambda o: o.update(j5_process_outputs=["|c\0a;b\0$d\0`e`\0f>g\0"]),
    )
    assert not claim_after(
        "shell_metacharacters_literal",
        lambda o: o.update(j5_process_outputs=["a;b only, no full list"]),
    )
    # claim 15：canary key 泄入 child env keys / canary value 泄入 process 输出 → False。
    assert not claim_after(
        "closed_environment_secret_free",
        lambda o: o["j5_process_outputs"].append(
            "FIRST_AGENT_015_E3_CANARY\nPATH\nTMPDIR"
        ),
    )
    canary_value = e3.SYNTHETIC_CANARY_ENV["FIRST_AGENT_015_E3_CANARY"]
    assert not claim_after(
        "closed_environment_secret_free",
        lambda o: o["j5_process_outputs"].append(f"leaked {canary_value}"),
    )
    # 真实 E3 配置名或任意 ambient key 泄入 child 都必须令 claim False；不能只
    # 检查一个专用 synthetic canary。
    assert not claim_after(
        "closed_environment_secret_free",
        lambda o: o["j5_process_outputs"].append(
            "FIRST_AGENT_015_E3_API_KEY\nPATH\nTMPDIR"
        ),
    )
    assert not claim_after(
        "closed_environment_secret_free",
        lambda o: o["j5_process_outputs"].append("UNEXPECTED_AMBIENT_KEY\nPATH"),
    )
    # claim 21：完整 receipt 任一字段被改、digest 未同步重铸 → strict decode 失败。
    def corrupt_process_receipt(o):  # noqa: ANN001, ANN202
        journeys = dict(o["journeys"])
        for journey_name, state in journeys.items():
            facts = list(state.facts)
            for index, fact in enumerate(facts):
                metadata = fact.content.get("metadata")
                if not isinstance(metadata, dict) or not isinstance(
                    metadata.get("process_receipt"), dict
                ):
                    continue
                receipt = dict(metadata["process_receipt"])
                receipt["stdout_bytes"] = receipt["stdout_bytes"] + 1
                changed_metadata = {**metadata, "process_receipt": receipt}
                facts[index] = replace(
                    fact,
                    content={**fact.content, "metadata": changed_metadata},
                )
                journeys[journey_name] = replace(state, facts=tuple(facts))
                o["journeys"] = journeys
                return
        raise AssertionError("precondition: expected a durable process receipt")

    assert not claim_after("process_receipt_kernel_minted", corrupt_process_receipt)
    # claim 20：frozen journey J4 step 4 的用户 stop 必须真实驱动——观察删除/篡改
    # （未驱动、stop 后有重放、最终状态漂移）任一 → False。仅停在 AWAITING_RECOVERY
    # 不构成「用户选择 stop」（Codex 终审 P2）。
    assert not claim_after(
        "unknown_recovery_requires_user",
        lambda o: o.pop("j4_user_stop_exit_code"),
    )
    assert not claim_after(
        "unknown_recovery_requires_user",
        lambda o: o.pop("j4_user_stop_message"),
    )
    assert not claim_after(
        "unknown_recovery_requires_user",
        lambda o: o.update(j4_user_stop_send_count=1),
    )
    assert not claim_after(
        "unknown_recovery_requires_user",
        lambda o: o.update(j4_final_status_after_stop="completed"),
    )


def test_015_j4_phase3_drives_user_stop_via_production_cli_adapter(
    tmp_path: Path,
) -> None:
    """Codex 终审 P2：J4 step 4 的用户 stop 必须真实经过 production CLI adapter。

    run_repl 输入 "stop" → contextual safe exit（exit 0 + stop message + 零
    provider send + state 不变）。记录的 stop message 必须与 production adapter
    对同一 post-stop state 的输出完全一致——证明真实 adapter 路径，而非 harness
    no-op 后把 AWAITING_RECOVERY 当作用户选择。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": e3._J3JourneyProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        from agent.runtime.contracts import ProviderDescriptor

        return providers[journey_name](fixtures), ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )

    observation = e3.drive_attempt(
        factory,
        fixtures,
        attempt_id="stop",
        clock=None,
        real_adapter_used=True,
        materialized_verified=True,
    )
    raw = observation.raw_observed
    assert raw["j4_crash_happened"] is True
    assert raw["j4_user_stop_exit_code"] == 0
    assert raw["j4_user_stop_send_count"] == raw["j4_post_restart_send_count"]
    assert raw["j4_final_status_after_stop"] == "awaiting_recovery"
    # stop message 与 production adapter 对真实 post-stop state 的输出逐字相等。
    from agent.cli.app import _contextual_exit_message

    j4_state = raw["journeys"]["j4"]
    assert isinstance(raw["j4_user_stop_message"], str)
    assert raw["j4_user_stop_message"] == _contextual_exit_message("stop", j4_state)
    assert observation.claims["unknown_recovery_requires_user"] is True



class _J3RealisticRepairProvider:
    """模拟真实 DeepSeek j3 行为（§3.48 实测失败类别）。

    第一次 GoalProposal 通过 provider normalize，但违反 reducer 校验（模型自造
    source fact id / 预铸字段）；真实 E3 中该类拒绝使 run_turn 直接
    FAILED_FATAL(runtime_failure)，j3 journey 静默终止（1 send、goal null、
    claims 16/17 False）。修正后的提案与其余行为与 _J3JourneyProvider 一致。
    """

    def __init__(self, fixtures: e3.FixtureSet) -> None:
        self.fixtures = fixtures
        self.calls: list = []

    @property
    def send_count(self) -> int:
        return len(self.calls)

    def generate(self, context):  # noqa: ANN001, ANN201
        from agent.runtime.contracts import (
            GoalFrame,
            GoalProposal,
            GoalStatus,
            ModelResponse,
            ModelToolCall,
            ProposedCriterion,
        )

        self.calls.append(context)
        index = len(self.calls)
        bootstrap = getattr(context, "goal_bootstrap", None)
        if index in (1, 2) and bootstrap is not None:
            # 第一次：模型自造 source fact id（真实模型常见错误）→ reducer 拒绝；
            # 第二次：复制 bootstrap 的正确 binding。
            source_fact = (
                bootstrap.source_fact_id if index == 2 else "model-fabricated-fact"
            )
            return ModelResponse(
                (),
                control=GoalProposal(
                    correlation_id=f"proposal-015-j3-r{index}",
                    goal_frame=GoalFrame(
                        goal_id="goal-015-j3",
                        revision=1,
                        created_from_fact_ids=(source_fact,),
                        workspace_identity_digest=bootstrap.workspace_identity_digest,
                        user_outcome="Exercise process timeout and group cleanup",
                        beneficiary="user",
                        targets=("hang-output",),
                        scope=("workspace",),
                        non_goals=(),
                        assumptions=(),
                        proposed_criteria=(
                            ProposedCriterion(
                                "criterion-j3",
                                "local_process hang-tree timeout handled",
                            ),
                        ),
                        admitted_criteria=(),
                        authority_snapshot=bootstrap.authority_snapshot,
                        status=GoalStatus.GOAL_READY,
                        created_at="2026-08-09T00:00:00Z",
                        updated_at="2026-08-09T00:00:00Z",
                    ),
                ),
            )
        if index == 3:
            return ModelResponse(
                (
                    ModelToolCall(
                        "call-process-j3",
                        "local_process",
                        {
                            "executable": self.fixtures.paths["hang-tree"],
                            "argv": [],
                            "cwd": ".",
                            "profile": "short",
                        },
                    ),
                )
            )
        if index == 4:
            # j3 无 CompletionClaim（acceptance：timeout 意味着无验证）；活跃 Goal
            # 的合法终态是 blocked_claim——repair 消息明确列出该选项，真实模型在
            # 有界预算内可自纠。
            from agent.runtime.contracts import BlockedClaim

            return ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="block-015-j3",
                    goal_id="goal-015-j3",
                    goal_revision=1,
                    blocker=(
                        "hang-tree timed out and was reaped; "
                        "the outcome cannot be verified"
                    ),
                    safe_attempts=("local_process hang-tree profile=short",),
                    resume_condition="user confirms the timeout handling",
                ),
            )
        return ModelResponse(())


def test_015_j3_rejected_first_proposal_gets_bounded_repair(tmp_path: Path) -> None:
    """Codex 复验：j3 claims 16/17 False 的根因是 proposal 被 reducer 拒绝即 fatal。

    真实 E3 §3.48：j3 只有一次 send（GoalProposal 通过 normalize），run 以
    runtime_failure 告终、goal 未创建、无 exception shape——accept_goal_proposal 的
    ValueError 经 run_turn 外层 except 变 FAILED_FATAL，harness 静默 break。可修复的
    控制参数错误（与 malformed_control 同类）必须有有界修复路径，接受条件零放宽：
    被拒提案不得创建 Goal，修正提案才创建并驱动 local_process 真实执行。
    """

    fixtures = e3.FixtureSet.create(tmp_path / "root")
    providers = {
        "j1": e3._J1JourneyProvider,
        "j5": e3._J5JourneyProvider,
        "j3": _J3RealisticRepairProvider,
        "j2": e3._J2JourneyProvider,
        "j4": e3._J4JourneyProvider,
    }

    def factory(journey_name, _workspace):  # noqa: ANN001, ANN202
        from agent.runtime.contracts import ProviderDescriptor

        return providers[journey_name](fixtures), ProviderDescriptor(
            family="openai_compatible",
            model="fixture-model",
            canonical_destination="https://provider.invalid",
            trust_profile="remote-https-v1",
            remote=True,
        )

    observation = e3.drive_attempt(
        factory,
        fixtures,
        attempt_id="j3repair",
        clock=None,
        real_adapter_used=True,
        materialized_verified=True,
    )
    raw = observation.raw_observed
    # 被拒提案不得创建 Goal；修复后提案创建 Goal 并驱动真实 timeout 执行。
    j3_state = raw["journeys"]["j3"]
    assert j3_state.goal is not None, (
        f"j3 goal missing (run died on first rejected proposal); "
        f"unhandled={raw.get('j3_unhandled_status')}/{raw.get('j3_unhandled_error_code')}"
    )
    assert raw.get("j3_outcome") == "timed_out_reaped"
    assert observation.claims["timeout_group_cleanup_confirmed"] is True
    assert observation.claims["timeout_not_verified_done"] is True
    # run 不得因可修复的提案错误静默 fatal。
    assert "j3_unhandled_status" not in raw


def test_015_j2_provider_timeout_resumes_via_retryable_path(tmp_path: Path) -> None:
    """真实 E3 §3.52：j2 在 GoalProposal 后的 send 命中 ``ProviderTimeoutError``
    （DeepSeek ReadTimeout）→ product 正确进入 ``FAILED_RETRYABLE``/PAUSED_RETRYABLE
    （product 合同不动），但 harness ``else: break`` 把 journey 整个放弃 →
    claims 11/12/13（exact reuse / changed re-approval / rejected zero spawn）
    的 durable observation 从未产生 → 三 claim False、
    ``015_E3_BLOCKED(reason=product_invalid_model_output)``。

    Green：driver（journey 用户）在有界预算内对 FAILED_RETRYABLE 发 ``Resume``
    （PAUSED_RETRYABLE 的合法 product 恢复路径），每次 resume 都是真实 send；
    journey 必须完成并产出三个 claim 的完整观察。"""

    from agent.provider.protocol import ProviderTimeoutError

    fixtures = e3.FixtureSet.create(tmp_path / "root")

    class _J2TimeoutProvider:
        def __init__(self, fixtures):  # noqa: ANN001, ANN202
            self.fixtures = fixtures
            self.calls: list = []
            self.response_shapes: list = []

        @property
        def send_count(self) -> int:
            return len(self.calls)

        def _shape(self, response_or_error):  # noqa: ANN001, ANN202
            if isinstance(response_or_error, Exception):
                self.response_shapes.append(
                    {
                        "control": "exception",
                        "error_type": type(response_or_error).__name__,
                        "reason": "provider_timeout",
                    }
                )
            else:
                from agent.runtime.contracts import ModelToolCall

                control = getattr(response_or_error, "control", None)
                calls = [
                    block
                    for block in response_or_error.blocks
                    if isinstance(block, ModelToolCall)
                ]
                self.response_shapes.append(
                    {
                        "control": type(control).__name__ if control else None,
                        "text_len": 0,
                        "tool_args": [dict(call.arguments) for call in calls],
                        "tools": [call.name for call in calls],
                    }
                )

        def generate(self, context):  # noqa: ANN001, ANN201
            from agent.runtime.contracts import (
                GoalFrame,
                GoalProposal,
                GoalStatus,
                ModelResponse,
                ModelToolCall,
                ProposedCriterion,
            )

            self.calls.append(context)
            index = len(self.calls)
            bootstrap = getattr(context, "goal_bootstrap", None)
            if index == 1 and bootstrap is not None:
                response = ModelResponse(
                    (),
                    control=GoalProposal(
                        correlation_id="p-j2timeout",
                        goal_frame=GoalFrame(
                            goal_id="goal-j2timeout",
                            revision=1,
                            created_from_fact_ids=(bootstrap.source_fact_id,),
                            workspace_identity_digest=bootstrap.workspace_identity_digest,
                            user_outcome="Exercise lease reuse and rejection",
                            beneficiary="user",
                            targets=("count-run-counter",),
                            scope=("workspace",),
                            non_goals=(),
                            assumptions=(),
                            proposed_criteria=(
                                ProposedCriterion("c-j2timeout", "count-run contract"),
                            ),
                            admitted_criteria=(),
                            authority_snapshot=bootstrap.authority_snapshot,
                            status=GoalStatus.GOAL_READY,
                            created_at="2026-08-16T00:00:00Z",
                            updated_at="2026-08-16T00:00:00Z",
                        ),
                    ),
                )
                self._shape(response)
                return response
            if index == 2:
                # 真实运行同形：第二次 send（goal 建立后）ReadTimeout。
                timeout = ProviderTimeoutError()
                self._shape(timeout)
                raise timeout
            if index in (3, 4):
                response = ModelResponse(
                    (
                        ModelToolCall(
                            f"call-exact-{index}",
                            "local_process",
                            {
                                "executable": self.fixtures.paths["count-run"],
                                "argv": ["count-run-counter"],
                                "cwd": ".",
                                "profile": "short",
                            },
                        ),
                    )
                )
                self._shape(response)
                return response
            if index in (5, 6):
                response = ModelResponse(
                    (
                        ModelToolCall(
                            f"call-changed-{index}",
                            "local_process",
                            {
                                "executable": self.fixtures.paths["count-run"],
                                "argv": ["count-run-counter", "changed"],
                                "cwd": ".",
                                "profile": "short",
                            },
                        ),
                    )
                )
                self._shape(response)
                return response
            from agent.runtime.contracts import BlockedClaim

            response = ModelResponse(
                (),
                control=BlockedClaim(
                    correlation_id="block-015-j2-timeout",
                    goal_id="goal-j2timeout",
                    goal_revision=1,
                    blocker=(
                        "the user rejected the changed command; "
                        "the exact command cannot satisfy the outcome alone"
                    ),
                    safe_attempts=("local_process count-run profile=short",),
                    resume_condition="user approves the changed command",
                ),
            )
            self._shape(response)
            return response

    provider = _J2TimeoutProvider(fixtures)
    from agent.runtime.contracts import ProviderDescriptor

    descriptor = ProviderDescriptor(
        family="openai_compatible",
        model="fixture-model",
        canonical_destination="https://provider.invalid",
        trust_profile="remote-https-v1",
        remote=True,
    )
    composition = e3._build_e3_composition(
        provider=provider,
        provider_descriptor=descriptor,
        fixtures=fixtures,
        clock=None,
    )
    observed: dict = {
        "fixture_invocations": {},
        "secret_hits": [],
        "journeys": {},
    }
    final, _sends = e3._drive_journey(
        "j2", composition, provider, fixtures, observed
    )

    assert observed.get("j2_unhandled_status") is None, (
        "journey must not die on FAILED_RETRYABLE: "
        f"{observed.get('j2_unhandled_status')} / "
        f"{observed.get('j2_unhandled_error_code')}"
    )
    assert observed.get("j2_provider_retryable"), (
        "driver must resume the product's PAUSED_RETRYABLE path"
    )
    fingerprints = observed.get("j2_receipt_fingerprints", ())
    rejected = observed.get("j2_rejected_fingerprint")
    exact = [
        f
        for f in fingerprints
        if f != rejected
    ]
    assert len(exact) >= 2, (
        "exact command must reuse the lease and execute twice after the resume"
    )
    assert rejected is not None, "changed command must be rejected once"
    assert rejected not in fingerprints, "rejected command must never spawn"


def test_015_j5_frozen_tokens_cover_acceptance_contract_classes(tmp_path) -> None:  # noqa: ANN001
    """Reviewer Finding 2（P2）：E3 §5 J5.1 冻结合同要求 argv 覆盖 ``;``、``|``、
    ``>``、``$()``、backtick、**space** 和 **newline** token 类。缩减列表
    ``("a;b", "|c", "$d", "`e`", "f>g")`` 缺 ``$()`` 形式、含空格 token 与含换行
    token——三次 26/26 只是对缩减 journey 的通过，证据范围窄于冻结合同。

    Green：扩充 frozen 列表并同步 real-mode prompt（本测试与 claim 14 用同一常量，
    防止 harness 与 prompt 再漂移）。"""

    tokens = e3._J5_LITERAL_TOKENS
    joined = "\x00".join(tokens)
    # 每个合同 token 类至少一个专门 token 覆盖（非「任一字符命中」的宽松检查）。
    assert any(";" in t for t in tokens), "contract class ';'"
    assert any(t.startswith("|") or "|" in t for t in tokens), "contract class '|'"
    assert any(">" in t for t in tokens), "contract class '>'"
    assert any("$(" in t and ")" in t for t in tokens), "contract class '$()'"
    assert any("`" in t for t in tokens), "contract class backtick"
    assert any(" " in t for t in tokens), "contract class space (inside one token)"
    assert any("\n" in t for t in tokens), "contract class newline (inside one token)"
    # token 之间以 NUL 分隔后仍可无损还原（claim 14 的比较基础）。
    assert tuple(t for t in joined.split("\x00")) == tokens
    # real-mode J5 用户消息必须由同一常量生成，不得另写缩减列表。
    fixtures = e3.FixtureSet.create(tmp_path / "j5-tokens-root")
    message = e3._journey_messages(fixtures)["j5"]
    for token in tokens:
        rendered = token if "\n" not in token else token.replace("\n", "\\n")
        assert rendered in message, (
            f"real-mode prompt must carry frozen token {token!r} (newline shown as \\n)"
        )
