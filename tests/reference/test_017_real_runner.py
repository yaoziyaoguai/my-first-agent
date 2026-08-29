"""017 native E3 real-runner 合同（audit T8）。

Receipt closed schema mutation、stage 一致性，以及 11 条 journey 的
non-vacuous control mutation（control 失败 → journey False；confined
被模拟为「未真正约束」→ denial journey False）。focused 集不跑真实
sandbox-exec——真实三连由 T9 一次执行。
"""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from scripts import run_017_e3 as runner
from scripts import verify_017_materialized_tree as verifier
from scripts.run_017_e3 import JourneyHarness

_DEFAULT_BACKEND = object()


def _loopback_listener_supported() -> bool:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
    except PermissionError:
        return False
    finally:
        listener.close()
    return True


_LOOPBACK_LISTENER_SUPPORTED = _loopback_listener_supported()
_LOOPBACK_REQUIRED = pytest.mark.skipif(
    not _LOOPBACK_LISTENER_SUPPORTED,
    reason="verification host forbids local listener creation",
)


def _delivery() -> dict:
    return {key: "0" * 64 for key in runner.IDENTITY_KEYS}


def _backend() -> dict:
    return {
        "executable_path": "/usr/bin/sandbox-exec",
        "platform_system": "Darwin",
        "platform_release": "24.5.0",
        "functional_probe_digest": "a" * 64,
        "probe_profile_digest": "b" * 64,
        "backend_identity_digest": "c" * 64,
    }


def _blocked_receipt() -> dict:
    return {
        "schema": runner.SCHEMA,
        "observed_at": "2026-08-27T00:00:00Z",
        "stage": "NEEDS_017_SEATBELT_BACKEND",
        "delivery_identity": _delivery(),
        "blocked": {
            "reason_code": "sandbox_exec_missing",
            "qualification": {"reason_code": "sandbox_exec_missing"},
            "missing_owner_action": "restore sandbox-exec",
        },
        "closed_preconditions": {
            "source_gates": True, "materialized_gates": True,
        },
        "attempts": [],
    }


def _u2_receipt(stage: str = "U2_PASS") -> dict:
    return {
        "schema": runner.SCHEMA,
        "observed_at": "2026-08-27T00:00:00Z",
        "stage": stage,
        "delivery_identity": _delivery(),
        "backend_identity": _backend(),
        "attempts": [
            {
                "attempt_id": f"attempt-{i}",
                "wheel_sha256": "0" * 64,
                "workspace_root_sha256": f"{i}" * 64,
                "temp_root_sha256": f"{i + 3}" * 64,
                "sentinel_sha256": f"{i + 6}" * 64,
                "attempt_record_sha256": f"{i + 9:x}" * 64,
                "journeys": {
                    name: stage == "U2_PASS" for name in runner.JOURNEY_NAMES
                },
            }
            for i in (1, 2, 3)
        ],
    }


def _errors(  # noqa: ANN001, ANN202
    receipt: dict,
    backend: dict | None | object = _DEFAULT_BACKEND,
):
    return runner.receipt_errors(
        receipt,
        expected_delivery_identity=_delivery(),
        expected_backend_identity=(
            _backend() if backend is _DEFAULT_BACKEND else backend
        ),
    )


# --------------------------------------------------------------------------- #
# Step 1: receipt/verifier mutation Reds（closed schema）
# --------------------------------------------------------------------------- #


def test_baseline_receipts_validate() -> None:
    assert _errors(_blocked_receipt()) == []
    assert _errors(_u2_receipt()) == []


def test_old_docker_fields_are_rejected() -> None:
    receipt = _blocked_receipt()
    receipt["environment_identity"] = {"docker_context": "colima"}
    assert _errors(receipt)

    u2 = _u2_receipt()
    u2["attempts"][0]["image_digest"] = "sha256:" + "9" * 64
    assert _errors(u2)


def test_missing_extra_keys_wrong_digests_rejected() -> None:
    extra = _blocked_receipt()
    extra["extra"] = True
    assert _errors(extra)

    missing = _u2_receipt()
    del missing["backend_identity"]
    assert _errors(missing)

    drift = _u2_receipt()
    drift["delivery_identity"]["wheel_sha256"] = "1" * 64
    assert _errors(drift)

    backend_drift = _u2_receipt()
    backend_drift["backend_identity"]["platform_release"] = "23.0.0"
    assert _errors(backend_drift)

    runner_drift = _u2_receipt()
    runner_drift["delivery_identity"]["runner_sha256"] = "2" * 64
    assert _errors(runner_drift)


def test_delivery_identity_schema_binds_detached_runner() -> None:
    assert "runner_sha256" in runner.IDENTITY_KEYS


def test_attempts_must_be_three_frozen_ids_with_bool_journeys() -> None:
    wrong_ids = _u2_receipt()
    wrong_ids["attempts"][0]["attempt_id"] = "attempt-9"
    assert _errors(wrong_ids)

    non_bool = _u2_receipt()
    non_bool["attempts"][0]["journeys"]["host_toolchain_works"] = "yes"
    assert _errors(non_bool)

    extra_journey = _u2_receipt()
    extra_journey["attempts"][0]["journeys"]["container_escape"] = True
    assert _errors(extra_journey)


@pytest.mark.parametrize(
    "field",
    ("workspace_root_sha256", "temp_root_sha256", "sentinel_sha256"),
)
def test_attempt_roots_and_sentinels_must_be_unique(field: str) -> None:
    receipt = _u2_receipt()
    receipt["attempts"][1][field] = receipt["attempts"][0][field]
    assert _errors(receipt)


def test_attempt_roots_are_canonical_before_policy_build(tmp_path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    roots = runner.attempt_roots(alias_parent / "attempt")

    assert all(path == path.resolve() for path in roots.values())


def test_attempt_wheel_and_record_digests_are_closed() -> None:
    wrong_wheel = _u2_receipt()
    wrong_wheel["attempts"][0]["wheel_sha256"] = "f" * 64
    assert _errors(wrong_wheel)

    missing_record = _u2_receipt()
    del missing_record["attempts"][0]["attempt_record_sha256"]
    assert _errors(missing_record)


def test_failed_attempt_record_cannot_be_overwritten(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runner, "JOURNEYS", (lambda _h: False,))
    monkeypatch.setattr(runner, "JOURNEY_NAMES", ("failed_journey",))
    attempt_root = tmp_path / "attempt-1"

    first = runner.run_attempt(
        "attempt-1", attempt_root, wheel_sha256="0" * 64,
    )
    journal = attempt_root / runner.ATTEMPT_RECORD_NAME
    original = journal.read_bytes()
    assert first["journeys"] == {"failed_journey": False}

    with pytest.raises(FileExistsError):
        runner.run_attempt(
            "attempt-1", attempt_root, wheel_sha256="0" * 64,
        )
    assert journal.read_bytes() == original
    assert json.loads(original)["journeys"] == {"failed_journey": False}


def test_materialized_wheel_build_is_deterministic_and_does_not_mutate_tree(
    tmp_path,
) -> None:
    tree = tmp_path / "tree"
    package = tree / "agent"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tree / "main.py").write_text("def main(): return 0\n", encoding="utf-8")
    (tree / "README.md").write_text("fixture\n", encoding="utf-8")
    (tree / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"
[project]
name = "first-agent"
version = "1.0.0"
description = "fixture"
readme = "README.md"
requires-python = ">=3.11"
[tool.setuptools]
py-modules = ["main"]
[tool.setuptools.packages.find]
include = ["agent"]
""",
        encoding="utf-8",
    )
    before = runner._materialized_tree_digest(tree)
    first, first_error = verifier.build_materialized_wheel(
        tree, tmp_path / "wheel-1",
    )
    second, second_error = verifier.build_materialized_wheel(
        tree, tmp_path / "wheel-2",
    )
    assert first is not None, first_error
    assert second is not None, second_error
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(
        second.read_bytes(),
    ).hexdigest()
    assert runner._materialized_tree_digest(tree) == before


def test_materialized_test_dependency_bridge_is_explicit(tmp_path) -> None:
    site_dir = tmp_path / "clean-site"
    host_site = tmp_path / "verified-host-site"
    site_dir.mkdir()
    host_site.mkdir()

    bridge = verifier.attach_verified_test_dependencies(site_dir, host_site)

    assert bridge.parent == site_dir
    assert bridge.read_text(encoding="utf-8") == str(host_site.resolve()) + "\n"


def test_materialized_loopback_controls_are_partitioned_from_deny_network(
    tmp_path,
) -> None:
    tree = tmp_path / "tree"
    denied = verifier.materialized_pytest_argv(
        "/clean/python",
        tree,
        loopback_controls=False,
    )
    loopback = verifier.materialized_pytest_argv(
        "/clean/python",
        tree,
        loopback_controls=True,
    )
    assert denied[-3:] == [
        str(tree / "tests"),
        "-m",
        "not materialized_loopback",
    ]
    assert loopback[-3:] == [
        str(tree / "tests"),
        "-m",
        "materialized_loopback",
    ]


def test_u2_pass_all_true_u2_fail_at_least_one_false() -> None:
    assert _errors(_u2_receipt("U2_PASS")) == []
    fail = _u2_receipt("U2_FAIL")
    assert _errors(fail) == []
    all_true_fail = _u2_receipt("U2_FAIL")
    for attempt in all_true_fail["attempts"]:
        for name in attempt["journeys"]:
            attempt["journeys"][name] = True
    assert _errors(all_true_fail)


def test_blocked_shape_is_closed() -> None:
    qualified_blocked = _blocked_receipt()
    qualified_blocked["blocked"]["reason_code"] = "qualified"
    assert _errors(qualified_blocked)

    unclosed_reason = _blocked_receipt()
    unclosed_reason["blocked"]["reason_code"] = "docker_daemon_unavailable"
    assert _errors(unclosed_reason)

    with_attempts = _blocked_receipt()
    with_attempts["attempts"] = [{"attempt_id": "attempt-1"}]
    assert _errors(with_attempts)

    open_qualification = _blocked_receipt()
    open_qualification["blocked"]["qualification"]["docker_context"] = "legacy"
    assert _errors(open_qualification)

    mismatched_qualification = _blocked_receipt()
    mismatched_qualification["blocked"]["qualification"]["reason_code"] = (
        "functional_probe_failed"
    )
    assert _errors(mismatched_qualification)


def test_u2_with_unavailable_current_backend_not_attestable() -> None:
    assert _errors(_u2_receipt(), backend=None)


def test_forbidden_needles_rejected() -> None:
    leaked = _u2_receipt()
    leaked["attempts"][0]["attempt_id"] = "/Users/leak"
    assert _errors(leaked)


# --------------------------------------------------------------------------- #
# Step 2: non-vacuous journey control mutations
# --------------------------------------------------------------------------- #


class BrokenControlHarness(JourneyHarness):
    """control 全部失败——任何依赖 control 前提的 journey 必须 False。"""

    def control(self, argv, *, cwd=None):  # noqa: ANN001, ANN202
        from scripts.run_017_e3 import _ControlResult
        self.control_calls.append({"argv": list(argv), "cwd": cwd})
        return _ControlResult(1, "")


class UnconfiningHarness(JourneyHarness):
    """confined 通道实际不约束（等价 control）——denial journeys 必须 False。"""

    def confined(self, argv, **kwargs):  # noqa: ANN003, ANN202
        from types import SimpleNamespace

        control = self.control(argv)
        return SimpleNamespace(exit_code=control.returncode)


def _roots(tmp_path: Path) -> dict:
    roots = {}
    for name in ("workspace", "temp", "state", "home", "outside"):
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        roots[name] = path
    return roots


_CONTROL_GATED_JOURNEYS = (
    ("host_toolchain", runner.journey_host_toolchain_works),
    ("git_metadata", runner.journey_git_metadata_readable_write_denied),
    ("outside_write", runner.journey_outside_write_denied),
    ("credential_sentinel", runner.journey_credential_sentinel_unreadable),
    pytest.param(
        "network_off",
        runner.journey_network_off_denied,
        marks=(pytest.mark.materialized_loopback, _LOOPBACK_REQUIRED),
    ),
    ("process_tree", runner.journey_process_tree_inheritance),
)


@pytest.mark.parametrize(("name", "journey"), _CONTROL_GATED_JOURNEYS)
def test_control_failure_makes_journey_fail(tmp_path, name, journey):  # noqa: ANN001
    harness = BrokenControlHarness(_roots(tmp_path))
    assert journey(harness) is False, name


_DENIAL_JOURNEYS = (
    ("git_metadata_write", runner.journey_git_metadata_readable_write_denied),
    ("outside_write", runner.journey_outside_write_denied),
    ("credential_sentinel", runner.journey_credential_sentinel_unreadable),
    pytest.param(
        "network_off",
        runner.journey_network_off_denied,
        marks=(pytest.mark.materialized_loopback, _LOOPBACK_REQUIRED),
    ),
    ("process_tree", runner.journey_process_tree_inheritance),
)


@pytest.mark.parametrize(("name", "journey"), _DENIAL_JOURNEYS)
def test_unconfining_harness_makes_denial_journeys_fail(tmp_path, name, journey):  # noqa: ANN001
    harness = UnconfiningHarness(_roots(tmp_path))
    assert journey(harness) is False, name


def test_workspace_write_succeeds_with_unconfining_harness(tmp_path):
    # 正向 journey 在「未约束」通道下也应通过（写 workspace 本来就允许）
    harness = UnconfiningHarness(_roots(tmp_path))
    assert runner.journey_workspace_write_succeeds(harness) is True


def _readback_result():
    from types import SimpleNamespace

    return SimpleNamespace(
        is_error=False,
        metadata={
            "sandbox_receipt_kind": "native_sandbox_v1",
            "receipt_digest": "a" * 64,
            "sandbox_receipt": {
                "outcome": "exited",
                "enforcement": "confined",
                "backend": "seatbelt",
            },
        },
    )


def test_read_back_requires_receipt_and_host_digest(tmp_path, monkeypatch):
    harness = UnconfiningHarness(_roots(tmp_path))
    target = harness.roots["workspace"] / "artifact.txt"

    def good(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        target.write_text("read-back-ok", encoding="utf-8")
        return _readback_result()

    monkeypatch.setattr(runner, "_invoke_with_exact_sandbox_approval", good)
    assert runner.journey_read_back_completion(harness) is True

    def no_receipt(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        target.write_text("read-back-ok", encoding="utf-8")
        result = _readback_result()
        result.metadata = {}
        return result

    monkeypatch.setattr(runner, "_invoke_with_exact_sandbox_approval", no_receipt)
    assert runner.journey_read_back_completion(harness) is False

    def wrong_content(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        target.write_text("wrong", encoding="utf-8")
        return _readback_result()

    monkeypatch.setattr(runner, "_invoke_with_exact_sandbox_approval", wrong_content)
    assert runner.journey_read_back_completion(harness) is False


@pytest.mark.materialized_loopback
@_LOOPBACK_REQUIRED
def test_network_control_uses_real_connect_exit_status(tmp_path):
    harness = BrokenControlHarness(_roots(tmp_path))
    assert runner.journey_network_off_denied(harness) is False
    argv = harness.control_calls[0]["argv"]
    assert argv[0] == "/usr/bin/nc"
    assert "; echo $?" not in " ".join(argv)


def test_timeout_journey_uses_short_profile() -> None:
    from types import SimpleNamespace

    class _Harness:
        kwargs = None

        def confined(self, _argv, **kwargs):  # noqa: ANN001, ANN202
            self.kwargs = kwargs
            return SimpleNamespace(outcome=SimpleNamespace(value="timed_out_reaped"))

    harness = _Harness()
    assert runner.journey_timeout_cleanup_capped(harness) is True
    assert harness.kwargs["profile"] == "short"


def test_backend_unavailable_journey_uses_known_not_executed(tmp_path) -> None:
    from types import SimpleNamespace

    class _Harness(JourneyHarness):
        def bypass(self, _argv, **_kwargs):  # noqa: ANN001, ANN202
            return SimpleNamespace(exit_code=0)

    roots = runner.attempt_roots(tmp_path / "attempt")
    assert runner.journey_backend_unavailable_confined_zero_execution(
        _Harness(roots),
    ) is True


def test_journey_names_match_functions() -> None:
    assert len(runner.JOURNEYS) == 11
    assert len(runner.JOURNEY_NAMES) == 11
    # frozen 顺序：journey 函数元组与名称元组一一对应（run_attempt zip strict）
    assert all(callable(fn) for fn in runner.JOURNEYS)
