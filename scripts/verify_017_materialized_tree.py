#!/usr/bin/env python3
"""验证 017 overlay、016 parent seal 与 native materialized content。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import verify_016_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        run_under_sandbox,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import verify_016_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
        build_sandbox_profile,
        deny_network_preflight,
        run_under_sandbox,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "016_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "implementation" / "017_DELIVERY_SEAL.json"
ATTESTATION_PATH = (
    REPO / "docs" / "acceptance" / "017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json"
)
VERIFIER_PATH = REPO / "scripts" / "verify_017_materialized_tree.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v6"
SEAL_KEYS = frozenset(
    {
        "schema",
        "base_manifest_sha256",
        "parent_seal_sha256",
        "verifier_sha256",
        "entry_count",
        "overlay_root_sha256",
    }
)

# delivery controls 与 E3 receipt 是 detached evidence，不混入它们证明的 root。
CONTROL_PATHS = inherited.CONTROL_PATHS | frozenset(
    {
        "docs/implementation/017_DELIVERY_SEAL.json",
        "docs/implementation/017_EXECUTION_LOG.md",
        "scripts/verify_017_materialized_tree.py",
        "scripts/run_017_e3.py",
        "docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json",
        "docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_INDEPENDENT_REVIEW.md",
        "docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_WHEEL.json",
    }
)

# materialized content gate 的 detached wheel artifact：记录 gate 构建的 wheel
# digest 与 gate 时的 overlay root（attestation 阶段与当前 seal 交叉核对，
# 防 wheel 来自旧树）。仅在 content gate 全部检查通过后写入。
WHEEL_ARTIFACT_REL = Path(
    "docs/acceptance/017_SANDBOXED_WORKSPACE_EXECUTION_WHEEL.json",
)
SOURCE_DATE_EPOCH = "315532800"
MATERIALIZED_LOOPBACK_MARKER = "materialized_loopback"


def materialized_wheel_identity(repo_root: Path = REPO) -> dict:
    """读取 wheel artifact（closed keys）；缺失/形状错误即 ValueError。"""

    artifact = _load_json(repo_root / WHEEL_ARTIFACT_REL)
    if set(artifact) != {"wheel_sha256", "overlay_root_sha256"}:
        raise ValueError("wheel artifact keys must be exact")
    return artifact


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON control {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return value


@contextmanager
def _inherited_controls():
    previous = inherited.CONTROL_PATHS
    inherited.CONTROL_PATHS = CONTROL_PATHS
    try:
        yield
    finally:
        inherited.CONTROL_PATHS = previous


def derive_overlay(base_manifest: dict, repo_root: Path = REPO) -> list[dict]:
    with _inherited_controls():
        entries = inherited.derive_overlay(base_manifest, repo_root)
    if len({entry["path"] for entry in entries}) != len(entries):
        raise ValueError("duplicate path in derived 017 overlay")
    return entries


def overlay_root(
    base_manifest_sha256: str,
    parent_seal_sha256: str,
    entries: list[dict],
) -> str:
    return inherited.overlay_root(
        base_manifest_sha256,
        parent_seal_sha256,
        entries,
    )


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except ValueError as exc:
        return [], [str(exc)]
    if set(seal) != SEAL_KEYS:
        errors.append("017 seal keys must match the strict schema")
    if seal.get("schema") != SCHEMA:
        errors.append(f"seal schema must be {SCHEMA!r}")
    try:
        base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
        parent_digest = _sha256(repo_root / PARENT_SEAL_PATH.relative_to(REPO))
        verifier_digest = _sha256(repo_root / VERIFIER_PATH.relative_to(REPO))
    except OSError as exc:
        return [], [*errors, f"delivery control unavailable: {exc}"]
    if seal.get("base_manifest_sha256") != base_digest:
        errors.append("009 base manifest digest drift")
    if seal.get("parent_seal_sha256") != parent_digest:
        errors.append("016 parent seal digest drift")
    if seal.get("verifier_sha256") != verifier_digest:
        errors.append("017 verifier digest drift")
    try:
        entries = derive_overlay(base, repo_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [], [*errors, f"overlay admission failed: {exc}"]
    actual_root = overlay_root(base_digest, parent_digest, entries)
    if seal.get("entry_count") != len(entries):
        errors.append(
            f"overlay entry count drift: expected {seal.get('entry_count')}, "
            f"actual {len(entries)}"
        )
    if seal.get("overlay_root_sha256") != actual_root:
        errors.append("017 overlay root digest drift")
    return entries, errors


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"017 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("017 control seal ok: 009 manifest + 016 parent + verifier + overlay")
    return 0


def check_attestation(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    try:
        receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
        wheel_artifact = materialized_wheel_identity(repo_root)
        import run_017_e3 as e3  # type: ignore[import-not-found]
    except (OSError, ValueError) as exc:
        return _report([f"017 E3 attestation unavailable: {exc}"])
    if wheel_artifact["overlay_root_sha256"] != seal["overlay_root_sha256"]:
        return _report(
            ["wheel artifact binds a different overlay root than the current seal"],
        )
    try:
        sys.path.insert(0, str(repo_root))
        reason = e3.qualification_reason()
        current_identity = e3.delivery_identity(repo_root)
        current_backend = e3.backend_identity()
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return _report([f"017 delivery identity unavailable: {exc}"])
    errors = e3.receipt_errors(
        receipt,
        expected_delivery_identity=current_identity,
        expected_backend_identity=current_backend,
    )
    if errors:
        return _report(errors)
    # stage 与当前 qualification 的一致性
    stage = receipt.get("stage")
    if stage in ("U2_PASS", "U2_FAIL") and reason != "qualified":
        return _report(
            [f"current backend unavailable ({reason}); U2 receipt not attestable"],
        )
    if stage == "NEEDS_017_SEATBELT_BACKEND" and reason == "qualified":
        return _report(["backend currently qualified; blocked receipt is stale"])
    if stage == "NEEDS_017_SEATBELT_BACKEND":
        blocked = receipt.get("blocked", {})
        if blocked.get("reason_code") != reason:
            return _report(
                [f"blocked reason {blocked.get('reason_code')!r} != current {reason!r}"],
            )
        print(
            "017 detached E3 attestation ok: blocked shape binds current "
            "delivery identity with closed preconditions "
            "(NEEDS_017_SEATBELT_BACKEND stage=U2)"
        )
    else:
        print(
            "017 detached E3 attestation ok: 3 real attempts × 11 journeys "
            "bind the current delivery + backend identity"
        )
    return 0


def materialize_tree(entries: list[dict], repo_root: Path, dest: Path) -> list[str]:
    with _inherited_controls():
        return inherited.materialize_tree(entries, repo_root, dest)


def build_materialized_wheel(
    tree: Path,
    wheel_dir: Path,
    *,
    python: str | None = None,
) -> tuple[Path | None, str]:
    """从同一 materialized tree 构建 deterministic wheel，不写入 source tree。"""

    wheel_dir.mkdir(parents=True, exist_ok=False)
    build_source = wheel_dir.with_name(f"{wheel_dir.name}-source")
    shutil.copytree(tree, build_source)
    built = subprocess.run(
        [
            python or sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(build_source),
        ],
        cwd=str(wheel_dir.parent),
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            **os.environ,
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
        },
    )
    if built.returncode != 0:
        return None, (built.stdout + built.stderr)[-1000:]
    wheels = tuple(wheel_dir.glob("first_agent-1.0.0-*.whl"))
    if len(wheels) != 1:
        return None, "materialized wheel was not produced exactly once"
    return wheels[0], ""


def _clean_test_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    return inherited._clean_test_environment(home, site_dir, tree)


def attach_verified_test_dependencies(site_dir: Path, host_site: Path) -> Path:
    """让 clean test interpreter 及其空环境子进程读取已验证的 dev dependencies。"""

    bridge = site_dir / "_017_verified_test_dependencies.pth"
    bridge.write_text(str(host_site.resolve()) + "\n", encoding="utf-8")
    return bridge


def materialized_pytest_argv(
    clean_python: str,
    tree: Path,
    *,
    loopback_controls: bool,
) -> list[str]:
    base = [clean_python, "-m", "pytest", "-q", "-rx", "-ra"]
    test_root = tree / "tests"
    expression = (
        MATERIALIZED_LOOPBACK_MARKER
        if loopback_controls
        else f"not {MATERIALIZED_LOOPBACK_MARKER}"
    )
    return [*base, str(test_root), "-m", expression]


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    """materialized tree → wheel → clean venv → 离线（deny-network）完整 gate。"""

    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    with tempfile.TemporaryDirectory(prefix="017-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            return _report(errors)
        prefix = Path(tempfile.mkdtemp(prefix="017-prefix-"))
        home = Path(tempfile.mkdtemp(prefix="017-home-")).resolve()
        wheel_dir = Path(tempfile.mkdtemp(prefix="017-wheel-parent-")) / "wheel"
        try:
            created = subprocess.run(
                [py, "-m", "venv", str(prefix)],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if created.returncode != 0:
                return _report([f"clean venv: {(created.stdout + created.stderr)[-1000:]}"])
            configuration = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
            if "include-system-site-packages = false" not in configuration:
                return _report(["clean venv inherited system site-packages"])
            clean_python = str(prefix / "bin" / "python")
            wheel, build_error = build_materialized_wheel(tree, wheel_dir, python=py)
            if wheel is None:
                return _report([f"materialized wheel: {build_error}"])
            wheel_digest = _sha256(wheel)
            installed = subprocess.run(
                [
                    clean_python,
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--force-reinstall",
                    str(wheel),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if installed.returncode != 0:
                return _report(
                    [f"clean base install: {(installed.stdout + installed.stderr)[-1000:]}"]
                )
            optional_probe = subprocess.run(
                [
                    clean_python,
                    "-c",
                    (
                        "import importlib.util; "
                        "assert all(importlib.util.find_spec(name) is None "
                        "for name in ('yaml', 'mcp', 'textual'))"
                    ),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if optional_probe.returncode != 0:
                return _report(["base install pulled optional product dependencies"])
            uv = shutil.which("uv")
            if uv is None:
                return _report(["offline base dependency installer unavailable"])
            base_dependencies = subprocess.run(
                [
                    uv,
                    "pip",
                    "install",
                    "--offline",
                    "--python",
                    clean_python,
                    "httpx>=0.27.1",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if base_dependencies.returncode != 0:
                return _report(
                    [
                        "offline base dependency install: "
                        + (base_dependencies.stdout + base_dependencies.stderr)[-1000:]
                    ]
                )
            ok, message = assert_origin(prefix, repo_root, python=clean_python)
            if not ok:
                return _report([message])
            ok, message = assert_console_entrypoint_origin(
                prefix, repo_root, python=clean_python,
            )
            if not ok:
                return _report([message])
            profile = build_sandbox_profile(extra_writable=(prefix, tree, home))
            denied, message = deny_network_preflight(profile, python=clean_python)
            if not denied:
                return _report([message])
            site_dir = _site_packages_dir(prefix, clean_python)
            test_env = _clean_test_environment(home, site_dir, tree)
            # dev-only test tooling来自当前已验证 source venv。先完成 optional
            # dependency probe，再用显式 .pth 挂到 clean test interpreter；这样
            # MCP 的 env={} 子进程也能导入 SDK，但没有继承父进程环境变量。
            host_site = _site_packages_dir(Path(sys.prefix), py)
            attach_verified_test_dependencies(site_dir, host_site)
            test_env["PYTHONPATH"] = os.pathsep.join(
                (str(site_dir), str(tree)),
            )
            ruff = str(Path(py).parent / "ruff")
            rc, output = run_under_sandbox(
                [ruff, "check", str(tree)],
                profile,
                timeout=300,
                env=test_env,
            )
            if rc != 0:
                return _report([f"materialized ruff: {output[-2000:]}"])
            neutral = Path(tempfile.mkdtemp(prefix="017-neutral-"))
            try:
                rc, output = run_under_sandbox(
                    materialized_pytest_argv(
                        clean_python,
                        tree,
                        loopback_controls=False,
                    ),
                    profile,
                    timeout=1800,
                    env=test_env,
                    cwd=neutral,
                )
            finally:
                shutil.rmtree(neutral, ignore_errors=True)
            if rc != 0:
                failed = [
                    line.strip()
                    for line in output.splitlines()
                    if line.strip().startswith("FAILED")
                ]
                return _report(
                    [
                        f"materialized pytest: {output[-4000:]}",
                        "017_CONTENT_FAILED_TESTS: "
                        + (" | ".join(failed) if failed else "(see tail)"),
                    ]
                )
            summary = output.strip().splitlines()[-1] if output.strip() else "no output"
            loopback_neutral = Path(tempfile.mkdtemp(prefix="017-loopback-neutral-"))
            try:
                loopback = subprocess.run(
                    materialized_pytest_argv(
                        clean_python,
                        tree,
                        loopback_controls=True,
                    ),
                    cwd=str(loopback_neutral),
                    env=test_env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            finally:
                shutil.rmtree(loopback_neutral, ignore_errors=True)
            if loopback.returncode != 0:
                return _report(
                    [
                        "materialized loopback controls: "
                        + (loopback.stdout + loopback.stderr)[-4000:]
                    ]
                )
            loopback_summary = (
                (loopback.stdout + loopback.stderr).strip().splitlines()[-1]
                if (loopback.stdout + loopback.stderr).strip()
                else "no output"
            )
            print(
                "017 content gate: deny-network pytest passed "
                f"({summary}); bounded loopback controls passed ({loopback_summary})"
            )
        finally:
            shutil.rmtree(prefix, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
            shutil.rmtree(wheel_dir.parent, ignore_errors=True)
    # 只有全部检查通过才落盘 wheel artifact（E3 14–16 的 wheel digest 绑定源；
    # 记录 gate 时的 overlay root，attestation 与当前 seal 交叉核对）。
    (REPO / WHEEL_ARTIFACT_REL).write_text(
        json.dumps(
            {
                "wheel_sha256": wheel_digest,
                "overlay_root_sha256": _load_json(SEAL_PATH)["overlay_root_sha256"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("017 content gate: ALL CHECKS PASSED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    group.add_argument("--control-seal", action="store_true")
    group.add_argument("--attestation", action="store_true")
    args = parser.parse_args(argv)
    if args.check_membership:
        return check_membership()
    if args.content:
        return run_content_gate()
    if args.control_seal:
        return check_control_seal()
    if args.attestation:
        return check_attestation()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
