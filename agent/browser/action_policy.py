"""018 纯 browser action consequence policy 与 exact binding（Task 4，spec §6）。

深模块边界：本模块只 import ``agent.browser.contracts``（加标准库），是纯
函数——从 durable bounded observation 产生 ToolRuntime approval binding，
不访问 browser/resolver/Playwright/Runtime，不做任何 I/O。preview 只由
typed metadata（origin/role/name/type/form action/字段 digest）构造，
value 原文与页面 prose 永不进入；unknown 元素语义一律 COMMIT；模型自带
的 ``risk=low`` 不参与判定。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import urlsplit

from agent.browser.contracts import (
    BrowserActionKind,
    BrowserActionV1,
    BrowserConsequence,
    BrowserElementRefV1,
    BrowserObservationV1,
    canonical_json_digest,
)

PREVIEW_MAX_CHARS = 512
_VALUE_DIGEST_PREFIX = 16


@dataclass(frozen=True, slots=True)
class BrowserActionBindingV1:
    """approval 绑定：exact consequence + 冻结 target 元数据 + bounded preview。

    adapter ``execute`` 在 effect 前逐一重验这些冻结字段；任一漂移只返回
    冻结的 KnownNotExecuted 分类，零副作用。``binding_digest`` 覆盖全部
    绑定字段（single-use 消费由 adapter 记账）。"""

    action_digest: str
    observation_digest: str
    page_id: str
    frame_id: str
    canonical_origin: str
    consequence: BrowserConsequence
    target_ref: str | None
    target_role: str | None
    target_name: str | None
    target_input_type: str | None
    target_form_action: str | None
    target_form_method: str | None
    preview: str
    binding_digest: str = ""

    def __post_init__(self) -> None:
        # closed immutable invariant：digest 由全部字段 deterministic 派生；
        # 构造/replace 携带不一致 digest 一律 ValueError（伪造在构造层即拒）。
        computed = _binding_digest(self)
        if self.binding_digest not in ("", computed):
            raise ValueError("binding digest does not match its fields")
        object.__setattr__(self, "binding_digest", computed)


def _short_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_VALUE_DIGEST_PREFIX]


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc.lower()}"


def _navigate_consequence(
    url: str,
    observation: BrowserObservationV1,
    *,
    allow_public_navigation: bool,
) -> BrowserConsequence:
    parts = urlsplit(url)
    if (
        allow_public_navigation
        and parts.scheme == "https"
        and bool(parts.netloc)
        and not parts.query
        and not parts.fragment
    ):
        return BrowserConsequence.OBSERVE
    if f"{parts.scheme}://{parts.netloc.lower()}" != observation.canonical_origin:
        return BrowserConsequence.DISCLOSE
    if parts.query or parts.fragment:
        # 模型构造 query/fragment 或把用户/本地文本编码进 URL：DISCLOSE。
        return BrowserConsequence.DISCLOSE
    return BrowserConsequence.OBSERVE


def _classify(
    action: BrowserActionV1,
    observation: BrowserObservationV1,
    element: BrowserElementRefV1 | None,
    *,
    allow_public_navigation: bool,
) -> BrowserConsequence:
    if action.kind in (
        BrowserActionKind.BACK,
        BrowserActionKind.RELOAD,
        BrowserActionKind.SCROLL,
        BrowserActionKind.CLOSE,
    ):
        return BrowserConsequence.OBSERVE
    if action.kind is BrowserActionKind.NAVIGATE:
        return _navigate_consequence(
            action.params["url"],
            observation,
            allow_public_navigation=allow_public_navigation,
        )
    if action.kind in (BrowserActionKind.FILL_FORM, BrowserActionKind.SELECT):
        return BrowserConsequence.DISCLOSE
    if action.kind is BrowserActionKind.UPLOAD:
        return BrowserConsequence.UPLOAD
    if action.kind is BrowserActionKind.DOWNLOAD:
        return BrowserConsequence.DOWNLOAD
    if action.kind is BrowserActionKind.CLICK:
        # observed link（无 form 绑定）是 OBSERVE；form 提交语义、按钮或
        # 未知元素语义一律 COMMIT（不信任模型自述 risk）。
        if element is not None and element.role == "link" and element.form_action is None:
            return BrowserConsequence.OBSERVE
        return BrowserConsequence.COMMIT
    return BrowserConsequence.COMMIT


def _build_preview(
    action: BrowserActionV1,
    observation: BrowserObservationV1,
    element: BrowserElementRefV1 | None,
    consequence: BrowserConsequence,
) -> str:
    parts = [consequence.value, action.kind.value, observation.canonical_origin]
    if element is not None:
        label = (element.name or "")[:64]
        parts.append(f"{element.role or 'generic'}:{label}")
        if element.input_type is not None:
            parts.append(f"type={element.input_type}")
        if element.form_action is not None:
            parts.append(f"form={_origin_of(element.form_action)}")
    if action.kind is BrowserActionKind.FILL_FORM:
        fields = action.params["fields"]
        for key in sorted(fields):
            # value 原文绝不进入 preview：只展示字段名 + digest 摘要。
            parts.append(f"{key}=sha256:{_short_digest(fields[key])}")
    elif action.kind is BrowserActionKind.UPLOAD and isinstance(action.params, dict):
        parts.extend(
            (
                f"path={action.params['path']}",
                f"sha256={action.params['sha256']}",
                f"purpose={action.params['purpose'][:96]}",
            )
        )
    elif action.kind is BrowserActionKind.DOWNLOAD:
        parts.append("quarantine-only; max=104857600 bytes")
    return "; ".join(parts)[:PREVIEW_MAX_CHARS]


def _binding_payload(binding: BrowserActionBindingV1) -> dict:
    # digest 覆盖全部绑定字段（含 preview 与 form_method）——closed invariant。
    return {
        "action_digest": binding.action_digest,
        "observation_digest": binding.observation_digest,
        "page_id": binding.page_id,
        "frame_id": binding.frame_id,
        "canonical_origin": binding.canonical_origin,
        "consequence": binding.consequence.value,
        "target": {
            "ref": binding.target_ref,
            "role": binding.target_role,
            "name": binding.target_name,
            "input_type": binding.target_input_type,
            "form_action": binding.target_form_action,
            "form_method": binding.target_form_method,
        },
        "preview": binding.preview,
    }


def _binding_digest(binding: BrowserActionBindingV1) -> str:
    return canonical_json_digest(_binding_payload(binding))


class BrowserActionPolicy:
    """纯函数 policy：prepare/validate 是 binding 的唯一铸造与验证 seam。"""

    @staticmethod
    def validate_binding(binding: BrowserActionBindingV1) -> None:
        """唯一重算 seam：digest 必须与全部字段的 deterministic 重算一致。"""
        if binding.binding_digest != _binding_digest(binding):
            raise ValueError("binding digest does not match its fields")

    @staticmethod
    def prepare(
        observation: BrowserObservationV1,
        action: BrowserActionV1,
        *,
        allow_public_navigation: bool = False,
    ) -> BrowserActionBindingV1:
        element = next(
            (item for item in observation.element_refs if item.ref == action.target_ref),
            None,
        )
        consequence = _classify(
            action,
            observation,
            element,
            allow_public_navigation=allow_public_navigation,
        )
        preview = _build_preview(action, observation, element, consequence)
        binding = BrowserActionBindingV1(
            action_digest=action.identity_digest,
            observation_digest=action.observation_digest,
            page_id=action.page_id,
            frame_id=action.frame_id,
            canonical_origin=observation.canonical_origin,
            consequence=consequence,
            target_ref=action.target_ref,
            target_role=element.role if element else None,
            target_name=element.name if element else None,
            target_input_type=element.input_type if element else None,
            target_form_action=element.form_action if element else None,
            target_form_method=element.form_method if element else None,
            preview=preview,
        )
        object.__setattr__(binding, "binding_digest", _binding_digest(binding))
        return binding
