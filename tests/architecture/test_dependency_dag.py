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

    leaf_only = {"agent.runtime.contracts"}
    assert {name for name in state_imports if name.startswith("agent.")} <= leaf_only
    assert {name for name in port_imports if name.startswith("agent.")} <= leaf_only
    # context/tools 是领域层，可依赖叶子合同与 ports（ContextSource 等）。
    assert {name for name in context_imports if name.startswith("agent.")} <= {
        "agent.runtime.contracts",
        "agent.runtime.ports",
    }
    all_imports = state_imports | port_imports | context_imports
    assert "agent.core" not in all_imports
    assert "agent.state" not in all_imports
