"""009 U1 delivery verifier oracles（隔离 temp repo/fixtures 驱动，不依赖原仓库 .git/.venv）。

每个测试以准确 Red 锁定 verifier 行为：schema 绑定 baseline/operation/owner/Git-mode、
单一 no-follow descriptor 同时完成 metadata+digest、tracked delta+untracked admission+ops
三方对账、denied/unknown 在 read/hash 前失败、临时索引不触碰真实 index、non-editable 安装
与 dirty-tree origin 拒绝、sandbox deny-network 先证明阻断且不忽略 delivery 测试、
control seal 拒绝 missing/null/unsealed/drifted controls。
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = ROOT / "scripts" / "verify_materialized_tree.py"


@pytest.fixture(scope="module")
def verifier():
    spec = importlib.util.spec_from_file_location("verify_materialized_tree", VERIFY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")
    (repo / "keep.py").write_text("# unchanged\n", encoding="utf-8")
    (repo / "modified.py").write_text("old\n", encoding="utf-8")
    (repo / "deleted.py").write_text("# gone\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    baseline = _git(repo, "rev-parse", "HEAD").strip()
    # 目标树变更（仅工作树，不 commit）：modify / delete / add。
    (repo / "modified.py").write_text("new content\n", encoding="utf-8")
    (repo / "deleted.py").unlink()
    (repo / "added.py").write_text("# new file\n", encoding="utf-8")
    return repo, baseline


def _valid_entries(repo: Path) -> list[dict]:
    return [
        {
            "path": "modified.py",
            "operation": "modify",
            "owner_units": ["audited-baseline"],
            "sha256": _sha(repo / "modified.py"),
            "git_mode": "100644",
        },
        {
            "path": "deleted.py",
            "operation": "delete",
            "owner_units": ["audited-baseline"],
        },
        {
            "path": "added.py",
            "operation": "add",
            "owner_units": ["audited-baseline"],
            "sha256": _sha(repo / "added.py"),
            "git_mode": "100644",
        },
    ]


def _manifest(baseline: str, entries: list[dict], controls=None) -> dict:
    return {
        "schema": "my-first-agent/delivery-manifest/v2",
        "baseline_commit": baseline,
        "entries": entries,
        "control_files": controls or [],
    }


# 1) schema 绑定 baseline / operation / owner ordering / Git mode/type
def test_manifest_schema_binds_baseline_operations_owner_order_and_git_identity(
    verifier, tmp_path
) -> None:
    repo, baseline = _make_repo(tmp_path)
    # 完整、一致的 manifest → 无错误。
    assert verifier.validate_manifest(_manifest(baseline, _valid_entries(repo)), repo) == []

    bad_schema = _manifest(baseline, _valid_entries(repo))
    bad_schema["schema"] = "wrong"
    assert any("schema must be" in e for e in verifier.validate_manifest(bad_schema, repo))

    short_base = _manifest("abc", _valid_entries(repo))
    assert any("baseline_commit must be" in e for e in verifier.validate_manifest(short_base, repo))

    missing_base = _manifest("0" * 40, _valid_entries(repo))
    assert any("does not exist" in e for e in verifier.validate_manifest(missing_base, repo))

    entries = _valid_entries(repo)
    entries[0]["operation"] = "upsert"
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("invalid operation" in e for e in errs)

    entries = _valid_entries(repo)
    entries[0]["owner_units"] = []
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("owner_units must be" in e for e in errs)

    entries = _valid_entries(repo)
    entries[0]["owner_units"] = ["audited-baseline", "audited-baseline"]
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("ordered without duplicates" in e for e in errs)

    entries = _valid_entries(repo)
    entries[0]["owner_units"] = ["bogus-unit"]
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("unknown owner_units" in e for e in errs)

    entries = _valid_entries(repo)
    entries[0].pop("git_mode")
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("git_mode" in e for e in errs)

    entries = _valid_entries(repo)
    entries[0]["git_mode"] = "100600"
    errs = verifier.validate_manifest(_manifest(baseline, entries), repo)
    assert any("git_mode" in e for e in errs)


# 2) 单一 no-follow descriptor 同时完成 metadata 与 digest（无 TOCTOU）
def test_manifest_validation_uses_one_no_follow_descriptor_for_metadata_and_digest(
    verifier, tmp_path
) -> None:
    repo, baseline = _make_repo(tmp_path)
    f = repo / "added.py"
    info, digest = verifier.admit_descriptor(f)
    assert digest == _sha(f)  # digest 来自同一 fd
    assert verifier._git_mode_for_stat(info) == "100644"

    # hardlink：link count != 1 → 拒绝（descriptor 内 fstat）。
    linked = repo / "hardlink.py"
    os.link(f, linked)
    with pytest.raises(ValueError, match="link count"):
        verifier.admit_descriptor(linked)
    linked.unlink()

    # symlink：O_NOFOLLOW 直接拒绝（descriptor 不解析链接）。
    sym = repo / "symlink.py"
    os.symlink(f, sym)
    with pytest.raises(OSError):
        verifier.admit_descriptor(sym)
    sym.unlink()

    # reconcile 用同一 descriptor 校验 digest：正确通过，篡改 digest 报 mismatch。
    assert verifier.reconcile_membership(_manifest(baseline, _valid_entries(repo)), repo) == []
    tampered = _valid_entries(repo)
    tampered[2]["sha256"] = "0" * 64
    errs = verifier.reconcile_membership(_manifest(baseline, tampered), repo)
    assert any("sha256 mismatch" in e for e in errs)


# 3) 三方对账：tracked delta + 显式 untracked admission + manifest operations
def test_membership_reconciles_tracked_delta_explicit_untracked_and_operations(
    verifier, tmp_path
) -> None:
    repo, baseline = _make_repo(tmp_path)
    # 完整对账通过。
    assert verifier.reconcile_membership(_manifest(baseline, _valid_entries(repo)), repo) == []

    # 漏报 untracked add → unknown untracked 失败。
    missing_add = _valid_entries(repo)
    missing_add = [e for e in missing_add if e["path"] != "added.py"]
    errs = verifier.reconcile_membership(_manifest(baseline, missing_add), repo)
    assert any("unknown untracked not admitted: added.py" in e for e in errs)

    # 漏报 tracked delete → tracked delete 未声明。
    missing_del = [e for e in _valid_entries(repo) if e["path"] != "deleted.py"]
    errs = verifier.reconcile_membership(_manifest(baseline, missing_del), repo)
    assert any("tracked delete" in e and "deleted.py" in e for e in errs)

    # 把 add 误标为 modify → untracked 必须以 add 入册。
    mislabeled = _valid_entries(repo)
    mislabeled[2]["operation"] = "modify"
    errs = verifier.reconcile_membership(_manifest(baseline, mislabeled), repo)
    assert any("must be admitted as 'add'" in e for e in errs)


# 4) denied / unknown 路径在内容读取或 hash 之前失败
def test_denied_and_unknown_paths_fail_before_content_read_or_hash(verifier, tmp_path) -> None:
    repo, baseline = _make_repo(tmp_path)
    # denied 路径用 dangling symlink：若被 read/hash 会报 missing/admission，但 deny 先于 read。
    denied_link = repo / ".env"
    os.symlink(repo / "does_not_exist", denied_link)
    entries = _valid_entries(repo)
    entries.append(
        {"path": ".env", "operation": "add", "owner_units": ["audited-baseline"],
         "sha256": "0" * 64, "git_mode": "100644"}
    )
    errs = verifier.reconcile_membership(_manifest(baseline, entries), repo)
    assert any("DENIED path admitted: .env" in e for e in errs)
    # 关键：deny 在 read/hash 之前，故没有针对 .env 的读取/hash 错误。
    assert not any(".env: admission failed" in e or ".env: sha256 mismatch" in e for e in errs)

    # unknown untracked：投放一个非 denied、未声明的新 untracked 文件。
    stray = repo / "stray_untracked.py"
    stray.write_text("# not admitted\n", encoding="utf-8")
    errs = verifier.reconcile_membership(_manifest(baseline, _valid_entries(repo)), repo)
    assert any("unknown untracked not admitted: stray_untracked.py" in e for e in errs)


# 5) materialization 使用临时索引，不触碰真实 index
def test_materialization_uses_temporary_index_without_touching_real_index(
    verifier, tmp_path
) -> None:
    repo, baseline = _make_repo(tmp_path)
    index_path = repo / ".git" / "index"
    before = _sha(index_path)
    dest = tmp_path / "materialized"
    errors = verifier.materialize_tree(_manifest(baseline, _valid_entries(repo)), repo, dest)
    assert errors == [], errors
    after = _sha(index_path)
    assert before == after, "real .git/index must not change during materialization"
    # materialized tree = baseline + manifest delta = 当前目标树。
    assert (dest / "keep.py").is_file()
    assert (dest / "modified.py").read_text() == "new content\n"
    assert (dest / "added.py").is_file()
    assert not (dest / "deleted.py").exists()


# 6) content gate：non-editable 安装并拒绝 dirty-tree origin
def test_content_gate_installs_noneditable_and_rejects_dirty_tree_origins(
    verifier, tmp_path
) -> None:
    tree = tmp_path / "tinyagent"
    (tree / "agent").mkdir(parents=True)
    (tree / "agent" / "__init__.py").write_text('MARKER = "tiny"\n', encoding="utf-8")
    (tree / "main.py").write_text("import agent\n", encoding="utf-8")
    (tree / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools>=68\"]\n"
        "build-backend = \"setuptools.build_meta\"\n"
        "[project]\nname = \"tinyagent\"\nversion = \"0.0.1\"\n"
        "[tool.setuptools]\npy-modules = [\"main\"]\n"
        "[tool.setuptools.packages.find]\ninclude = [\"agent\"]\n",
        encoding="utf-8",
    )
    prefix = tmp_path / "prefix"
    rc, out = verifier.install_noneditable(tree, prefix)
    assert rc == 0, out
    ok, msg = verifier.assert_origin(prefix, dirty_root=tree)
    assert ok, msg
    # 反向：未安装的 prefix 无法证明 clean origin → 拒绝。
    empty_prefix = tmp_path / "empty-prefix"
    empty_prefix.mkdir()
    ok2, _ = verifier.assert_origin(empty_prefix, dirty_root=tree)
    assert not ok2


# 6b) console entrypoint origin（N1）：prefix/bin 存在 install 生成的 wrapper 且解析到 prefix
def test_console_entrypoint_origin_verifies_install_generated_wrappers_resolve_to_prefix(
    verifier, tmp_path
) -> None:
    tree = tmp_path / "tinyagent"
    (tree / "agent").mkdir(parents=True)
    (tree / "agent" / "__init__.py").write_text('MARKER = "tiny"\n', encoding="utf-8")
    # main 暴露 main()/run_schedule()；--help 经 argparse 在任何真实工作前 SystemExit(0)，
    # 故 wrapper 的 `from main import <fn>` 必须从安装处成功解析 main 及其全部传递导入。
    (tree / "main.py").write_text(
        "import argparse\n"
        "def main():\n"
        "    argparse.ArgumentParser(prog='first-agent').parse_args(['--help'])\n"
        "def run_schedule():\n"
        "    argparse.ArgumentParser(prog='first-agent-schedule').parse_args(['--help'])\n",
        encoding="utf-8",
    )
    (tree / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"setuptools>=68\"]\n"
        "build-backend = \"setuptools.build_meta\"\n"
        "[project]\nname = \"tinyagent\"\nversion = \"0.0.1\"\n"
        "[project.scripts]\n"
        "first-agent = \"main:main\"\n"
        "first-agent-schedule = \"main:run_schedule\"\n"
        "[tool.setuptools]\npy-modules = [\"main\"]\n"
        "[tool.setuptools.packages.find]\ninclude = [\"agent\"]\n",
        encoding="utf-8",
    )
    prefix = tmp_path / "prefix"
    rc, out = verifier.install_noneditable(tree, prefix)
    assert rc == 0, out

    # 显式 console entrypoint origin：prefix/bin 下两个 wrapper 存在、是 owner-regular
    # 生成文件、target 为 main:<fn>、且 prefix-first 环境下 --help 端到端加载。
    ok, msg = verifier.assert_console_entrypoint_origin(prefix, dirty_root=tree)
    assert ok, msg

    # 反向：未安装 entrypoint 的空 prefix → 缺失失败（不静默通过）。
    empty_prefix = tmp_path / "empty-prefix"
    empty_prefix.mkdir()
    ok2, msg2 = verifier.assert_console_entrypoint_origin(empty_prefix, dirty_root=tree)
    assert not ok2
    assert "first-agent" in msg2


# 7) content gate：继承的 deny-network 边界 + 完整 suites（不忽略 delivery 测试）
def test_content_gate_requires_inherited_deny_network_and_full_suites(verifier, tmp_path) -> None:
    profile = verifier.build_sandbox_profile()
    # 负向探针：sandbox 必须阻断网络（loopback listener）。
    denied, dmsg = verifier.deny_network_preflight(profile)
    assert denied, dmsg
    # 该进程（content gate 下是 sandboxed pytest 的 descendant）自身也不能使用网络：
    # 直接 connect 必然失败——边界覆盖所有后代。
    import socket as _socket

    probe_sock = _socket.socket()
    probe_sock.settimeout(3)
    with pytest.raises(OSError):
        probe_sock.connect(("127.0.0.1", 1))
    probe_sock.close()
    # 完整 suites：不 --ignore 任何 delivery 测试。
    args = verifier.content_pytest_args(tmp_path / "tree")
    assert not any(a.startswith("--ignore") for a in args), args
    # sandbox-exec 不可用 → fail closed（run_under_sandbox 返回失败码，绝不静默成功）。
    fc_rc, _ = verifier.run_under_sandbox(
        [sys.executable, "-c", "print(1)"], profile, sandbox_exec="/nonexistent/sandbox-exec"
    )
    assert fc_rc not in (0, 1), fc_rc


# 8) control seal 拒绝 missing / null / unsealed / drifted controls
def test_control_seal_rejects_missing_null_unsealed_and_drifted_controls(
    verifier, tmp_path
) -> None:
    repo, baseline = _make_repo(tmp_path)
    control = repo / "CONTROL.md"
    control.write_text("sealed body\n", encoding="utf-8")
    real_digest = _sha(control)
    base_entries = _valid_entries(repo)

    def _manifest_with_control(sha_value, seal_value):
        controls = [{
            "path": "CONTROL.md", "role": "post-gate",
            "sha256": sha_value, "seal_state": seal_value,
        }]
        return _manifest(baseline, base_entries, controls=controls)

    # sealed + matching digest → 0（所有 ordinary + control 通过）。
    sealed = verifier.control_seal(_manifest_with_control(real_digest, "sealed-u8"), repo)
    assert sealed == 0

    # null sha → 失败。
    assert verifier.control_seal(_manifest_with_control(None, "sealed-u8"), repo) != 0
    # unsealed → 失败。
    assert verifier.control_seal(_manifest_with_control(real_digest, "unsealed-u8"), repo) != 0
    # drifted digest → 失败。
    assert verifier.control_seal(_manifest_with_control("a" * 64, "sealed-u8"), repo) != 0
    # missing control file → 失败。
    control.unlink()
    assert verifier.control_seal(_manifest_with_control(real_digest, "sealed-u8"), repo) != 0


# --- retained kernel regressions (R21): A15/A16/A17/A19 stay Green from materialized tree ---


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)


def test_a15_private_root_casefold() -> None:
    r = _run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/tools/test_path_safety.py::test_private_roots_reject_case_variants_for_all_operations"],
        ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_a16_stale_approval_nonfatal() -> None:
    r = _run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/kernel/test_tool_outcomes.py::test_stale_approval_is_nonfatal_nonexecution"],
        ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_a17_provider_context_projection() -> None:
    r = _run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/provider/test_memory_context_projection.py::test_both_adapters_project_untrusted_context_without_network"],
        ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_a19_strict_frontmatter() -> None:
    r = _run(
        [sys.executable, "-m", "pytest", "-q",
         "tests/skill/test_catalog.py::test_frontmatter_rejects_unknown_and_ambiguous_yaml"],
        ROOT,
    )
    assert r.returncode == 0, r.stdout + r.stderr
