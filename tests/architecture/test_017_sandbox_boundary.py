"""017 native sandbox 架构边界（静态断言，audit T7）。

- 产品源不 import Coding Agent 辅助产物（graphify-out/`.ua`/superpowers）。
- sandbox 纯模块（ports/qualification/seatbelt/policy/contracts/executor）不
  import runtime loop/context/tools/state/evidence/checkpoint（叶子合同
  runtime.contracts 除外——sandbox→runtime.contracts 是冻结依赖方向）。
- 无动态 registry：sandbox + composition 不使用 importlib/`__import__`/
  globals 注册。
- main 只经 build_composition 组合，不直接构造第二个 Runtime/ToolRuntime。
- Docker 时代词汇与退役模块在产品源中零残留（absence gate）。
- sandbox 资源永不回落 local_process。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# runtime 内部器官：sandbox 纯模块不允许认识。
_RUNTIME_ORGANS = (
    "agent.runtime.loop",
    "agent.runtime.tools",
    "agent.runtime.context",
    "agent.runtime.state",
    "agent.runtime.evidence",
    "agent.runtime.checkpoint",
)

# 纯 sandbox 模块（tools.py 是 registration 缝合层、authority.py 是
# runtime.contracts 的 re-export，二者允许出现在 composition 侧）。
_PURE_SANDBOX_MODULES = (
    "agent/sandbox/contracts.py",
    "agent/sandbox/executor.py",
    "agent/sandbox/policy.py",
    "agent/sandbox/ports.py",
    "agent/sandbox/qualification.py",
    "agent/sandbox/seatbelt.py",
)

_RETIRED_DOCKER_NAMES = (
    "DockerSandboxEnvironment",
    "DockerQualification",
    "SandboxStore",
    "ChangeBundle",
    "SandboxBundleReceipt",
    "sandbox_capture_changes",
    "sandbox_apply_bundle",
    "egress_proxy",
    "image_digest",
    "workspace_snapshot_digest",
    "proxy_image_digest",
)


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_pure_sandbox_modules_do_not_import_runtime_organs() -> None:
    for relative in _PURE_SANDBOX_MODULES:
        path = ROOT / relative
        assert path.is_file(), f"retired/missing sandbox module leaked: {relative}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        offenders = _imported_modules(tree) & set(_RUNTIME_ORGANS)
        assert not offenders, f"{relative} imports runtime organs: {offenders}"


def test_product_source_has_no_retired_docker_sandbox_path() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "agent").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for retired in _RETIRED_DOCKER_NAMES:
            if retired in text:
                offenders.append(f"{relative}: {retired}")
    assert not offenders, f"retired Docker sandbox vocabulary leaked: {offenders}"


def test_sandbox_and_composition_have_no_dynamic_registry() -> None:
    for relative in (*_PURE_SANDBOX_MODULES, "agent/composition.py", "agent/sandbox/tools.py"):
        path = ROOT / relative
        assert path.is_file(), relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "importlib":
                offenders = [a.name for a in node.names if a.name != "annotations"]
                assert not offenders, f"{relative} imports importlib: {offenders}"
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "__import__":
                    raise AssertionError(f"{relative} uses __import__")


def test_sandbox_never_falls_back_to_local_process() -> None:
    # 015 的 local_process 是独立产品工具（composition 合法注册）；回退禁令
    # 针对的是 sandbox 文件自身——sandbox 工具/executor 不得调用它。
    for relative in ("agent/sandbox/tools.py", "agent/sandbox/executor.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "build_local_process_registration" not in text, relative
        assert "LOCAL_PROCESS_TOOL_NAME" not in text, relative


def test_main_composes_only_through_build_composition() -> None:
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "KernelToolRuntime(" not in text
    assert "AgentRuntime(" not in text
    assert "build_composition(" in text


def test_sandbox_modules_do_not_import_coding_agent_artifacts() -> None:
    forbidden = ("graphify", "superpowers")
    for path in sorted((ROOT / "agent").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith("agent/sandbox/"):
            continue
        modules = _imported_modules(
            ast.parse(path.read_text(encoding="utf-8"), filename=relative),
        )
        offenders = {
            module for module in modules
            if any(token in module for token in forbidden)
        }
        assert not offenders, f"{relative} imports coding-agent artifacts: {offenders}"
