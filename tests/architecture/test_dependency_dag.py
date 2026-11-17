from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_runtime_leaf_contracts_do_not_import_services_or_adapters() -> None:
    imports = _imports(ROOT / "agent/runtime/contracts.py")

    assert not {name for name in imports if name.startswith("agent.")}


def test_state_and_ports_depend_only_on_leaf_contracts() -> None:
    state_imports = _imports(ROOT / "agent/runtime/state.py")
    port_imports = _imports(ROOT / "agent/runtime/ports.py")
    context_imports = _imports(ROOT / "agent/runtime/context.py")
    context_control_imports = _imports(ROOT / "agent/runtime/context_control.py")
    context_source_imports = _imports(ROOT / "agent/runtime/context_source.py")
    compaction_rules_imports = _imports(ROOT / "agent/runtime/compaction_rules.py")
    resource_lifecycle_imports = _imports(
        ROOT / "agent/runtime/resource_lifecycle.py"
    )

    leaf_only = {"agent.runtime.contracts"}
    # state 额外依赖三个窄 leaf：compaction_rules 负责 turn grammar/removal，
    # resource_lifecycle 只从 closed receipts 推导 active ownership，
    # provider_consent 只做许可投影/比较，不推进循环或写 state。
    assert {name for name in state_imports if name.startswith("agent.")} <= {
        "agent.runtime.contracts",
        "agent.runtime.compaction_rules",
        "agent.runtime.resource_lifecycle",
        "agent.runtime.provider_consent",
    }
    assert {name for name in port_imports if name.startswith("agent.")} <= leaf_only
    assert {name for name in context_imports if name.startswith("agent.")} <= {
        "agent.runtime.contracts",
        "agent.runtime.context_control",
        "agent.runtime.context_source",
        "agent.runtime.ports",
        "agent.runtime.compaction_rules",
        "agent.runtime.provider_consent",
    }
    assert {
        name for name in context_control_imports if name.startswith("agent.")
    } <= leaf_only
    assert {
        name for name in context_source_imports if name.startswith("agent.")
    } <= leaf_only
    # 两个 leaf 不得反向依赖 state/context/ports 等任何服务层；
    # compaction_rules 可复用 resource lifecycle 的同一 ownership 解释。
    assert {
        name for name in compaction_rules_imports if name.startswith("agent.")
    } <= leaf_only | {"agent.runtime.resource_lifecycle"}
    assert {
        name for name in resource_lifecycle_imports if name.startswith("agent.")
    } <= leaf_only
    all_imports = state_imports | port_imports | context_imports
    assert "agent.core" not in all_imports
    assert "agent.state" not in all_imports


def test_loop_and_tool_governance_follow_runtime_dag() -> None:
    loop_imports = _imports(ROOT / "agent/runtime/loop.py")
    tool_governance_imports = _imports(ROOT / "agent/runtime/tool_governance.py")

    # loop 是唯一的 effect-ordering 服务层：只允许依赖更低的 runtime 层
    # （叶子合同、leaf 投影、state、ports、治理知识）。adapter 与实现层
    # （checkpoint/tools/events/views）以及 provider/CLI/文件工具不在其
    # 依赖内（KERNEL_ARCHITECTURE「单向依赖」）；新增依赖必须先扩本清单。
    assert {name for name in loop_imports if name.startswith("agent.runtime")} <= {
        "agent.runtime.contracts",
        "agent.runtime.state",
        "agent.runtime.ports",
        "agent.runtime.context",
        "agent.runtime.context_control",
        "agent.runtime.context_source",
        "agent.runtime.control",
        "agent.runtime.evidence",
        "agent.runtime.provider_consent",
        "agent.runtime.resource_lifecycle",
    }
    # tool_governance 是从 KernelToolRuntime 收拢的治理知识：只依赖叶子合同。
    assert {name for name in tool_governance_imports if name.startswith("agent.runtime")} <= {
        "agent.runtime.contracts"
    }


# runtime 模块反向外溢到其他 agent 包的已记录例外清单。每个条目都必须有
# docs 或源码注释中的既有定性；新边先进记录、再进本清单，不得静默放宽。
_REVERSE_EDGE_EXCEPTIONS: dict[str, set[str]] = {
    # loop 驱动 compaction 的 archive-before-CAS 序列（KERNEL_ARCHITECTURE
    # 「上下文管理」），archive 写入 adapter 在 agent.continuity.compaction。
    # user_message_urls/admit_public_url 留在 web 层与 closed admission 判据
    # 同居（loop.py 头部注释、2026-10-25 handoff STATE #5）；runtime↔web 双向
    # 包依赖已成形、属已记录 LOW（「DAG 未钉」）——本断言即把它钉住。
    "loop.py": {"agent.continuity.compaction", "agent.web.safety"},
    # web_fetch_url 的 source 归一与 fact 侧用同一个 admit_public_url
    # canonical 化后精确匹配（2026-10-25 handoff STATE #5）。
    "tool_governance.py": {"agent.web.safety"},
    # KernelToolRuntime 独占 draft admission：process/sandbox runner 只能返回
    # closed draft，receipt/ToolResult 由 runtime 铸造（015 设计流图
    # Runner→Draft→ToolRuntime、017 §2 owner 合同）。
    "tools.py": {"agent.process.contracts", "agent.sandbox.contracts"},
}


def test_runtime_modules_no_reverse_package_dependencies() -> None:
    violations: list[str] = []
    for path in sorted((ROOT / "agent" / "runtime").glob("*.py")):
        allowed = _REVERSE_EDGE_EXCEPTIONS.get(path.name, set())
        for name in _imports(path):
            if (
                name.startswith("agent.")
                and not name.startswith("agent.runtime")
                and name not in allowed
            ):
                violations.append(f"{path.name} -> {name}")

    assert not violations, f"runtime 出现未记录的反向包依赖: {violations}"
