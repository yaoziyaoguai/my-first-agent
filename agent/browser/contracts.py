"""018 governed browser tasks 的 immutable typed 合同（v1）。

只描述跨 boundary 的数据形状与 closed 校验；不拥有 loop、持久化或 adapter 行为。
所有 identity 都由 ``agent.runtime.contracts.canonical_json_digest`` 派生；
唯一 ``KnownNotExecuted`` 由 runtime contracts 拥有，本包只经 ports re-export。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from agent.browser.quarantine import QuarantinedDownloadV1
from agent.runtime.contracts import (
    FrozenJSONDict,
    FrozenJSONList,
    JSONValue,
    canonical_json_digest,
)


class BrowserMode(StrEnum):
    """closed session modes；两种模式不可静默切换（spec §4）。"""

    PUBLIC_READ_EPHEMERAL = "public_read_ephemeral"
    SITE_BOUND_INTERACTIVE = "site_bound_interactive"


class BrowserActionKind(StrEnum):
    """v1 closed actions（spec §5.2）；observe/find 是 read-only query，不是 effect。"""

    NAVIGATE = "navigate"
    BACK = "back"
    RELOAD = "reload"
    SCROLL = "scroll"
    CLICK = "click"
    SELECT = "select"
    FILL_FORM = "fill_form"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    CLOSE = "close"


class BrowserConsequence(StrEnum):
    """closed consequence classes（spec §6）；unknown 一律 COMMIT。"""

    OBSERVE = "observe"
    DISCLOSE = "disclose"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    COMMIT = "commit"


class BrowserActionOutcome(StrEnum):
    """executed receipt 的 closed outcome class（spec §10）。"""

    EFFECT_APPLIED = "effect_applied"
    EFFECT_BLOCKED = "effect_blocked"


class BrowserCleanupOutcome(StrEnum):
    """close/cleanup 的 closed outcome；不可确认时必须 CLEANUP_UNKNOWN（spec §10）。"""

    CLEANED = "cleaned"
    CLEANUP_UNKNOWN = "cleanup_unknown"


def _require_positive_int(value: int, field: str) -> None:
    # bool 是 int 的子类：closed positive limit 必须显式拒绝，防止 True 被当成 1。
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive int, got {value!r}")


def _require_enum(value: object, enum_type: type, field: str) -> None:
    if not isinstance(value, enum_type):
        raise ValueError(f"{field} must be a {enum_type.__name__}, got {value!r}")


def _freeze_params(value: JSONValue | None) -> JSONValue | None:
    # 复用 runtime 的 frozen JSON 容器，保证 action parameters 不可被原地篡改。
    if isinstance(value, dict):
        return FrozenJSONDict({key: _freeze_params(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return FrozenJSONList(_freeze_params(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class BrowserSessionSpecV1:
    """session authority 的 immutable 输入（spec §4）。

    site-bound 必须绑定 exact canonical origins 与 opaque profile ref；
    public-read 不得携带 profile。identity_digest 覆盖全部 authority 字段，
    任一漂移（含 Goal correction）即生成不同 session identity。
    """

    mode: BrowserMode
    goal_id: str
    goal_revision: int
    profile_ref: str | None
    allowed_origins: tuple[str, ...]
    action_budget: int
    profile_revision: int | None = None
    browser_identity_digest: str | None = None
    expiry_monotonic: float | None = None
    identity_digest: str = ""

    def __post_init__(self) -> None:
        if not self.goal_id:
            raise ValueError("goal_id must not be empty")
        _require_positive_int(self.goal_revision, "goal_revision")
        _require_positive_int(self.action_budget, "action_budget")
        _require_enum(self.mode, BrowserMode, "mode")
        if self.mode is BrowserMode.SITE_BOUND_INTERACTIVE:
            if not self.profile_ref:
                raise ValueError("site_bound spec requires an opaque profile_ref")
            if not self.allowed_origins:
                raise ValueError("site_bound spec requires a non-empty exact origin allowlist")
            # spec §4.2：site-bound authority 必须显式绑定 positive profile
            # revision、64-hex browser identity 与 finite expiry（monotonic）。
            if (
                isinstance(self.profile_revision, bool)
                or not isinstance(self.profile_revision, int)
                or self.profile_revision <= 0
            ):
                raise ValueError("site_bound spec requires a positive profile_revision")
            if (
                not isinstance(self.browser_identity_digest, str)
                or len(self.browser_identity_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.browser_identity_digest)
            ):
                raise ValueError("site_bound spec requires a 64-hex browser identity")
            if not isinstance(self.expiry_monotonic, float) or not math.isfinite(
                self.expiry_monotonic
            ):
                raise ValueError("site_bound spec requires a finite expiry_monotonic")
        else:
            if self.profile_ref is not None:
                raise ValueError("public_read spec must not carry a profile_ref")
            if (
                self.profile_revision is not None
                or self.browser_identity_digest is not None
                or self.expiry_monotonic is not None
            ):
                raise ValueError("public_read spec authority fields must be null")
        object.__setattr__(self, "allowed_origins", tuple(self.allowed_origins))
        object.__setattr__(
            self,
            "identity_digest",
            canonical_json_digest(
                {
                    "mode": self.mode.value,
                    "goal_id": self.goal_id,
                    "goal_revision": self.goal_revision,
                    "profile_ref": self.profile_ref,
                    "allowed_origins": list(self.allowed_origins),
                    "action_budget": self.action_budget,
                    "profile_revision": self.profile_revision,
                    "browser_identity_digest": self.browser_identity_digest,
                    "expiry_monotonic": self.expiry_monotonic,
                }
            ),
        )

    @classmethod
    def site_bound(
        cls,
        *,
        goal_id: str,
        goal_revision: int,
        profile_ref: str | None,
        allowed_origins: tuple[str, ...],
        action_budget: int,
        profile_revision: int,
        browser_identity_digest: str,
        expiry_monotonic: float,
    ) -> BrowserSessionSpecV1:
        return cls(
            mode=BrowserMode.SITE_BOUND_INTERACTIVE,
            goal_id=goal_id,
            goal_revision=goal_revision,
            profile_ref=profile_ref,
            allowed_origins=tuple(allowed_origins),
            action_budget=action_budget,
            profile_revision=profile_revision,
            browser_identity_digest=browser_identity_digest,
            expiry_monotonic=expiry_monotonic,
        )

    @classmethod
    def public_read(
        cls,
        *,
        goal_id: str,
        goal_revision: int,
        action_budget: int = 64,
    ) -> BrowserSessionSpecV1:
        return cls(
            mode=BrowserMode.PUBLIC_READ_EPHEMERAL,
            goal_id=goal_id,
            goal_revision=goal_revision,
            profile_ref=None,
            allowed_origins=(),
            action_budget=action_budget,
        )


@dataclass(frozen=True, slots=True)
class BrowserHandleV1:
    """adapter ``open`` 返回的 opaque session handle（spec §3.1）。

    只携带 identity 绑定，不携带 browser 对象，也不是 action authority 本身。
    """

    session_ref: str
    mode: BrowserMode
    authority_digest: str

    def __post_init__(self) -> None:
        if not self.session_ref or not self.authority_digest:
            raise ValueError("handle requires session_ref and authority_digest")
        _require_enum(self.mode, BrowserMode, "mode")


@dataclass(frozen=True, slots=True)
class BrowserElementRefV1:
    """observation 中的 opaque element ref 与最小 metadata（spec §5.1）。

    password/secret/hidden input 的 value 永不投影；普通 input 只投影是否为空。
    """

    ref: str
    role: str | None = None
    name: str | None = None
    input_type: str | None = None
    form_action: str | None = None
    form_method: str | None = None
    value_empty: bool | None = None


@dataclass(frozen=True, slots=True)
class BrowserObservationV1:
    """bounded durable observation（spec §5.1）。

    只携带 bounded ARIA projection 与 opaque refs；不携带 HTML、cookie、header、
    body、network 数据或 screenshot。digest 覆盖全部绑定字段与截断事实。
    """

    session_ref: str
    page_id: str
    frame_id: str
    navigation_revision: int
    browser_revision: str
    profile_revision: int | None
    canonical_url: str
    canonical_origin: str
    frame_tree_digest: str
    aria_projection: str
    element_refs: tuple[BrowserElementRefV1, ...]
    node_count: int
    byte_size: int
    truncated: bool
    observed_at: float
    observation_digest: str = ""

    def __post_init__(self) -> None:
        # 与 durable profile revision 同型：positive int | None（拒 bool/0/str）。
        if self.profile_revision is not None and (
            isinstance(self.profile_revision, bool)
            or not isinstance(self.profile_revision, int)
            or self.profile_revision <= 0
        ):
            raise ValueError("profile_revision must be a positive int or None")
        object.__setattr__(self, "element_refs", tuple(self.element_refs))
        object.__setattr__(
            self,
            "observation_digest",
            canonical_json_digest(
                {
                    "session_ref": self.session_ref,
                    "page_id": self.page_id,
                    "frame_id": self.frame_id,
                    "navigation_revision": self.navigation_revision,
                    "browser_revision": self.browser_revision,
                    "profile_revision": self.profile_revision,
                    "canonical_url": self.canonical_url,
                    "canonical_origin": self.canonical_origin,
                    "frame_tree_digest": self.frame_tree_digest,
                    "aria_projection": self.aria_projection,
                    "element_refs": [
                        {
                            "ref": item.ref,
                            "role": item.role,
                            "name": item.name,
                            "input_type": item.input_type,
                            "form_action": item.form_action,
                            "form_method": item.form_method,
                            "value_empty": item.value_empty,
                        }
                        for item in self.element_refs
                    ],
                    "node_count": self.node_count,
                    "byte_size": self.byte_size,
                    "truncated": self.truncated,
                    "observed_at": self.observed_at,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class BrowserActionV1:
    """一个 closed browser action 的 exact identity（spec §5.2）。

    action 必须引用 current observation digest、page/frame、element ref（适用时）
    与 exact parameters；identity_digest 覆盖全部字段，任一漂移即不同 action。
    """

    kind: BrowserActionKind
    observation_digest: str
    page_id: str
    frame_id: str
    target_ref: str | None = None
    params: JSONValue | None = None
    identity_digest: str = ""

    def __post_init__(self) -> None:
        if not self.observation_digest or not self.page_id or not self.frame_id:
            raise ValueError("action must bind observation digest and page/frame identity")
        _require_enum(self.kind, BrowserActionKind, "kind")
        object.__setattr__(self, "params", _freeze_params(self.params))
        object.__setattr__(
            self,
            "identity_digest",
            canonical_json_digest(
                {
                    "kind": self.kind.value,
                    "observation_digest": self.observation_digest,
                    "page_id": self.page_id,
                    "frame_id": self.frame_id,
                    "target_ref": self.target_ref,
                    "params": self.params,
                }
            ),
        )

    @classmethod
    def click(
        cls, observation_digest: str, page_id: str, frame_id: str, target_ref: str,
    ) -> BrowserActionV1:
        return cls(
            kind=BrowserActionKind.CLICK,
            observation_digest=observation_digest,
            page_id=page_id,
            frame_id=frame_id,
            target_ref=target_ref,
        )

    @classmethod
    def navigate(
        cls, observation_digest: str, page_id: str, frame_id: str, url: str,
    ) -> BrowserActionV1:
        return cls(
            kind=BrowserActionKind.NAVIGATE,
            observation_digest=observation_digest,
            page_id=page_id,
            frame_id=frame_id,
            params={"url": url},
        )

    @classmethod
    def fill_form(
        cls,
        observation_digest: str,
        page_id: str,
        frame_id: str,
        target_ref: str,
        fields: dict[str, str],
    ) -> BrowserActionV1:
        return cls(
            kind=BrowserActionKind.FILL_FORM,
            observation_digest=observation_digest,
            page_id=page_id,
            frame_id=frame_id,
            target_ref=target_ref,
            params={"fields": dict(fields)},
        )


@dataclass(frozen=True, slots=True)
class BrowserActionReceiptV1:
    """已执行 action 的 durable receipt（spec §10）。

    executed receipt 必须携带 pre/post observation identity 与 outcome class；
    缺任一项即拒绝构造，防止伪造“已执行”。
    """

    action_digest: str
    pre_observation_digest: str | None = None
    post_observation_digest: str | None = None
    outcome: BrowserActionOutcome | None = None
    executed: bool = True
    download: QuarantinedDownloadV1 | None = None
    receipt_digest: str = ""

    def __post_init__(self) -> None:
        if not self.action_digest:
            raise ValueError("receipt requires the executed action_digest")
        if self.executed and (
            not self.pre_observation_digest
            or not self.post_observation_digest
            or self.outcome is None
        ):
            raise ValueError(
                "executed receipt requires pre/post observation identity and an outcome class"
            )
        if self.outcome is not None:
            _require_enum(self.outcome, BrowserActionOutcome, "outcome")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_json_digest(
                {
                    "action_digest": self.action_digest,
                    "pre_observation_digest": self.pre_observation_digest,
                    "post_observation_digest": self.post_observation_digest,
                    "outcome": self.outcome.value if self.outcome is not None else None,
                    "executed": self.executed,
                    "download_receipt_digest": (
                        self.download.receipt_digest if self.download is not None else None
                    ),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class BrowserCleanupReceiptV1:
    """close/cleanup 的 closed receipt；不可确认时必须 CLEANUP_UNKNOWN（spec §10）。"""

    session_ref: str
    outcome: BrowserCleanupOutcome
    receipt_digest: str = ""

    def __post_init__(self) -> None:
        if not self.session_ref:
            raise ValueError("cleanup receipt requires a session_ref")
        _require_enum(self.outcome, BrowserCleanupOutcome, "outcome")
        object.__setattr__(
            self,
            "receipt_digest",
            canonical_json_digest(
                {"session_ref": self.session_ref, "outcome": self.outcome.value}
            ),
        )
