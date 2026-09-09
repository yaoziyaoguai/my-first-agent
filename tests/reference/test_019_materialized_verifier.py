"""019 materialized verifier 的 overlay、boundary 与 receipt gates。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import verify_019_materialized_tree as verifier
from tests.reference.test_019_core_e3_harness import make_valid_receipt


def test_019_controls_are_detached_but_runner_is_sealed() -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source overlay membership requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    paths = {entry["path"] for entry in verifier.derive_overlay(base)}

    assert "scripts/run_019_core_e3.py" in paths
    assert "scripts/verify_019_materialized_tree.py" not in paths
    assert "docs/acceptance/019_CORE_SEAL.json" not in paths
    assert "docs/acceptance/019_CORE_RECEIPT.json" not in paths
    assert not any(path == "tui" or path.startswith("tui/") for path in paths)


def test_materialized_tree_omits_detached_mutable_019_evidence(tmp_path: Path) -> None:
    if not (verifier.REPO / ".git").exists():
        pytest.skip("source materialization requires repository metadata")
    base = json.loads(verifier.BASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = verifier.derive_overlay(base)
    tree = tmp_path / "tree"

    assert verifier.materialize_tree(entries, verifier.REPO, tree) == []
    # 019 overlay 只记录相对 009 candidate 的 delta；materializer 仍必须恢复
    # 未在 delta 中重列、但已由 009 manifest 验收的父阶段文件。
    assert not any(entry["path"] == "agent/tools/edit.py" for entry in entries)
    assert (tree / "agent/tools/edit.py").read_bytes() == (
        verifier.REPO / "agent/tools/edit.py"
    ).read_bytes()
    assert (tree / "scripts/verify_019_materialized_tree.py").is_file()
    assert (tree / "docs/implementation/009_DELIVERY_MANIFEST.json").is_file()
    for relative in verifier.DETACHED_MUTABLE_PATHS:
        assert not (tree / relative).exists(), relative


def test_portable_boundary_rejects_concrete_backend_import_and_token(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent" / "automation"
    package.mkdir(parents=True)
    module = package / "bad.py"
    module.write_text("import subprocess\n", encoding="utf-8")
    assert any("subprocess" in item for item in verifier.portable_boundary_errors(tmp_path))

    module.write_text("BACKEND = 'launchd'\n", encoding="utf-8")
    assert any("launchd" in item for item in verifier.portable_boundary_errors(tmp_path))


def test_current_portable_boundary_is_green() -> None:
    assert verifier.portable_boundary_errors(verifier.REPO) == []


def test_wheel_artifact_schema_is_exact(tmp_path: Path) -> None:
    path = tmp_path / verifier.WHEEL_ARTIFACT_PATH.relative_to(verifier.REPO)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "wheel_sha256": "a" * 64,
                "materialized_root_sha256": "b" * 64,
                "overlay_root_sha256": "c" * 64,
                "materialized_full_count": 1,
            }
        ),
        encoding="utf-8",
    )
    assert verifier._wheel_identity(tmp_path)["materialized_full_count"] == 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["extra"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="keys must be exact"):
        verifier._wheel_identity(tmp_path)


def test_materialized_pytest_count_ignores_terminal_color_codes() -> None:
    assert verifier._passed_count("\x1b[32m2486 passed\x1b[0m, 8 skipped") == 2486


def test_receipt_identity_mutation_fails_shared_reducer() -> None:
    receipt = make_valid_receipt()
    receipt["wheel_sha256"] = "not-a-digest"
    from scripts.run_019_core_e3 import validate_receipt

    assert any("wheel_sha256" in item for item in validate_receipt(receipt))


# --- Round 019 Packet 1A：候选物化验证缺失 seam 的 Named Red 合同 ---
#
# 以下测试只针对 verifier 上“应当存在、但尚未实现”的小型纯/辅助 API 冻结行为：
# 完整 pytest 证据、固定产品根来源、guarded 解析与候选报告语义。
# Green 之前的失败必须是 AttributeError（API 缺失）或目标断言失败，
# 而不是 fixture、收集或环境错误。这里定义的是 delivery/test harness 边界，
# 不新增产品 loop、授权路径或通用导入框架。


def _outcome_record(node_id: str, outcome: str, *, reason: str | None = None) -> dict:
    """单个测试节点的终态记录：node_id + 最终 outcome（skip 附带精确 reason）。"""
    return {"node_id": node_id, "outcome": outcome, "reason": reason}


def _pytest_evidence_base() -> dict:
    """合格 pytest 证据报告的最小事实集：exact schema keys + 两个 passed 节点。"""
    one = "tests/test_a.py::test_one"
    two = "tests/test_a.py::test_two"
    return {
        "schema": "my-first-agent/materialized-pytest-evidence/v1",
        "collected_node_ids": [one, two],
        "outcomes": [_outcome_record(one, "passed"), _outcome_record(two, "passed")],
        "deselected_node_ids": [],
        "session_completed": True,
    }


REQUIRED_PRODUCT_MODULES = ("main", "agent", "agent.tools", "first_agent_skill_runner")


def _product_origin_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """安装侧 site-packages 与测试树源码副本的最小固定根布局。

    固定产品根为 ``main`` / ``agent`` / ``first_agent_skill_runner``；安装侧文件
    标记 ``installed``，测试树副本标记 ``source``。``test_tree/tests`` 内含用
    importlib 实际导入四个固定模块并断言 ``ORIGIN_MARKER == "installed"`` 的
    来源测试，模拟物化树内 pytest 的真实运行方式。
    """
    installed_site = tmp_path / "site-packages"
    test_tree = tmp_path / "tree"
    product_files = (
        "main.py",
        "agent/__init__.py",
        "agent/tools.py",
        "first_agent_skill_runner/__init__.py",
    )
    for relative in product_files:
        for root, marker in ((installed_site, "installed"), (test_tree, "source")):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'ORIGIN_MARKER = "{marker}"\n', encoding="utf-8")

    origin_test = '''import importlib

PRODUCT_MODULES = (
    "main",
    "agent",
    "agent.tools",
    "first_agent_skill_runner",
)


def test_product_origin_is_installed() -> None:
    for name in PRODUCT_MODULES:
        assert importlib.import_module(name).ORIGIN_MARKER == "installed"
'''
    test_path = test_tree / "tests" / "test_product_origin.py"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(origin_test, encoding="utf-8")
    return installed_site, test_tree


def _candidate_report_base() -> dict:
    """合格候选报告的最小事实集：candidate-only、不晋级、不写历史工件。"""
    return {
        "schema": "my-first-agent/019-candidate-content-report/v1",
        "verification_scope": "candidate_only",
        "candidate_identity": {
            "base_manifest_sha256": "a" * 64,
            "parent_seal_sha256": "b" * 64,
            "overlay_root_sha256": "c" * 64,
            "entry_count": 1,
        },
        "materialized_root_sha256": "d" * 64,
        "test_input_root_sha256": "e" * 64,
        "wheel_sha256": "f" * 64,
        "verifier_sha256": "1" * 64,
        "bootstrap_sha256": "2" * 64,
        "collected_node_set_sha256": "3" * 64,
        "python_version": "3.12.3",
        "test_dependency_versions": {"pytest": "8.2.0"},
        "pytest_evidence": _pytest_evidence_base(),
        "outcome_summary": {"passed": 2, "failed": 0, "skipped": 0, "deselected": 0},
        "skips": [],
        "evidence_complete": True,
        "origin_ok": True,
        "promotion_performed": False,
        "artifacts_written": [],
        "chromium": {"status": "provided"},
    }


def test_materialized_pytest_rejects_incomplete_evidence() -> None:
    base = _pytest_evidence_base()
    one, two = base["collected_node_ids"]

    def errors(report: object) -> list[str]:
        return verifier.pytest_evidence_errors(report, approved_skips={})

    # 完整证据基线：每个收集节点恰有一个 passed 终态且会话完整。
    assert errors(base) == []

    # 报告本身不是 JSON 对象。
    assert errors([base]) != []

    # 任一 schema key 缺失都不算合格证据。
    for key in base:
        assert errors({k: v for k, v in base.items() if k != key}) != [], key

    # 会话未跑完：再多的 passed 也不能冒充完整证据。
    assert errors(dict(base, session_completed=False)) != []

    # 缺少终态：节点被收集但没有任何结果。
    assert errors(dict(base, outcomes=[_outcome_record(one, "passed")])) != []

    # 重复终态：同一节点出现两条结果。
    duplicated = [_outcome_record(one, "passed"), *base["outcomes"]]
    assert errors(dict(base, outcomes=duplicated)) != []

    # 未收集节点的结果不得混入证据。
    ghost = "tests/test_ghost.py::test_ghost"
    ghost_extra = [*base["outcomes"], _outcome_record(ghost, "passed")]
    assert errors(dict(base, outcomes=ghost_extra)) != []

    # 损坏终态：outcomes 内混入非对象记录。
    malformed = ["tests/test_a.py::test_one|passed", _outcome_record(two, "passed")]
    assert errors(dict(base, outcomes=malformed)) != []

    # 终态记录 key 必须精确为 node_id/outcome/reason，夹带额外字段即拒绝。
    extra_key = dict(_outcome_record(one, "passed"), extra=True)
    assert (
        errors(dict(base, outcomes=[extra_key, _outcome_record(two, "passed")])) != []
    )

    # 非空 deselected_node_ids 必须显式失败，不得静默吞掉。
    deselected = ["tests/test_a.py::test_three"]
    assert errors(dict(base, deselected_node_ids=deselected)) != []

    # failed/xfailed/xpassed 不得因出现 passed 数字而被洗白。
    for bad in ("failed", "xfailed", "xpassed"):
        outcomes = [_outcome_record(one, "passed"), _outcome_record(two, bad)]
        assert errors(dict(base, outcomes=outcomes)) != [], bad


def test_materialized_pytest_rejects_unapproved_skip() -> None:
    node = "tests/test_env.py::test_git_membership"
    frozen_reason = "source repository metadata unavailable in materialized tree"
    report = dict(
        _pytest_evidence_base(),
        collected_node_ids=[node],
        outcomes=[_outcome_record(node, "skipped", reason=frozen_reason)],
    )

    # 事前冻结的精确 skip node+reason 允许通过（限制项单独列出，不是全量通过）。
    assert (
        verifier.pytest_evidence_errors(report, approved_skips={node: frozen_reason})
        == []
    )

    # 未声明的 skip：即使原因看似合理也失败。
    assert verifier.pytest_evidence_errors(report, approved_skips={}) != []

    # 声明了节点但 reason 漂移：同样失败。
    drifted = dict(
        report,
        outcomes=[_outcome_record(node, "skipped", reason="reason drift")],
    )
    assert (
        verifier.pytest_evidence_errors(drifted, approved_skips={node: frozen_reason})
        != []
    )


def test_materialized_pytest_uses_installed_product_modules(tmp_path: Path) -> None:
    installed_site, test_tree = _product_origin_fixture(tmp_path)
    result = verifier.run_wheel_bound_pytest(
        python=sys.executable,
        installed_site=installed_site,
        test_tree=test_tree,
        required_modules=REQUIRED_PRODUCT_MODULES,
    )

    # 子进程内 pytest 必须真实运行并通过 fixture 内置的来源测试。
    assert result["returncode"] == 0
    # 断言 runner 是独立进程，而不是在当前进程内伪造执行。
    assert result["runner_pid"] != os.getpid()
    # 子进程观测到的产品模块来源必须全部绑定 canonical 安装位置。
    assert (
        verifier.product_origin_errors(
            result["loaded_product_origins"],
            installed_site=installed_site,
            copied_source_root=test_tree,
            required_modules=REQUIRED_PRODUCT_MODULES,
        )
        == []
    )


def test_materialized_pytest_rejects_late_source_import(tmp_path: Path) -> None:
    installed_site, test_tree = _product_origin_fixture(tmp_path)
    late_module = test_tree / "agent" / "late_loaded.py"
    late_module.write_text('ORIGIN_MARKER = "source"\n', encoding="utf-8")
    late_test_source = '''def test_late_import_origin() -> None:
    import agent.late_loaded

    assert agent.late_loaded.ORIGIN_MARKER == "source"
'''
    late_test = test_tree / "tests" / "test_late_product_import.py"
    late_test.write_text(late_test_source, encoding="utf-8")
    result = verifier.run_wheel_bound_pytest(
        python=sys.executable,
        installed_site=installed_site,
        test_tree=test_tree,
        required_modules=REQUIRED_PRODUCT_MODULES,
    )

    # 执行期才延迟加载的 copied product module 必须让子进程 pytest 失败并留痕。
    assert result["returncode"] != 0
    assert any("agent.late_loaded" in e for e in result["origin_errors"])


@pytest.mark.parametrize(
    ("module_name", "installed_relative"),
    [("main", "main.py"), ("agent.tools", "agent/tools.py")],
)
def test_materialized_pytest_cannot_rescue_broken_install(
    tmp_path: Path, module_name: str, installed_relative: str
) -> None:
    installed_site, test_tree = _product_origin_fixture(tmp_path)

    # 破坏安装侧文件：源码副本仍完好。
    (installed_site / installed_relative).unlink()
    assert (test_tree / installed_relative).is_file()

    # 无 guard 的普通子进程会因 cwd 落在测试树内而从副本救活来源。
    code = (
        "import importlib\n"
        f"print(importlib.import_module({module_name!r}).ORIGIN_MARKER)\n"
    )
    unguarded = subprocess.run(
        [sys.executable, "-c", code], cwd=test_tree, capture_output=True, text=True
    )
    assert unguarded.returncode == 0
    assert unguarded.stdout.strip() == "source"

    # wheel-bound pytest 必须拒绝这种未经授权的测试树来源救活。
    result = verifier.run_wheel_bound_pytest(
        python=sys.executable,
        installed_site=installed_site,
        test_tree=test_tree,
        required_modules=REQUIRED_PRODUCT_MODULES,
    )
    assert result["returncode"] != 0
    assert any(module_name in e for e in result["origin_errors"])


def test_candidate_content_preserves_delivery_controls(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    detached_report = tmp_path / "019-candidate-report.json"

    def errors(
        report: dict,
        report_path: Path,
        approved_skips: dict[str, str] | None = None,
    ) -> list[str]:
        # 只在调用方显式给出批准时透传：缺省调用不得替报告自我授权 skip。
        if approved_skips is None:
            return verifier.candidate_report_errors(
                report, repo_root=repo_root, report_path=report_path
            )
        return verifier.candidate_report_errors(
            report,
            repo_root=repo_root,
            report_path=report_path,
            approved_skips=approved_skips,
        )

    base = _candidate_report_base()

    # 合格候选报告：报告路径在仓库外、不晋级、不写历史工件。
    assert errors(base, detached_report) == []

    # 任一 schema key 缺失都不算合格报告。
    for key in base:
        assert errors({k: v for k, v in base.items() if k != key}, detached_report) != [], key

    # 任一顶层 digest 损坏都不算合格报告。
    for key in (
        "materialized_root_sha256",
        "test_input_root_sha256",
        "wheel_sha256",
        "verifier_sha256",
        "bootstrap_sha256",
        "collected_node_set_sha256",
    ):
        assert errors(dict(base, **{key: "not-a-digest"}), detached_report) != [], key

    # 嵌套 candidate_identity 内的 digest 损坏同样失败。
    for key in ("base_manifest_sha256", "parent_seal_sha256", "overlay_root_sha256"):
        identity = dict(base["candidate_identity"], **{key: "not-a-digest"})
        assert errors(dict(base, candidate_identity=identity), detached_report) != [], key

    # 报告写进仓库（尤其是 docs/acceptance 历史工件位置）必须失败。
    inside_repo = repo_root / "docs" / "acceptance" / "019_CORE_RECEIPT.json"
    assert errors(base, inside_repo) != []

    # 不得自封晋级。
    assert errors(dict(base, promotion_performed=True), detached_report) != []

    # 不得输出历史工件（receipt/wheel/review 等）。
    tainted = dict(base, artifacts_written=["docs/acceptance/019_CORE_RECEIPT.json"])
    assert errors(tainted, detached_report) != []

    # verification_scope 漂移即失败。
    assert errors(dict(base, verification_scope="full_delivery"), detached_report) != []

    # 测试依赖版本必须真实声明：空映射或缺 pytest 都不得通过。
    assert errors(dict(base, test_dependency_versions={}), detached_report) != []
    without_pytest = dict(base, test_dependency_versions={"coverage": "7.5.0"})
    assert errors(without_pytest, detached_report) != []

    # 证据不完整或产品来源未经校验都不得通过。
    assert errors(dict(base, evidence_complete=False), detached_report) != []
    assert errors(dict(base, origin_ok=False), detached_report) != []

    # outcome_summary 与 pytest 证据不一致即失败。
    drifted = dict(base, outcome_summary=dict(base["outcome_summary"], passed=1))
    assert errors(drifted, detached_report) != []

    # 报告自带的 skips 不得自我授权：skip 只能由调用方显式批准。
    skip_node = "tests/test_env.py::test_git_membership"
    skip_reason = "source repository metadata unavailable in materialized tree"
    skipped_evidence = dict(
        _pytest_evidence_base(),
        collected_node_ids=[skip_node],
        outcomes=[_outcome_record(skip_node, "skipped", reason=skip_reason)],
    )
    self_approved = dict(
        base,
        pytest_evidence=skipped_evidence,
        outcome_summary={"passed": 0, "failed": 0, "skipped": 1, "deselected": 0},
        skips=[{"node_id": skip_node, "reason": skip_reason}],
    )
    assert errors(self_approved, detached_report) != []
    assert (
        errors(
            self_approved, detached_report, approved_skips={skip_node: skip_reason}
        )
        == []
    )


def test_candidate_content_reports_absent_chromium_without_launch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    detached_report = tmp_path / "019-candidate-report.json"

    def errors(report: dict) -> list[str]:
        return verifier.candidate_report_errors(
            report, repo_root=repo_root, report_path=detached_report
        )

    base = _candidate_report_base()

    # Chromium 缺失：如实记录 unavailable + 原因，可通过候选证据校验。
    unavailable = dict(
        base,
        chromium={"status": "unavailable", "reason": "chromium bundle not provided"},
    )
    assert errors(unavailable) == []

    # unavailable 必须携带非空原因。
    assert errors(dict(base, chromium={"status": "unavailable"})) != []

    # 不得把缺失改写成启动、下载或资格通过。
    for bad_status in ("launched", "downloaded", "qualified"):
        assert errors(dict(base, chromium={"status": bad_status})) != [], bad_status
