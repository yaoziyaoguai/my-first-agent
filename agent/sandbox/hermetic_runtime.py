"""``skill-runtime-v1`` 的固定闭包资格校验与 child command 准备。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from agent.process.preparation import PreparedProcessV1, prepare_process
from agent.runtime.contracts import KnownNotExecuted, canonical_json_digest

_HEX64: Final = re.compile(r"^[0-9a-f]{64}$")
_ENTRYPOINT_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_MANIFEST_NAME: Final = "runtime-closure-v1.json"
_MANIFEST_MAX_BYTES: Final = 64 * 1024
_RUNTIME_FILE_MAX_BYTES: Final = 512 * 1024 * 1024
_ROLES: Final = frozenset({"interpreter", "stdlib", "dynload", "runner", "distribution"})


def _require_hex64(value: object, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{name} must be bare hex64")
    return value


def _canonical_relative(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"{name} must be a canonical relative path")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{name} must be NFC normalized")
    parts = value.split("/")
    if value.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{name} must be a canonical relative path")
    return value


def _closure_failure() -> KnownNotExecuted:
    return KnownNotExecuted(
        code="hermetic_runtime_closure_invalid",
        message="skill-runtime-v1 closure could not be verified",
    )


@dataclass(frozen=True, slots=True)
class HermeticRuntimeFileV1:
    path: str
    role: str
    mode: int
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _canonical_relative(self.path, "runtime inventory path")
        if self.role not in _ROLES:
            raise ValueError("runtime inventory role is not closed")
        if (
            not isinstance(self.mode, int)
            or isinstance(self.mode, bool)
            or self.mode not in {0o444, 0o555}
            or not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
            or self.size > _RUNTIME_FILE_MAX_BYTES
        ):
            raise ValueError("runtime inventory mode or size is invalid")
        _require_hex64(self.sha256, "runtime file digest")


@dataclass(frozen=True, slots=True)
class HermeticRuntimeClosureV1:
    runtime_root: str
    interpreter_path: str
    readable_roots: tuple[str, ...]
    inventory: tuple[HermeticRuntimeFileV1, ...]
    inventory_digest: str
    manifest_digest: str
    closure_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "readable_roots", tuple(self.readable_roots))
        object.__setattr__(self, "inventory", tuple(self.inventory))
        if not (
            Path(self.runtime_root).is_absolute()
            and Path(self.interpreter_path).is_absolute()
        ):
            raise ValueError("runtime closure paths must be absolute")
        sorted_roots = tuple(
            sorted(self.readable_roots, key=lambda item: item.encode("utf-8"))
        )
        if sorted_roots != self.readable_roots:
            raise ValueError("runtime readable roots must be byte-sorted")
        if any(not Path(item).is_absolute() for item in self.readable_roots):
            raise ValueError("runtime readable roots must be absolute")
        sorted_inventory = tuple(
            sorted(self.inventory, key=lambda item: item.path.encode("utf-8"))
        )
        if sorted_inventory != self.inventory:
            raise ValueError("runtime inventory must be sorted")
        if len({item.path for item in self.inventory}) != len(self.inventory):
            raise ValueError("runtime inventory paths must be unique")
        _require_hex64(self.inventory_digest, "runtime inventory digest")
        inventory_digest = canonical_json_digest([asdict(item) for item in self.inventory])
        if inventory_digest != self.inventory_digest:
            raise ValueError("runtime inventory digest mismatch")
        _require_hex64(self.manifest_digest, "runtime manifest digest")
        digest = canonical_json_digest(
            {
                "domain": "first-agent-skill-runtime-v1",
                "runtime_root": self.runtime_root,
                "interpreter_path": self.interpreter_path,
                "readable_roots": list(self.readable_roots),
                "inventory_digest": self.inventory_digest,
                "manifest_digest": self.manifest_digest,
            }
        )
        if self.closure_digest and self.closure_digest != digest:
            raise ValueError("runtime closure digest mismatch")
        object.__setattr__(self, "closure_digest", digest)


def _open_root(root: Path) -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise OSError("required no-follow directory support is unavailable")
    supplied = root.absolute()
    info = supplied.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError("runtime root is not an owned regular directory")
    absolute = supplied.resolve(strict=True)
    return os.open(absolute, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _stat_is_stable(before: os.stat_result, after: os.stat_result) -> bool:
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


def _require_regular_owned_single_link(info: os.stat_result, *, cap: int) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size < 0
        or info.st_size > cap
    ):
        raise OSError("runtime file is not a bounded owned single-link regular file")


def _read_fd_bounded(fd: int, expected_size: int, *, cap: int) -> bytes:
    if expected_size > cap:
        raise OSError("runtime file exceeds fixed scan cap")
    chunks: list[bytes] = []
    remaining = expected_size + 1
    while remaining:
        chunk = os.read(fd, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    if len(raw) != expected_size:
        raise OSError("runtime file changed while being read")
    return raw


def _open_relative_parent(root_fd: int, parts: tuple[str, ...], *, create: bool = False) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=current)
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            info = os.fstat(child)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                os.close(child)
                raise OSError("runtime directory is not owned and regular")
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _read_relative_file(root_fd: int, path: str, *, cap: int) -> tuple[bytes, os.stat_result]:
    parts = tuple(path.split("/"))
    parent_fd = _open_relative_parent(root_fd, parts[:-1])
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)
    try:
        before = os.fstat(fd)
        _require_regular_owned_single_link(before, cap=cap)
        raw = _read_fd_bounded(fd, before.st_size, cap=cap)
        after = os.fstat(fd)
        if not _stat_is_stable(before, after):
            raise OSError("runtime file changed while being read")
        return raw, after
    finally:
        os.close(fd)


def _loads_canonical_json(raw: bytes, *, name: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{name} contains duplicate key")
            result[key] = value
        return result

    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _constant: (_ for _ in ()).throw(ValueError("non-finite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{name} is not canonical JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if raw != canonical:
        raise ValueError(f"{name} is not canonical JSON")
    return value


def _manifest_roots(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of canonical roots")
    roots = tuple(_canonical_relative(item, name) for item in value)
    sorted_roots = tuple(sorted(roots, key=lambda item: item.encode("utf-8")))
    if sorted_roots != roots or len(set(roots)) != len(roots):
        raise ValueError(f"{name} must be byte-sorted and unique")
    return roots


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root + "/")


def _is_declared_directory(
    path: str, *, interpreter: str, roots_by_role: dict[str, tuple[str, ...]]
) -> bool:
    return interpreter.startswith(path + "/") or any(
        _under(path, root) or _under(root, path)
        for roots in roots_by_role.values()
        for root in roots
    )


def _file_role(
    path: str,
    *,
    interpreter: str,
    roots_by_role: dict[str, tuple[str, ...]],
) -> str | None:
    if path == interpreter:
        return "interpreter"
    matches = [
        role
        for role, roots in roots_by_role.items()
        if any(path.startswith(root + "/") for root in roots)
    ]
    if len(matches) != 1:
        return None
    return matches[0]


def _scan_runtime_tree(
    root_fd: int,
    *,
    interpreter: str,
    roots_by_role: dict[str, tuple[str, ...]],
) -> tuple[HermeticRuntimeFileV1, ...]:
    inventory: list[HermeticRuntimeFileV1] = []

    def scan(directory_fd: int, prefix: str) -> None:
        entries = list(os.scandir(directory_fd))
        for entry in entries:
            if entry.name == _MANIFEST_NAME and not prefix:
                continue
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            _canonical_relative(relative, "runtime tree path")
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                raise OSError("runtime tree contains a symlink")
            if stat.S_ISDIR(info.st_mode):
                if info.st_uid != os.getuid() or not _is_declared_directory(
                    relative, interpreter=interpreter, roots_by_role=roots_by_role
                ):
                    raise OSError("runtime tree contains an unknown directory")
                child_fd = os.open(
                    entry.name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    scan(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            role = _file_role(relative, interpreter=interpreter, roots_by_role=roots_by_role)
            if role is None:
                raise OSError("runtime tree contains an unknown file")
            _require_regular_owned_single_link(info, cap=_RUNTIME_FILE_MAX_BYTES)
            raw, stable = _read_relative_file(root_fd, relative, cap=_RUNTIME_FILE_MAX_BYTES)
            mode = stat.S_IMODE(stable.st_mode)
            expected_mode = 0o555 if role == "interpreter" else 0o444
            if mode != expected_mode:
                raise OSError("runtime file mode is not canonical")
            inventory.append(
                HermeticRuntimeFileV1(
                    path=relative,
                    role=role,
                    mode=mode,
                    size=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )

    scan(root_fd, "")
    return tuple(sorted(inventory, key=lambda item: item.path.encode("utf-8")))


def qualify_hermetic_runtime_closure(
    root: Path | str,
) -> HermeticRuntimeClosureV1 | KnownNotExecuted:
    """验证 immutable ``skill-runtime-v1``；任何不确定性一律不执行。"""

    try:
        supplied_root = Path(root).absolute()
        if stat.S_ISLNK(supplied_root.lstat().st_mode):
            raise OSError("runtime root is not canonical")
        runtime_root = supplied_root.resolve(strict=True)
        root_fd = _open_root(runtime_root)
        try:
            raw_manifest, _ = _read_relative_file(root_fd, _MANIFEST_NAME, cap=_MANIFEST_MAX_BYTES)
            manifest = _loads_canonical_json(raw_manifest, name="runtime closure manifest")
            if set(manifest) != {
                "schema",
                "interpreter",
                "stdlib_roots",
                "dynload_roots",
                "runner_roots",
                "distribution_roots",
                "inventory_digest",
            }:
                raise ValueError("runtime closure manifest keys are not closed")
            if manifest["schema"] != "first-agent-skill-runtime-closure/v1":
                raise ValueError("runtime closure manifest schema is not closed")
            interpreter = _canonical_relative(manifest["interpreter"], "interpreter")
            roots_by_role = {
                "stdlib": _manifest_roots(manifest["stdlib_roots"], "stdlib_roots"),
                "dynload": _manifest_roots(manifest["dynload_roots"], "dynload_roots"),
                "runner": _manifest_roots(manifest["runner_roots"], "runner_roots"),
                "distribution": _manifest_roots(
                    manifest["distribution_roots"], "distribution_roots"
                ),
            }
            all_roots = (interpreter, *[item for roots in roots_by_role.values() for item in roots])
            if len(set(all_roots)) != len(all_roots):
                raise ValueError("runtime closure roots overlap")
            for first in all_roots:
                if any(first != second and _under(first, second) for second in all_roots):
                    raise ValueError("runtime closure roots overlap")
            inventory = _scan_runtime_tree(
                root_fd,
                interpreter=interpreter,
                roots_by_role=roots_by_role,
            )
            if not any(
                item.path == interpreter and item.role == "interpreter" for item in inventory
            ):
                raise ValueError("runtime interpreter is absent from inventory")
            if not any(
                item.role == "runner"
                and item.path.endswith("/first_agent_skill_runner/__main__.py")
                and any(
                    item.path.startswith(root_name + "/")
                    for root_name in roots_by_role["runner"]
                )
                for item in inventory
            ):
                raise ValueError("runtime runner __main__.py is not declared")
            inventory_digest = canonical_json_digest([asdict(item) for item in inventory])
            if inventory_digest != _require_hex64(manifest["inventory_digest"], "inventory_digest"):
                raise ValueError("runtime inventory digest drifted")
            readable_roots = tuple(
                sorted(
                    {
                        str(runtime_root / interpreter.rsplit("/", 1)[0])
                        if "/" in interpreter
                        else str(runtime_root),
                        *(
                            str(runtime_root / root_name)
                            for roots in roots_by_role.values()
                            for root_name in roots
                        ),
                    },
                    key=lambda item: item.encode("utf-8"),
                )
            )
            return HermeticRuntimeClosureV1(
                runtime_root=str(runtime_root),
                interpreter_path=str(runtime_root / interpreter),
                readable_roots=readable_roots,
                inventory=inventory,
                inventory_digest=inventory_digest,
                manifest_digest=hashlib.sha256(raw_manifest).hexdigest(),
            )
        finally:
            os.close(root_fd)
    except (OSError, ValueError, TypeError):
        return _closure_failure()


def prepare_hermetic_skill_process(
    closure: HermeticRuntimeClosureV1,
    *,
    package_root: Path,
    package_digest: str,
    entrypoint_id: str,
) -> PreparedProcessV1 | KnownNotExecuted:
    """只准备固定 runner command；不读取 package 或发现 entrypoint。"""

    _require_hex64(package_digest, "package_digest")
    if _ENTRYPOINT_ID.fullmatch(entrypoint_id) is None:
        raise ValueError("entrypoint_id has an invalid shape")
    supplied_package = Path(package_root).absolute()
    if not supplied_package.is_dir() or supplied_package.is_symlink():
        raise ValueError("package_root must be a canonical directory")
    package = supplied_package.resolve(strict=True)
    runtime = Path(closure.runtime_root)
    if package == runtime or package.is_relative_to(runtime) or runtime.is_relative_to(package):
        raise ValueError("package_root overlaps hermetic runtime closure")
    return prepare_process(
        {
            "executable": closure.interpreter_path,
            "argv": [
                "-I",
                "-m",
                "first_agent_skill_runner",
                "--package",
                package_digest,
                "--entrypoint",
                entrypoint_id,
            ],
            "cwd": ".",
            "profile": "standard",
        },
        workspace=package,
        captured_path="",
    )
