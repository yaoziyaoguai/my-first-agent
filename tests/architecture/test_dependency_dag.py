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
