from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 012 U0：冻结基线时锁定“没有第二个 loop / 动态注册 / 前置意图分类”的架构不变量。
# 这些名字一旦出现在 production tree，即意味着引入了被禁止的并行执行路径或动态扩权机制，
# 与 STRATEGY.md / 012 design 中“唯一 AgentRuntime.run_turn、静态 composition”的边界冲突。
_FORBIDDEN_NAMES = {
    "CodingLoop",
    "GoalSessionDriver",
    "ServiceLocator",
    "DynamicRegistry",
    "IntentRouter",
    "IntentClassifier",
    "service_locator",
    "dynamic_registry",
    "intent_router",
    "classify_intent",
}


def _production_sources() -> list[Path]:
    return [path for path in (ROOT / "agent").rglob("*.py") if "graphify-out" not in path.parts]


def test_no_forbidden_parallel_execution_symbols_in_production() -> None:
    offenders: list[tuple[str, str, int]] = []
    for path in _production_sources():
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            name: str | None = None
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                name = node.name
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name in _FORBIDDEN_NAMES:
                offenders.append((relative, name, getattr(node, "lineno", 0)))
    assert not offenders, f"forbidden parallel-execution symbols found: {offenders}"


def test_production_never_uses_dynamic_module_registry() -> None:
    # importlib.import_module 是热加载 / 动态服务注册的典型机制；
    # 012 静态 composition 不允许它进入产品树。
    # 例外：process_runner.py 的 __import__("contextlib") 是 stdlib suppress 惯用法，
    # 不属于动态扩权，故不在此禁止范围。
    offenders: list[tuple[str, int]] = []
    for path in _production_sources():
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "importlib" or alias.name.startswith("importlib."):
                        offenders.append((relative, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "importlib" or node.module.startswith("importlib."):
                    offenders.append((relative, node.lineno))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                offenders.append((relative, node.lineno))
    assert not offenders, f"dynamic module registry usage found: {offenders}"
