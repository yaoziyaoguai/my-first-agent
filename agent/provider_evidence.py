"""Provider evidence metadata 解析（从 agent/core.py _resolve_provider_evidence_metadata 提取）。

中文学习边界——为什么在构造点预解析而非在消费点（loop.py）派生：
1. core.py 是 provider 信息的「构造点」——LoopDependencies 在这里组装，
   在这里解析 provider metadata 是信息在「最完整的地方」被处理。
2. loop.py 是「消费点」——它不应知道 provider 的结构、类型体系、白名单。
   LoopDependencies 只接收已解析的 string/bool，保持 loop 的 provider-agnostic。
3. 如果未来新增 provider 类型，只需更新此处的白名单，loop.py 零改动。

为什么 provider_kind 只允许 coarse-grained 三态（fake/real/unknown）：
- raw provider_type（如 "anthropic_native"）是 provider 实现细节，
  不应泄漏到 evidence 的 provider_kind 字段
- evidence 消费者只需要知道「是否真实 API」这种粗粒度分类
- 精确的 provider_type 通过 evidence_extra 的 provider_type 字段保留
- 不回退到 type(provider).__name__：class name 是实现细节

为什么 provider_external_call 和 external_side_effects 拆开：
- provider_external_call: provider 本身是否调用了真实外部 API（由 provider 类型决定）
- external_side_effects: 整个 turn 是否有工具/文件/MCP/memory retain 等副作用
- 一个 real Anthropic provider 在 real smoke 场景下 provider_external_call=True
  （确实调了 API），但 external_side_effects=False（没有工具/文件/memory retain）
- 这两个概念正交，不应从 provider 类型推导 external_side_effects

安全边界：
- 只读 provider.provider_type 类属性（字符串常量），不读 .env / os.environ
- 不访问 API key 或任何 secret
- 未知/缺失 provider_type → fail-closed ("unknown", False)
"""

from __future__ import annotations

from typing import Any


def resolve_provider_evidence_metadata(provider: Any) -> tuple[str, bool]:
    """预解析 provider 的 coarse-grained runtime evidence metadata。

    返回值：
        (provider_kind, provider_external_call)
        - provider_kind: "fake" | "real" | "unknown"
        - provider_external_call: bool
    """
    if provider is None:
        return ("unknown", False)

    pt = getattr(provider, "provider_type", None)
    if not isinstance(pt, str) or not pt:
        return ("unknown", False)

    if pt == "fake":
        return ("fake", False)

    # 白名单归一化：所有已知真实 provider 类型归一化为 "real"
    if pt in (
        "anthropic_native", "anthropic_compatible",
        "openai_native", "openai_compatible",
    ):
        return ("real", True)

    # 未知 provider_type → fail-closed：不 overclaim real
    return ("unknown", False)
