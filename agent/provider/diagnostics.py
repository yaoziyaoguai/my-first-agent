"""Provider 配置/认证诊断映射（diagnostic mapping）。

本模块负责将 provider 配置状态、已知错误码（401/403/timeout 等）映射为
用户可执行的中文修复建议。不调用真实 API——所有诊断都是静态推断。

为什么需要这个模块：
- 真实 provider dogfood 曾出现 401 config/auth concern
- 用户需要比 "ProviderAuthError" 更具体的诊断信息
- manual dogfood checklist 包含 provider setup 步骤，诊断信息帮助用户快速定位问题

为什么不做真实 API 连接验证：
- 真实连接验证需要 .env 中的 secret，而 AutoRun 不读取 .env
- 静态诊断覆盖了大部分配置错误场景（缺 key、缺 model、无效 provider 类型）
- 连接性验证留待 manual human dogfood 阶段人工完成
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 已知 provider 错误码 → 用户可执行修复建议（中文）
# key 是 ProviderError code / status_code 字符串，value 是诊断信息
DIAGNOSTIC_ERROR_MAP: dict[str, str] = {
    "unknown_provider": (
        "未知的 provider 类型。请检查 MY_FIRST_AGENT_LLM_PROVIDER 环境变量，"
        "支持的类型：anthropic_native, anthropic_compatible, "
        "openai_native, openai_compatible, fake"
    ),
    "api_key_missing": (
        "API key 未配置。当前 provider 需要真实 API key，但环境变量中未找到。"
        "如需使用真实 provider，请设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY；"
        "如仅需本地体验，设置 MY_FIRST_AGENT_LLM_PROVIDER=fake 启动安全路径"
    ),
    "model_missing": (
        "模型名未配置。请设置 ANTHROPIC_MODEL 或 OPENAI_MODEL 或 "
        "MY_FIRST_AGENT_LLM_MODEL 环境变量指定要使用的模型"
    ),
    "base_url_missing": (
        "兼容模式 provider 需要 base_url。请设置 ANTHROPIC_BASE_URL 或 "
        "OPENAI_BASE_URL 或 MY_FIRST_AGENT_LLM_BASE_URL"
    ),
    "unsupported_auth_scheme": (
        "不支持的认证方案。MY_FIRST_AGENT_LLM_AUTH_SCHEME 只能是 "
        "auto, x-api-key 或 bearer"
    ),
    "invalid_max_tokens": (
        "max_tokens 值无效。MY_FIRST_AGENT_LLM_MAX_TOKENS 必须是正整数"
    ),
    "invalid_timeout": (
        "timeout 值无效。MY_FIRST_AGENT_LLM_TIMEOUT 必须是正数（秒）"
    ),
    "unknown_model": (
        "未知的模型名。请确认模型名拼写正确。当前 fake/local 模式下"
        "会使用假模型，但真实 provider 需要准确的模型名"
    ),
    "provider_not_implemented": (
        "该 provider 类型已注册但未实现对应的 adapter。"
        "请检查 agent/provider/ 下的 provider adapter 是否已正确注册"
    ),
    "provider_timeout_error": (
        "provider 请求超时。请检查网络连接，或通过 "
        "MY_FIRST_AGENT_LLM_TIMEOUT 增加超时时间（默认 30 秒）"
    ),
    "provider_capability_error": (
        "当前 provider 不支持所需的能力（如 tool_use / streaming）。"
        "请确认 provider 和模型支持该能力，或切换到支持该能力的配置"
    ),
}

# HTTP 状态码 → 用户可执行修复建议
HTTP_STATUS_DIAGNOSTIC_MAP: dict[int, str] = {
    401: (
        "401 Unauthorized — API key 无效或已过期。"
        "请检查以下环境变量是否正确：ANTHROPIC_API_KEY 或 OPENAI_API_KEY。"
        "确认 key 未被截断、未包含多余空格、未在 provider 控制台被撤销。"
        "不要将 key 写入仓库文件、日志、checkpoint 或文档。"
    ),
    403: (
        "403 Forbidden — 当前 API key 没有访问该模型/端点的权限。"
        "请检查 provider 控制台中的 API key 权限和模型访问授权。"
        "部分 provider 需要单独申请模型访问权限。"
    ),
    408: (
        "408 Request Timeout — 请求超时。请检查网络连接是否稳定，"
        "或通过 MY_FIRST_AGENT_LLM_TIMEOUT 增加超时时间（默认 30 秒）"
    ),
    429: (
        "429 Too Many Requests — 已触发 API 速率限制。"
        "请等待后再试，或在 provider 控制台中升级 API 配额"
    ),
    500: (
        "500 Internal Server Error — provider 服务器内部错误。"
        "这通常不是本地配置问题。稍后重试，或查看 provider status page"
    ),
    502: (
        "502 Bad Gateway — provider 网关错误。"
        "这可能与代理/兼容端点配置有关。检查 ANTHROPIC_BASE_URL 或 "
        "OPENAI_BASE_URL 是否正确"
    ),
    503: (
        "503 Service Unavailable — provider 服务暂时不可用。"
        "稍后重试，或在 provider status page 查看是否正在维护"
    ),
}


@dataclass(frozen=True)
class ProviderDiagnostic:
    """provider 配置诊断结果（只含脱敏信息）。"""

    provider_type: str
    model: str
    base_url: str  # "SET" | "not_set"
    api_key_present: bool
    api_key_env: str | None
    auth_scheme: str
    request_path: str
    status: str  # "ok" | "warn" | "error"
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def map_provider_error(error: Exception) -> str:
    """将 ProviderError 映射为用户可读的中文诊断信息。

    不打印任何 secret、环境变量值或路径。只提供检测到的错误类型的通用建议。
    """
    from agent.provider.protocol import (
        ProviderAuthError,
        ProviderCapabilityError,
        ProviderConfigurationError,
        ProviderError,
        ProviderNotImplementedError,
        ProviderTimeoutError,
    )

    if isinstance(error, ProviderAuthError):
        status_code = getattr(error, "status_code", None)
        if status_code and status_code in HTTP_STATUS_DIAGNOSTIC_MAP:
            return HTTP_STATUS_DIAGNOSTIC_MAP[status_code]
        return DIAGNOSTIC_ERROR_MAP.get("api_key_missing", str(error))

    code = getattr(error, "code", "")
    if code in DIAGNOSTIC_ERROR_MAP:
        return DIAGNOSTIC_ERROR_MAP[code]

    if isinstance(error, ProviderConfigurationError):
        return DIAGNOSTIC_ERROR_MAP.get("api_key_missing", str(error))
    if isinstance(error, ProviderNotImplementedError):
        return DIAGNOSTIC_ERROR_MAP.get("provider_not_implemented", str(error))
    if isinstance(error, ProviderTimeoutError):
        return DIAGNOSTIC_ERROR_MAP.get("provider_timeout_error", str(error))
    if isinstance(error, ProviderCapabilityError):
        return DIAGNOSTIC_ERROR_MAP.get("provider_capability_error", str(error))
    if isinstance(error, ProviderError):
        return f"provider 错误（{error.code}）: {error}"

    return f"未知错误类型: {type(error).__name__}: {error}"


def diagnose_provider_config(
    provider_type: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> ProviderDiagnostic:
    """静态诊断 provider 配置状态（不调用真实 API，不泄露 secret）。

    返回 ProviderDiagnostic，包含脱敏配置摘要和问题/建议列表。
    """
    import os

    if env is None:
        env = dict(os.environ)

    # 从环境变量推断配置
    provider = (provider_type or env.get("MY_FIRST_AGENT_LLM_PROVIDER") or "fake").lower().strip()
    model = (
        env.get("MY_FIRST_AGENT_LLM_MODEL")
        or env.get("ANTHROPIC_MODEL")
        or env.get("OPENAI_MODEL")
        or ("fake-llm" if provider == "fake" else None)
    )
    base_url = (
        env.get("MY_FIRST_AGENT_LLM_BASE_URL")
        or env.get("ANTHROPIC_BASE_URL")
        or env.get("OPENAI_BASE_URL")
    )
    api_key = env.get("ANTHROPIC_API_KEY") or env.get("OPENAI_API_KEY")
    api_key_env = "ANTHROPIC_API_KEY" if env.get("ANTHROPIC_API_KEY") else (
        "OPENAI_API_KEY" if env.get("OPENAI_API_KEY") else None
    )
    auth_scheme = env.get("MY_FIRST_AGENT_LLM_AUTH_SCHEME") or "auto"
    request_path = (
        env.get("MY_FIRST_AGENT_LLM_REQUEST_PATH")
        or ("/v1/messages" if provider.startswith("anthropic") else "/v1/chat/completions")
    )

    issues: list[str] = []
    suggestions: list[str] = []

    # 检查 provider 类型有效性
    valid_types = {
        "anthropic_native", "anthropic_compatible",
        "openai_native", "openai_compatible", "fake",
    }
    if provider not in valid_types:
        issues.append(f"未知 provider 类型: {provider}")
        suggestions.append(
            "设置 MY_FIRST_AGENT_LLM_PROVIDER 为以下之一: "
            "fake, anthropic_native, anthropic_compatible, "
            "openai_native, openai_compatible"
        )

    # 真实 provider 需要 key
    if provider != "fake" and not api_key:
        issues.append("真实 provider 缺少 API key")
        suggestions.append(
            "设置 ANTHROPIC_API_KEY 或 OPENAI_API_KEY 环境变量；"
            "或设置 MY_FIRST_AGENT_LLM_PROVIDER=fake 使用安全路径"
        )

    # 真实 provider 需要 model
    if provider != "fake" and not model:
        issues.append("真实 provider 缺少模型名")
        suggestions.append("设置 ANTHROPIC_MODEL 或 MY_FIRST_AGENT_LLM_MODEL")

    # 兼容模式需要 base_url
    if provider.endswith("_compatible") and not base_url:
        issues.append("兼容模式 provider 缺少 base_url")
        suggestions.append(
            "设置 ANTHROPIC_BASE_URL 或 OPENAI_BASE_URL 或 "
            "MY_FIRST_AGENT_LLM_BASE_URL"
        )

    # auth_scheme 检查
    if auth_scheme not in {"auto", "x-api-key", "bearer"}:
        issues.append(f"不支持的 auth_scheme: {auth_scheme}")
        suggestions.append("MY_FIRST_AGENT_LLM_AUTH_SCHEME 只能为 auto, x-api-key 或 bearer")

    status = "ok"
    if issues:
        # fake 模式无 key 是正常状态
        if provider == "fake" and all("API key" in i for i in issues):
            status = "ok"
            issues.clear()
        # 未知 provider 类型是阻塞性 error（不是 warn）
        elif any("未知" in i or "unknown" in i.lower() for i in issues):
            status = "error"
        elif any("API key" in i or "模型名" in i for i in issues):
            status = "warn"
        else:
            status = "error"

    return ProviderDiagnostic(
        provider_type=provider,
        model=model or "unspecified",
        base_url="SET" if base_url else "not_set",
        api_key_present=bool(api_key),
        api_key_env=api_key_env,
        auth_scheme=auth_scheme,
        request_path=request_path,
        status=status,
        issues=issues,
        suggestions=suggestions,
    )


def render_diagnostic_report(diagnostic: ProviderDiagnostic) -> str:
    """将 ProviderDiagnostic 渲染为人类可读的诊断报告。"""
    lines = [
        "=" * 60,
        "  Provider Config Diagnostic",
        "=" * 60,
        "",
        f"  Provider type : {diagnostic.provider_type}",
        f"  Model         : {diagnostic.model}",
        f"  Base URL      : {diagnostic.base_url}",
        f"  API key       : {'SET (redacted)' if diagnostic.api_key_present else 'not set'}",
        f"  Key source    : {diagnostic.api_key_env or 'N/A'}",
        f"  Auth scheme   : {diagnostic.auth_scheme}",
        f"  Request path  : {diagnostic.request_path}",
        f"  Status        : {diagnostic.status.upper()}",
        "",
    ]

    if diagnostic.status == "ok":
        lines.append("  结论：provider 配置无问题。")
        if diagnostic.provider_type == "fake":
            lines.append("  provider mode = fake (local only) — 不调用真实 API。")
            if diagnostic.api_key_present:
                lines.append(
                    "  检测到 API key 已配置（环境变量中存在），"
                    "但当前 fake 模式不会使用该 key。"
                )
            else:
                lines.append("  当前为 fake (local only) 安全路径，无需 API key。")
            lines.append(
                "  如需切换到真实 LLM，请设置 "
                "MY_FIRST_AGENT_LLM_PROVIDER=anthropic_native "
                "（或 openai_native）并确保对应 API key 已配置。"
            )
        else:
            if diagnostic.api_key_present:
                lines.append("  配置看起来完整，但连接性需 manual human dogfood 验证。")
            else:
                lines.append("  provider mode = real，但缺少 API key——连接性未验证。")

    if diagnostic.issues:
        lines.append("  Issues:")
        for i in diagnostic.issues:
            lines.append(f"    ⚠️  {i}")

    if diagnostic.suggestions:
        lines.append("  Suggestions:")
        for s in diagnostic.suggestions:
            lines.append(f"    → {s}")

    lines.append("")
    return "\n".join(lines)
