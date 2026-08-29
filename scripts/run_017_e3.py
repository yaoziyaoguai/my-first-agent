#!/usr/bin/env python3
"""017 native sandbox E3 runner（frozen acceptance 执行器）。

顺序（frozen E3）：offline 前置（diff-check/ruff/full suite）→ materialized
content gate（verifier --content）→ backend qualification（真实 Seatbelt 探测）
→ 三连真实 attempt（11 条 non-vacuous journey/attempt）→ attestation。

backend 不可用且为唯一 confined-journey 缺口时输出
``NEEDS_017_SEATBELT_BACKEND(stage=U2)``；不安装/启动/修改系统配置；不降级。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECEIPT_PATH = (
    REPO / "docs" / "acceptance"
    / "017_SANDBOXED_WORKSPACE_EXECUTION_E3_RECEIPTS.json"
)
VERIFY = REPO / "scripts" / "verify_017_materialized_tree.py"
PYTHON = sys.executable
RUFF = REPO / ".venv" / "bin" / "ruff"

SCHEMA = "first-agent-017-native-e3-receipt-v1"
IDENTITY_KEYS = (
    "seal_sha256", "entry_count", "overlay_root_sha256",
    "verifier_sha256", "runner_sha256", "wheel_sha256",
)
BACKEND_KEYS = (
    "executable_path", "platform_system", "platform_release",
    "functional_probe_digest", "probe_profile_digest",
    "backend_identity_digest",
)
QUALIFICATION_REASONS = frozenset(
    {"qualified", "unsupported_platform", "sandbox_exec_missing",
     "seatbelt_profile_refused", "functional_probe_failed"},
)
BLOCKED_REASON_KEYS = frozenset(
    {"reason_code", "qualification", "missing_owner_action"},
)
CLOSED_PRECONDITIONS = (
    "source_gates", "materialized_gates",
)
# frozen E3 §12 的 11 条 journey（顺序即文档编号）
JOURNEY_NAMES = (
    "host_toolchain_works",
    "git_metadata_readable_write_denied",
    "workspace_write_succeeds",
    "outside_write_denied",
    "credential_sentinel_unreadable",
    "network_off_denied",
    "process_tree_inheritance",
    "timeout_cleanup_capped",
    "backend_unavailable_confined_zero_execution",
    "bypass_authority_exact",
    "read_back_completion",
)
FROZEN_ATTEMPT_IDS = ("attempt-1", "attempt-2", "attempt-3")
ATTEMPT_IDENTITY_KEYS = (
    "wheel_sha256",
    "workspace_root_sha256",
    "temp_root_sha256",
    "sentinel_sha256",
    "attempt_record_sha256",
)
ATTEMPT_RECORD_NAME = "attempt-result.json"
_FORBIDDEN_NEEDLES = ("/Users/", str(Path.home()), "API_KEY=", "\n")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OBSERVED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_INSTALLED_PRODUCT_ONLY = False


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run(argv: list[str], *, timeout: int, cwd: Path = REPO) -> subprocess.CompletedProcess:  # noqa: ANN202
    return subprocess.run(
        argv, cwd=str(cwd), check=False, timeout=timeout,
        capture_output=True, text=True,
    )


def _admit_live_product_import() -> None:
    """父 runner 可审计 live qualification；materialized child 只准用 wheel。"""

    if not _INSTALLED_PRODUCT_ONLY:
        sys.path.insert(0, str(REPO))


# --------------------------------------------------------------------------- #
# delivery / backend identity
# --------------------------------------------------------------------------- #


def delivery_identity(repo_root: Path = REPO) -> dict[str, object]:
    sys.path.insert(0, str(repo_root / "scripts"))
    import verify_017_materialized_tree as verifier  # type: ignore[import-not-found]

    entries, errors = verifier.validate_delivery(repo_root)
    if errors:
        raise ValueError("; ".join(errors))
    seal_bytes = (repo_root / "docs/implementation/017_DELIVERY_SEAL.json").read_bytes()
    wheel = verifier.materialized_wheel_identity(repo_root)
    return {
        "seal_sha256": hashlib.sha256(seal_bytes).hexdigest(),
        "entry_count": len(entries),
        "overlay_root_sha256": json.loads(seal_bytes)["overlay_root_sha256"],
        "verifier_sha256": hashlib.sha256(
            (repo_root / "scripts/verify_017_materialized_tree.py").read_bytes(),
        ).hexdigest(),
        "runner_sha256": hashlib.sha256(
            (repo_root / "scripts/run_017_e3.py").read_bytes(),
        ).hexdigest(),
        "wheel_sha256": wheel["wheel_sha256"],
    }


def backend_identity() -> dict[str, object] | None:
    _admit_live_product_import()
    from agent.sandbox.seatbelt import SeatbeltConfiner

    report = SeatbeltConfiner().qualify()
    if not report.available or report.backend_identity is None:
        return None
    identity = report.backend_identity
    return {
        "executable_path": identity.executable_path,
        "platform_system": identity.platform_system,
        "platform_release": identity.platform_release,
        "functional_probe_digest": identity.functional_probe_digest,
        "probe_profile_digest": identity.probe_profile_digest,
        "backend_identity_digest": identity.backend_identity_digest,
    }


def qualification_reason() -> str:
    _admit_live_product_import()
    from agent.sandbox.seatbelt import SeatbeltConfiner

    return SeatbeltConfiner().qualify().reason_code


# --------------------------------------------------------------------------- #
# receipt validation（closed schema）
# --------------------------------------------------------------------------- #


def receipt_errors(
    receipt: dict,
    *,
    expected_delivery_identity: dict[str, object],
    expected_backend_identity: dict[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema") != SCHEMA:
        errors.append("receipt schema mismatch")
    if not _OBSERVED_AT_RE.match(str(receipt.get("observed_at", ""))):
        errors.append("observed_at must be a closed UTC timestamp")
    identity = receipt.get("delivery_identity")
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_KEYS):
        errors.append("delivery identity keys must be exact")
    elif any(identity[k] != expected_delivery_identity[k] for k in IDENTITY_KEYS):
        errors.append("receipt does not bind the current delivery identity")
    stage = receipt.get("stage")
    if stage == "NEEDS_017_SEATBELT_BACKEND":
        if set(receipt) != {
            "schema", "observed_at", "stage", "delivery_identity",
            "blocked", "closed_preconditions", "attempts",
        }:
            errors.append("blocked receipt keys must be exact")
        blocked = receipt.get("blocked")
        if not isinstance(blocked, dict) or set(blocked) != BLOCKED_REASON_KEYS:
            errors.append("blocked keys must be exact")
        else:
            reason_code = blocked.get("reason_code")
            if reason_code not in QUALIFICATION_REASONS:
                errors.append("blocked reason must be closed")
            if reason_code == "qualified":
                errors.append("blocked reason must not be qualified")
            qualification = blocked.get("qualification")
            if (
                not isinstance(qualification, dict)
                or set(qualification) != {"reason_code"}
                or qualification.get("reason_code") != reason_code
            ):
                errors.append("blocked qualification must exactly bind its reason")
        pre = receipt.get("closed_preconditions")
        if (
            not isinstance(pre, dict)
            or set(pre) != set(CLOSED_PRECONDITIONS)
            or any(pre.get(n) is not True for n in CLOSED_PRECONDITIONS)
        ):
            errors.append("blocked receipt must record closed preconditions")
        if receipt.get("attempts") != []:
            errors.append("blocked receipt must carry no attempts")
    elif stage in ("U2_PASS", "U2_FAIL"):
        if set(receipt) != {
            "schema", "observed_at", "stage", "delivery_identity",
            "backend_identity", "attempts",
        }:
            errors.append("U2 receipt keys must be exact")
        backend = receipt.get("backend_identity")
        if expected_backend_identity is None:
            errors.append("current backend unavailable; U2 receipt not attestable")
        elif not isinstance(backend, dict) or set(backend) != set(BACKEND_KEYS):
            errors.append("backend identity keys must be exact")
        elif any(
            backend[k] != expected_backend_identity[k] for k in BACKEND_KEYS
        ):
            errors.append("receipt does not bind the current backend identity")
        attempts = receipt.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != 3:
            errors.append("U2 receipt requires exactly three attempts")
            attempts = []
        if [a.get("attempt_id") for a in attempts if isinstance(a, dict)] != list(
            FROZEN_ATTEMPT_IDS,
        ):
            errors.append("attempt ids must be frozen")
        for attempt in attempts:
            if not isinstance(attempt, dict) or set(attempt) != {
                "attempt_id", *ATTEMPT_IDENTITY_KEYS, "journeys",
            }:
                errors.append("attempt keys must be exact")
                continue
            for key in ATTEMPT_IDENTITY_KEYS:
                if not _HEX64.fullmatch(str(attempt.get(key, ""))):
                    errors.append(f"attempt {key} must be sha256")
            if attempt.get("wheel_sha256") != expected_delivery_identity.get(
                "wheel_sha256"
            ):
                errors.append("attempt wheel does not bind delivery wheel")
            journeys = attempt.get("journeys")
            if (
                not isinstance(journeys, dict)
                or set(journeys) != set(JOURNEY_NAMES)
                or any(not isinstance(v, bool) for v in journeys.values())
            ):
                errors.append("attempt journeys must be the frozen booleans")
            elif stage == "U2_PASS" and any(v is not True for v in journeys.values()):
                errors.append("U2_PASS requires all journeys true")
            elif stage == "U2_FAIL" and all(v is True for v in journeys.values()):
                errors.append("U2_FAIL must record at least one false journey")
        for key in (
            "workspace_root_sha256",
            "temp_root_sha256",
            "sentinel_sha256",
            "attempt_record_sha256",
        ):
            values = [
                attempt.get(key) for attempt in attempts if isinstance(attempt, dict)
            ]
            if len(values) == 3 and len(set(values)) != 3:
                errors.append(f"attempt {key} values must be unique")
    else:
        errors.append("stage must be U2_PASS/U2_FAIL/NEEDS_017_SEATBELT_BACKEND")
    encoded = json.dumps(receipt, sort_keys=True, ensure_ascii=False)
    for needle in _FORBIDDEN_NEEDLES[:-1]:
        if needle in encoded:
            errors.append(f"receipt contains forbidden needle: {needle[:12]}…")
    return errors


# --------------------------------------------------------------------------- #
# Journey harness（control / confined / bypass 三条运行通道）
# --------------------------------------------------------------------------- #


class _ControlResult:
    __slots__ = ("returncode", "stdout")

    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


class JourneyHarness:
    """一个 attempt 的运行通道。默认全真实（bounded subprocess + 真实
    Seatbelt confine + 既有 runner）；测试注入替身驱动 mutation oracle。"""

    def __init__(self, roots: dict, *, confiner=None) -> None:  # noqa: ANN001
        self.roots = roots
        self._confiner = confiner
        self.confined_calls: list[dict] = []
        self.control_calls: list[dict] = []
        self.bypass_calls: list[dict] = []

    # -- control：未隔离通道（证明前提） ------------------------------ #

    def control(self, argv: list[str], *, cwd: str | None = None) -> _ControlResult:  # noqa: ANN202
        self.control_calls.append({"argv": list(argv), "cwd": cwd})
        completed = subprocess.run(  # noqa: S603 - argv 精确构造
            argv, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
        return _ControlResult(completed.returncode, completed.stdout)

    # -- confined：经 policy + executor ------------------------------- #

    def _build_policy(self, mode: str, network: str, private_roots: tuple):  # noqa: ANN202
        _admit_live_product_import()
        from agent.sandbox.contracts import SandboxMode, SandboxNetworkMode
        from agent.sandbox.policy import build_sandbox_policy

        return build_sandbox_policy(
            mode=SandboxMode(mode),
            network=SandboxNetworkMode(network),
            workspace=self.roots["workspace"],
            temp_root=self.roots["temp"],
            state_root=self.roots["state"],
            home=self.roots["home"],
            private_roots=private_roots,
        )

    def _executor(self):  # noqa: ANN202
        _admit_live_product_import()
        from agent.sandbox.executor import NativeSandboxExecutor

        if self._confiner is None:
            from agent.sandbox.seatbelt import SeatbeltConfiner
            self._confiner = SeatbeltConfiner()
        return NativeSandboxExecutor(
            confiner=self._confiner,
            captured_path=os.environ.get("PATH", "/usr/bin:/bin"),
        )

    def confined(self, argv: list[str], *, cwd: str = ".", mode: str = "workspace-write",
                 network: str = "off", private_roots: tuple = (),
                 profile: str | None = None) -> object:  # noqa: ANN202
        from agent.process.preparation import prepare_process

        arguments = {"executable": argv[0], "argv": list(argv[1:]), "cwd": cwd}
        if profile is not None:
            arguments["profile"] = profile
        prepared = prepare_process(
            arguments,
            workspace=self.roots["workspace"],
            captured_path=os.environ.get("PATH", "/usr/bin:/bin"),
        )
        policy = self._build_policy(mode, network, private_roots)
        call = {"argv": list(argv), "mode": mode}
        self.confined_calls.append(call)
        return self._executor().execute(prepared, policy)

    def bypass(self, argv: list[str], *, cwd: str = ".") -> object:  # noqa: ANN202
        return self.confined(argv, cwd=cwd, mode="danger-full-access")

    def confined_exit(self, argv: list[str], **kwargs) -> int | None:  # noqa: ANN003, ANN202
        result = self.confined(argv, **kwargs)
        if not hasattr(result, "exit_code"):
            return None  # KnownNotExecuted
        return result.exit_code


# --------------------------------------------------------------------------- #
# 11 条 frozen journey（每条先 control 证明前提，再 confined 断言）
# --------------------------------------------------------------------------- #


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def journey_host_toolchain_works(h: JourneyHarness) -> bool:
    argv = ["/bin/sh", "-c", "echo toolchain-ok"]
    if h.control(argv).returncode != 0:
        return False
    result = h.confined(argv)
    return getattr(result, "exit_code", None) == 0


def journey_git_metadata_readable_write_denied(h: JourneyHarness) -> bool:
    git_dir = Path(h.roots["workspace"]) / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    head = git_dir / "HEAD"
    _write_file(head, "ref: refs/heads/main\n")
    original = head.read_text(encoding="utf-8")
    read_argv = ["/bin/cat", str(head)]
    if h.control(read_argv).returncode != 0:
        return False
    if h.confined_exit(read_argv, mode="read-only") != 0:
        return False
    write_argv = [
        "/bin/sh", "-c", f"echo tampered >> {head}",
    ]
    h.confined_exit(write_argv)
    return head.read_text(encoding="utf-8") == original


def journey_workspace_write_succeeds(h: JourneyHarness) -> bool:
    target = Path(h.roots["workspace"]) / "out.txt"
    argv = ["/bin/sh", "-c", f"echo workspace-write-ok > {target}"]
    result = h.confined(argv)
    if getattr(result, "exit_code", None) != 0:
        return False
    return target.exists() and target.read_text(encoding="utf-8").strip() == "workspace-write-ok"


def journey_outside_write_denied(h: JourneyHarness) -> bool:
    target = Path(h.roots["outside"]) / "denied.txt"
    _write_file(Path(h.roots["outside"]) / "keep", "")
    probe = ["/bin/sh", "-c", f"echo x > {Path(h.roots['outside']) / 'probe.txt'}"]
    if h.control(probe).returncode != 0:
        return False  # 前提：parent 可写
    argv = ["/bin/sh", "-c", f"echo leak > {target}"]
    h.confined_exit(argv)
    return not target.exists()


def journey_credential_sentinel_unreadable(h: JourneyHarness) -> bool:
    sentinel = Path(h.roots["outside"]) / "sentinel.key"
    if not sentinel.exists():
        _write_file(sentinel, "SENTINEL-DO-NOT-READ")
    read_argv = ["/bin/cat", str(sentinel)]
    if h.control(read_argv).returncode != 0:
        return False  # 前提：sentinel 可读
    result = h.confined_exit(read_argv, private_roots=(str(sentinel),))
    return result is None or result != 0


def journey_network_off_denied(h: JourneyHarness) -> bool:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    connect_argv = [
        "/usr/bin/nc", "-w", "2", "127.0.0.1", str(port),
    ]
    try:
        if h.control(connect_argv).returncode != 0:
            return False  # 前提：listener 可达（nc 自身 exit 0）
        listener.settimeout(2)
        control_connection, _address = listener.accept()
        control_connection.close()
        result = h.confined_exit(connect_argv, network="off")
        return result is None or result != 0
    finally:
        listener.close()


def journey_process_tree_inheritance(h: JourneyHarness) -> bool:
    target = Path(h.roots["outside"]) / "child-leak.txt"
    probe_target = Path(h.roots["outside"]) / "child-probe.txt"
    probe = ["/bin/sh", "-c", f"/bin/sh -c 'echo p > {probe_target}'"]
    if h.control(probe).returncode != 0:
        return False  # 前提：child 可写该 parent
    argv = ["/bin/sh", "-c", f"/bin/sh -c 'echo leak > {target}'"]
    h.confined_exit(argv)
    return not target.exists()


def journey_timeout_cleanup_capped(h: JourneyHarness) -> bool:
    argv = ["/bin/sleep", "600"]
    start = time.monotonic()
    result = h.confined(argv, cwd=".", profile="short")
    elapsed = time.monotonic() - start
    outcome = getattr(result, "outcome", None)
    return (
        outcome is not None
        and outcome.value == "timed_out_reaped"
        and elapsed < 120
    )


def journey_backend_unavailable_confined_zero_execution(h: JourneyHarness) -> bool:
    _admit_live_product_import()
    from agent.process.preparation import prepare_process
    from agent.runtime.contracts import KnownNotExecuted
    from agent.sandbox.contracts import SandboxQualificationV1
    from agent.sandbox.executor import NativeSandboxExecutor

    class _UnavailableConfiner:
        def qualify(self):  # noqa: ANN202
            return SandboxQualificationV1(False, "sandbox_exec_missing")

        def confine(self, command, policy, environment):  # noqa: ANN001, ANN202
            return KnownNotExecuted(
                code="sandbox_exec_missing",
                message="sandbox backend unavailable",
            )

    prepared = prepare_process(
        {"executable": "/bin/sh", "argv": ["-c", "true"], "cwd": "."},
        workspace=h.roots["workspace"],
        captured_path=os.environ.get("PATH", "/usr/bin:/bin"),
    )
    policy = h._build_policy("workspace-write", "off", ())
    executor = NativeSandboxExecutor(
        confiner=_UnavailableConfiner(),
        captured_path=os.environ.get("PATH", "/usr/bin:/bin"),
    )
    outcome = executor.execute(prepared, policy)
    if not isinstance(outcome, KnownNotExecuted):
        return False
    # bypass 不受 backend 影响
    bypass_result = h.bypass(["/bin/sh", "-c", "echo bypass-ok"])
    return getattr(bypass_result, "exit_code", None) == 0


def _invoke_with_exact_sandbox_approval(
    h: JourneyHarness,
    arguments: dict,
    *,
    call_prefix: str,
    before_invoke,
):  # noqa: ANN001, ANN202
    _admit_live_product_import()
    from agent.runtime.contracts import SandboxAuthorityLeaseV1, ToolCall, ToolPrepareContext
    from agent.runtime.tools import ApprovalRequired, KernelToolRuntime
    from agent.sandbox.tools import build_sandbox_exec_registration

    registration = build_sandbox_exec_registration(
        workspace=h.roots["workspace"],
        temp_root=h.roots["temp"],
        state_root=h.roots["state"],
        home=h.roots["home"],
        captured_path=os.environ.get("PATH", "/usr/bin:/bin"),
        confiner=h._executor()._confiner,
    )
    runtime = KernelToolRuntime((registration,), clock=_now_utc)
    context = ToolPrepareContext(
        conversation_id="e3", run_id=call_prefix, state_revision=1,
        goal_id="goal-e3", goal_revision=1,
        workspace_identity_digest="workspace-e3",
    )
    pending = runtime.prepare(
        ToolCall(f"{call_prefix}:proposal", "sandbox_exec", arguments), context,
    )
    if not isinstance(pending, ApprovalRequired):
        return None
    if not before_invoke(pending):
        return None
    candidate = pending.request.sandbox_authority_candidate
    lease = SandboxAuthorityLeaseV1.create(
        lease_id=f"sandbox-lease:{candidate.policy_digest[:12]}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity=f"e3:{call_prefix}:approval",
        issued_at=_now_utc(),
        expires_at="2100-01-01T00:00:00+00:00",
    )
    approved = ToolPrepareContext(
        conversation_id="e3", run_id=call_prefix, state_revision=1,
        goal_id="goal-e3", goal_revision=1,
        workspace_identity_digest="workspace-e3",
        sandbox_leases=(lease,),
    )
    intent = runtime.prepare(
        ToolCall(f"{call_prefix}:approved", "sandbox_exec", arguments), approved,
    )
    if isinstance(intent, ApprovalRequired):
        return None
    return runtime.invoke(intent)


def journey_bypass_authority_exact(h: JourneyHarness) -> bool:
    external_target = Path(h.roots["outside"]) / "bypass-owned.txt"
    command = f"echo bypass-owned > {external_target}"
    result = _invoke_with_exact_sandbox_approval(
        h,
        {
            "executable": "/bin/sh",
            "argv": ["-c", command],
            "cwd": ".",
            "mode": "danger-full-access",
        },
        call_prefix="bypass",
        before_invoke=lambda _pending: not external_target.exists(),
    )
    if result is None:
        return False
    if result.is_error is True:
        return False
    receipt = result.metadata.get("sandbox_receipt", {})
    return (
        receipt.get("backend") == "none"
        and receipt.get("enforcement") == "unconfined"
        and external_target.exists()
    )


def journey_read_back_completion(h: JourneyHarness) -> bool:
    target = Path(h.roots["workspace"]) / "artifact.txt"
    content = "read-back-ok"
    result = _invoke_with_exact_sandbox_approval(
        h,
        {
            "executable": "/bin/sh",
            "argv": ["-c", f"printf %s {content} > {target}"],
            "cwd": ".",
            "mode": "workspace-write",
            "network": "off",
        },
        call_prefix="read-back",
        before_invoke=lambda _pending: not target.exists(),
    )
    if result is None or result.is_error is True:
        return False
    metadata = result.metadata
    receipt = metadata.get("sandbox_receipt")
    if (
        metadata.get("sandbox_receipt_kind") != "native_sandbox_v1"
        or not isinstance(receipt, dict)
        or receipt.get("outcome") != "exited"
        or receipt.get("enforcement") != "confined"
        or receipt.get("backend") != "seatbelt"
        or not _HEX64.fullmatch(str(metadata.get("receipt_digest", "")))
    ):
        return False
    digest = hashlib.sha256(content.encode()).hexdigest()
    actual = hashlib.sha256(
        target.read_text(encoding="utf-8").strip().encode(),
    ).hexdigest()
    # receipt 与 exit 0 齐全时，host read-back 不匹配仍不得完成。
    return digest == actual


JOURNEYS = (
    journey_host_toolchain_works,
    journey_git_metadata_readable_write_denied,
    journey_workspace_write_succeeds,
    journey_outside_write_denied,
    journey_credential_sentinel_unreadable,
    journey_network_off_denied,
    journey_process_tree_inheritance,
    journey_timeout_cleanup_capped,
    journey_backend_unavailable_confined_zero_execution,
    journey_bypass_authority_exact,
    journey_read_back_completion,
)


def attempt_roots(attempt_root: Path) -> dict:
    attempt_root.mkdir(parents=False, exist_ok=False)
    canonical_root = attempt_root.resolve()
    roots = {
        "workspace": canonical_root / "workspace",
        "temp": canonical_root / "sbx-tmp",
        "state": canonical_root / "state",
        "home": canonical_root / "sbx-home",
        "outside": canonical_root / "outside",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    _write_file(roots["outside"] / "sentinel.key", secrets.token_hex(32))
    return roots


def _path_digest(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()


def run_attempt(
    attempt_id: str,
    attempt_root: Path,
    *,
    wheel_sha256: str,
    confiner=None,
) -> dict:  # noqa: ANN001
    roots = attempt_roots(attempt_root)
    harness = JourneyHarness(roots, confiner=confiner)
    journeys = {name: False for name in JOURNEY_NAMES}
    for name, function in zip(JOURNEY_NAMES, JOURNEYS, strict=True):
        try:
            journeys[name] = bool(function(harness))
        except Exception:  # noqa: BLE001 — 单 journey 异常只记 False，不中止 attempt
            journeys[name] = False
    record = {
        "attempt_id": attempt_id,
        "wheel_sha256": wheel_sha256,
        "workspace_root_sha256": _path_digest(roots["workspace"]),
        "temp_root_sha256": _path_digest(roots["temp"]),
        "sentinel_sha256": hashlib.sha256(
            (roots["outside"] / "sentinel.key").read_bytes(),
        ).hexdigest(),
        "journeys": journeys,
    }
    encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
    journal = attempt_root / ATTEMPT_RECORD_NAME
    with journal.open("xb") as stream:
        stream.write(encoded)
    return {
        **record,
        "attempt_record_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _load_attempt_record(path: Path, *, wheel_sha256: str) -> dict:
    encoded = path.read_bytes()
    value = json.loads(encoded)
    expected_keys = {
        "attempt_id",
        "wheel_sha256",
        "workspace_root_sha256",
        "temp_root_sha256",
        "sentinel_sha256",
        "journeys",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError("attempt journal keys must be exact")
    if value.get("wheel_sha256") != wheel_sha256:
        raise ValueError("attempt journal wheel digest mismatch")
    journeys = value.get("journeys")
    if (
        not isinstance(journeys, dict)
        or set(journeys) != set(JOURNEY_NAMES)
        or any(not isinstance(item, bool) for item in journeys.values())
    ):
        raise ValueError("attempt journal journeys must be exact booleans")
    return {
        **value,
        "attempt_record_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _create_clean_environment(prefix: Path, wheel: Path) -> str:
    created = subprocess.run(
        [PYTHON, "-m", "venv", str(prefix)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if created.returncode != 0:
        raise RuntimeError("attempt clean venv creation failed")
    configuration = (prefix / "pyvenv.cfg").read_text(encoding="utf-8")
    if "include-system-site-packages = false" not in configuration:
        raise RuntimeError("attempt venv inherited system site-packages")
    python = str(prefix / "bin" / "python")
    installed = subprocess.run(
        [
            python,
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
        raise RuntimeError("attempt wheel installation failed")
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("attempt offline base dependency installer unavailable")
    dependencies = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--python",
            python,
            "httpx>=0.27.1",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if dependencies.returncode != 0:
        raise RuntimeError("attempt offline base dependency installation failed")
    return python


def _run_materialized_attempt(
    *,
    attempt_id: str,
    attempt_root: Path,
    materialized_tree: Path,
    build_root: Path,
    expected_wheel_sha256: str,
) -> dict:
    sys.path.insert(0, str(REPO / "scripts"))
    import verify_017_materialized_tree as verifier  # type: ignore[import-not-found]

    wheel_dir = build_root / "wheel"
    wheel, error = verifier.build_materialized_wheel(
        materialized_tree, wheel_dir, python=PYTHON,
    )
    if wheel is None:
        raise RuntimeError(f"attempt wheel build failed: {error}")
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if wheel_sha256 != expected_wheel_sha256:
        raise RuntimeError("attempt wheel does not match materialized gate artifact")
    python = _create_clean_environment(build_root / "venv", wheel)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "FIRST_AGENT_017_E3_IMPORT_MODE": "installed",
        }
    )
    child = subprocess.run(
        [
            python,
            str(Path(__file__).resolve()),
            "--single-attempt",
            attempt_id,
            "--attempt-root",
            str(attempt_root),
            "--wheel-sha256",
            wheel_sha256,
        ],
        cwd=str(build_root),
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if child.returncode != 0:
        raise RuntimeError("materialized attempt child failed")
    return _load_attempt_record(
        attempt_root / ATTEMPT_RECORD_NAME,
        wheel_sha256=wheel_sha256,
    )


def _single_attempt_main(attempt_id: str, attempt_root: Path, wheel_sha256: str) -> int:
    global _INSTALLED_PRODUCT_ONLY
    _INSTALLED_PRODUCT_ONLY = True
    if os.environ.get("FIRST_AGENT_017_E3_IMPORT_MODE") != "installed":
        return 4
    try:
        import agent

        origin = Path(agent.__file__).resolve()
        if not origin.is_relative_to(Path(sys.prefix).resolve()):
            return 4
        run_attempt(
            attempt_id,
            attempt_root,
            wheel_sha256=wheel_sha256,
        )
    except (OSError, RuntimeError, ValueError):
        return 4
    return 0


def _materialize_once(destination: Path) -> str:
    sys.path.insert(0, str(REPO / "scripts"))
    import verify_017_materialized_tree as verifier  # type: ignore[import-not-found]

    entries, errors = verifier.validate_delivery(REPO)
    if errors:
        raise ValueError("; ".join(errors))
    materialize_errors = verifier.materialize_tree(entries, REPO, destination)
    if materialize_errors:
        raise ValueError("; ".join(materialize_errors))
    return _materialized_tree_digest(destination)


def _materialized_tree_digest(tree: Path) -> str:
    members: list[tuple[str, str]] = []
    for path in sorted(tree.rglob("*")):
        if path.is_symlink():
            raise ValueError("materialized tree contains a symlink")
        if path.is_file():
            members.append(
                (
                    path.relative_to(tree).as_posix(),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return hashlib.sha256(
        json.dumps(members, separators=(",", ":")).encode(),
    ).hexdigest()


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #


def run_source_gates() -> list[str]:
    failed: list[str] = []
    gates = (
        (["git", "diff", "--check"], 60, "diff_check"),
        ([str(RUFF), "check", "."], 300, "ruff"),
        ([str(PYTHON), "-m", "pytest", "-q", "-rx"], 3600, "full_suite"),
    )
    for argv, timeout, name in gates:
        result = _run(argv, timeout=timeout)
        if result.returncode != 0:
            failed.append(name)
            print(f"017_E3_BLOCKED(source_gate={name})")
    return failed


def run_materialized_gates() -> bool:
    result = _run([str(PYTHON), str(VERIFY), "--content"], timeout=3600)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-4:]
        for line in tail:
            print(f"017_CONTENT_TAIL {line}")
        print("017_E3_BLOCKED(materialized_gates)")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts-root", type=Path, default=None)
    parser.add_argument("--single-attempt", choices=FROZEN_ATTEMPT_IDS)
    parser.add_argument("--attempt-root", type=Path)
    parser.add_argument("--wheel-sha256")
    args = parser.parse_args(argv)

    if args.single_attempt is not None:
        if (
            args.attempt_root is None
            or not _HEX64.fullmatch(str(args.wheel_sha256 or ""))
        ):
            return 4
        return _single_attempt_main(
            args.single_attempt,
            args.attempt_root,
            args.wheel_sha256,
        )
    if args.attempt_root is not None or args.wheel_sha256 is not None:
        return 4

    if run_source_gates():
        return 1
    if not run_materialized_gates():
        return 1

    reason = qualification_reason()
    try:
        identity = delivery_identity(REPO)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"017_E3_BLOCKED(identity_unavailable): {exc}")
        return 1
    started = {"delivery": identity, "backend": backend_identity()}

    if reason != "qualified":
        receipt = {
            "schema": SCHEMA,
            "observed_at": _now_utc(),
            "stage": "NEEDS_017_SEATBELT_BACKEND",
            "delivery_identity": identity,
            "blocked": {
                "reason_code": reason,
                "qualification": {"reason_code": reason},
                "missing_owner_action": (
                    "restore /usr/bin/sandbox-exec availability on this macOS host"
                ),
            },
            "closed_preconditions": {
                "source_gates": True, "materialized_gates": True,
            },
            "attempts": [],
        }
        errors = receipt_errors(
            receipt,
            expected_delivery_identity=identity,
            expected_backend_identity=None,
        )
        if errors:
            for error in errors:
                print(f"017_RECEIPT_INVALID: {error}")
            return 3
        RECEIPT_PATH.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        attested = _run([str(PYTHON), str(VERIFY), "--attestation"], timeout=300)
        if attested.returncode != 0:
            print("017_E3_BLOCKED(attestation)")
            return 3
        print(f"NEEDS_017_SEATBELT_BACKEND(stage=U2, reason={reason})")
        return 2

    # 重验 identity（drift 拒绝写 receipt）
    if {"delivery": delivery_identity(REPO), "backend": backend_identity()} != started:
        print("017_E3_BLOCKED(identity_drift)")
        return 1

    attempts_root = args.attempts_root
    if attempts_root is None:
        attempts_root = Path(tempfile.mkdtemp(prefix="017-e3-attempts-"))
    else:
        attempts_root.mkdir(parents=True, exist_ok=True)
        if any(attempts_root.iterdir()):
            print("017_E3_BLOCKED(attempts_root_not_fresh)")
            return 1
    materialized_parent = Path(tempfile.mkdtemp(prefix="017-e3-materialized-"))
    build_parent = Path(tempfile.mkdtemp(prefix="017-e3-builds-"))
    materialized_tree = materialized_parent / "tree"
    materialized_tree.mkdir()
    try:
        frozen_tree_digest = _materialize_once(materialized_tree)
        attempts: list[dict] = []
        for attempt_id in FROZEN_ATTEMPT_IDS:
            attempts.append(
                _run_materialized_attempt(
                    attempt_id=attempt_id,
                    attempt_root=attempts_root / attempt_id,
                    materialized_tree=materialized_tree,
                    build_root=build_parent / attempt_id,
                    expected_wheel_sha256=str(identity["wheel_sha256"]),
                )
            )
            if _materialized_tree_digest(materialized_tree) != frozen_tree_digest:
                print("017_E3_BLOCKED(materialized_tree_drift)")
                return 1
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"017_E3_BLOCKED(materialized_attempt): {exc}")
        return 1
    finally:
        shutil.rmtree(materialized_parent, ignore_errors=True)
        shutil.rmtree(build_parent, ignore_errors=True)
    all_green = all(
        all(a["journeys"].values()) for a in attempts  # type: ignore[union-attr]
    )
    receipt = {
        "schema": SCHEMA,
        "observed_at": _now_utc(),
        "stage": "U2_PASS" if all_green else "U2_FAIL",
        "delivery_identity": identity,
        "backend_identity": started["backend"],
        "attempts": attempts,
    }
    if {"delivery": delivery_identity(REPO), "backend": backend_identity()} != started:
        print("017_E3_BLOCKED(identity_drift)")
        return 1
    errors = receipt_errors(
        receipt,
        expected_delivery_identity=identity,
        expected_backend_identity=started["backend"],  # type: ignore[arg-type]
    )
    if errors:
        for error in errors:
            print(f"017_RECEIPT_INVALID: {error}")
        return 3
    RECEIPT_PATH.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    attested = _run([str(PYTHON), str(VERIFY), "--attestation"], timeout=300)
    if attested.returncode != 0:
        print("017_E3_BLOCKED(attestation)")
        return 3
    if receipt["stage"] == "U2_FAIL":
        print("017_E3_REAL_FAIL attempts=3")
        return 3
    print("017_E3_REAL_PASS attempts=3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
