"""015 Governed Local Action 的 stop-ship 架构合同（E0）。

每个测试映射到 015 plan 的 R-ID / KTD，断言一条用户可见合同或 stop-ship 边界，
而不是源码形状的琐碎细节。在 015 product code 落地前，这些测试因为 process
contract / tool 不存在而准确失败（Red）；落地后转为 Green。``_find_contract_type``、
``_process_module`` 与 ``getattr`` 守卫保证失败是干净的断言，而不是 collection 期
import error；合同查找跨 runtime/process 两处，避免把模块路径写成琐碎约束。
"""

from __future__ import annotations

import enum
import importlib
from dataclasses import fields
from pathlib import Path

import agent.runtime.contracts as contracts

ROOT = Path(__file__).resolve().parents[2]


def _process_module(name: str):
    """安全导入 ``agent.process.<name>``；不存在时返回 ``None`` 而非抛 ImportError。"""

    try:
        return importlib.import_module(f"agent.process.{name}")
    except ModuleNotFoundError:
        return None


def _find_contract_type(name: str):
    """跨模块查找 named closed contract；先 runtime contracts（durable authority
    合同的家），再 process contracts（process-package 内部合同的家）。

    模块路径属源码形状琐碎细节：Red 只断言 closed type 的存在与形状，不钉死模块。
    """

    for module in (contracts, _process_module("contracts")):
        if module is None:
            continue
        value = getattr(module, name, None)
        if value is not None:
            return value
    return None


def _closed_enum_with_values(expected: set[str]):
    """在 runtime contracts 与 process contracts 里找出成员值恰好等于 ``expected``
    的 closed enum；用于断言 receipt outcome 的 closed 形状而不钉死 enum 名/模块。"""

    for module in (contracts, _process_module("contracts")):
        if module is None:
            continue
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, enum.Enum):
                try:
                    members = {item.value for item in value}
                except TypeError:
                    continue
                if members == expected:
                    return value
    return None


def _find_toolspec_named(module, name: str):
    """从 process tools 模块里找出名为 ``name`` 的 ToolSpec，兼容直接属性、
    零参 builder 与返回 ``RegisteredTool`` tuple 的 builder 三种暴露方式。"""

    if module is None:
        return None

    def is_match(spec: object) -> bool:
        return isinstance(spec, contracts.ToolSpec) and spec.name == name

    def specs_from_tuple(value: object):
        items = list(value) if isinstance(value, (tuple, list)) else []
        specs = []
        for item in items:
            spec = getattr(item, "spec", None) or getattr(item, "tool_spec", None)
            if isinstance(spec, contracts.ToolSpec):
                specs.append(spec)
        return specs

    for value in vars(module).values():
        if is_match(value):
            return value
        if callable(value):
            try:
                result = value()
            except TypeError:
                continue
            except Exception:  # noqa: BLE001 - builder 可能需要参数，跳过而非失败
                continue
            if is_match(result):
                return result
            for spec in specs_from_tuple(result):
                if is_match(spec):
                    return spec
    return None


def test_015_has_closed_execution_authority_class() -> None:
    """R23 / KTD13：必须存在与 EgressClass 正交的 closed 执行权威枚举。

    现有静态工具投影 ``IN_PROCESS``，``local_process`` 使用 ``LOCAL_SAME_UID_PROCESS``。
    不能从 SideEffectClass 或 EgressClass 推断，也不允许运行时 optional fallback。
    """

    authority = getattr(contracts, "ExecutionAuthorityClass", None)
    assert authority is not None, "015 requires a closed ExecutionAuthorityClass contract"
    # 017 合法扩展：ISOLATED_SANDBOX——命令只在 qualified Docker 隔离
    # environment 内执行（sandbox_exec 系列）；不授予 same-UID host process。
    # 018 合法扩展：BROWSER_SESSION——动作只在专属 governed browser session
    # 内执行，不授予 host process 或任意 desktop authority。
    assert {item.value for item in authority} == {
        "in_process",
        "local_same_uid_process",
        "isolated_sandbox",
        "browser_session",
    }


def test_015_tool_identity_carries_explicit_execution_authority() -> None:
    """R23 / KTD13：ToolSpec / ExecutionIntent / ExecutingIntentRecord 必须显式携带
    execution authority，进入 identity digest；不得从 egress/side_effect 推断。"""

    for dataclass_type in (
        contracts.ToolSpec,
        contracts.ExecutionIntent,
        contracts.ExecutingIntentRecord,
    ):
        assert "execution_authority" in {
            field.name for field in fields(dataclass_type)
        }, f"{dataclass_type.__name__} must carry explicit execution_authority"


def test_015_local_process_tool_is_structured_and_shell_free() -> None:
    """R4 / R6 / KTD1 / KTD6：local_process 只接受结构化 shell-free 命令。

    schema 只暴露 ``executable``/``argv``/``cwd``/``profile``；
    profile 是 closed ``short|standard|long`` 枚举。禁止 ``command``/``shell``/``stdin``/``env``/
    raw ``timeout``/``background``/``pty`` 等字段——安全性来自无 shell parsing。
    artifact 期望由用户批准 action 的 typed fields 提供，不接受 model 自报。
    """

    spec = _find_toolspec_named(_process_module("tools"), "local_process")
    assert spec is not None, "015 requires a local_process ToolSpec in agent.process.tools"
    properties = dict(spec.input_schema.get("properties", {}))
    # F4（review finding / design §6）：closed 4 字段——expected_artifact 已移除
    # （artifact digest 由用户在 ResolveApproval.confirmed_artifact_* 确认）。
    assert set(properties) == {"executable", "argv", "cwd", "profile"}
    forbidden = {"command", "shell", "script", "stdin", "env", "timeout", "background", "pty"}
    assert not (forbidden & set(properties)), (
        f"local_process must not expose shell/stdio/env fields: {forbidden & set(properties)}"
    )
    assert set(properties["profile"].get("enum", [])) == {"short", "standard", "long"}
    assert spec.side_effect is contracts.SideEffectClass.EXTERNAL
    assert spec.egress is contracts.EgressClass.NONE
    assert spec.risk is contracts.ToolRisk.HIGH
    assert spec.approval_policy is contracts.ApprovalPolicy.ALWAYS
    assert spec.execution_authority is contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS


def test_015_authority_lease_is_exact_finite_goal_scoped_and_revocable() -> None:
    """R8 / R9 / R10 / KTD4：authority lease 是 exact、有限、可过期、可撤销的 durable 合同。

    固定 8 次 reuse、60 分钟过期；绑定 Goal/revision/workspace/executable identity。
    不允许 wildcard、prefix、regex、目录级或 session-wide 授权字段。
    """

    lease = _find_contract_type("ProcessAuthorityLeaseV1")
    assert lease is not None, "015 requires ProcessAuthorityLeaseV1"
    lease_fields = {field.name for field in fields(lease)}
    assert lease_fields.isdisjoint(
        {"glob", "wildcard", "pattern", "prefix", "regex", "directory"}
    ), "lease must not carry wildcard/pattern authorization"
    assert {"max_uses", "expires_at", "issued_at"} <= lease_fields
    max_uses_default = next(
        field.default for field in fields(lease) if field.name == "max_uses"
    )
    assert max_uses_default == 8, f"lease max_uses must be fixed at 8, got {max_uses_default}"


def test_015_candidate_binds_goal_and_workspace_before_any_effect() -> None:
    """R5 / KTD3：approval candidate 必须绑定当前 Goal/revision/workspace identity。

    无 durable Goal、Goal 已 terminal、workspace identity mismatch 时在 spawn 前
    fail closed。candidate 不携带 secret/raw env/absolute workspace path。
    """

    candidate = _find_contract_type("ProcessAuthorityCandidateV1")
    assert candidate is not None, "015 requires ProcessAuthorityCandidateV1"
    candidate_fields = {field.name for field in fields(candidate)}
    assert {"goal_id", "goal_revision", "workspace_identity_digest"} <= candidate_fields, (
        "candidate must bind current Goal/revision/workspace"
    )
    assert candidate_fields.isdisjoint(
        {"credential", "raw_environment", "api_key", "secret"}
    ), "candidate must not carry secret/raw env values"


def test_015_receipt_and_draft_are_closed_kernel_minted_types() -> None:
    """R17 / KTD8 / KTD10：receipt 由 Kernel 铸造；runner 只返回 closed draft。

    普通 callable 不能自报 receipt。receipt outcome 是 closed
    ``exited|signaled|timed_out_reaped``；unknown 不产生 receipt。``TOOL_RECEIPT``
    oracle 保持加式 closed shape：012-014 非 process 的单键形状不变。
    """

    assert _find_contract_type("ProcessExecutionDraftV1") is not None, (
        "015 requires ProcessExecutionDraftV1 (runner-only output)"
    )
    receipt = _find_contract_type("ProcessReceiptV1")
    assert receipt is not None, "015 requires ProcessReceiptV1 (Kernel-minted)"
    receipt_fields = {field.name for field in fields(receipt)}
    assert {"outcome", "lease_id", "goal_id", "goal_revision"} <= receipt_fields, (
        "receipt must bind outcome + lease + Goal identity"
    )
    outcome_enum = _closed_enum_with_values({"exited", "signaled", "timed_out_reaped"})
    assert outcome_enum is not None, (
        "receipt outcome must be a closed exited|signaled|timed_out_reaped enum"
    )
    # 加式证据合同：legacy 非 process 单键形状不被破坏。
    assert "tool_receipt" in {item.value for item in contracts.EvidenceOracleKind}


def test_015_no_second_loop_or_runtime_for_process_action() -> None:
    """R1 / R2：本地执行仍走唯一 AgentRuntime.run_turn + 唯一 KernelToolRuntime。

    不得新增 CodingLoop / ProcessAgent / ShellAgent / 第二 Runtime 或 loop。
    本测试是回归守卫：015 实现期间必须保持单 Runtime/单 ToolRuntime。
    """

    import agent.runtime.loop as loop
    import agent.runtime.tools as tools

    assert hasattr(loop, "AgentRuntime")
    assert hasattr(tools, "KernelToolRuntime")
    forbidden_names = {"CodingLoop", "ProcessAgent", "ShellAgent", "ProcessRuntime"}
    assert forbidden_names.isdisjoint(set(dir(loop)) | set(dir(tools))), (
        "015 must not introduce a second loop/runtime class"
    )


def test_015_docs_mark_governed_local_action_as_delivered_with_limits() -> None:
    """R13-R16 / R22 / E3 §10：晋级后必须同时披露已交付事实与安全边界。"""

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "015" in readme
    # 旧现在时否认已由 §3.53 后事实取代（reviewer F1）。
    assert "下一里程碑 015" not in readme
    assert "尚未提供本机进程执行" not in readme
    assert "作为已交付能力提供受治理的结构化本机执行" in readme
    assert "真实 DeepSeek E3 三连、独立评审与 Codex 终裁均已通过" in readme
    strategy = (ROOT / "STRATEGY.md").read_text(encoding="utf-8")
    assert "（已交付并验证）" in strategy
    assert "不宣称 OS sandbox" in strategy
