"""018 opaque browser session/action lifecycle ledger（plan Task 2 Step 4）。

browser-owned bounded ledger：只存 opaque IDs/digests、closed phases 与 last
action outcome，不存页面正文、URL 原文、cookie 或 account label。迁移集
``OPENING→ACTIVE→ACTION_PREPARED→EXECUTING→RESULT_OBSERVED→CLOSED`` 冻结；
EXECUTING 而无 result 的记录是 recoverable unknown，绝不静默转 not-executed。
profile revision drift 使整个 site-bound session authority 失效：所有公开
mutation（compare_and_swap/record_observation/begin_action/record_result/
close）都要求显式 expected_profile_revision 并在 effect 前重验；公开
compare_and_swap 只做机械迁移（OPENING→ACTIVE、ACTION_PREPARED→
EXECUTING），不能绕过专用 API 的 binding/revision。所有 mutation 走
flock CAS + 重读校验，调用方必须持有与存储一致的完整 record
（forged/stale 拒绝）。
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SESSION_ID_PATTERN = re.compile(r"session-[0-9a-f]{16}")
PROFILE_ID_PATTERN = re.compile(r"profile-[0-9a-f]{16}")
HEX64_PATTERN = re.compile(r"[0-9a-f]{64}")
LEDGER_NAME = "ledger.json"
MAX_LEDGER_BYTES = 16 * 1024
LEDGER_KEYS = frozenset(
    {
        "session_id",
        "spec_digest",
        "profile_ref",
        "profile_revision",
        "browser_identity_digest",
        "phase",
        "observation_digest",
        "last_action_digest",
        "last_action_outcome",
        "action_count",
    }
)


class SessionIntegrityError(Exception):
    """ledger 不再可信（corrupt/symlink/forged 或 stale record）。"""


class SessionNotFoundError(Exception):
    """请求的 opaque session 不存在。"""


class SessionPhaseConflict(Exception):  # noqa: N818  测试冻结的公开合同名
    """phase CAS 失败：非法迁移、非源阶段或 stale phase。"""


class SessionObservationBindingError(Exception):
    """action 未绑定 current observation digest。"""


class SessionProfileDriftError(Exception):
    """profile revision 已漂移，session authority 失效。"""


class SessionPhase(StrEnum):
    OPENING = "opening"
    ACTIVE = "active"
    ACTION_PREPARED = "action_prepared"
    EXECUTING = "executing"
    RESULT_OBSERVED = "result_observed"
    CLOSED = "closed"


class SessionActionOutcome(StrEnum):
    APPLIED = "applied"
    NOT_EXECUTED = "not_executed"
    UNKNOWN = "unknown"


class SessionRecovery(StrEnum):
    NONE = "none"
    UNKNOWN_OUTCOME = "unknown_outcome"


# 冻结的合法迁移集：EXECUTING 不能直接 CLOSED（必须先记录 result），
# CLOSED 是终态。
ALLOWED_TRANSITIONS = frozenset(
    {
        (SessionPhase.OPENING, SessionPhase.ACTIVE),
        (SessionPhase.ACTIVE, SessionPhase.ACTION_PREPARED),
        (SessionPhase.RESULT_OBSERVED, SessionPhase.ACTION_PREPARED),
        (SessionPhase.ACTION_PREPARED, SessionPhase.EXECUTING),
        (SessionPhase.EXECUTING, SessionPhase.RESULT_OBSERVED),
        (SessionPhase.ACTIVE, SessionPhase.CLOSED),
        (SessionPhase.RESULT_OBSERVED, SessionPhase.CLOSED),
    }
)

# 公开 compare_and_swap 只允许纯机械迁移；进入 ACTION_PREPARED、记录
# result、close 都必须走专用 API（observation binding / outcome / profile
# revision 检查），不得经 CAS 绕过。
MECHANICAL_CAS_TRANSITIONS = frozenset(
    {
        (SessionPhase.OPENING, SessionPhase.ACTIVE),
        (SessionPhase.ACTION_PREPARED, SessionPhase.EXECUTING),
    }
)


@dataclass(frozen=True, slots=True)
class BrowserSessionRecordV1:
    """opaque session 状态投影；没有 URL/body/cookie/account 原文的安放处。"""

    session_id: str
    spec_digest: str
    profile_ref: str | None
    profile_revision: int | None
    browser_identity_digest: str
    phase: SessionPhase
    observation_digest: str | None
    last_action_digest: str | None
    last_action_outcome: SessionActionOutcome | None
    action_count: int


def _read_bounded_json(fd: int, *, limit: int) -> object:
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise SessionIntegrityError("ledger exceeds the bounded size")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as decode_error:
        raise SessionIntegrityError("ledger is not valid JSON") from decode_error


def _require_digest(value: object, field: str, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or HEX64_PATTERN.fullmatch(value) is None:
        raise SessionIntegrityError(f"{field} must be 64 lowercase hex chars")


class BrowserSessionStore:
    """session ledger 的唯一 owner；所有操作锚定在 owned root fd 上。"""

    def __init__(self, *, root: Path) -> None:
        self._root = Path(root)

    # ------------------------------------------------------------------ #
    # dirfd 锚定的基础设施
    # ------------------------------------------------------------------ #

    @contextlib.contextmanager
    def _sessions_root_fd(self) -> int:
        try:
            fd = os.open(self._root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise SessionNotFoundError("sessions root missing") from None
        except OSError as error:
            raise SessionIntegrityError("sessions root must be a real directory") from error
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def _session_dir_fd(self, root_fd: int, session_id: str) -> int:
        self._require_session_id(session_id)
        try:
            fd = os.open(
                session_id,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError as error:
            raise SessionNotFoundError(f"session {session_id!r} does not exist") from error
        except OSError as error:
            raise SessionIntegrityError("session directory must be real") from error
        try:
            if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
                os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)

    @staticmethod
    def _require_session_id(session_id: str) -> None:
        if SESSION_ID_PATTERN.fullmatch(session_id) is None:
            raise SessionNotFoundError(f"session {session_id!r} does not exist")

    # ------------------------------------------------------------------ #
    # closed decode / record 校验
    # ------------------------------------------------------------------ #

    @staticmethod
    def _decode_ledger(payload: object) -> dict:
        if not isinstance(payload, dict) or set(payload) != LEDGER_KEYS:
            raise SessionIntegrityError("ledger keys are not the closed contract")
        if not isinstance(payload["session_id"], str):
            raise SessionIntegrityError("session_id must be a string")
        if SESSION_ID_PATTERN.fullmatch(payload["session_id"]) is None:
            raise SessionIntegrityError("session_id is not an opaque id")
        _require_digest(payload["spec_digest"], "spec_digest")
        _require_digest(payload["browser_identity_digest"], "browser_identity_digest")
        _require_digest(payload["observation_digest"], "observation_digest", nullable=True)
        _require_digest(payload["last_action_digest"], "last_action_digest", nullable=True)
        if payload["profile_ref"] is not None and (
            not isinstance(payload["profile_ref"], str)
            or PROFILE_ID_PATTERN.fullmatch(payload["profile_ref"]) is None
        ):
            raise SessionIntegrityError("profile_ref must be an opaque id or null")
        if payload["profile_revision"] is not None and (
            type(payload["profile_revision"]) is not int or payload["profile_revision"] <= 0
        ):
            raise SessionIntegrityError("profile_revision must be a positive int or null")
        # 配对：同时 null 或同时完整；一边有值的损坏 ledger fail closed。
        if (payload["profile_ref"] is None) != (payload["profile_revision"] is None):
            raise SessionIntegrityError("profile binding must be null-paired or complete")
        if type(payload["action_count"]) is not int or payload["action_count"] < 0:
            raise SessionIntegrityError("action_count must be a non-negative int")
        try:
            SessionPhase(payload["phase"])
        except ValueError as error:
            raise SessionIntegrityError("phase must be an exact member") from error
        if payload["last_action_outcome"] is not None:
            try:
                SessionActionOutcome(payload["last_action_outcome"])
            except ValueError as error:
                raise SessionIntegrityError("outcome must be an exact member") from error
        BrowserSessionStore._verify_phase_shape(payload)
        return payload

    @staticmethod
    def _verify_phase_shape(payload: dict) -> None:
        # 跨字段矛盾一律 fail closed：phase 与 action/observation 数据必须自洽。
        phase = payload["phase"]
        has_action = payload["last_action_digest"] is not None
        has_outcome = payload["last_action_outcome"] is not None
        count = payload["action_count"]
        if phase == SessionPhase.OPENING.value:
            if payload["observation_digest"] is not None or has_action or has_outcome or count:
                raise SessionIntegrityError("OPENING must carry no action/observation data")
        elif phase == SessionPhase.ACTIVE.value:
            if has_action or has_outcome or count:
                raise SessionIntegrityError("ACTIVE must carry no action data")
        elif phase in (SessionPhase.ACTION_PREPARED.value, SessionPhase.EXECUTING.value):
            if (
                not has_action
                or has_outcome
                or count <= 0
                or payload["observation_digest"] is None
            ):
                raise SessionIntegrityError(
                    "prepared/executing must bind action and current observation"
                )
        elif phase == SessionPhase.RESULT_OBSERVED.value and (
            not has_action or not has_outcome or count <= 0
            or payload["observation_digest"] is None
        ):
            raise SessionIntegrityError("result_observed must bind action and outcome")
        elif phase == SessionPhase.CLOSED.value:
            # CLOSED 只接受两个合法来源形态的 union；混合形态 fail closed。
            from_active = not has_action and not has_outcome and count == 0
            from_observed = (
                has_action and has_outcome and count > 0
                and payload["observation_digest"] is not None
            )
            if not (from_active or from_observed):
                raise SessionIntegrityError("closed ledger must match a legal source shape")

    @staticmethod
    def _record_from_payload(payload: dict) -> BrowserSessionRecordV1:
        return BrowserSessionRecordV1(
            session_id=payload["session_id"],
            spec_digest=payload["spec_digest"],
            profile_ref=payload["profile_ref"],
            profile_revision=payload["profile_revision"],
            browser_identity_digest=payload["browser_identity_digest"],
            phase=SessionPhase(payload["phase"]),
            observation_digest=payload["observation_digest"],
            last_action_digest=payload["last_action_digest"],
            last_action_outcome=(
                SessionActionOutcome(payload["last_action_outcome"])
                if payload["last_action_outcome"] is not None
                else None
            ),
            action_count=payload["action_count"],
        )

    @staticmethod
    def _verify_record(record: BrowserSessionRecordV1, current: dict) -> None:
        # 调用方 record 必须与存储一致：identity 漂移=forged，数据漂移=stale。
        if (
            record.session_id != current["session_id"]
            or record.spec_digest != current["spec_digest"]
            or record.profile_ref != current["profile_ref"]
            or record.profile_revision != current["profile_revision"]
            or record.browser_identity_digest != current["browser_identity_digest"]
        ):
            raise SessionIntegrityError("session record does not match stored identity")
        if record.phase.value != current["phase"]:
            raise SessionPhaseConflict("session record phase is stale")
        if (
            record.observation_digest != current["observation_digest"]
            or record.last_action_digest != current["last_action_digest"]
            or record.last_action_outcome != current["last_action_outcome"]
            or record.action_count != current["action_count"]
        ):
            raise SessionIntegrityError("session record data is stale")

    # ------------------------------------------------------------------ #
    # 通用 mutation：flock CAS + 重读校验
    # ------------------------------------------------------------------ #

    def _mutate(
        self,
        record: BrowserSessionRecordV1,
        *,
        expected_profile_revision: int | None,
        apply,
    ) -> BrowserSessionRecordV1:
        with (
            self._sessions_root_fd() as root_fd,
            self._session_dir_fd(root_fd, record.session_id) as session_fd,
        ):
            try:
                fd = os.open(
                    LEDGER_NAME,
                    os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=session_fd,
                )
            except OSError as error:
                raise SessionIntegrityError("ledger not updatable") from error
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise SessionIntegrityError("ledger must be a regular file")
                if stat.S_IMODE(info.st_mode) & 0o077:
                    os.fchmod(fd, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                except OSError as error:
                    raise SessionIntegrityError("ledger cannot be locked") from error
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    current = self._decode_ledger(
                        _read_bounded_json(fd, limit=MAX_LEDGER_BYTES)
                    )
                    self._verify_record(record, current)
                    # spec §4.2：profile revision 漂移使整个 session authority
                    # 失效——每个公开 mutation（含机械 CAS）都显式重验。
                    if expected_profile_revision != current["profile_revision"]:
                        raise SessionProfileDriftError(
                            "profile revision drifted; session authority is void"
                        )
                    new_payload = apply(current)
                    encoded = json.dumps(new_payload, sort_keys=True).encode("utf-8")
                    os.lseek(fd, 0, os.SEEK_SET)
                    os.truncate(fd, 0)
                    os.write(fd, encoded)
                    os.fsync(fd)
                finally:
                    with contextlib.suppress(OSError):
                        fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
            return self._record_from_payload(new_payload)

    # ------------------------------------------------------------------ #
    # 公开 API
    # ------------------------------------------------------------------ #

    def begin(
        self,
        *,
        spec,
        profile_revision: int | None,
        browser_identity_digest: str,
        session_ref: str | None = None,
    ) -> BrowserSessionRecordV1:
        from agent.browser.contracts import BrowserSessionSpecV1

        if not isinstance(spec, BrowserSessionSpecV1):
            raise SessionIntegrityError("spec must be a BrowserSessionSpecV1")
        _require_digest(browser_identity_digest, "browser_identity_digest")
        # profile_ref/profile_revision 配对必须在写盘前成立：public-read 两者
        # 皆 None；site-bound 必须 canonical opaque ref + positive revision。
        if spec.profile_ref is None:
            if profile_revision is not None:
                raise SessionIntegrityError(
                    "public-read session must not carry a profile revision"
                )
        else:
            if PROFILE_ID_PATTERN.fullmatch(spec.profile_ref) is None:
                raise SessionIntegrityError("profile_ref must be an opaque canonical id")
            if type(profile_revision) is not int or profile_revision <= 0:
                raise SessionIntegrityError(
                    "site-bound session requires a positive profile revision"
                )
        try:
            os.makedirs(self._root, 0o700, exist_ok=True)
        except OSError as error:
            raise SessionIntegrityError("sessions root cannot be created") from error
        session_id = session_ref or f"session-{secrets.token_hex(8)}"
        self._require_session_id(session_id)
        payload = {
            "session_id": session_id,
            "spec_digest": spec.identity_digest,
            "profile_ref": spec.profile_ref,
            "profile_revision": profile_revision,
            "browser_identity_digest": browser_identity_digest,
            "phase": SessionPhase.OPENING.value,
            "observation_digest": None,
            "last_action_digest": None,
            "last_action_outcome": None,
            "action_count": 0,
        }
        # 单一 truth：begin 构造的 payload 必须先通过与 load 相同的 closed
        # decode（含配对与 phase shape），杜绝 begin/load 规则漂移。
        self._decode_ledger(payload)
        with self._sessions_root_fd() as root_fd:
            try:
                os.mkdir(session_id, 0o700, dir_fd=root_fd)
            except OSError as error:
                raise SessionIntegrityError("cannot create session directory") from error
            with self._session_dir_fd(root_fd, session_id) as session_fd:
                try:
                    fd = os.open(
                        LEDGER_NAME,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=session_fd,
                    )
                except OSError as error:
                    raise SessionIntegrityError("cannot create ledger") from error
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
        return self._record_from_payload(payload)

    def load(self, session_id: str) -> BrowserSessionRecordV1:
        with (
            self._sessions_root_fd() as root_fd,
            self._session_dir_fd(root_fd, session_id) as session_fd,
        ):
            try:
                fd = os.open(
                    LEDGER_NAME,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=session_fd,
                )
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise SessionIntegrityError("ledger must not be a symlink") from error
                raise SessionNotFoundError("ledger missing") from error
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise SessionIntegrityError("ledger must be a regular file")
                if stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
                    os.fchmod(fd, 0o600)
                payload = self._decode_ledger(
                    _read_bounded_json(fd, limit=MAX_LEDGER_BYTES)
                )
            finally:
                os.close(fd)
        return self._record_from_payload(payload)

    def compare_and_swap(
        self,
        record: BrowserSessionRecordV1,
        *,
        new_phase: SessionPhase,
        expected_profile_revision: int | None,
    ) -> BrowserSessionRecordV1:
        def apply(current: dict) -> dict:
            if (SessionPhase(current["phase"]), new_phase) not in MECHANICAL_CAS_TRANSITIONS:
                raise SessionPhaseConflict(
                    f"CAS only performs mechanical transitions; "
                    f"{current['phase']} -> {new_phase.value} needs a domain-specific API"
                )
            return {**current, "phase": new_phase.value}

        return self._mutate(
            record,
            expected_profile_revision=expected_profile_revision,
            apply=apply,
        )

    def record_observation(
        self,
        record: BrowserSessionRecordV1,
        *,
        observation_digest: str,
        expected_profile_revision: int | None,
    ) -> BrowserSessionRecordV1:
        _require_digest(observation_digest, "observation_digest")

        def apply(current: dict) -> dict:
            if current["phase"] not in (
                SessionPhase.ACTIVE.value,
                SessionPhase.RESULT_OBSERVED.value,
            ):
                raise SessionPhaseConflict("observation requires an active session")
            return {**current, "observation_digest": observation_digest}

        return self._mutate(
            record,
            expected_profile_revision=expected_profile_revision,
            apply=apply,
        )

    def begin_action(
        self,
        record: BrowserSessionRecordV1,
        *,
        action_digest: str,
        observation_digest: str,
        expected_profile_revision: int | None,
    ) -> BrowserSessionRecordV1:
        _require_digest(action_digest, "action_digest")
        _require_digest(observation_digest, "observation_digest")

        def apply(current: dict) -> dict:
            if current["phase"] not in (
                SessionPhase.ACTIVE.value,
                SessionPhase.RESULT_OBSERVED.value,
            ):
                raise SessionPhaseConflict("action requires a settled session")
            # action-observation binding：必须引用 current observation。
            if observation_digest != current["observation_digest"]:
                raise SessionObservationBindingError(
                    "action must bind the current observation digest"
                )
            return {
                **current,
                "phase": SessionPhase.ACTION_PREPARED.value,
                "last_action_digest": action_digest,
                "last_action_outcome": None,
                "action_count": current["action_count"] + 1,
            }

        return self._mutate(
            record, expected_profile_revision=expected_profile_revision, apply=apply
        )

    def record_result(
        self,
        record: BrowserSessionRecordV1,
        *,
        outcome: SessionActionOutcome,
        expected_profile_revision: int | None,
    ) -> BrowserSessionRecordV1:
        if not isinstance(outcome, SessionActionOutcome):
            raise SessionIntegrityError("outcome must be a SessionActionOutcome")

        def apply(current: dict) -> dict:
            if current["phase"] != SessionPhase.EXECUTING.value:
                raise SessionPhaseConflict("result requires an EXECUTING session")
            return {
                **current,
                "phase": SessionPhase.RESULT_OBSERVED.value,
                "last_action_outcome": outcome.value,
            }

        return self._mutate(
            record, expected_profile_revision=expected_profile_revision, apply=apply
        )

    def close(
        self,
        record: BrowserSessionRecordV1,
        *,
        expected_profile_revision: int | None,
    ) -> BrowserSessionRecordV1:
        def apply(current: dict) -> dict:
            if (SessionPhase(current["phase"]), SessionPhase.CLOSED) not in (
                ALLOWED_TRANSITIONS
            ):
                raise SessionPhaseConflict("session cannot close from this phase")
            return {**current, "phase": SessionPhase.CLOSED.value}

        return self._mutate(
            record, expected_profile_revision=expected_profile_revision, apply=apply
        )

    @staticmethod
    def pending_recovery(record: BrowserSessionRecordV1) -> SessionRecovery:
        # EXECUTING 而无 result：recoverable unknown，绝不静默转 not-executed。
        if (
            record.phase is SessionPhase.EXECUTING
            and record.last_action_outcome is None
        ):
            return SessionRecovery.UNKNOWN_OUTCOME
        return SessionRecovery.NONE
