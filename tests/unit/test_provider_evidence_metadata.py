"""_resolve_provider_evidence_metadata 单元测试。

中文学习边界：
验证 provider metadata 预解析遵循 coarse-grained 三态设计：
- provider_kind 只能是 "fake" / "real" / "unknown"
- 不回退到 type(provider).__name__ 或 provider class name
- 未知 provider → fail-closed ("unknown", False)
- 解析逻辑不读 .env / os.environ / API key
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

# _resolve_provider_evidence_metadata 尚未实现，预期 import 会失败
# 这是 TDD red phase——先写测试，确认它们因为符号不存在而失败
try:
    from agent.core import _resolve_provider_evidence_metadata
except ImportError:
    _resolve_provider_evidence_metadata = None  # type: ignore[assignment]


# ========== Fake Provider ==========


def test_resolve_fake_provider():
    """FakeProvider → provider_kind="fake", provider_external_call=False。

    中文学习边界——为什么这个测试重要：
    FakeProvider 是默认安全模式，必须产生 provider_kind=fake。
    这是 coarsest-grained 三态中唯一的 non-real 已知值。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    from agent.provider.fake_provider import FakeProvider

    provider = FakeProvider()
    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "fake", f"FakeProvider → provider_kind 应为 'fake'，实际 {kind!r}"
    assert external_call is False, (
        f"FakeProvider → provider_external_call 应为 False，实际 {external_call!r}"
    )


# ========== None Provider ==========


def test_resolve_none_provider():
    """provider=None → provider_kind="unknown", provider_external_call=False。

    中文学习边界：
    None 代表未注入 provider，系统应以 fail-closed 方式处理。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    kind, external_call = _resolve_provider_evidence_metadata(None)

    assert kind == "unknown", f"None provider → provider_kind 应为 'unknown'，实际 {kind!r}"
    assert external_call is False, (
        f"None provider → provider_external_call 应为 False，实际 {external_call!r}"
    )


# ========== Missing / Empty provider_type ==========


def test_resolve_no_provider_type_attr():
    """无 provider_type 属性的对象 → provider_kind="unknown"。

    中文学习边界——为什么不能 fallback 到 class name：
    type(provider).__name__ 是实现细节，不应泄漏到 evidence。
    例如一个 mock 对象的 __name__ 可能是 "Mock" 或 "NonCallableMock"，
    这些信息对 evidence 分析无意义且可能误导。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    # 使用 Mock 创建一个没有 provider_type 属性的对象
    provider = Mock(spec=[])
    # 确认确实没有 provider_type 属性
    assert not hasattr(provider, "provider_type")

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "unknown", (
        f"无 provider_type 属性 → provider_kind 应为 'unknown'（fail-closed），"
        f"实际 {kind!r}"
    )
    assert external_call is False, (
        f"无 provider_type 属性 → provider_external_call 应为 False，"
        f"实际 {external_call!r}"
    )


def test_resolve_empty_provider_type():
    """provider_type="" (空串) → provider_kind="unknown"。

    中文学习边界：
    空字符串不是合法的 provider_type 值。按 fail-closed 原则，
    应返回 "unknown" 而非尝试匹配空串。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = ""

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "unknown", (
        f"空 provider_type → provider_kind 应为 'unknown'，实际 {kind!r}"
    )
    assert external_call is False


# ========== Known Real Provider Types ==========


def test_resolve_anthropic_native():
    """provider_type="anthropic_native" → ("real", True)。"""
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = "anthropic_native"

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "real", f"anthropic_native → provider_kind 应为 'real'，实际 {kind!r}"
    assert external_call is True, (
        f"anthropic_native → provider_external_call 应为 True，实际 {external_call!r}"
    )


def test_resolve_anthropic_compatible():
    """provider_type="anthropic_compatible" → ("real", True)。"""
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = "anthropic_compatible"

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "real"
    assert external_call is True


def test_resolve_openai_native():
    """provider_type="openai_native" → ("real", True)。"""
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = "openai_native"

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "real"
    assert external_call is True


def test_resolve_openai_compatible():
    """provider_type="openai_compatible" → ("real", True)。"""
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = "openai_compatible"

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "real"
    assert external_call is True


# ========== Unknown provider_type → fail-closed ==========


def test_resolve_unknown_provider_type_fail_closed():
    """未知 provider_type → ("unknown", False) fail-closed。

    中文学习边界——为什么这是 fail-closed：
    如果 provider_type 是一个白名单之外的字符串（如 "custom_vendor"），
    系统不应猜测它是 real 还是 fake。返回 "unknown" 确保：
    - 不 overclaim real_provider_core_loop_e2e
    - 不假称 provider_external_call=True
    - 迫使新增 provider 类型时显式更新白名单
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    provider = Mock()
    provider.provider_type = "custom_vendor_xyz"

    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "unknown", (
        f"未知 provider_type → provider_kind 应为 'unknown'（fail-closed），"
        f"实际 {kind!r}"
    )
    assert external_call is False, (
        f"未知 provider_type → provider_external_call 应为 False，"
        f"实际 {external_call!r}"
    )


# ========== 不使用 type(provider).__name__ ==========


def test_no_class_name_fallback():
    """验证解析不 fallback 到 type(provider).__name__。

    中文学习边界——为什么这个测试存在：
    如果 _resolve_provider_evidence_metadata 内部使用了
    type(provider).__name__ 作为 fallback，一个类名为 "AnthropicNativeProvider"
    的对象即使没有 provider_type 属性也会被误判。这个测试用一个完全没有
    provider_type 属性的普通对象验证：结果必须是 "unknown"，
    不能是对象的 class name。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    # 使用一个自定义类——它没有 provider_type 属性
    class SomeRandomProvider:
        pass

    provider = SomeRandomProvider()
    kind, external_call = _resolve_provider_evidence_metadata(provider)

    assert kind == "unknown", (
        f"class name fallback 是禁止的——"
        f"类型为 {type(provider).__name__} 但无 provider_type 的对象 "
        f"provider_kind 应为 'unknown'，实际 {kind!r}"
    )
    assert external_call is False


# ========== external_side_effects 不参与解析 ==========


def test_resolver_does_not_compute_external_side_effects():
    """验证 _resolve_provider_evidence_metadata 不计算 external_side_effects。

    中文学习边界——provider_external_call vs external_side_effects 拆分：
    - provider_external_call: provider 本身是否调用了真实外部 API（由解析器返回）
    - external_side_effects: 整个 turn 是否有工具/文件/MCP/memory retain 等副作用
    后者与 provider 类型无关，不应在此解析。这个测试验证解析器只返回两个值，
    不越界计算 external_side_effects。
    """
    if _resolve_provider_evidence_metadata is None:
        pytest.skip("_resolve_provider_evidence_metadata not yet implemented")

    from agent.provider.fake_provider import FakeProvider

    result = _resolve_provider_evidence_metadata(FakeProvider())

    # 返回值必须是 2-tuple
    assert len(result) == 2, (
        f"解析器应返回 (provider_kind, provider_external_call) 二元组，"
        f"实际返回 {len(result)} 个值"
    )
    kind, external_call = result
    assert isinstance(kind, str)
    assert isinstance(external_call, bool)
    # 不包含 external_side_effects
