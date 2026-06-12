"""F2.1 / F3.1 — Missing-descriptor taxonomy + real failure surface coverage.

F2.1: descriptor missing 必须产生 status="rejected" + failure_kind="descriptor_not_found"，
      而非 status="failed" + failure_kind="invalid_v0_contract"。

F3.1: _failed_contract 和 provider_failure 必须通过真实 SubAgentV0Handler 的
      production code path 触发，而非替换整个 handler。

测试级别：F2.1 为 E2E（chat() public path）；F3.1 为 integration
（dispatcher.route + real handler）。不夸大为 E2E。
"""

from __future__ import annotations

import pytest

from agent.core import chat
from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionType
from tests.runtime_integration.subagent_v0_contract_helpers import (
    build_v0_dispatcher_and_handler,
    build_v0_request,
    route_v0,
)

V0 = str(RuntimeActionType.SUBAGENT_DELEGATE_V0.value)


def _v0_events(dispatcher):
    return [ev for ev in dispatcher.action_log if ev.action_type == V0]


# =====================================================================
# F2.1: Missing descriptor — public chat() path
# =====================================================================


class TestF21MissingDescriptorTaxonomy:
    """descriptor missing 必须是 rejected + descriptor_not_found。"""

    def test_descriptor_missing_status_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-core: chat() + flag on + unknown descriptor → status="rejected"。

        当前代码产生 status="failed"（因为 from_payload ValueError），
        这个测试在修复前应 FAIL。
        """
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        reply = chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-test",
        )

        assert isinstance(reply, str) and reply
        v0 = _v0_events(dispatcher)
        assert v0, "F2.1: must produce a V0 event"
        target = v0[-1]

        assert target.status == "rejected", (
            f"F2.1: descriptor missing must be 'rejected', not '{target.status}'. "
            f"Follows tool.gate not_found precedent."
        )

    def test_descriptor_missing_failure_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-kind: failure_kind 必须是 descriptor_not_found，而非 invalid_v0_contract。"""
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-kind",
        )

        v0 = _v0_events(dispatcher)
        assert v0
        evidence = v0[-1].evidence
        assert evidence.get("failure_kind") == "descriptor_not_found", (
            f"F2.1: failure_kind must be 'descriptor_not_found'; "
            f"got {evidence.get('failure_kind')!r}"
        )

    def test_descriptor_missing_no_child_no_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-boundary: descriptor missing 不执行 child、不调 provider。"""
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-boundary",
        )

        v0 = _v0_events(dispatcher)
        assert v0
        evidence = v0[-1].evidence
        assert evidence.get("provider_called") is not True, (
            "F2.1: descriptor missing must NOT call provider"
        )
        assert evidence.get("execution_started") is not True, (
            "F2.1: descriptor missing must NOT start execution"
        )

    def test_descriptor_missing_user_sees_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-ux: user 得到稳定 not-found 输出。"""
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        reply = chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-ux",
        )

        assert "找不到" in reply or "not found" in reply.lower() or "未找到" in reply, (
            f"F2.1: user must see a not-found message; got {reply!r}"
        )

    def test_descriptor_missing_no_inline_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-no-fallback: descriptor missing 不得触发 inline-local fallback。

        inline-local fallback 只在 v0_result.status=="not_supported" 时触发。
        descriptor missing 的 status 应是 "rejected"，不是 "not_supported"。
        """
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")
        dispatcher = build_phase1_dispatcher()

        chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-no-fallback",
        )

        v0 = _v0_events(dispatcher)
        assert v0
        target = v0[-1]
        assert target.status != "not_supported", (
            "F2.1: descriptor missing must NOT be 'not_supported' "
            "(that triggers inline-local fallback)"
        )

    def test_flag_off_descriptor_missing_no_regression(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F2.1-regression: flag off + unknown descriptor 不崩溃。"""
        monkeypatch.delenv("SUBAGENT_V0_ROUTING_ENABLED", raising=False)
        dispatcher = build_phase1_dispatcher()

        reply = chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
            session_id="f21-flagoff",
        )

        assert isinstance(reply, str) and reply


# =====================================================================
# F2.1 五类 Outcome 区分
# =====================================================================


class TestF21FiveWayDiscrimination:
    """五种 outcome 的 status 必须互不混淆。"""

    def test_descriptor_missing_vs_handler_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """descriptor missing (rejected) vs handler missing (not_supported)。"""
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")

        # descriptor missing via chat()
        d1 = build_phase1_dispatcher()
        chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=d1,
            session_id="disc-desc",
        )
        v0_desc = _v0_events(d1)
        assert v0_desc
        desc_status = v0_desc[-1].status

        # handler missing via route with unregistered action type
        d2 = build_phase1_dispatcher()
        from agent.runtime_integration.schema import RuntimeActionRequest
        handler_missing_req = RuntimeActionRequest(
            action_type=RuntimeActionType.SUBAGENT_DELEGATE_L2,
            source="test-handler-missing",
            parent_trace_id="test-trace",
            payload={},
        )
        handler_missing_result = d2.route(handler_missing_req)
        handler_status = handler_missing_result.status

        assert desc_status != handler_status, (
            f"descriptor missing ({desc_status}) must differ from "
            f"handler missing ({handler_status})"
        )
        assert desc_status == "rejected"
        assert handler_status == "not_supported"

    def test_descriptor_missing_vs_policy_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """descriptor missing (rejected) vs policy blocked (policy_blocked)。"""
        monkeypatch.setenv("SUBAGENT_V0_ROUTING_ENABLED", "1")

        # descriptor missing
        d1 = build_phase1_dispatcher()
        chat(
            "delegate to nonexistent-agent-xyz: do something",
            provider=FakeProvider(),
            runtime_action_dispatcher=d1,
            session_id="disc-desc2",
        )
        desc_status = _v0_events(d1)[-1].status

        # policy blocked via route_v0
        result_blocked = route_v0({"scenario": "policy_blocked"})
        assert desc_status != result_blocked.status
        assert desc_status == "rejected"
        assert result_blocked.status == "policy_blocked"

    def test_descriptor_missing_vs_provider_failure(self) -> None:
        """descriptor missing (rejected) vs provider failure (failed)。"""
        # provider failure via route_v0
        result_failure = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("test_provider_error"),
        })
        assert result_failure.status == "failed"
        assert result_failure.evidence.get("failure_kind") == "provider_failure"

    def test_descriptor_missing_vs_v0_success(self) -> None:
        """descriptor missing (rejected) vs V0 success (success)。"""
        result_success = route_v0()
        assert result_success.status == "success"


# =====================================================================
# F3.1: Real _failed_contract path (contract failure)
# =====================================================================


class TestF31RealContractFailure:
    """通过真实 SubAgentV0Handler + 真实 contract parser 触发 _failed_contract。

    测试级别：integration (dispatcher.route + real handler)。
    不是 E2E (chat())，因为 core.py 硬编码 max_turns=1。
    """

    def test_contract_failure_via_invalid_max_turns(self) -> None:
        """F3.1-contract: max_turns=2 触发真实 __post_init__ ValueError。

        SubAgentV0ProfileContract.__post_init__ 校验 max_turns==1，
        max_turns=2 → ValueError → _failed_contract。
        """
        result = route_v0({"max_turns": 2})

        assert result.status == "failed", (
            f"F3.1: contract failure must be 'failed'; got {result.status!r}"
        )
        assert result.evidence.get("failure_kind") == "invalid_v0_contract", (
            f"F3.1: failure_kind must be 'invalid_v0_contract'; "
            f"got {result.evidence.get('failure_kind')!r}"
        )

    def test_contract_failure_no_provider_called(self) -> None:
        """F3.1-contract: contract failure 在 execution 前，不调 provider。"""
        result = route_v0({"max_turns": 2})

        assert result.evidence.get("provider_called") is not True
        assert result.evidence.get("execution_started") is not True

    def test_contract_failure_no_inline_fallback(self) -> None:
        """F3.1-contract: contract failure (failed) 不触发 inline-local fallback。"""
        result = route_v0({"max_turns": 2})
        assert result.status != "not_supported", (
            "contract failure must NOT be not_supported (that triggers fallback)"
        )

    def test_contract_failure_uses_real_handler(self) -> None:
        """F3.1-real: 必须通过真实 SubAgentV0Handler 而非假 handler。"""
        dispatcher, handler = build_v0_dispatcher_and_handler()
        assert type(handler).__name__ == "SubAgentV0Handler"

        request = build_v0_request(payload={"max_turns": 2})
        result = dispatcher.route(request)

        assert result.status == "failed"
        handler_name = result.evidence.get("handler_name")
        assert handler_name == "SubAgentV0Handler", (
            f"F3.1: must use real SubAgentV0Handler; got {handler_name!r}"
        )


# =====================================================================
# F3.1: Real provider failure path
# =====================================================================


class TestF31RealProviderFailure:
    """通过真实 SubAgentV0Handler 触发 provider_failure。

    测试级别：integration (dispatcher.route + real handler)。
    payload 注入 provider_failure 是合法 test seam — handler 逻辑是真实 production code。
    """

    def test_provider_failure_status_is_failed(self) -> None:
        """F3.1-provider: provider failure → status="failed"。"""
        result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("simulated_provider_crash"),
        })

        assert result.status == "failed", (
            f"F3.1: provider failure must be 'failed'; got {result.status!r}"
        )

    def test_provider_failure_kind(self) -> None:
        """F3.1-provider: failure_kind 是 provider_failure。"""
        result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("simulated_provider_crash"),
        })

        assert result.evidence.get("failure_kind") == "provider_failure", (
            f"F3.1: failure_kind must be 'provider_failure'; "
            f"got {result.evidence.get('failure_kind')!r}"
        )

    def test_provider_failure_provider_called_true(self) -> None:
        """F3.1-provider: provider 确实被调用过。"""
        result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("simulated_provider_crash"),
        })

        assert result.evidence.get("provider_called") is True, (
            "F3.1: provider_called must be True for provider failure"
        )
        assert result.evidence.get("provider_completed") is not True, (
            "F3.1: provider must NOT have completed successfully"
        )

    def test_provider_failure_no_inline_fallback(self) -> None:
        """F3.1-provider: provider failure 不触发 inline-local fallback。"""
        result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("simulated_provider_crash"),
        })

        assert result.status != "not_supported"

    def test_provider_failure_uses_real_handler(self) -> None:
        """F3.1-real: 必须通过真实 SubAgentV0Handler。"""
        dispatcher, handler = build_v0_dispatcher_and_handler()
        assert type(handler).__name__ == "SubAgentV0Handler"

        request = build_v0_request(payload={
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("simulated_provider_crash"),
        })
        result = dispatcher.route(request)

        assert result.status == "failed"
        assert result.evidence.get("handler_name") == "SubAgentV0Handler"

    def test_provider_failure_error_metadata_redacted(self) -> None:
        """F3.1-provider: error metadata 不泄漏原始错误内容。"""
        result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("secret_internal_detail"),
        })

        safe_meta = result.evidence.get("safe_error_metadata", {})
        assert safe_meta.get("redacted") is True
        assert "secret_internal_detail" not in str(safe_meta.get("error_hash", ""))


# =====================================================================
# F3.1: Contract failure vs provider failure 区分
# =====================================================================


class TestF31FailureDiscrimination:
    """contract failure 和 provider failure 必须可区分。"""

    def test_contract_vs_provider_failure_kind_differs(self) -> None:
        """两种 failure 的 failure_kind 不同。"""
        contract_result = route_v0({"max_turns": 2})
        provider_result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("test"),
        })

        contract_kind = contract_result.evidence.get("failure_kind")
        provider_kind = provider_result.evidence.get("failure_kind")

        assert contract_kind != provider_kind, (
            f"contract ({contract_kind}) and provider ({provider_kind}) "
            f"failure_kind must differ"
        )
        assert contract_kind == "invalid_v0_contract"
        assert provider_kind == "provider_failure"

    def test_contract_vs_provider_execution_started(self) -> None:
        """contract failure: execution_started=False; provider failure: True。"""
        contract_result = route_v0({"max_turns": 2})
        provider_result = route_v0({
            "scenario": "provider_failure",
            "provider_failure": RuntimeError("test"),
        })

        assert contract_result.evidence.get("execution_started") is not True
        assert provider_result.evidence.get("execution_started") is True
