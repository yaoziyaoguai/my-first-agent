"""020a structured invocation 的单次 descriptor-pinned staging session。"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from agent.sandbox.contracts import (
    StructuredReadbackOutcome,
    StructuredResultKind,
    StructuredSandboxIoPlanV1,
)

_ROOT_ENTRIES = frozenset({"request.json", "inputs", "result.json", "artifact.bin"})
_RESULT_PROTOCOL = "first-agent-skill-result-v1"
_FileIdentity = tuple[int, int, int, int]


class StructuredSessionCleanupError(RuntimeError):
    """spawn 后无法严格移除 session 时由 Runtime 转入 recovery。"""


@dataclass(frozen=True, slots=True)
class StructuredSessionReadbackV1:
    outcome: StructuredReadbackOutcome
    result_bytes: bytes = b""
    artifact_bytes: bytes | None = None


@dataclass(slots=True)
class StructuredSandboxSessionV1:
    """只在一次 executor 调用期间存活的 raw-byte 容器。"""

    root: str
    root_fd: int
    inputs_fd: int
    temp_parent_fd: int
    basename: str
    result_identity: _FileIdentity
    artifact_identity: _FileIdentity
    input_slots: tuple[str, ...]
    _closed: bool = field(default=False, init=False, repr=False)

    def close_and_remove(self) -> None:
        """只沿已固定 descriptor 删除已知条目；意外条目一律不递归清理。"""

        if self._closed:
            return
        failures: list[OSError] = []

        def attempt(operation, *, missing_ok: bool = False) -> None:  # noqa: ANN001
            try:
                operation()
            except FileNotFoundError:
                if not missing_ok:
                    failures.append(OSError("structured session entry disappeared"))
            except OSError as error:
                failures.append(error)

        # root 曾被 child 解冻也无妨：owner 使用它最初固定的 descriptor 清理。
        attempt(lambda: os.fchmod(self.root_fd, 0o700))
        attempt(lambda: os.fchmod(self.inputs_fd, 0o700))
        for slot in self.input_slots:
            attempt(
                lambda slot=slot: os.unlink(slot, dir_fd=self.inputs_fd), missing_ok=True
            )
        attempt(lambda: os.unlink("request.json", dir_fd=self.root_fd), missing_ok=True)
        attempt(lambda: os.unlink("result.json", dir_fd=self.root_fd), missing_ok=True)
        attempt(lambda: os.unlink("artifact.bin", dir_fd=self.root_fd), missing_ok=True)
        attempt(lambda: os.rmdir("inputs", dir_fd=self.root_fd))
        # rmdir 不跟随 leaf symlink；basename 来自本次 mkdtemp，且 parent fd 固定。
        attempt(lambda: os.rmdir(self.basename, dir_fd=self.temp_parent_fd))

        for descriptor in (self.inputs_fd, self.root_fd, self.temp_parent_fd):
            attempt(lambda descriptor=descriptor: os.close(descriptor))
        self._closed = True
        if failures:
            raise StructuredSessionCleanupError(
                "structured session cleanup could not be proved"
            ) from failures[0]


def _identity_from_stat(info: os.stat_result) -> _FileIdentity:
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("structured session file must be regular")
    if info.st_uid != os.getuid() or info.st_nlink != 1:
        raise ValueError("structured session file ownership is invalid")
    return (info.st_dev, info.st_ino, info.st_uid, info.st_nlink)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("structured session write made no progress")
        offset += written


def _create_exact_file(
    parent_fd: int,
    name: str,
    data: bytes,
    mode: int,
) -> _FileIdentity:
    descriptor = os.open(
        name,
        os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
        mode,
        dir_fd=parent_fd,
    )
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        return _identity_from_stat(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def _validate_magic(plan: StructuredSandboxIoPlanV1) -> None:
    for item in plan.inputs:
        if item.allowed_magic_hex and not any(
            item.content.startswith(bytes.fromhex(value))
            for value in item.allowed_magic_hex
        ):
            raise ValueError("structured input does not match its allowed magic")


def create_structured_session(
    temp_parent: str | os.PathLike[str],
    plan: StructuredSandboxIoPlanV1,
) -> StructuredSandboxSessionV1:
    """创建并冻结唯一可见的 I/O protocol surface。"""

    _validate_magic(plan)
    parent_path = os.fspath(temp_parent)
    temp_parent_fd = os.open(
        parent_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    )
    root = tempfile.mkdtemp(prefix="fa-structured-", dir=parent_path)
    try:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except Exception:
        os.close(temp_parent_fd)
        raise
    try:
        os.fchmod(root_fd, 0o700)
        os.mkdir("inputs", 0o700, dir_fd=root_fd)
        inputs_fd = os.open(
            "inputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        try:
            _create_exact_file(root_fd, "request.json", plan.request_bytes, 0o400)
            for item in plan.inputs:
                _create_exact_file(inputs_fd, item.slot, item.content, 0o400)
            result_identity = _create_exact_file(root_fd, "result.json", b"", 0o600)
            artifact_identity = _create_exact_file(root_fd, "artifact.bin", b"", 0o600)
            os.fchmod(inputs_fd, 0o500)
            os.fchmod(root_fd, 0o500)
            return StructuredSandboxSessionV1(
                root=root,
                root_fd=root_fd,
                inputs_fd=inputs_fd,
                temp_parent_fd=temp_parent_fd,
                basename=Path(root).name,
                result_identity=result_identity,
                artifact_identity=artifact_identity,
                input_slots=tuple(item.slot for item in plan.inputs),
            )
        except Exception:
            os.close(inputs_fd)
            raise
    except Exception:
        os.close(root_fd)
        os.close(temp_parent_fd)
        raise


def _invalid(outcome: StructuredReadbackOutcome) -> StructuredSessionReadbackV1:
    return StructuredSessionReadbackV1(outcome=outcome)


def _read_at_most(descriptor: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_pinned_output(
    session: StructuredSandboxSessionV1,
    *,
    name: str,
    identity: _FileIdentity,
    cap: int,
    replaced: StructuredReadbackOutcome,
    too_large: StructuredReadbackOutcome,
) -> StructuredSessionReadbackV1 | bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=session.root_fd
        )
    except OSError:
        return _invalid(replaced)
    try:
        try:
            current = _identity_from_stat(os.fstat(descriptor))
        except ValueError:
            return _invalid(replaced)
        if current != identity:
            return _invalid(replaced)
        data = _read_at_most(descriptor, cap + 1)
    finally:
        os.close(descriptor)
    if len(data) > cap:
        return _invalid(too_large)
    return data


def _is_canonical_result(
    raw_result: bytes,
    plan: StructuredSandboxIoPlanV1,
) -> bool:
    try:
        document = json.loads(raw_result.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(document, dict)
        or set(document) != {"kind", "payload", "protocol"}
        or document["protocol"] != _RESULT_PROTOCOL
        or document["kind"] != plan.expected_result_kind.value
    ):
        return False
    try:
        json.dumps(
            document["payload"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return canonical == raw_result


def read_structured_session(
    session: StructuredSandboxSessionV1,
    plan: StructuredSandboxIoPlanV1,
) -> StructuredSessionReadbackV1:
    """在 child 结束后读取固定 outputs；任何形状偏差均不泄露 staged bytes。"""

    entries = set(os.listdir(session.root_fd))
    if "result.json" not in entries:
        return _invalid(StructuredReadbackOutcome.RESULT_MISSING)
    if "artifact.bin" not in entries:
        return _invalid(StructuredReadbackOutcome.ARTIFACT_MISSING)
    if entries != _ROOT_ENTRIES or set(os.listdir(session.inputs_fd)) != set(
        session.input_slots
    ):
        return _invalid(StructuredReadbackOutcome.EXTRA_OUTPUT)

    raw_result = _read_pinned_output(
        session,
        name="result.json",
        identity=session.result_identity,
        cap=plan.result_cap_bytes,
        replaced=StructuredReadbackOutcome.RESULT_REPLACED,
        too_large=StructuredReadbackOutcome.RESULT_TOO_LARGE,
    )
    if isinstance(raw_result, StructuredSessionReadbackV1):
        return raw_result
    raw_artifact = _read_pinned_output(
        session,
        name="artifact.bin",
        identity=session.artifact_identity,
        cap=plan.artifact_cap_bytes,
        replaced=StructuredReadbackOutcome.ARTIFACT_REPLACED,
        too_large=StructuredReadbackOutcome.ARTIFACT_TOO_LARGE,
    )
    if isinstance(raw_artifact, StructuredSessionReadbackV1):
        return raw_artifact
    if len(raw_result) + len(raw_artifact) > plan.aggregate_output_cap_bytes:
        return _invalid(StructuredReadbackOutcome.RESULT_TOO_LARGE)
    if not _is_canonical_result(raw_result, plan):
        return _invalid(StructuredReadbackOutcome.RESULT_MALFORMED)
    if plan.expected_result_kind is StructuredResultKind.OBSERVATION:
        if raw_artifact:
            return _invalid(StructuredReadbackOutcome.ARTIFACT_UNEXPECTED)
        return StructuredSessionReadbackV1(
            outcome=StructuredReadbackOutcome.VALID,
            result_bytes=raw_result,
        )
    if not raw_artifact:
        return _invalid(StructuredReadbackOutcome.ARTIFACT_MISSING)
    return StructuredSessionReadbackV1(
        outcome=StructuredReadbackOutcome.VALID,
        result_bytes=raw_result,
        artifact_bytes=raw_artifact,
    )
