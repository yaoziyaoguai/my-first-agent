"""013 ProviderProfileV1 — owner-only、non-secret 的一次 setup Provider 配置。

profile 是 composition configuration,不是 conversation checkpoint:它只保存
非秘密 metadata,credential value 永远只按 credential_env 名称在 composition
root 从环境注入。文件语义与 state root 其余部分一致:0700 目录、0600 单链接
regular 文件、no-follow、strict schema、同目录临时文件 + fsync + atomic replace。
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent.provider.config import AgentProviderConfig

PROFILE_FILE_NAME = "provider-profile.json"
PROFILE_SCHEMA_VERSION = 1

_PERSISTABLE_PROVIDER_TYPES = frozenset({"anthropic_compatible", "openai_compatible"})
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_PROFILE_BYTES = 64 * 1024
_MAX_BASE_URL_CHARS = 2000
_MAX_MODEL_CHARS = 256
_MAX_REQUEST_PATH_CHARS = 1000
_MAX_TIMEOUT_SECONDS = 3600.0

_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "provider_type",
        "model",
        "base_url",
        "credential_env",
        "thinking_mode",
        "request_path",
        "strict_tools",
        "timeout_seconds",
    }
)


class ProviderProfileError(ValueError):
    """profile 内容、schema 或文件安全属性不满足合同。"""


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value)


def _validate_base_url(base_url: str) -> str:
    if not base_url or len(base_url) > _MAX_BASE_URL_CHARS:
        raise ProviderProfileError("base URL is empty or exceeds its bound")
    if _has_control_chars(base_url) or any(ch.isspace() for ch in base_url):
        raise ProviderProfileError("base URL contains control or whitespace characters")
    try:
        parts = urlsplit(base_url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise ProviderProfileError("base URL is malformed") from error
    if parts.scheme not in {"https", "http"}:
        raise ProviderProfileError("base URL must use https (or loopback http)")
    if not hostname:
        raise ProviderProfileError("base URL must include a host")
    if parts.scheme == "http" and hostname not in _LOOPBACK_HOSTS:
        raise ProviderProfileError("plain http is only allowed for loopback development")
    if parts.username is not None or parts.password is not None:
        raise ProviderProfileError("base URL must not embed userinfo")
    if parts.query or parts.fragment:
        raise ProviderProfileError("base URL must not carry query or fragment")
    normalized = base_url.rstrip("/")
    if not urlsplit(normalized).netloc:
        raise ProviderProfileError("base URL host is missing after normalization")
    return normalized


def _validate_request_path(request_path: str | None) -> str | None:
    if request_path is None:
        return None
    if (
        not request_path
        or len(request_path) > _MAX_REQUEST_PATH_CHARS
        or not request_path.startswith("/")
        or request_path.startswith("//")
        or _has_control_chars(request_path)
        or any(ch.isspace() for ch in request_path)
        or "?" in request_path
        or "#" in request_path
    ):
        raise ProviderProfileError("request path is malformed")
    return request_path


@dataclass(frozen=True, slots=True)
class ProviderProfileV1:
    """一次 setup 保存的 non-secret Provider 选择;禁止保存任何 credential。"""

    provider_type: str
    model: str
    base_url: str
    credential_env: str
    thinking_mode: str | None = None
    request_path: str | None = None
    strict_tools: bool = False
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.provider_type not in _PERSISTABLE_PROVIDER_TYPES:
            # FakeProvider 只能显式用于开发测试,不允许成为持久化日常 profile。
            raise ProviderProfileError("provider type cannot be persisted as a profile")

        model = self.model.strip()
        if not model or len(model) > _MAX_MODEL_CHARS or _has_control_chars(model):
            raise ProviderProfileError("model name is empty, oversized, or unsafe")
        object.__setattr__(self, "model", model)

        object.__setattr__(self, "base_url", _validate_base_url(self.base_url))

        if not _ENV_NAME.fullmatch(self.credential_env):
            raise ProviderProfileError("credential env name is not a safe variable name")

        if self.thinking_mode is not None and (
            self.thinking_mode != "disabled" or self.provider_type != "openai_compatible"
        ):
            raise ProviderProfileError("thinking_mode only supports openai disabled")
        object.__setattr__(self, "request_path", _validate_request_path(self.request_path))
        if not isinstance(self.strict_tools, bool):
            raise ProviderProfileError("strict_tools must be a boolean")
        if self.strict_tools and self.provider_type != "openai_compatible":
            raise ProviderProfileError("strict_tools only supports openai compatible")

        timeout = self.timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ProviderProfileError("timeout must be a real number")
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0 or timeout > _MAX_TIMEOUT_SECONDS:
            raise ProviderProfileError("timeout is outside the supported range")
        object.__setattr__(self, "timeout_seconds", timeout)


def profile_path(state_root: Path) -> Path:
    return Path(state_root) / PROFILE_FILE_NAME


def to_provider_config(
    profile: ProviderProfileV1, *, credential: str | None = None
) -> AgentProviderConfig:
    """投影为既有 AgentProviderConfig;credential 只由 composition root 传入。"""
    return AgentProviderConfig(
        provider_type=profile.provider_type,
        model=profile.model,
        base_url=profile.base_url,
        credential=credential,
        timeout=profile.timeout_seconds,
        thinking_mode=profile.thinking_mode,
        request_path=profile.request_path,
        strict_tools=profile.strict_tools,
    )


def _reject_symlink_components(path: Path) -> None:
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode):
                raise ProviderProfileError("profile path must not traverse symlinks")
        if current.parent == current:
            return
        current = current.parent


def _ensure_owner_state_root(state_root: Path, *, create: bool) -> None:
    if create:
        with suppress(FileExistsError):
            state_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        info = state_root.lstat()
    except FileNotFoundError as error:
        raise ProviderProfileError("state root is missing") from error
    if not stat.S_ISDIR(info.st_mode):
        raise ProviderProfileError("state root must be a real directory")
    if info.st_uid != os.getuid():
        raise ProviderProfileError("state root owner mismatch")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise ProviderProfileError("state root mode must be 0700")


def _open_state_root_fd(state_root: Path) -> int:
    try:
        return os.open(state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ProviderProfileError("state root cannot be opened safely") from error


def _encode_profile(profile: ProviderProfileV1) -> bytes:
    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "provider_type": profile.provider_type,
        "model": profile.model,
        "base_url": profile.base_url,
        "credential_env": profile.credential_env,
        "thinking_mode": profile.thinking_mode,
        "request_path": profile.request_path,
        "strict_tools": profile.strict_tools,
        "timeout_seconds": profile.timeout_seconds,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode()


def save_provider_profile(state_root: Path, profile: ProviderProfileV1) -> Path:
    root = Path(state_root).absolute()
    _reject_symlink_components(root)
    _ensure_owner_state_root(root, create=True)
    data = _encode_profile(profile)
    directory_fd = _open_state_root_fd(root)
    temp_name = f".{PROFILE_FILE_NAME}.tmp-{secrets.token_hex(8)}"
    temp_created = False
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        temp_created = True
        try:
            os.fchmod(fd, 0o600)
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(
            temp_name,
            PROFILE_FILE_NAME,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temp_created = False
        os.fsync(directory_fd)
    finally:
        if temp_created:
            with suppress(OSError):
                os.unlink(temp_name, dir_fd=directory_fd)
        os.close(directory_fd)
    return profile_path(root)


def _decode_profile(data: bytes) -> ProviderProfileV1:
    try:
        document = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderProfileError("profile document is not valid JSON") from error
    if not isinstance(document, dict):
        raise ProviderProfileError("profile document must be a JSON object")
    if set(document) != _PROFILE_KEYS:
        raise ProviderProfileError("profile document has unknown or missing fields")

    schema_version = document["schema_version"]
    if isinstance(schema_version, bool) or schema_version != PROFILE_SCHEMA_VERSION:
        raise ProviderProfileError("profile schema version is unsupported")
    for key in ("provider_type", "model", "base_url", "credential_env"):
        if not isinstance(document[key], str):
            raise ProviderProfileError(f"profile field {key} must be a string")
    thinking_mode = document["thinking_mode"]
    if thinking_mode is not None and not isinstance(thinking_mode, str):
        raise ProviderProfileError("profile thinking_mode must be null or a string")
    request_path = document["request_path"]
    if request_path is not None and not isinstance(request_path, str):
        raise ProviderProfileError("profile request_path must be null or a string")
    strict_tools = document["strict_tools"]
    if not isinstance(strict_tools, bool):
        raise ProviderProfileError("profile strict_tools must be a boolean")
    timeout_seconds = document["timeout_seconds"]
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ProviderProfileError("profile timeout_seconds must be a number")

    return ProviderProfileV1(
        provider_type=document["provider_type"],
        model=document["model"],
        base_url=document["base_url"],
        credential_env=document["credential_env"],
        thinking_mode=thinking_mode,
        request_path=request_path,
        strict_tools=strict_tools,
        timeout_seconds=float(timeout_seconds),
    )


def load_provider_profile(state_root: Path) -> ProviderProfileV1 | None:
    root = Path(state_root).absolute()
    _reject_symlink_components(root)
    try:
        root.lstat()
    except FileNotFoundError:
        return None
    _ensure_owner_state_root(root, create=False)
    directory_fd = _open_state_root_fd(root)
    try:
        try:
            fd = os.open(
                PROFILE_FILE_NAME,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise ProviderProfileError("profile file cannot be opened safely") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ProviderProfileError("profile must be a regular file")
            if info.st_uid != os.getuid():
                raise ProviderProfileError("profile owner mismatch")
            if info.st_nlink != 1:
                raise ProviderProfileError("profile must have a single hard link")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise ProviderProfileError("profile mode must be 0600")
            if info.st_size > _MAX_PROFILE_BYTES:
                raise ProviderProfileError("profile exceeds its size bound")
            chunks: list[bytes] = []
            remaining = _MAX_PROFILE_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > _MAX_PROFILE_BYTES:
                raise ProviderProfileError("profile exceeds its size bound")
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    return _decode_profile(data)


__all__ = [
    "PROFILE_FILE_NAME",
    "PROFILE_SCHEMA_VERSION",
    "ProviderProfileError",
    "ProviderProfileV1",
    "load_provider_profile",
    "profile_path",
    "save_provider_profile",
    "to_provider_config",
]
