#!/usr/bin/env python3
"""验证 019 portable overlay、materialized wheel 与 U2A attestation。"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path

try:
    from scripts import run_019_core_e3 as e3
    from scripts import verify_018_materialized_tree as inherited
    from scripts.verify_materialized_tree import (
        _is_denied,
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import run_019_core_e3 as e3  # type: ignore[no-redef]
    import verify_018_materialized_tree as inherited  # type: ignore[no-redef]
    from verify_materialized_tree import (  # type: ignore[no-redef]
        _is_denied,
        _site_packages_dir,
        assert_console_entrypoint_origin,
        assert_origin,
    )

REPO = Path(__file__).resolve().parents[1]
BASE_MANIFEST_PATH = REPO / "docs" / "implementation" / "009_DELIVERY_MANIFEST.json"
PARENT_SEAL_PATH = REPO / "docs" / "implementation" / "018_DELIVERY_SEAL.json"
SEAL_PATH = REPO / "docs" / "acceptance" / "019_CORE_SEAL.json"
ATTESTATION_PATH = REPO / "docs" / "acceptance" / "019_CORE_RECEIPT.json"
WHEEL_ARTIFACT_PATH = REPO / "docs" / "acceptance" / "019_CORE_WHEEL.json"
REVIEW_PATH = REPO / "docs" / "acceptance" / "019_CORE_INDEPENDENT_REVIEW.md"
VERIFIER_PATH = REPO / "scripts" / "verify_019_materialized_tree.py"
RUNNER_PATH = REPO / "scripts" / "run_019_core_e3.py"
SCHEMA = "my-first-agent/delivery-overlay-seal/v8"
SEAL_KEYS = frozenset({
    "schema",
    "base_manifest_sha256",
    "parent_seal_sha256",
    "verifier_sha256",
    "entry_count",
    "overlay_root_sha256",
})
CONTROL_PATHS = inherited.CONTROL_PATHS | frozenset({
    "docs/acceptance/019_CORE_SEAL.json",
    "docs/acceptance/019_CORE_RECEIPT.json",
    "docs/acceptance/019_CORE_WHEEL.json",
    "docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_EXECUTION_LOG.md",
    "scripts/verify_019_materialized_tree.py",
    "docs/acceptance/019_MACOS_PROFILE_SEAL.json",
    "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
    "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
    "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
    "scripts/verify_019_macos_materialized_tree.py",
})
DETACHED_MUTABLE_PATHS = frozenset({
    "docs/acceptance/019_CORE_RECEIPT.json",
    "docs/acceptance/019_CORE_WHEEL.json",
    "docs/acceptance/019_CORE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_EXECUTION_LOG.md",
    "docs/acceptance/019_MACOS_PROFILE_RECEIPT.json",
    "docs/acceptance/019_MACOS_PROFILE_WHEEL.json",
    "docs/acceptance/019_MACOS_PROFILE_INDEPENDENT_REVIEW.md",
    "docs/implementation/019_MACOS_PROFILE_EXECUTION_LOG.md",
})
SOURCE_DATE_EPOCH = "315532800"
_BANNED_IMPORT_ROOTS = frozenset({
    "fcntl",
    "playwright",
    "resource",
    "signal",
    "subprocess",
    "winreg",
})
_BANNED_BACKEND_TOKENS = ("launchd", "systemd", "seatbelt", "playwright")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON control {path.name}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON control {path.name}: object required")
    return payload


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
        raise ValueError("duplicate path in derived 019 overlay")
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


def _delivery_identity(repo_root: Path) -> tuple[dict, list[dict]]:
    base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    base_digest = _sha256(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    parent_digest = _sha256(repo_root / PARENT_SEAL_PATH.relative_to(REPO))
    verifier_digest = _sha256(repo_root / VERIFIER_PATH.relative_to(REPO))
    entries = derive_overlay(base, repo_root)
    return (
        {
            "schema": SCHEMA,
            "base_manifest_sha256": base_digest,
            "parent_seal_sha256": parent_digest,
            "verifier_sha256": verifier_digest,
            "entry_count": len(entries),
            "overlay_root_sha256": overlay_root(
                base_digest,
                parent_digest,
                entries,
            ),
        },
        entries,
    )


def validate_delivery(repo_root: Path = REPO) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    try:
        expected, entries = _delivery_identity(repo_root)
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        return [], [f"019 delivery identity unavailable: {error}"]
    if set(seal) != SEAL_KEYS:
        errors.append("019 seal keys must match the strict schema")
    for key, value in expected.items():
        if seal.get(key) != value:
            errors.append(f"019 {key} drift")
    return entries, errors


def _write_json_atomically(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_seal(repo_root: Path = REPO) -> int:
    try:
        identity, _entries = _delivery_identity(repo_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        return _report([f"019 seal unavailable: {error}"])
    _write_json_atomically(repo_root / SEAL_PATH.relative_to(REPO), identity)
    print(
        "019 seal written: "
        f"{identity['entry_count']} entries / {identity['overlay_root_sha256']}"
    )
    return 0


def _report(errors: list[str]) -> int:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    return 1


def check_membership(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print(f"019 overlay membership ok: {len(entries)} exact entries")
    return 0


def check_control_seal(repo_root: Path = REPO) -> int:
    _entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    print("019 control seal ok: 009 manifest + 018 parent + verifier + overlay")
    return 0


def materialize_tree(
    entries: list[dict],
    repo_root: Path,
    destination: Path,
) -> list[str]:
    base = _load_json(repo_root / BASE_MANIFEST_PATH.relative_to(REPO))
    baseline = base.get("baseline_commit")
    if not isinstance(baseline, str) or len(baseline) != 40:
        return ["baseline_commit must be a full 40-char Git SHA"]
    archived = subprocess.run(
        ["git", "archive", "--format=tar", baseline],
        cwd=repo_root,
        check=False,
        capture_output=True,
        timeout=120,
    )
    if archived.returncode != 0:
        return ["git archive baseline failed"]
    destination.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            relative = member.name.rstrip("/")
            if not relative or _is_denied(relative):
                continue
            if relative.startswith("/") or ".." in Path(relative).parts:
                errors.append(f"unsafe baseline archive path: {relative}")
                continue
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                errors.append(f"unsupported baseline archive member: {relative}")
                continue
            source = archive.extractfile(member)
            if source is None:
                errors.append(f"baseline archive member unreadable: {relative}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    # ``entries`` 是当前树相对 009 candidate 的 delta，不是相对 Git baseline
    # 的完整清单。先应用 009 manifest 中未被本阶段覆盖的文件，才能在完全
    # 只读 ``.git`` 的前提下恢复父阶段已经验收、但本阶段没有再次修改的源码。
    overlay_paths = {entry["path"] for entry in entries}
    for entry in base.get("entries", []):
        relative = entry.get("path")
        operation = entry.get("operation")
        if (
            not isinstance(relative, str)
            or relative in overlay_paths
            or relative in CONTROL_PATHS
            or _is_denied(relative)
        ):
            continue
        target = destination / relative
        if operation == "delete":
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        source = repo_root / relative
        if not source.is_file() or source.is_symlink():
            errors.append(f"009 source unavailable: {relative}")
            continue
        expected_digest = entry.get("sha256")
        if not isinstance(expected_digest, str) or _sha256(source) != expected_digest:
            errors.append(f"009 source digest drift: {relative}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if entry.get("git_mode") == "100755" else 0o644)

    for entry in entries:
        relative = entry["path"]
        target = destination / relative
        if entry["operation"] == "delete":
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        source = repo_root / relative
        if not source.is_file() or source.is_symlink():
            errors.append(f"overlay source unavailable: {relative}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if entry["git_mode"] == "100755" else 0o644)
        if _sha256(target) != entry["sha256"]:
            errors.append(f"materialized digest drift: {relative}")
    controls = {
        control.get("path")
        for control in base.get("control_files", [])
        if isinstance(control, dict)
    }
    controls.update(CONTROL_PATHS)
    for relative in controls:
        if (
            not isinstance(relative, str)
            or relative in DETACHED_MUTABLE_PATHS
        ):
            continue
        source = repo_root / relative
        if source.is_file() and not source.is_symlink() and not _is_denied(relative):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for relative in DETACHED_MUTABLE_PATHS:
        candidate = destination / relative
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
    return errors


def portable_boundary_errors(tree: Path) -> list[str]:
    errors: list[str] = []
    package = tree / "agent" / "automation"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(tree).as_posix()
        source = path.read_text(encoding="utf-8")
        parsed = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(parsed)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(parsed)
            if isinstance(node, ast.ImportFrom)
        }
        for name in sorted(imports & _BANNED_IMPORT_ROOTS):
            errors.append(f"{relative}: concrete backend import {name}")
        folded = source.casefold()
        for token in _BANNED_BACKEND_TOKENS:
            if token in folded:
                errors.append(f"{relative}: concrete backend token {token}")
    return errors


def _wheel_identity(repo_root: Path = REPO) -> dict:
    artifact = _load_json(repo_root / WHEEL_ARTIFACT_PATH.relative_to(REPO))
    expected = {
        "wheel_sha256",
        "materialized_root_sha256",
        "overlay_root_sha256",
        "materialized_full_count",
    }
    if set(artifact) != expected:
        raise ValueError("019 wheel artifact keys must be exact")
    for key in ("wheel_sha256", "materialized_root_sha256", "overlay_root_sha256"):
        if not e3._valid_digest(artifact.get(key)):
            raise ValueError(f"019 wheel artifact {key} must be hex64")
    count = artifact.get("materialized_full_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("019 materialized_full_count must be positive")
    return artifact


def _current_materialized_root(entries: list[dict], repo_root: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="019-attestation-tree-") as tree_name:
        tree = Path(tree_name)
        errors = materialize_tree(entries, repo_root, tree)
        if errors:
            raise ValueError("materialization failed: " + "; ".join(errors))
        return e3._sha256_tree(tree)


def check_attestation(repo_root: Path = REPO) -> int:
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    try:
        seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
        receipt = _load_json(repo_root / ATTESTATION_PATH.relative_to(REPO))
        wheel = _wheel_identity(repo_root)
        materialized_root = _current_materialized_root(entries, repo_root)
        spec_digest, standards_digest = e3._review_section_digests(
            repo_root / REVIEW_PATH.relative_to(REPO)
        )
    except (OSError, ValueError) as error:
        return _report([f"019 U2A attestation unavailable: {error}"])
    errors = e3.validate_receipt(receipt)
    expected = {
        "materialized_root_sha256": materialized_root,
        "seal_sha256": _sha256(repo_root / SEAL_PATH.relative_to(REPO)),
        "verifier_sha256": _sha256(repo_root / VERIFIER_PATH.relative_to(REPO)),
        "runner_sha256": _sha256(repo_root / RUNNER_PATH.relative_to(REPO)),
        "wheel_sha256": wheel["wheel_sha256"],
        "spec_product_review_sha256": spec_digest,
        "standards_architecture_review_sha256": standards_digest,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            errors.append(f"receipt {key} does not match current delivery identity")
    if wheel["materialized_root_sha256"] != materialized_root:
        errors.append("wheel artifact binds a different materialized root")
    if wheel["overlay_root_sha256"] != seal.get("overlay_root_sha256"):
        errors.append("wheel artifact binds a different overlay root")
    gate = receipt.get("materialized_full_gate")
    if isinstance(gate, dict) and gate.get("node_count") != wheel["materialized_full_count"]:
        errors.append("receipt materialized full count does not match content gate")
    errors.extend(portable_boundary_errors(repo_root))
    if errors:
        return _report(errors)
    print("019 detached U2A attestation ok: 3 fresh attempts × 13 journeys + 25 claims")
    return 0


def _clean_environment(home: Path, site_dir: Path, tree: Path) -> dict[str, str]:
    return inherited._clean_environment(home, site_dir, tree)


def _passed_count(output: str) -> int:
    import re

    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    match = re.search(r"(?:^|\s)(\d+) passed(?:,|\s|$)", plain)
    return 0 if match is None else int(match.group(1))


_PYTEST_EVIDENCE_SCHEMA = "my-first-agent/materialized-pytest-evidence/v1"
_PYTEST_EVIDENCE_KEYS = frozenset({
    "schema",
    "collected_node_ids",
    "outcomes",
    "deselected_node_ids",
    "session_completed",
})
# 物化证据只接受 passed 与事前冻结的精确 skipped；failed/xfailed/xpassed
# 不得因汇总数字而被洗白。
_PYTEST_EVIDENCE_OUTCOMES = frozenset({"passed", "skipped"})
_OUTCOME_RECORD_KEYS = frozenset({"node_id", "outcome", "reason"})
_CANDIDATE_REPORT_SCHEMA = "my-first-agent/019-candidate-content-report/v1"
_CANDIDATE_REPORT_KEYS = frozenset({
    "schema",
    "verification_scope",
    "candidate_identity",
    "materialized_root_sha256",
    "test_input_root_sha256",
    "wheel_sha256",
    "verifier_sha256",
    "bootstrap_sha256",
    "collected_node_set_sha256",
    "python_version",
    "test_dependency_versions",
    "pytest_evidence",
    "outcome_summary",
    "skips",
    "evidence_complete",
    "origin_ok",
    "promotion_performed",
    "artifacts_written",
    "chromium",
})
_CANDIDATE_IDENTITY_KEYS = frozenset({
    "base_manifest_sha256",
    "parent_seal_sha256",
    "overlay_root_sha256",
    "entry_count",
})
_CANDIDATE_DIGEST_KEYS = (
    "materialized_root_sha256",
    "test_input_root_sha256",
    "wheel_sha256",
    "verifier_sha256",
    "bootstrap_sha256",
    "collected_node_set_sha256",
)


def pytest_evidence_errors(report: object, approved_skips: dict[str, str]) -> list[str]:
    """校验 wheel-bound pytest 的完整证据；任何缺口都必须显式失败。"""
    if not isinstance(report, dict):
        return ["pytest evidence must be a JSON object"]
    if not isinstance(approved_skips, dict):
        return ["approved_skips must be a mapping"]
    errors: list[str] = []
    if set(report) != _PYTEST_EVIDENCE_KEYS:
        errors.append("pytest evidence keys must match the strict schema")
    if report.get("schema") != _PYTEST_EVIDENCE_SCHEMA:
        errors.append("pytest evidence schema drift")
    if report.get("session_completed") is not True:
        errors.append("pytest session did not complete")
    collected = report.get("collected_node_ids")
    collected_set: set[str] = set()
    if not isinstance(collected, list):
        errors.append("collected_node_ids must be a list")
    elif any(not isinstance(node, str) or not node for node in collected):
        errors.append("collected node ids must be non-empty strings")
    else:
        collected_set = set(collected)
        if len(collected_set) != len(collected):
            errors.append("collected node ids must be unique")
    outcomes = report.get("outcomes")
    if not isinstance(outcomes, list):
        errors.append("outcomes must be a list")
        outcomes = []
    observed: set[str] = set()
    for record in outcomes:
        if not isinstance(record, dict):
            errors.append("outcome records must be objects")
            continue
        if set(record) != _OUTCOME_RECORD_KEYS:
            errors.append("outcome record keys must be exact node_id/outcome/reason")
            continue
        node = record.get("node_id")
        if not isinstance(node, str) or not node:
            errors.append("outcome record node_id must be a non-empty string")
            continue
        if node not in collected_set:
            errors.append(f"outcome for uncollected node: {node}")
            continue
        if node in observed:
            errors.append(f"duplicate terminal outcome for node: {node}")
            continue
        observed.add(node)
        outcome = record.get("outcome")
        if outcome not in _PYTEST_EVIDENCE_OUTCOMES:
            errors.append(f"node {node} terminal outcome is not allowed: {outcome!r}")
            continue
        if outcome == "skipped":
            reason = record.get("reason")
            if not isinstance(reason, str) or not reason:
                errors.append(f"skipped node {node} must carry a reason")
            elif approved_skips.get(node) != reason:
                errors.append(f"skip for node {node} is not exactly pre-approved")
    for node in sorted(collected_set - observed):
        errors.append(f"collected node has no terminal outcome: {node}")
    deselected = report.get("deselected_node_ids")
    if not isinstance(deselected, list):
        errors.append("deselected_node_ids must be a list")
    elif deselected:
        errors.append("materialized evidence must not deselect nodes")
    return errors


def run_wheel_bound_pytest(
    *,
    python: str,
    installed_site: Path,
    test_tree: Path,
    required_modules: tuple[str, ...] | list[str],
) -> dict:
    """wheel-bound pytest 的父进程驱动：guard 子进程内运行 materialized 测试树。

    子进程经 ``scripts/_019_installed_pytest.py`` 先装 installed-site origin
    guard，再以 ``test_tree`` 为测试根运行 pytest；固定产品根只能从
    installed_site 解析，测试树源码副本不得救活来源。返回 pytest 退出码、
    guard 记录的 origin 错误（含模块名与错误码的字符串）与观测到的产品
    模块 origins，供 ``product_origin_errors`` 复核。
    """
    runner_path = Path(__file__).resolve().parent / "_019_installed_pytest.py"
    with tempfile.TemporaryDirectory(prefix="fa-019-wheel-bound-") as temp_dir:
        temp = Path(temp_dir)
        origin_log = temp / "origin-log.jsonl"
        completed = subprocess.run(
            [
                python,
                str(runner_path),
                "--installed-site", str(installed_site),
                "--test-tree", str(test_tree),
                "--report-path", str(temp / "evidence-report.json"),
                "--origin-log", str(origin_log),
                "--basetemp", str(temp / "pytest-basetemp"),
                *(
                    argument
                    for module in required_modules
                    for argument in ("--required-module", module)
                ),
            ],
            cwd=test_tree,
            capture_output=True,
            text=True,
            check=False,
        )
        origin_errors: list[str] = []
        loaded_product_origins: dict[str, str] = {}
        runner_pid: int | None = None
        if origin_log.exists():
            for line in origin_log.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    origin_errors.append(f"origin-log unparseable: {line[:200]}")
                    continue
                if runner_pid is None and isinstance(event.get("pid"), int):
                    runner_pid = event["pid"]
                module = event.get("module")
                origin = event.get("origin")
                if event.get("error") is None:
                    if module and origin:
                        loaded_product_origins[module] = origin
                else:
                    origin_errors.append(f"{module}: {event.get('error')} (origin={origin})")
        return {
            "returncode": completed.returncode,
            "runner_pid": runner_pid,
            "origin_errors": origin_errors,
            "loaded_product_origins": loaded_product_origins,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }


def product_origin_errors(
    loaded_product_origins: object,
    installed_site: Path,
    copied_source_root: Path,
    required_modules: tuple[str, ...],
) -> list[str]:
    """固定产品根模块只能来自 canonical 安装位置；测试树副本或外部来源一律拒绝。"""
    if not isinstance(loaded_product_origins, dict):
        return ["loaded_product_origins must be an object"]
    errors: list[str] = []
    for module in required_modules:
        if module not in loaded_product_origins:
            errors.append(f"product module origin unobserved: {module}")
    names = [
        module
        for module in loaded_product_origins
        if isinstance(module, str) and module
    ]
    if len(names) != len(loaded_product_origins):
        errors.append("loaded_product_origins keys must be module names")
    canonical_site = installed_site.resolve()
    canonical_source = copied_source_root.resolve()
    for module in sorted(names):
        origin = loaded_product_origins[module]
        if not isinstance(origin, str) or not origin:
            errors.append(f"product module origin malformed: {module}")
            continue
        resolved = Path(origin).resolve()
        if resolved.is_relative_to(canonical_site):
            continue
        if resolved.is_relative_to(canonical_source):
            errors.append(f"product module loaded from copied source: {module}")
        else:
            errors.append(f"product module origin is foreign: {module}")
    return errors


def _candidate_summary_errors(report: dict) -> list[str]:
    """outcome_summary 必须逐项重算自 pytest 证据，不得独立美化成数字。"""
    evidence = report.get("pytest_evidence")
    outcomes = evidence.get("outcomes") if isinstance(evidence, dict) else []
    if not isinstance(outcomes, list):
        outcomes = []
    outcome_values = [
        record.get("outcome") for record in outcomes if isinstance(record, dict)
    ]
    deselected = evidence.get("deselected_node_ids") if isinstance(evidence, dict) else None
    expected = {
        "passed": outcome_values.count("passed"),
        "failed": outcome_values.count("failed"),
        "skipped": outcome_values.count("skipped"),
        "deselected": len(deselected) if isinstance(deselected, list) else 0,
    }
    summary = report.get("outcome_summary")
    if (
        not isinstance(summary, dict)
        or set(summary) != set(expected)
        or any(
            isinstance(summary.get(key), bool) or not isinstance(summary.get(key), int)
            for key in expected
        )
    ):
        return ["outcome_summary must be exact passed/failed/skipped/deselected integers"]
    return [
        f"outcome_summary {key} drift"
        for key in expected
        if summary.get(key) != expected[key]
    ]


def _chromium_status_errors(chromium: object) -> list[str]:
    """Chromium 只能如实报告 provided 或 unavailable+reason，不得把缺失改写成资格。"""
    if not isinstance(chromium, dict):
        return ["chromium must be an object"]
    if chromium.get("status") == "provided":
        if set(chromium) != {"status"}:
            return ["provided chromium must carry exactly the status"]
        return []
    if chromium.get("status") == "unavailable":
        reason = chromium.get("reason")
        if (
            set(chromium) != {"status", "reason"}
            or not isinstance(reason, str)
            or not reason
        ):
            return ["unavailable chromium must carry a non-empty reason"]
        return []
    return ["chromium status must be provided or unavailable"]


def candidate_report_errors(
    report: object,
    repo_root: Path,
    report_path: Path,
    *,
    approved_skips: dict[str, str] | None = None,
) -> list[str]:
    """候选报告只证明 candidate 本身：不晋级、不写历史工件、报告留在仓库外。

    skip 批准只能由调用方通过 approved_skips 显式给出；报告内的 skips 仅是
    如实申报，必须与观测到的 skipped 终态精确一致，永不自我授权。
    """
    if not isinstance(report, dict):
        return ["candidate report must be a JSON object"]
    errors: list[str] = []
    if set(report) != _CANDIDATE_REPORT_KEYS:
        errors.append("candidate report keys must match the strict schema")
    if report.get("schema") != _CANDIDATE_REPORT_SCHEMA:
        errors.append("candidate report schema drift")
    if report.get("verification_scope") != "candidate_only":
        errors.append("candidate verification_scope must stay candidate_only")
    identity = report.get("candidate_identity")
    if not isinstance(identity, dict):
        errors.append("candidate_identity must be an object")
    else:
        if set(identity) != _CANDIDATE_IDENTITY_KEYS:
            errors.append("candidate_identity keys must be exact")
        for key in (
            "base_manifest_sha256",
            "parent_seal_sha256",
            "overlay_root_sha256",
        ):
            if not e3._valid_digest(identity.get(key)):
                errors.append(f"candidate_identity {key} must be hex64")
        entry_count = identity.get("entry_count")
        if (
            isinstance(entry_count, bool)
            or not isinstance(entry_count, int)
            or entry_count < 1
        ):
            errors.append("candidate_identity entry_count must be a positive integer")
    for key in _CANDIDATE_DIGEST_KEYS:
        if not e3._valid_digest(report.get(key)):
            errors.append(f"candidate report {key} must be hex64")
    python_version = report.get("python_version")
    if not isinstance(python_version, str) or not python_version:
        errors.append("python_version must be a non-empty string")
    dependency_versions = report.get("test_dependency_versions")
    if not isinstance(dependency_versions, dict) or not all(
        isinstance(name, str)
        and name
        and isinstance(version, str)
        and version
        for name, version in dependency_versions.items()
    ):
        errors.append("test_dependency_versions must map names to versions")
    elif not dependency_versions or not dependency_versions.get("pytest"):
        errors.append("test_dependency_versions must declare a non-empty pytest version")
    # skip 批准只能来自调用方显式给出的 approved_skips；形状损坏时按无批准
    # 处理并显式报错，绝不静默放宽。
    approved: dict[str, str] = {}
    if approved_skips is not None and (
        not isinstance(approved_skips, dict)
        or not all(
            isinstance(node, str)
            and node
            and isinstance(reason, str)
            and reason
            for node, reason in approved_skips.items()
        )
    ):
        errors.append("approved_skips must map non-empty node ids to non-empty reasons")
    elif isinstance(approved_skips, dict):
        approved = approved_skips
    # 报告自带的 skips 只是如实申报：必须与 pytest 证据中观测到的 skipped
    # 终态精确一致，但永远不构成批准。
    evidence = report.get("pytest_evidence")
    outcomes = evidence.get("outcomes") if isinstance(evidence, dict) else None
    observed_skips: dict[str, object] = {}
    if isinstance(outcomes, list):
        for record in outcomes:
            if (
                isinstance(record, dict)
                and record.get("outcome") == "skipped"
                and isinstance(record.get("node_id"), str)
                and record.get("node_id")
            ):
                observed_skips[record["node_id"]] = record.get("reason")
    skips = report.get("skips")
    declared: dict[str, str] = {}
    if not isinstance(skips, list):
        errors.append("skips must be a list of exact node_id+reason entries")
    else:
        for item in skips:
            if (
                not isinstance(item, dict)
                or set(item) != {"node_id", "reason"}
                or not isinstance(item.get("node_id"), str)
                or not item.get("node_id")
                or not isinstance(item.get("reason"), str)
                or not item.get("reason")
            ):
                errors.append("skip entries must be exact node_id+reason objects")
                continue
            declared[item["node_id"]] = item["reason"]
        if declared != observed_skips:
            errors.append("report skips must exactly match observed skipped outcomes")
    errors.extend(
        pytest_evidence_errors(report.get("pytest_evidence"), approved_skips=approved)
    )
    errors.extend(_candidate_summary_errors(report))
    if report.get("evidence_complete") is not True:
        errors.append("candidate evidence must be complete")
    if report.get("origin_ok") is not True:
        errors.append("candidate product origin must be verified")
    if report.get("promotion_performed") is not False:
        errors.append("candidate verification must not promote the delivery")
    artifacts_written = report.get("artifacts_written")
    if not isinstance(artifacts_written, list) or artifacts_written:
        errors.append("candidate verification must not write delivery artifacts")
    errors.extend(_chromium_status_errors(report.get("chromium")))
    if Path(report_path).resolve().is_relative_to(Path(repo_root).resolve()):
        errors.append("candidate report must stay detached from the repository")
    return errors


def _verified_playwright_browsers_root(python: str) -> Path:
    """从已挂载的 Playwright 取得精确 browser bundle root，不继承用户 HOME。"""

    probe = subprocess.run(
        [
            python,
            "-c",
            (
                "from playwright.sync_api import sync_playwright; "
                "p=sync_playwright().start(); "
                "print(p.chromium.executable_path); p.stop()"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = probe.stdout.strip().splitlines()
    if probe.returncode != 0 or len(lines) != 1:
        raise ValueError("verified Playwright browser probe failed")
    executable = Path(lines[0]).resolve(strict=True)
    for candidate in executable.parents:
        family, separator, revision = candidate.name.rpartition("-")
        if (
            separator
            and family in {"chromium", "chromium_headless_shell"}
            and revision.isdigit()
        ):
            return candidate.parent.resolve(strict=True)
    raise ValueError("verified Playwright browser root is not canonical")


def run_content_gate(repo_root: Path = REPO, *, python: str | None = None) -> int:
    py = python or sys.executable
    entries, errors = validate_delivery(repo_root)
    if errors:
        return _report(errors)
    seal = _load_json(repo_root / SEAL_PATH.relative_to(REPO))
    bundle = Path(tempfile.gettempdir()).resolve() / (
        f"my-first-agent-019-{seal['overlay_root_sha256'][:12]}"
    )
    if bundle.exists():
        shutil.rmtree(bundle)
    tree = bundle / "tree"
    wheel_dir = bundle / "wheel"
    prefix = bundle / "venv"
    home = bundle / "home"
    bundle.mkdir(parents=True, mode=0o700)
    home.mkdir(mode=0o700)
    errors = materialize_tree(entries, repo_root, tree)
    errors.extend(portable_boundary_errors(tree))
    if errors:
        return _report(errors)
    materialized_root = e3._sha256_tree(tree)
    created = subprocess.run(
        [py, "-m", "venv", str(prefix)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if created.returncode != 0:
        return _report(["clean venv: " + (created.stdout + created.stderr)[-1000:]])
    clean_python = str(prefix / "bin" / "python")
    wheel, build_error = inherited.inherited.build_materialized_wheel(
        tree,
        wheel_dir,
        python=py,
    )
    if wheel is None:
        return _report([f"materialized wheel: {build_error}"])
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
        return _report(["clean install: " + (installed.stdout + installed.stderr)[-1000:]])
    # origin check 会 import ``main``；先挂载已验证依赖，仍由后续检查保证
    # ``main`` / ``agent`` 自身只能来自新安装的 materialized wheel。
    site_dir = _site_packages_dir(prefix, clean_python)
    host_site = _site_packages_dir(Path(sys.prefix), py)
    inherited.inherited.attach_verified_test_dependencies(site_dir, host_site)
    try:
        playwright_browsers_root = _verified_playwright_browsers_root(clean_python)
    except (OSError, ValueError, subprocess.SubprocessError):
        return _report(["materialized browser dependency is unavailable"])
    ok, message = assert_origin(prefix, repo_root, python=clean_python)
    if not ok:
        return _report([message])
    ok, message = assert_console_entrypoint_origin(
        prefix,
        repo_root,
        python=clean_python,
        entrypoints=(
            ("first-agent", "main", "main"),
            ("first-agent-schedule", "agent.automation.cli", "main"),
        ),
    )
    if not ok:
        return _report([message])
    test_tree = bundle / "test-tree"
    shutil.copytree(tree, test_tree)
    test_env = _clean_environment(home, site_dir, test_tree)
    test_env["PYTHONPATH"] = os.pathsep.join((str(site_dir), str(test_tree)))
    test_env["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright_browsers_root)
    ruff = str(Path(py).parent / "ruff")
    ruff_result = subprocess.run(
        [ruff, "check", "--no-cache", str(test_tree)],
        cwd=test_tree,
        env=test_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if ruff_result.returncode != 0:
        return _report(["materialized ruff: " + (ruff_result.stdout + ruff_result.stderr)[-2000:]])
    tests = subprocess.run(
        [
            clean_python,
            "-m",
            "pytest",
            "-q",
            "-rx",
            "--color=no",
            str(test_tree / "tests"),
        ],
        cwd=test_tree,
        env=test_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if tests.returncode != 0:
        return _report(["materialized pytest: " + (tests.stdout + tests.stderr)[-5000:]])
    count = _passed_count(tests.stdout)
    if count < 1:
        return _report(["materialized pytest count is unavailable"])
    if e3._sha256_tree(tree) != materialized_root:
        return _report(["receipt-bound materialized source mutated during content gate"])
    _write_json_atomically(
        repo_root / WHEEL_ARTIFACT_PATH.relative_to(REPO),
        {
            "wheel_sha256": _sha256(wheel),
            "materialized_root_sha256": materialized_root,
            "overlay_root_sha256": seal["overlay_root_sha256"],
            "materialized_full_count": count,
        },
    )
    print(f"019 content gate passed: {count} tests")
    print(f"019 materialized bundle: {bundle}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seal", action="store_true")
    group.add_argument("--check-membership", action="store_true")
    group.add_argument("--content", action="store_true")
    group.add_argument("--control-seal", action="store_true")
    group.add_argument("--attestation", action="store_true")
    args = parser.parse_args(argv)
    if args.seal:
        return write_seal()
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
