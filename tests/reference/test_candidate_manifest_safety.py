"""候选构建脚本的防误删 / 防覆盖回归（2026-10-12 补漏 W2）。

覆盖合同（WORK-PACKAGES W2）：

1. 默认只创建全新 output；已有目录/普通文件/软链接在**任何写入前**失败。
2. output 与 manifest 收窄到「仓库之外、本次拥有、已存在的同一物理父目录」下
   两个不同、尚不存在的叶子。
3. 叶子用不跟随链接的检查；父目录先规范化，叶子保留链接身份。
4. 任何目标写入前完成整份输入清单预检并冻结字节摘要。
5. 全部复制成功后才以不覆盖方式发布 manifest；失败不留有效 manifest，
   partial candidate 保留为 incomplete，不做递归删除回滚。

仓库边界类负例（仓库根、仓库祖先、仓库内输出）一律在独立临时 Git fixture 中
运行脚本副本，绝不拿真实仓库试删；真实仓库只用于只读的正常成功路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_candidate_manifest.py"

SENTINEL_BYTES = b"precious user bytes \xe4\xb8\xad\xe6\x96\x87\n"


def _run(script: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(cwd),
        check=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=fixture", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _script_module() -> object:
    """加载脚本模块，取它声明的必需输入路径（fixture 必须镜像真实输入要求）。"""

    import importlib.util

    spec = importlib.util.spec_from_file_location("_candidate_manifest_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """独立临时 Git fixture：脚本副本 + 最小可跟踪树。

    fixture 必须提供脚本声明的闭包/本轮清单路径，否则失败会来自 fixture 缺口
    而不是被检验的边界行为。
    """

    repo = tmp_path / "fixture-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "agent").mkdir()
    (repo / "tests").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / "build_candidate_manifest.py")
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / "agent" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "tests" / "test_sample.py").write_text(
        "def test_sample():\n    assert True\n", encoding="utf-8"
    )
    module = _script_module()
    required = set(module.WORKTREE_CLOSURE) | set(module.THIS_ROUND_TESTS)
    for rel in sorted(required):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture placeholder for {rel}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fixture baseline")
    return repo


@pytest.fixture
def owned_parent(tmp_path: Path) -> Path:
    parent = tmp_path / "owned"
    parent.mkdir()
    return parent


# --- 1. 已有目标绝不被删除或覆盖 -------------------------------------------


def test_existing_non_empty_output_directory_is_never_deleted(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """核心 P0：已有非空目录不得被 rmtree。"""

    sentinel = owned_parent / "user-data.txt"
    sentinel.write_bytes(SENTINEL_BYTES)
    out = owned_parent / "candidate"
    out.mkdir()
    (out / "keep-me.txt").write_bytes(b"existing candidate content\n")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert sentinel.read_bytes() == SENTINEL_BYTES
    assert (out / "keep-me.txt").read_bytes() == b"existing candidate content\n"
    assert not (owned_parent / "candidate-manifest.json").exists()


def test_existing_empty_output_directory_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    out = owned_parent / "candidate"
    out.mkdir()
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert out.is_dir()
    assert list(out.iterdir()) == []
    assert not (owned_parent / "candidate-manifest.json").exists()


def test_existing_regular_file_output_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    out = owned_parent / "candidate"
    out.write_bytes(b"not a directory\n")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert out.read_bytes() == b"not a directory\n"


def test_broken_symlink_output_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """悬空链接既不是文件也不是目录：必须按「已存在」拒绝。"""

    out = owned_parent / "candidate"
    out.symlink_to(owned_parent / "does-not-exist")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert os.path.islink(out)
    assert not (owned_parent / "does-not-exist").exists()


def test_symlink_output_pointing_into_source_tree_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    out = owned_parent / "candidate"
    out.symlink_to(fixture_repo / "agent")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert os.path.islink(out)
    assert (fixture_repo / "agent" / "mod.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_symlink_manifest_leaf_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    target = owned_parent / "elsewhere.json"
    target.write_bytes(b"{}\n")
    manifest = owned_parent / "candidate-manifest.json"
    manifest.symlink_to(target)
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(manifest),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert target.read_bytes() == b"{}\n"
    assert not (owned_parent / "candidate").exists()


# --- 2/3. 边界与链接规范化 --------------------------------------------------


def test_parent_symlink_escaping_back_into_source_tree_is_rejected(
    fixture_repo: Path, tmp_path: Path
) -> None:
    """父路径链接解析后落在源树内：必须拒绝，且不得在源树写入。"""

    linked = tmp_path / "linked-parent"
    linked.symlink_to(fixture_repo / "agent")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script, fixture_repo,
        "--out", str(linked / "candidate"),
        "--manifest", str(linked / "candidate-manifest.json"),
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not (fixture_repo / "agent" / "candidate").exists()
    assert not (fixture_repo / "agent" / "candidate-manifest.json").exists()


def test_system_path_alias_parent_is_accepted(fixture_repo: Path) -> None:
    """系统级路径别名（macOS /var → /private/var）规范化后正常可用。"""

    raw = tempfile.mkdtemp(prefix="closeout-w2-")
    parent = Path(raw)
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"
    try:
        result = _run(
            script, fixture_repo,
            "--out", str(parent / "candidate"),
            "--manifest", str(parent / "candidate-manifest.json"),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert (parent / "candidate" / "main.py").is_file()
        assert (parent / "candidate-manifest.json").is_file()
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_output_inside_source_repository_is_rejected(
    fixture_repo: Path, tmp_path: Path
) -> None:
    """仓库内输出必须拒绝，且不能顺手清理仓库内已有内容。"""

    sentinel = fixture_repo / "agent" / "sentinel.txt"
    sentinel.write_bytes(SENTINEL_BYTES)
    _git(fixture_repo, "add", "-A")
    _git(fixture_repo, "commit", "-qm", "sentinel")
    outside = tmp_path / "outside-manifest.json"
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script, fixture_repo,
        "--out", str(fixture_repo / "candidate"),
        "--manifest", str(outside),
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert sentinel.read_bytes() == SENTINEL_BYTES
    assert not (fixture_repo / "candidate").exists()
    assert not outside.exists()


def test_repository_root_as_output_is_rejected(
    fixture_repo: Path, tmp_path: Path
) -> None:
    """仓库根本身作为 output：绝不删除，绝不写入。"""

    before = sorted(p.name for p in fixture_repo.iterdir())
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(fixture_repo),
        "--manifest",
        str(tmp_path / "m.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert sorted(p.name for p in fixture_repo.iterdir()) == before
    assert (fixture_repo / "main.py").read_text(encoding="utf-8") == "print('hi')\n"
    assert not (tmp_path / "m.json").exists()


def test_repository_ancestor_as_output_is_rejected(
    fixture_repo: Path, tmp_path: Path
) -> None:
    """仓库祖先作为 output：即使叶子尚不存在也必须拒绝。"""

    leaf = fixture_repo.parent / "closeout-ancestor-probe"
    assert not leaf.exists()
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(leaf),
        "--manifest",
        str(tmp_path / "m.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert not leaf.exists()
    assert fixture_repo.is_dir()


# --- manifest 叶子身份 ------------------------------------------------------


def test_manifest_pointing_at_existing_file_is_rejected_before_any_output(
    fixture_repo: Path, owned_parent: Path
) -> None:
    manifest = owned_parent / "candidate-manifest.json"
    manifest.write_bytes(b"occupied\n")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(manifest),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert manifest.read_bytes() == b"occupied\n"
    assert not (owned_parent / "candidate").exists()


def test_manifest_pointing_at_a_source_file_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """manifest 不得指到任意源文件路径。"""

    source = fixture_repo / "main.py"
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(source),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert source.read_text(encoding="utf-8") == "print('hi')\n"
    assert not (owned_parent / "candidate").exists()


def test_manifest_inside_candidate_output_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    out = owned_parent / "candidate"
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(out / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert not out.exists()


def test_output_and_manifest_must_share_the_same_parent(
    fixture_repo: Path, owned_parent: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other-parent"
    other.mkdir()
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script, fixture_repo,
        "--out", str(owned_parent / "candidate"),
        "--manifest", str(other / "candidate-manifest.json"),
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert not (owned_parent / "candidate").exists()
    assert not (other / "candidate-manifest.json").exists()


# --- 4. 预检先于任何写入 ----------------------------------------------------


def test_unreadable_manifest_input_fails_before_creating_output(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """输入清单预检失败时，output 不能提前出现。"""

    secret = fixture_repo / "agent" / "unreadable.py"
    secret.write_text("BLOCKED = True\n", encoding="utf-8")
    _git(fixture_repo, "add", "-A")
    _git(fixture_repo, "commit", "-qm", "unreadable")
    secret.chmod(0o000)
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"
    out = owned_parent / "candidate"
    try:
        result = _run(
            script,
            fixture_repo,
            "--out",
            str(out),
            "--manifest",
            str(owned_parent / "candidate-manifest.json"),
        )

    finally:
        secret.chmod(0o644)

    assert result.returncode != 0, result.stdout + result.stderr
    assert not out.exists(), "预检失败前不得创建 output"
    assert not (owned_parent / "candidate-manifest.json").exists()


def test_source_symlink_in_manifest_is_rejected(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """清单内的源路径链接必须拒绝，不因 tracked 就可读取。"""

    link = fixture_repo / "agent" / "linked.py"
    link.symlink_to(fixture_repo / "agent" / "mod.py")
    _git(fixture_repo, "add", "-A")
    _git(fixture_repo, "commit", "-qm", "link")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"
    out = owned_parent / "candidate"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(out),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert not out.exists()
    assert not (owned_parent / "candidate-manifest.json").exists()


# --- 5. 发布语义 ------------------------------------------------------------


def test_manifest_is_published_without_overwriting_an_occupied_leaf(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """manifest 已被占用时不得覆盖，且不提供默认开启的覆盖行为。"""

    manifest = owned_parent / "candidate-manifest.json"
    manifest.write_bytes(b"first owner\n")
    script = fixture_repo / "scripts" / "build_candidate_manifest.py"

    result = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(manifest),
    )


    assert result.returncode != 0, result.stdout + result.stderr
    assert manifest.read_bytes() == b"first owner\n"


def test_second_build_into_same_parent_requires_a_fresh_leaf(
    fixture_repo: Path, owned_parent: Path
) -> None:
    """第一次成功后，同父目录的同名叶子已存在，第二次必须失败而不是覆盖。"""

    script = fixture_repo / "scripts" / "build_candidate_manifest.py"
    first = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )
    assert first.returncode == 0, first.stdout + first.stderr
    manifest_bytes = (owned_parent / "candidate-manifest.json").read_bytes()
    (owned_parent / "candidate" / "main.py").write_bytes(b"tampered\n")

    second = _run(
        script,
        fixture_repo,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )

    assert second.returncode != 0, second.stdout + second.stderr
    assert (owned_parent / "candidate-manifest.json").read_bytes() == manifest_bytes
    assert (owned_parent / "candidate" / "main.py").read_bytes() == b"tampered\n"


# --- 正常成功路径（真实仓库，只读） ----------------------------------------


def test_happy_path_copies_whole_tree_with_matching_hashes(owned_parent: Path) -> None:
    out = owned_parent / "candidate"
    manifest_path = owned_parent / "candidate-manifest.json"

    result = _run(
        SCRIPT,
        ROOT,
        "--out",
        str(out),
        "--manifest",
        str(manifest_path),
    )


    assert result.returncode == 0, result.stdout + result.stderr
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == len(manifest["files"])
    assert manifest["file_count"] > 0
    for entry in manifest["files"]:
        copied = out / entry["path"]
        assert copied.is_file(), entry["path"]
        assert _sha256(copied) == entry["sha256"], entry["path"]
    listed = {entry["path"] for entry in manifest["files"]}
    # 本轮新增回归必须进入候选清单，否则安装物只跑旧测试。
    assert "tests/reference/test_candidate_manifest_safety.py" in listed
    assert manifest["round"] == "2026-10-18 cli-personal-trial-closeout"


def test_successful_build_does_not_modify_the_source_tree(owned_parent: Path) -> None:
    def status() -> str:
        return subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True, cwd=str(ROOT),
        ).stdout

    before = status()
    result = _run(
        SCRIPT,
        ROOT,
        "--out",
        str(owned_parent / "candidate"),
        "--manifest",
        str(owned_parent / "candidate-manifest.json"),
    )


    assert result.returncode == 0, result.stdout + result.stderr
    assert status() == before
