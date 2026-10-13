"""F3b：D06 独立断言冻结在 candidate 之外；候选空测试/坏服务/坏页面不能骗过。"""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts.coding_scenario_grader import grade_d06

D06_FIXTURE = (
    Path(__file__).parents[1] / "acceptance" / "fixtures" / "d06_local_page"
)


def _candidate(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    shutil.copytree(D06_FIXTURE, candidate)
    return candidate


def _fixed_reference(tmp_path: Path) -> Path:
    """修复后的参考实现：submit 后真实刷新列表（D06 任务的正确行为）。"""

    candidate = _candidate(tmp_path)
    app = candidate / "web" / "app.mjs"
    source = app.read_text(encoding="utf-8")
    source = source.replace(
        """  form.addEventListener("submit", (event) => {
    event.preventDefault();
    items.push(input.value);
    input.value = "";
  });""",
        """  form.addEventListener("submit", (event) => {
    event.preventDefault();
    items.push(input.value);
    input.value = "";
    render();
  });""",
    )
    app.write_text(source, encoding="utf-8")
    return candidate


def test_f3_broken_fixture_is_not_browser_behavior_green(tmp_path) -> None:
    """A12-1：reference 页面脚本缺陷（submit 不刷新）→ browser_behavior/regression false。"""

    checks = grade_d06(_candidate(tmp_path))
    assert checks["browser_behavior"] is False
    assert checks["regression"] is False


def test_f3_broken_server_fails_managed_server(tmp_path) -> None:
    candidate = _candidate(tmp_path)
    (candidate / "server.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    checks = grade_d06(candidate)
    assert checks["managed_server"] is False


def test_f3_candidate_empty_test_cannot_change_frozen_verdict(tmp_path) -> None:
    """A12-2：候选把自带测试改成空通过 → 独立断言不受影响。"""

    candidate = _fixed_reference(tmp_path)
    (candidate / "tests" / "app.test.mjs").write_text(
        'import test from "node:test";\n\ntest("always passes", () => {});\n',
        encoding="utf-8",
    )
    checks = grade_d06(candidate)
    assert checks["browser_behavior"] is True
    assert checks["regression"] is True


def test_f3_fixed_reference_is_green(tmp_path) -> None:
    checks = grade_d06(_fixed_reference(tmp_path))
    assert checks["managed_server"] is True
    assert checks["browser_behavior"] is True
    assert checks["regression"] is True
    # 该项只有外层 driver 能签发（资源门槛），grader 恒 false。
    assert checks["owned_resources_closed"] is False
