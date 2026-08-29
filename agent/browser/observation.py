"""018 bounded ARIA observation projection（spec §5.1）。

纯函数投影：从 adapter 收集的 raw ARIA snapshot 生成 durable、bounded 的
``BrowserObservationV1``。不接触 Playwright/Provider/Runtime；secret value
在进入任何输出前被剥离；截断按输入顺序确定性发生。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.browser.contracts import (
    BrowserElementRefV1,
    BrowserObservationV1,
)

# 这些 input type 的 value（以及是否为空）都是泄漏面，一律不投影。
SECRET_INPUT_TYPES = frozenset({"password", "secret", "hidden"})


@dataclass(frozen=True, slots=True)
class ObservationLimitsV1:
    """closed projection bounds；默认值即 spec §5.1 的合同上限。"""

    max_nodes: int
    max_bytes: int
    max_depth: int


DEFAULT_OBSERVATION_LIMITS = ObservationLimitsV1(
    max_nodes=400,
    max_bytes=64 * 1024,
    max_depth=15,
)


@dataclass(frozen=True, slots=True)
class RawAriaNodeV1:
    """adapter 收集的未截断节点；``value`` 只存在于输入侧，永不进入输出。"""

    ref: str
    role: str | None
    name: str | None
    depth: int
    input_type: str | None = None
    form_action: str | None = None
    form_method: str | None = None
    value: str | None = None


@dataclass(frozen=True, slots=True)
class RawBrowserSnapshotV1:
    """一次 observe 的 raw 输入；只含 ARIA 投影所需字段，无 HTML/cookie/body。"""

    nodes: tuple[RawAriaNodeV1, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))


@dataclass(frozen=True, slots=True)
class ObservationIdentityV1:
    """observation 必须绑定的 durable identity（spec §5.1）；全部进入 digest。"""

    session_ref: str
    page_id: str
    frame_id: str
    navigation_revision: int
    browser_revision: str
    profile_revision: int | None
    canonical_url: str
    canonical_origin: str
    frame_tree_digest: str
    observed_at: float

    def __post_init__(self) -> None:
        # 与 durable profile revision 同型：positive int | None（拒 bool/0/str）。
        if self.profile_revision is not None and (
            isinstance(self.profile_revision, bool)
            or not isinstance(self.profile_revision, int)
            or self.profile_revision <= 0
        ):
            raise ValueError("profile_revision must be a positive int or None")


def _render_line(item: RawAriaNodeV1) -> str:
    indent = "  " * max(item.depth, 0)
    role = item.role or "generic"
    # 只渲染公开 role/name；value（含 secret）与是否为空都不进入文本。
    label = f' "{item.name}"' if item.name else ""
    return f"{indent}- {role}{label}"


def _project_element(item: RawAriaNodeV1) -> BrowserElementRefV1:
    secret = item.input_type is not None and item.input_type.lower() in SECRET_INPUT_TYPES
    if secret:
        value_empty = None
    elif item.value is not None:
        value_empty = item.value == ""
    else:
        value_empty = None
    return BrowserElementRefV1(
        ref=item.ref,
        role=item.role,
        name=item.name,
        input_type=item.input_type,
        form_action=item.form_action,
        form_method=item.form_method,
        value_empty=value_empty,
    )


def project_aria_snapshot(
    raw: RawBrowserSnapshotV1,
    identity: ObservationIdentityV1,
    limits: ObservationLimitsV1 = DEFAULT_OBSERVATION_LIMITS,
) -> BrowserObservationV1:
    """把 raw snapshot 投影为 bounded durable observation。

    截断规则（确定性、按输入顺序）：depth 超限的节点整支丢弃但继续扫描浅层
    兄弟；nodes/bytes 任一到达上限即停止保留后续节点。任何截断都置
    ``truncated=True``，绝不静默丢弃。
    """
    truncated = False
    kept_refs: list[BrowserElementRefV1] = []
    projection_lines: list[str] = []
    byte_size = 0

    for item in raw.nodes:
        if item.depth > limits.max_depth:
            truncated = True
            continue
        if len(kept_refs) >= limits.max_nodes:
            truncated = True
            break
        line = _render_line(item)
        candidate_size = byte_size + len(line.encode("utf-8")) + 1
        if candidate_size > limits.max_bytes:
            truncated = True
            break
        byte_size = candidate_size
        projection_lines.append(line)
        kept_refs.append(_project_element(item))

    aria_projection = "\n".join(projection_lines)
    byte_size = len(aria_projection.encode("utf-8"))
    return BrowserObservationV1(
        session_ref=identity.session_ref,
        page_id=identity.page_id,
        frame_id=identity.frame_id,
        navigation_revision=identity.navigation_revision,
        browser_revision=identity.browser_revision,
        profile_revision=identity.profile_revision,
        canonical_url=identity.canonical_url,
        canonical_origin=identity.canonical_origin,
        frame_tree_digest=identity.frame_tree_digest,
        aria_projection=aria_projection,
        element_refs=tuple(kept_refs),
        node_count=len(kept_refs),
        byte_size=byte_size,
        truncated=truncated,
        observed_at=identity.observed_at,
    )
