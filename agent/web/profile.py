"""Owner-only、non-secret 的固定 Tavily Web profile。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from agent.runtime.contracts import canonical_json_digest

WEB_PROFILE_FILE_NAME = "web-profile.json"
WEB_PROFILE_SCHEMA_VERSION = 1
TAVILY_DESTINATION = "https://api.tavily.com"
TAVILY_TRUST_NOTICE_ID = "tavily-public-input-v1"
TAVILY_TRUST_NOTICE = (
    "Exact public search queries and approved public source URLs are sent to Tavily "
    "and handled under Tavily's terms. First Agent does not promise third-party zero "
    "retention, training exclusion, or deletion."
)
TAVILY_TRUST_NOTICE_DIGEST = hashlib.sha256(
    TAVILY_TRUST_NOTICE.encode("utf-8")
).hexdigest()

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_PROFILE_BYTES = 16 * 1024
_MAX_RESULTS = 8
_MAX_TIMEOUT_SECONDS = 60.0
_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "provider",
        "destination",
        "credential_env",
        "timeout_seconds",
        "max_results",
        "search_depth",
        "extract_depth",
        "trust_notice_id",
        "trust_notice_digest",
        "profile_digest",
    }
)


class WebProfileError(ValueError):
    """Web profile 内容或文件安全属性不满足固定合同。"""


def _profile_values(profile: WebProfileV1) -> dict[str, object]:
    return {
        "schema_version": WEB_PROFILE_SCHEMA_VERSION,
        "provider": profile.provider,
        "destination": profile.destination,
        "credential_env": profile.credential_env,
        "timeout_seconds": profile.timeout_seconds,
        "max_results": profile.max_results,
        "search_depth": profile.search_depth,
        "extract_depth": profile.extract_depth,
        "trust_notice_id": profile.trust_notice_id,
        "trust_notice_digest": profile.trust_notice_digest,
    }


def _digest_profile(profile: WebProfileV1) -> str:
    return canonical_json_digest(_profile_values(profile))


@dataclass(frozen=True, slots=True)
class WebProfileV1:
    credential_env: str
    timeout_seconds: float = 10.0
    max_results: int = 5
    provider: str = "tavily"
    destination: str = TAVILY_DESTINATION
    search_depth: str = "basic"
    extract_depth: str = "basic"
    trust_notice_id: str = TAVILY_TRUST_NOTICE_ID
    trust_notice_digest: str = TAVILY_TRUST_NOTICE_DIGEST
    profile_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.provider != "tavily":
            raise WebProfileError("Web provider must be tavily")
        if self.destination != TAVILY_DESTINATION:
            raise WebProfileError("Web destination must be the fixed Tavily endpoint")
        if self.search_depth != "basic" or self.extract_depth != "basic":
            raise WebProfileError("Web search and extract depth must remain basic")
        if (
            self.trust_notice_id != TAVILY_TRUST_NOTICE_ID
            or self.trust_notice_digest != TAVILY_TRUST_NOTICE_DIGEST
        ):
            raise WebProfileError("Web trust notice does not match the fixed contract")
        if not _ENV_NAME.fullmatch(self.credential_env):
            raise WebProfileError("credential env name is not a safe variable name")
        if (
            not isinstance(self.max_results, int)
            or isinstance(self.max_results, bool)
            or not 1 <= self.max_results <= _MAX_RESULTS
        ):
            raise WebProfileError("max_results is outside the supported range")
        timeout = self.timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, int | float):
            raise WebProfileError("timeout_seconds must be a real number")
        timeout = float(timeout)
        if (
            not math.isfinite(timeout)
            or timeout < 1.0
            or timeout > _MAX_TIMEOUT_SECONDS
        ):
            raise WebProfileError("timeout_seconds is outside the supported range")
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "profile_digest", _digest_profile(self))


def web_profile_path(state_root: Path) -> Path:
    return Path(state_root) / WEB_PROFILE_FILE_NAME


def _reject_symlink_components(path: Path) -> None:
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(info.st_mode):
                raise WebProfileError("Web profile path must not traverse symlinks")
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
        raise WebProfileError("state root is missing") from error
    if not stat.S_ISDIR(info.st_mode):
        raise WebProfileError("state root must be a real directory")
    if info.st_uid != os.getuid():
        raise WebProfileError("state root owner mismatch")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise WebProfileError("state root mode must be 0700")


def _open_state_root_fd(state_root: Path) -> int:
    try:
        return os.open(state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise WebProfileError("state root cannot be opened safely") from error


def _encode_profile(profile: WebProfileV1) -> bytes:
    payload = {**_profile_values(profile), "profile_digest": profile.profile_digest}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )


def save_web_profile(state_root: Path, profile: WebProfileV1) -> Path:
    root = Path(state_root).absolute()
    _reject_symlink_components(root)
    _ensure_owner_state_root(root, create=True)
    data = _encode_profile(profile)
    directory_fd = _open_state_root_fd(root)
    temp_name = f".{WEB_PROFILE_FILE_NAME}.tmp-{secrets.token_hex(8)}"
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
            WEB_PROFILE_FILE_NAME,
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
    return web_profile_path(root)


def _decode_profile(data: bytes) -> WebProfileV1:
    try:
        document = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WebProfileError("Web profile is not valid JSON") from error
    if not isinstance(document, dict):
        raise WebProfileError("Web profile must be a JSON object")
    if set(document) != _PROFILE_KEYS:
        raise WebProfileError("Web profile has unknown or missing fields")
    if document["schema_version"] != WEB_PROFILE_SCHEMA_VERSION or isinstance(
        document["schema_version"], bool
    ):
        raise WebProfileError("Web profile schema version is unsupported")
    string_fields = (
        "provider",
        "destination",
        "credential_env",
        "search_depth",
        "extract_depth",
        "trust_notice_id",
        "trust_notice_digest",
        "profile_digest",
    )
    if any(not isinstance(document[name], str) for name in string_fields):
        raise WebProfileError("Web profile string fields are malformed")
    profile = WebProfileV1(
        provider=document["provider"],
        destination=document["destination"],
        credential_env=document["credential_env"],
        timeout_seconds=document["timeout_seconds"],
        max_results=document["max_results"],
        search_depth=document["search_depth"],
        extract_depth=document["extract_depth"],
        trust_notice_id=document["trust_notice_id"],
        trust_notice_digest=document["trust_notice_digest"],
    )
    if document["profile_digest"] != profile.profile_digest:
        raise WebProfileError("Web profile digest mismatch")
    return profile


def load_web_profile(state_root: Path) -> WebProfileV1 | None:
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
                WEB_PROFILE_FILE_NAME,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as error:
            raise WebProfileError("Web profile cannot be opened safely") from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WebProfileError("Web profile must be a regular file")
            if info.st_uid != os.getuid():
                raise WebProfileError("Web profile owner mismatch")
            if info.st_nlink != 1:
                raise WebProfileError("Web profile must have a single hard link")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise WebProfileError("Web profile mode must be 0600")
            if info.st_size > _MAX_PROFILE_BYTES:
                raise WebProfileError("Web profile exceeds its size bound")
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
                raise WebProfileError("Web profile exceeds its size bound")
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    return _decode_profile(data)


__all__ = [
    "TAVILY_DESTINATION",
    "TAVILY_TRUST_NOTICE",
    "TAVILY_TRUST_NOTICE_DIGEST",
    "TAVILY_TRUST_NOTICE_ID",
    "WEB_PROFILE_FILE_NAME",
    "WebProfileError",
    "WebProfileV1",
    "load_web_profile",
    "save_web_profile",
    "web_profile_path",
]
