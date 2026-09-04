"""固定协议的 hermetic packaged-Skill child runner（仅使用 Python stdlib）。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import Final

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX child must fail closed
    resource = None  # type: ignore[assignment]

STRUCTURED_REQUEST_MAX_BYTES: Final = 64 * 1024
STRUCTURED_INPUT_MAX_ITEMS: Final = 16
STRUCTURED_INPUT_MAX_BYTES: Final = 32 * 1024 * 1024
STRUCTURED_INPUT_AGGREGATE_MAX_BYTES: Final = 64 * 1024 * 1024
STRUCTURED_RESULT_MAX_BYTES: Final = 64 * 1024 * 1024
STRUCTURED_ARTIFACT_MAX_BYTES: Final = 64 * 1024 * 1024
STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES: Final = 64 * 1024 * 1024
STRUCTURED_MAGIC_MAX_ITEMS: Final = 16
STRUCTURED_MAGIC_MAX_BYTES: Final = 64
_HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
_ENTRYPOINT_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_INPUT_SLOT: Final = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_RESULT_KINDS: Final = frozenset({"observation", "artifact"})
_REQUEST_KEYS: Final = frozenset(
    {
        "protocol",
        "package_digest",
        "entrypoint_id",
        "entrypoint_script",
        "arguments",
        "inputs",
        "expected_result_kind",
        "resource_limits_digest",
    }
)

LIMIT_PROFILE_VALUES: Final = {
    "skill-standard-v1": {
        "cpu_seconds": 60,
        "address_space_bytes": 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 64,
        "core_bytes": 0,
    },
    "artifact-standard-v1": {
        "cpu_seconds": 120,
        "address_space_bytes": 2 * 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 128,
        "core_bytes": 0,
    },
}


class RunnerProtocolError(ValueError):
    """child request/result 违反封闭协议，尚未加载 package code。"""


def _limit_digest(profile: str, values: dict[str, int]) -> str:
    raw = json.dumps(
        {"profile": profile, **values}, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


LIMITS_BY_DIGEST: Final = {
    _limit_digest(profile, values): values for profile, values in LIMIT_PROFILE_VALUES.items()
}


def _require_hex64(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise RunnerProtocolError(f"{name} must be lowercase hex64")
    return value


def _stable(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
    )


def _read_bounded_fd(fd: int, *, size: int, cap: int, label: str) -> bytes:
    if size < 0 or size > cap:
        raise RunnerProtocolError(f"{label} exceeds its fixed cap")
    remaining = size + 1
    chunks: list[bytes] = []
    while remaining:
        chunk = os.read(fd, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    value = b"".join(chunks)
    if len(value) != size:
        raise RunnerProtocolError(f"{label} changed while being read")
    return value


def _read_regular(
    path: Path,
    *,
    cap: int,
    label: str,
    expected_size: int | None = None,
    expected_digest: str | None = None,
) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise RunnerProtocolError(f"{label} preflight failed") from error
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
        ):
            raise RunnerProtocolError(f"{label} preflight failed")
        value = _read_bounded_fd(fd, size=before.st_size, cap=cap, label=label)
        after = os.fstat(fd)
        if not _stable(before, after):
            raise RunnerProtocolError(f"{label} preflight failed")
    finally:
        os.close(fd)
    if expected_size is not None and len(value) != expected_size:
        raise RunnerProtocolError(f"{label} preflight failed")
    if expected_digest is not None and hashlib.sha256(value).hexdigest() != expected_digest:
        raise RunnerProtocolError(f"{label} preflight failed")
    return value


def _read_exact_json(path: Path, *, cap: int) -> dict[str, object]:
    raw = _read_regular(path, cap=cap, label="request")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RunnerProtocolError("request contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(RunnerProtocolError("non-finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RunnerProtocolError) as error:
        raise RunnerProtocolError("request is not valid JSON") from error
    if not isinstance(value, dict):
        raise RunnerProtocolError("request must be a JSON object")
    return value


def _validate_json(value: object) -> None:
    if value is None or isinstance(value, (bool, str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RunnerProtocolError("payload must be finite JSON")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RunnerProtocolError("payload keys must be strings")
            _validate_json(item)
        return
    raise RunnerProtocolError("payload must be finite JSON")


def _canonical_script_path(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("scripts/") or "\\" in value:
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _validate_script_descriptor(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"path", "size", "sha256"}:
        raise RunnerProtocolError("entrypoint script descriptor keys are not closed")
    size = value["size"]
    if (
        not _canonical_script_path(value["path"])
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not 0 <= size <= STRUCTURED_INPUT_MAX_BYTES
    ):
        raise RunnerProtocolError("entrypoint script descriptor is invalid")
    _require_hex64(value["sha256"], "entrypoint script digest")
    return value


def _validate_magic(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list) or len(value) > STRUCTURED_MAGIC_MAX_ITEMS:
        raise RunnerProtocolError("input magic preflight failed")
    if any(
        not isinstance(item, str)
        or re.fullmatch(r"(?:[0-9a-f]{2})+", item) is None
        or len(item) // 2 > STRUCTURED_MAGIC_MAX_BYTES
        for item in value
    ):
        raise RunnerProtocolError("input magic preflight failed")
    if value != sorted(set(value)):
        raise RunnerProtocolError("input magic preflight failed")
    return tuple(bytes.fromhex(item) for item in value)


def _validate_input_descriptors(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > STRUCTURED_INPUT_MAX_ITEMS:
        raise RunnerProtocolError("input descriptors are not closed")
    total = 0
    slots: set[str] = set()
    descriptors: list[dict[str, object]] = []
    for descriptor in value:
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "slot",
            "size",
            "sha256",
            "allowed_magic_hex",
        }:
            raise RunnerProtocolError("input descriptor keys are not closed")
        slot = descriptor["slot"]
        size = descriptor["size"]
        if (
            not isinstance(slot, str)
            or _INPUT_SLOT.fullmatch(slot) is None
            or slot in slots
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 <= size <= STRUCTURED_INPUT_MAX_BYTES
        ):
            raise RunnerProtocolError("input descriptor is invalid")
        _require_hex64(descriptor["sha256"], "input digest")
        _validate_magic(descriptor["allowed_magic_hex"])
        total += size
        if total > STRUCTURED_INPUT_AGGREGATE_MAX_BYTES:
            raise RunnerProtocolError("input descriptors exceed aggregate cap")
        slots.add(slot)
        descriptors.append(descriptor)
    return descriptors


def _validate_request_identity(
    request: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if set(request) != _REQUEST_KEYS:
        raise RunnerProtocolError("request keys are not closed")
    if request["protocol"] != "first-agent-skill-request-v1":
        raise RunnerProtocolError("request protocol is not closed")
    _require_hex64(request["package_digest"], "package digest")
    if not isinstance(request["entrypoint_id"], str) or _ENTRYPOINT_ID.fullmatch(
        request["entrypoint_id"]
    ) is None:
        raise RunnerProtocolError("entrypoint id is invalid")
    descriptor = _validate_script_descriptor(request["entrypoint_script"])
    if not isinstance(request["arguments"], dict):
        raise RunnerProtocolError("arguments must be a JSON object")
    _validate_json(request["arguments"])
    descriptors = _validate_input_descriptors(request["inputs"])
    if request["expected_result_kind"] not in _RESULT_KINDS:
        raise RunnerProtocolError("expected result kind is not closed")
    _require_hex64(request["resource_limits_digest"], "resource limit digest")
    return descriptor, descriptors


def apply_hard_limits(resource_limits_digest: str) -> None:
    values = LIMITS_BY_DIGEST.get(resource_limits_digest)
    if values is None:
        raise RunnerProtocolError("resource limit digest is not closed")
    if resource is None:
        raise RunnerProtocolError("required resource limits are unavailable")
    limits = (
        ("cpu", resource.RLIMIT_CPU, values["cpu_seconds"]),
        ("as", resource.RLIMIT_AS, values["address_space_bytes"]),
        ("fsize", resource.RLIMIT_FSIZE, values["file_size_bytes"]),
        ("nofile", resource.RLIMIT_NOFILE, values["open_files"]),
        ("core", resource.RLIMIT_CORE, values["core_bytes"]),
    )
    for name, limit, value in limits:
        try:
            current_soft, current_hard = resource.getrlimit(limit)
            if current_soft > value:
                resource.setrlimit(limit, (value, current_hard))
            resource.setrlimit(limit, (value, value))
        except (OSError, ValueError) as error:
            raise RunnerProtocolError(f"required {name} limit could not be applied") from error


def _open_session_directory(session: Path) -> int:
    try:
        fd = os.open(session, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise RunnerProtocolError("session preflight failed") from error
    # open 成功后、return 前（fstat/身份检查）任何失败都必须关闭当前 fd。
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise RunnerProtocolError("session preflight failed")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_exact_input(session: Path, descriptor: dict[str, object]) -> bytes:
    session_fd = _open_session_directory(session)
    try:
        try:
            inputs_fd = os.open(
                "inputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=session_fd
            )
        except OSError as error:
            raise RunnerProtocolError("input preflight failed") from error
        try:
            slot = descriptor["slot"]
            assert isinstance(slot, str)
            try:
                input_fd = os.open(slot, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=inputs_fd)
            except OSError as error:
                raise RunnerProtocolError("input preflight failed") from error
            try:
                before = os.fstat(input_fd)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_uid != os.getuid()
                    or before.st_nlink != 1
                ):
                    raise RunnerProtocolError("input preflight failed")
                size = descriptor["size"]
                digest = descriptor["sha256"]
                assert isinstance(size, int) and isinstance(digest, str)
                value = _read_bounded_fd(
                    input_fd,
                    size=before.st_size,
                    cap=STRUCTURED_INPUT_MAX_BYTES,
                    label="input",
                )
                after = os.fstat(input_fd)
            finally:
                os.close(input_fd)
        finally:
            os.close(inputs_fd)
    finally:
        os.close(session_fd)
    if (
        not _stable(before, after)
        or len(value) != size
        or hashlib.sha256(value).hexdigest() != digest
    ):
        raise RunnerProtocolError("input preflight failed")
    magic = _validate_magic(descriptor["allowed_magic_hex"])
    if magic and not any(value.startswith(prefix) for prefix in magic):
        raise RunnerProtocolError("input preflight failed")
    return value


def _read_exact_script(package_root: Path, descriptor: dict[str, object]) -> bytes:
    raw_path = descriptor["path"]
    assert isinstance(raw_path, str)
    parts = tuple(raw_path.split("/"))
    try:
        current_fd = os.open(package_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise RunnerProtocolError("entrypoint script preflight failed") from error
    try:
        root_info = os.fstat(current_fd)
        if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid():
            raise RunnerProtocolError("entrypoint script preflight failed")
        for part in parts[:-1]:
            try:
                child_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
            except OSError as error:
                raise RunnerProtocolError("entrypoint script preflight failed") from error
            # child_fd 打开成功但尚未完成向 current_fd 的所有权转移前，
            # 任何失败（fstat/身份检查）都必须先关闭 child_fd。
            try:
                child_info = os.fstat(child_fd)
                if not stat.S_ISDIR(child_info.st_mode) or child_info.st_uid != os.getuid():
                    raise RunnerProtocolError("entrypoint script preflight failed")
            except BaseException:
                os.close(child_fd)
                raise
            # 先把所有权转移给 current_fd 再关闭旧 fd：即使关闭旧 fd 失败，
            # child_fd 也已由 current_fd 持有，outer finally 仍会关闭它。
            previous_fd = current_fd
            current_fd = child_fd
            os.close(previous_fd)
        try:
            script_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current_fd)
        except OSError as error:
            raise RunnerProtocolError("entrypoint script preflight failed") from error
        try:
            before = os.fstat(script_fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != os.getuid()
                or before.st_nlink != 1
            ):
                raise RunnerProtocolError("entrypoint script preflight failed")
            size = descriptor["size"]
            digest = descriptor["sha256"]
            assert isinstance(size, int) and isinstance(digest, str)
            value = _read_bounded_fd(
                script_fd,
                size=before.st_size,
                cap=STRUCTURED_INPUT_MAX_BYTES,
                label="entrypoint script",
            )
            after = os.fstat(script_fd)
        finally:
            os.close(script_fd)
    finally:
        os.close(current_fd)
    if (
        not _stable(before, after)
        or len(value) != size
        or hashlib.sha256(value).hexdigest() != digest
    ):
        raise RunnerProtocolError("entrypoint script preflight failed")
    return value


def _compile_and_exec_verified_script(
    descriptor: dict[str, object], content: bytes
) -> dict[str, object]:
    path = descriptor["path"]
    assert isinstance(path, str)
    try:
        code = compile(content, path, "exec")
    except (SyntaxError, ValueError, TypeError) as error:
        raise RunnerProtocolError("entrypoint script could not be compiled") from error
    namespace: dict[str, object] = {
        "__name__": "__first_agent_skill_entrypoint__",
        "__file__": path,
    }
    try:
        exec(code, namespace)  # noqa: S102 - verified package code is intentionally invoked here.
    except BaseException as error:
        raise RunnerProtocolError("entrypoint script raised during load") from error
    return namespace


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        offset += os.write(fd, content[offset:])


def _pin_precreated_outputs(session: Path) -> dict[str, tuple[int, os.stat_result]]:
    if not hasattr(os, "O_NONBLOCK"):
        raise RunnerProtocolError("required nonblocking output support is unavailable")
    session_fd = _open_session_directory(session)
    pinned: dict[str, tuple[int, os.stat_result]] = {}
    try:
        for name in ("result.json", "artifact.bin"):
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=session_fd,
                )
            except OSError as error:
                raise RunnerProtocolError("precreated output inode is unavailable") from error
            # fd 加入 pinned（ownership 转移给 outer cleanup）之前，
            # fstat/身份检查的任何失败都必须先关闭当前 fd。
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1
                ):
                    raise RunnerProtocolError("precreated output inode is unavailable")
                pinned[name] = (fd, info)
            except BaseException:
                os.close(fd)
                raise
    except BaseException:
        for fd, _info in pinned.values():
            os.close(fd)
        raise
    finally:
        os.close(session_fd)
    return pinned


def _write_pinned_precreated(
    pinned: tuple[int, os.stat_result], content: bytes
) -> None:
    fd, before = pinned
    after = os.fstat(fd)
    if (
        not _stable(before, after)
        or not stat.S_ISREG(after.st_mode)
        or after.st_uid != os.getuid()
        or after.st_nlink != 1
    ):
        raise RunnerProtocolError("precreated output inode is unavailable")
    os.ftruncate(fd, 0)
    _write_all(fd, content)
    os.fsync(fd)


def _result_bytes(kind: str, payload: object) -> bytes:
    result = {
        "protocol": "first-agent-skill-result-v1",
        "kind": kind,
        "payload": payload,
    }
    try:
        return json.dumps(
            result, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RunnerProtocolError("payload must be finite JSON") from error


def _execute_authenticated_request(
    request_path: Path,
    request: dict[str, object],
    *,
    execute_script: Callable[[dict[str, object], bytes], dict[str, object]],
) -> dict[str, object]:
    descriptor, input_descriptors = _validate_request_identity(request)
    resource_limits_digest = request["resource_limits_digest"]
    assert isinstance(resource_limits_digest, str)
    apply_hard_limits(resource_limits_digest)
    session = request_path.parent
    outputs = _pin_precreated_outputs(session)
    try:
        input_values = {
            descriptor["slot"]: _read_exact_input(session, descriptor)
            for descriptor in input_descriptors
        }
        script_bytes = _read_exact_script(Path.cwd(), descriptor)
        namespace = execute_script(descriptor, script_bytes)
        package_run = namespace.get("run")
        if not callable(package_run):
            raise RunnerProtocolError("entrypoint exports no callable run")
        arguments = request["arguments"]
        assert isinstance(arguments, dict)
        try:
            raw = package_run(arguments, MappingProxyType(input_values))
        except BaseException as error:
            raise RunnerProtocolError("entrypoint run failed") from error
        if not isinstance(raw, dict) or set(raw) != {"kind", "payload", "artifact"}:
            raise RunnerProtocolError("entrypoint result keys are not closed")
        kind = raw["kind"]
        if kind != request["expected_result_kind"] or kind not in _RESULT_KINDS:
            raise RunnerProtocolError("entrypoint result kind mismatch")
        _validate_json(raw["payload"])
        artifact = raw["artifact"]
        if artifact is not None and not isinstance(artifact, bytes):
            raise RunnerProtocolError("artifact must be bytes or null")
        result_bytes = _result_bytes(kind, raw["payload"])
        artifact_size = len(artifact) if artifact is not None else 0
        if (
            len(result_bytes) > STRUCTURED_RESULT_MAX_BYTES
            or artifact_size > STRUCTURED_ARTIFACT_MAX_BYTES
            or len(result_bytes) + artifact_size > STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES
        ):
            raise RunnerProtocolError("entrypoint output exceeds fixed cap")
        _write_pinned_precreated(outputs["result.json"], result_bytes)
        if artifact is not None:
            _write_pinned_precreated(outputs["artifact.bin"], artifact)
        return raw
    finally:
        for fd, _info in outputs.values():
            os.close(fd)


def run_request(
    request_path: Path,
    *,
    execute_script: Callable[[dict[str, object], bytes], dict[str, object]] = (
        _compile_and_exec_verified_script
    ),
) -> dict[str, object]:
    """执行一个已认证请求；返回值仅供 child-main 与协议测试使用。"""

    request = _read_exact_json(request_path, cap=STRUCTURED_REQUEST_MAX_BYTES)
    return _execute_authenticated_request(
        request_path, request, execute_script=execute_script
    )


def _parse_cli(argv: list[str]) -> tuple[str, str]:
    if len(argv) != 4 or argv[0] != "--package" or argv[2] != "--entrypoint":
        raise RunnerProtocolError("runner accepts exactly --package DIGEST --entrypoint ID")
    package_digest, entrypoint_id = argv[1], argv[3]
    _require_hex64(package_digest, "package digest")
    if _ENTRYPOINT_ID.fullmatch(entrypoint_id) is None:
        raise RunnerProtocolError("entrypoint id is invalid")
    return package_digest, entrypoint_id


def main(argv: list[str] | None = None) -> int:
    try:
        package_digest, entrypoint_id = _parse_cli(sys.argv[1:] if argv is None else argv)
        tmpdir = os.environ.get("TMPDIR")
        if not tmpdir:
            raise RunnerProtocolError("TMPDIR is required")
        request_path = Path(tmpdir) / "request.json"
        request = _read_exact_json(request_path, cap=STRUCTURED_REQUEST_MAX_BYTES)
        _validate_request_identity(request)
        if request["package_digest"] != package_digest or request["entrypoint_id"] != entrypoint_id:
            raise RunnerProtocolError("CLI identity does not match request")
        _execute_authenticated_request(
            request_path,
            request,
            execute_script=_compile_and_exec_verified_script,
        )
    except RunnerProtocolError as error:
        sys.stderr.write(f"first-agent-skill-runner: {error}\n")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entrypoint
    raise SystemExit(main())
