"""015 Governed Local Action 的 reference journey 合同（E0/E2 入口）。

与 ``tests/architecture/test_015_governed_local_action.py`` 互补：架构测试锁定 closed
contract 的存在与形状，本文件锁定**生产路径级**的 journey 入口合同——supported
composition 必须注册 governed ``local_process``、披露必须携带诚实的 same-UID notice、
文档不得把 015 写成已交付能力。完整 model→approval→checkpoint→process→receipt 的
真实 journey 由 U6/U8/U9 在本文件追加；U1 只先固化这些准确 Red 与诚实性守卫。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import agent.runtime.contracts as contracts

ROOT = Path(__file__).resolve().parents[2]


def _process_submodule(name: str):
    try:
        return importlib.import_module(f"agent.process.{name}")
    except ModuleNotFoundError:
        return None


def _same_uid_notice() -> str | None:
    """在 ``agent.process`` 包内找出 same-UID trust notice 常量；不存在返回 ``None``。"""

    try:
        package = importlib.import_module("agent.process")
    except ModuleNotFoundError:
        return None
    for submodule_name in ("contracts", "disclosure", "profile", "tools"):
        module = _process_submodule(submodule_name)
        if module is None:
            continue
        for value in vars(module).values():
            if isinstance(value, str) and "same-uid" in value.casefold():
                return value
    # 退一步：包级常量。
    for value in vars(package).values():
        if isinstance(value, str) and "same-uid" in value.casefold():
            return value
    return None


def test_supported_composition_registers_local_process_governed_tool(tmp_path) -> None:  # noqa: ANN001
    """AE1 / F1 / KTD1 / KTD11：supported POSIX 平台的标准 composition 必须注册
    一个默认可发现、默认无执行权的 ``local_process`` governed tool。

    首版只在支持 POSIX lifecycle 的平台注册；未支持平台不得注册伪实现。当前 host
    为 macOS/POSIX，故 standard ``build_tool_registrations`` 必须包含 local_process。
    """

    from agent.composition import build_tool_registrations

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registrations = build_tool_registrations(
        workspace=workspace,
        max_tool_result_chars=50_000,
    )
    definitions = {
        registration.spec.name: registration.spec for registration in registrations
    }
    spec = definitions.get("local_process")
    assert spec is not None, (
        "supported composition must register the governed local_process tool"
    )
    assert spec.execution_authority is contracts.ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS


def test_governed_local_action_exposes_same_uid_trust_notice() -> None:
    """R7 / R13 / R23 / AE1：approval 披露必须携带诚实的 same-UID trust notice。

    该 notice 是 same-UID trust boundary 的措辞来源，必须明确 same-UID 执行，且不得
    宣称 OS sandbox / filesystem confinement（实现并不提供这些保证）。
    """

    notice = _same_uid_notice()
    assert notice is not None, "015 requires a same-UID trust notice constant in agent.process"
    lowered = notice.casefold()
    assert "same-uid" in lowered
    # 诚实披露：明确否认 OS sandbox / filesystem confinement / network denial。
    assert "not an os sandbox" in lowered
    assert "not a filesystem confinement" in lowered
    assert "not a network denial" in lowered


def test_governed_local_action_marked_delivered_without_sandbox_overclaim() -> None:
    """R22 / E3 §10：最终晋级不等于扩大 same-UID process 的安全承诺。"""

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "下一里程碑 015" not in readme
    assert "尚未提供本机进程执行" not in readme
    assert "作为已交付能力提供受治理的结构化本机执行" in readme
    assert "真实 DeepSeek E3 三连、独立评审与 Codex 终裁均已通过" in readme
    strategy = (ROOT / "STRATEGY.md").read_text(encoding="utf-8")
    assert "（已交付并验证）" in strategy
    assert "不宣称 OS sandbox" in strategy
