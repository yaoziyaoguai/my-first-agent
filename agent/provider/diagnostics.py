"""Provider 配置/认证诊断映射（diagnostic mapping）。

本模块负责将 provider 配置状态、已知错误码（401/403/timeout 等）映射为
用户可执行的中文修复建议。不调用真实 API——所有诊断都是静态推断。

Config Source 追踪（v0.11+）:
- 区分 project_dotenv / shell_env / default_fake / mixed 四种配置来源
- 支持 isolated dotenv 模式：清理外层 env 后只加载项目 .env
- 不打印 secret，只输出 key present / source kind / variable name

为什么需要 config source 追踪：
- 外层 Coding Agent 环境变量（如 DeepSeek）会通过 override=False 抢占项目 .env
- 用户需要明确知道 provider 配置来自哪个源头
- isolated 模式让显式 provider validation 可以只用项目 .env 配置，不受外层污染
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agent.provider.config import AgentProviderConfig

ConfigSourceKind = Literal[
    "project_dotenv",          # 仅从项目 .env 加载
    "shell_env",               # 仅从外层进程环境变量
    "default_fake",            # 无任何配置，使用 fake 兜底
    "mixed",                   # .env 与外层 env 混合（override=False 导致外层优先）
    "unknown",                 # 无法判断来源
    "config_local",            # 来自 config/config.local.yaml（git 忽略，优先于 config.yaml）
    "config_yaml",             # 来自 config/config.yaml（provider.enabled=true）
    "config_yaml_disabled",    # config.yaml 存在但 provider.enabled=false
    "legacy_profile",          # 来自 FIRST_AGENT_PROVIDER_PROFILE（legacy fallback）
    "legacy_provider_env",     # 来自 MY_FIRST_AGENT_LLM_PROVIDER（legacy fallback）
]

# 已知 provider 错误码 → 用户可执行修复建议（中文）
# key 是 ProviderError code / status_code 字符串，value 是诊断信息
DIAGNOSTIC_ERROR_MAP: dict[str, str] = {
    "unknown_provider": (
        "未知的 provider 类型。请检查 config/config.yaml 中 provider.type 字段，"
        "支持的类型：anthropic_native, anthropic_compatible, "
        "openai_native, openai_compatible, fake"
    ),
    "api_key_missing": (
        "API key 未配置。请在 config/config.yaml 的 provider section "
        "中设置 api_key 字段；如仅需本地体验，设置 provider.enabled=false"
    ),
    "model_missing": (
        "模型名未配置。请在 config/config.yaml 的 provider.model 字段指定要使用的模型"
    ),
    "base_url_missing": (
        "兼容模式 provider 需要 base_url。"
        "请在 config/config.yaml 的 provider.base_url 字段设置"
    ),
    "unsupported_auth_scheme": (
        "不支持的认证方案。请在 config/config.yaml 的 provider.auth_scheme 字段设置，"
        "支持的值：auto, x-api-key, bearer"
    ),
    "invalid_max_tokens": (
        "max_tokens 值无效。请在 config/config.yaml 的 runtime.max_tokens 字段设置为正整数"
    ),
    "invalid_timeout": (
        "timeout 值无效。请在 config/config.yaml 的 runtime.timeout 字段设置为正数（秒）"
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
        "provider 请求超时。请检查网络连接，或在 config/config.yaml 的 "
        "runtime.timeout 字段增加超时时间（默认 30 秒）"
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
        "请检查 config/config.yaml 中 provider.api_key 是否正确。"
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
        "或在 config/config.yaml 的 runtime.timeout 字段增加超时时间（默认 30 秒）"
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
        "这可能与代理/兼容端点配置有关。检查 config/config.yaml 中 "
        "provider.base_url 是否正确"
    ),
    503: (
        "503 Service Unavailable — provider 服务暂时不可用。"
        "稍后重试，或在 provider status page 查看是否正在维护"
    ),
}


@dataclass(frozen=True)
class ProviderDiagnostic:
    """provider 配置诊断结果（只含脱敏信息）。

    config_source 描述配置值的来源类别，不包含配置值本身：
    - project_dotenv: 仅从项目 .env 加载（isolated 模式）
    - shell_env: 仅从 os.environ 读取（未加载 .env）
    - default_fake: 无任何配置，返回 fake 兜底
    - mixed: .env 与外层 env 混合，部分值可能被外层覆盖
    - unknown: 无法精确判断来源
    """

    provider_type: str
    model: str
    base_url: str  # "SET" | "not_set"
    api_key_present: bool
    api_key_env: str | None
    auth_scheme: str
    request_path: str
    status: str  # "ok" | "warn" | "error"
    config_source: ConfigSourceKind = "unknown"
    dotenv_loaded: bool = False
    dotenv_path: str | None = None
    outer_env_overrides: list[str] = field(default_factory=list)
    active_profile: str | None = None
    profile_source: str | None = None  # "profile_env" | "profile_yaml" | "default_fake" | "legacy"
    config_yaml_path: str | None = None  # config/config.yaml 路径（config_yaml 来源时）
    config_error: str | None = None  # YAML 解析失败等错误信息
    legacy_ignored: list[str] = field(default_factory=list)
    # config.yaml 存在时被忽略的 legacy env/profile
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


def _load_dotenv_values_safe(dotenv_path: Path) -> dict[str, str]:
    """安全读取 .env 文件，返回 key-value 映射（不写入 os.environ）。"""
    from dotenv import dotenv_values

    if not dotenv_path.is_file():
        return {}
    raw = dotenv_values(dotenv_path)
    result: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            result[k] = v.strip()
    return result


def _redact_base_url(url: str | None) -> str:
    """脱敏 base_url：只保留 scheme + host，不打印完整路径。"""
    if not url:
        return "not_set"
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return f"{parsed.scheme}://{parsed.hostname}"
        return "SET"
    except Exception:
        return "SET"


def _detect_config_source(
    env: Mapping[str, str],
    dotenv_values: dict[str, str] | None,
    provider_type: str,
) -> tuple[ConfigSourceKind, list[str]]:
    """检测 provider 配置的实际来源。

    返回 (source_kind, outer_env_overrides)。

    判断逻辑：
    - 如果 provider_type == "fake" 且无任何 key/model/base_url 配置 → default_fake
    - 提供了 dotenv_values 且外层 env 无覆盖 → project_dotenv
    - 提供了 dotenv_values 且外层 env 有覆盖 → mixed + 列出被覆盖的 key
    - 未提供 dotenv_values → shell_env（直接读 os.environ）
    """
    # 所有可能来自不同源的 provider 相关 env var
    provider_vars = [
        "MY_FIRST_AGENT_LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "MY_FIRST_AGENT_LLM_MODEL",
        "MY_FIRST_AGENT_LLM_BASE_URL",
        "MY_FIRST_AGENT_LLM_AUTH_SCHEME",
        "MY_FIRST_AGENT_LLM_REQUEST_PATH",
        "MODEL_NAME",
    ]

    has_any_config = any(
        env.get(v) for v in provider_vars
    ) or provider_type != "fake"

    if not has_any_config and provider_type == "fake":
        return "default_fake", []

    if dotenv_values is None:
        return "shell_env", []

    # 检查哪些 .env 中的 key 被外层 env 覆盖
    overrides: list[str] = []
    for var in provider_vars:
        dotenv_val = dotenv_values.get(var, "")
        env_val = env.get(var, "")
        if dotenv_val and env_val and dotenv_val != env_val:
            overrides.append(var)

    if overrides:
        return "mixed", overrides

    return "project_dotenv", []


def diagnose_provider_config(
    provider_type: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = None,
    active_profile: str | None = None,
    profile_source: str | None = None,
) -> ProviderDiagnostic:
    """静态诊断 provider 配置状态（不调用真实 API，不泄露 secret）。

    当提供 dotenv_path 时，会加载该 .env 文件的值并与当前 os.environ 比较，
    以此判断配置来源（project_dotenv / shell_env / mixed / default_fake）。

    active_profile 和 profile_source 描述当前使用的 provider profile：
    - active_profile: profile 名称（如 "kimi_anthropic"）
    - profile_source: 决议方式（profile_env / profile_yaml / default_fake / legacy）

    返回 ProviderDiagnostic，包含脱敏配置摘要、config_source、问题和建议列表。
    """
    import os as _os

    if env is None:
        env = dict(_os.environ)

    # 加载 dotenv 用于 source 检测（如有）
    _dotenv_values: dict[str, str] | None = None
    _dotenv_loaded = False
    _dotenv_path_str: str | None = None
    if dotenv_path is not None:
        _dotenv_path = Path(dotenv_path)
        _dotenv_path_str = str(_dotenv_path.resolve())
        _dotenv_values = _load_dotenv_values_safe(_dotenv_path)
        _dotenv_loaded = bool(_dotenv_values)

    # 从环境变量推断配置
    provider = (
        provider_type or env.get("MY_FIRST_AGENT_LLM_PROVIDER") or "fake"
    ).lower().strip()
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
    api_key_env = (
        "ANTHROPIC_API_KEY" if env.get("ANTHROPIC_API_KEY")
        else "OPENAI_API_KEY" if env.get("OPENAI_API_KEY")
        else None
    )
    auth_scheme = env.get("MY_FIRST_AGENT_LLM_AUTH_SCHEME") or "auto"
    request_path = (
        env.get("MY_FIRST_AGENT_LLM_REQUEST_PATH")
        or ("/v1/messages" if provider.startswith("anthropic") else "/v1/chat/completions")
    )

    # 检测 config source
    config_source, outer_env_overrides = _detect_config_source(
        env, _dotenv_values, provider,
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
            "在 config/config.yaml 中设置 provider.type 为以下之一: "
            "fake, anthropic_native, anthropic_compatible, "
            "openai_native, openai_compatible"
        )

    # 真实 provider 需要 key
    if provider != "fake" and not api_key:
        issues.append("真实 provider 缺少 API key")
        suggestions.append(
            "在 .env 中设置 config/config.yaml 里 api_key_env 对应的环境变量；"
            "或设置 config/config.yaml 中 provider.enabled=false 使用安全路径"
        )

    # 真实 provider 需要 model
    if provider != "fake" and not model:
        issues.append("真实 provider 缺少模型名")
        suggestions.append("在 config/config.yaml 的 provider.model 字段指定模型名")

    # 兼容模式需要 base_url
    if provider.endswith("_compatible") and not base_url:
        issues.append("兼容模式 provider 缺少 base_url")
        suggestions.append(
            "在 config/config.yaml 的 provider.base_url 字段设置端点地址"
        )

    # auth_scheme 检查
    if auth_scheme not in {"auto", "x-api-key", "bearer"}:
        issues.append(f"不支持的 auth_scheme: {auth_scheme}")
        suggestions.append(
            "请在 config/config.yaml 的 provider.auth_scheme 字段设置"
            "为 auto, x-api-key 或 bearer"
        )

    # config source 相关建议
    if config_source == "mixed" and outer_env_overrides:
        suggestions.append(
            f"外层 shell 环境变量覆盖了 .env 中的: {', '.join(sorted(outer_env_overrides))}。"
            "如需使用项目 .env 配置，请 unset 外层同名变量或使用 isolated 模式"
        )

    status = "ok"
    if issues:
        if provider == "fake" and all("API key" in i for i in issues):
            status = "ok"
            issues.clear()
        elif any("未知" in i or "unknown" in i.lower() for i in issues):
            status = "error"
        elif any("API key" in i or "模型名" in i for i in issues):
            status = "warn"
        else:
            status = "error"

    return ProviderDiagnostic(
        provider_type=provider,
        model=model or "unspecified",
        base_url=_redact_base_url(base_url),
        api_key_present=bool(api_key),
        api_key_env=api_key_env,
        auth_scheme=auth_scheme,
        request_path=request_path,
        status=status,
        config_source=config_source,
        dotenv_loaded=_dotenv_loaded,
        dotenv_path=_dotenv_path_str,
        outer_env_overrides=outer_env_overrides,
        active_profile=active_profile,
        profile_source=profile_source,
        issues=issues,
        suggestions=suggestions,
    )


def diagnose_provider_config_from_unified(
    dotenv_path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> ProviderDiagnostic:
    """从 config/config.yaml 统一配置入口诊断 provider 配置。

    这是 v0.12+ 推荐入口，完整 resolution chain：
    1. config/config.yaml（推荐入口）
    2. FIRST_AGENT_PROVIDER_PROFILE（legacy fallback）
    3. MY_FIRST_AGENT_LLM_PROVIDER + 分散 env vars（legacy fallback）
    4. default fake

    不调用真实 API，不泄露 secret。
    """
    import os as _os

    if env is None:
        env = dict(_os.environ)

    # 1. config/config.yaml（推荐入口）
    from agent.provider.simple_config import load_unified_provider_config

    unified = load_unified_provider_config(env=env)

    # 如果 config.yaml 不存在，尝试 legacy fallback
    if unified.source == "default_fake":
        # 2. FIRST_AGENT_PROVIDER_PROFILE（legacy）
        from agent.provider.profiles import (
            load_provider_profiles,
            profile_to_agent_config,
            resolve_active_profile,
        )

        profiles = load_provider_profiles()
        if profiles:
            resolved, method = resolve_active_profile(profiles, env=env)
            if resolved is not None and method not in ("legacy", "default_fake"):
                if resolved.provider_type == "fake":
                    unified_config = _make_fake_config()
                else:
                    unified_config = profile_to_agent_config(resolved)
                return _build_diagnostic_from_config(
                    unified_config,
                    config_source="legacy_profile",
                    dotenv_path=dotenv_path,
                    active_profile=resolved.name,
                    profile_source=method,
                )

        # 3. MY_FIRST_AGENT_LLM_PROVIDER（legacy）
        # 使用 lenient diagnose_provider_config 直接读 env vars，
        # 避免 load_agent_provider_config 的严格校验（如 base_url 缺失）
        # 阻碍诊断输出。
        from agent.provider.config import PROVIDER_ENV

        if env.get(PROVIDER_ENV):
            legacy_diag = diagnose_provider_config(env=env)
            object.__setattr__(legacy_diag, "config_source", "legacy_provider_env")
            if dotenv_path is not None:
                _dp = Path(dotenv_path) if not isinstance(dotenv_path, Path) else dotenv_path
                _dv = _load_dotenv_values_safe(_dp)
                object.__setattr__(legacy_diag, "dotenv_loaded", bool(_dv))
                object.__setattr__(legacy_diag, "dotenv_path", str(_dp.resolve()))
            return legacy_diag

        # 4. default fake
        return _build_diagnostic_from_config(
            _make_fake_config(),
            config_source="default_fake",
            dotenv_path=dotenv_path,
        )

    # config 文件命中（config_local / config_yaml / config_yaml_disabled）
    unified_config = unified.config
    config_source: ConfigSourceKind = (
        "config_local" if unified.source == "config_local"
        else "config_yaml" if unified.source == "config_yaml"
        else "config_yaml_disabled"
    )

    # 检测 config.yaml 存在时是否有 legacy env/profile 被忽略
    legacy_ignored: list[str] = []
    from agent.provider.config import PROVIDER_ENV
    if env.get(PROVIDER_ENV):
        legacy_ignored.append(f"{PROVIDER_ENV}={env[PROVIDER_ENV]}")
    if env.get("FIRST_AGENT_PROVIDER_PROFILE"):
        legacy_ignored.append(f"FIRST_AGENT_PROVIDER_PROFILE={env['FIRST_AGENT_PROVIDER_PROFILE']}")

    return _build_diagnostic_from_config(
        unified_config,
        config_source=config_source,
        dotenv_path=dotenv_path,
        config_yaml_path=unified.yaml_path,
        config_error=unified.config_error,
        legacy_ignored=legacy_ignored,
    )


def _make_fake_config() -> AgentProviderConfig:
    """创建默认 fake provider 配置（与 simple_config._make_fake_config 一致）。"""
    return AgentProviderConfig(
        provider_type="fake",
        provider_name="fake",
        api_key=None,
        api_key_env=None,
        base_url=None,
        model="fake-llm",
        auth_scheme="auto",
        request_path="",
        supports_tools=False,
        supports_streaming=False,
        compatibility_mode="fake",
    )


def _build_diagnostic_from_config(
    config: AgentProviderConfig,
    *,
    config_source: ConfigSourceKind,
    dotenv_path: str | Path | None = None,
    config_yaml_path: str | None = None,
    config_error: str | None = None,
    active_profile: str | None = None,
    profile_source: str | None = None,
    legacy_ignored: list[str] | None = None,
) -> ProviderDiagnostic:
    """从 AgentProviderConfig 构建 ProviderDiagnostic（共享 helper）。

    避免在 diagnose_provider_config_from_unified 的多个分支中重复构建逻辑。
    """
    # 加载 dotenv
    _dotenv_loaded = False
    _dotenv_path_str: str | None = None
    if dotenv_path is not None:
        _dotenv_path = Path(dotenv_path)
        _dotenv_path_str = str(_dotenv_path.resolve())
        _dotenv_vals = _load_dotenv_values_safe(_dotenv_path)
        _dotenv_loaded = bool(_dotenv_vals)

    api_key_present = bool(config.api_key)
    base_url_display = _redact_base_url(config.base_url)

    issues: list[str] = []
    suggestions: list[str] = []

    if config_error:
        issues.append(config_error)

    if config.provider_type != "fake" and not api_key_present:
        issues.append(
            "provider.api_key 缺失。请在 config/config.yaml 的 "
            "provider section 中设置 api_key 或 api_key_env 字段"
        )
        suggestions.append(
            "编辑 config/config.yaml，在 provider section 添加 api_key 字段；"
            "或设置 provider.enabled=false 使用安全路径"
        )

    status: str = "ok"
    if issues:
        if config.provider_type == "fake" and all("API key" in i for i in issues):
            status = "ok"
            issues.clear()
        elif any("不支持的 provider type" in i for i in issues):
            status = "error"
        elif any("API key" in i for i in issues):
            status = "warn"
        else:
            status = "error"

    return ProviderDiagnostic(
        provider_type=config.provider_type,
        model=config.model or "unspecified",
        base_url=base_url_display,
        api_key_present=api_key_present,
        api_key_env=config.api_key_env,
        auth_scheme=config.auth_scheme,
        request_path=config.request_path,
        status=status,
        config_source=config_source,
        dotenv_loaded=_dotenv_loaded,
        dotenv_path=_dotenv_path_str,
        config_yaml_path=config_yaml_path,
        config_error=config_error,
        active_profile=active_profile,
        profile_source=profile_source,
        legacy_ignored=legacy_ignored or [],
        issues=issues,
        suggestions=suggestions,
    )


def diagnose_provider_config_isolated(
    dotenv_path: str | Path,
    *,
    provider_type: str | None = None,
) -> ProviderDiagnostic:
    """在隔离环境中诊断 provider 配置：只加载项目 .env，排除外层 env 干扰。

    v0.12+ 使用 load_unified_provider_config() 作为统一入口，
    优先检查 config/config.yaml。

    实现方式：
    1. 从当前 os.environ 复制，但移除所有已知 provider 相关 env var
    2. 然后从 dotenv_path 加载值（override=True，确保 .env 优先）
    3. 使用 diagnose_provider_config_from_unified() 在清理后的 env 上诊断
    """
    import os as _os

    # 所有已知 provider 相关 env var（需从外层 env 中清除）
    _provider_env_vars = [
        "MY_FIRST_AGENT_LLM_PROVIDER",
        "MY_FIRST_AGENT_LLM_PROVIDER_NAME",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "MY_FIRST_AGENT_LLM_MODEL",
        "MY_FIRST_AGENT_LLM_BASE_URL",
        "MY_FIRST_AGENT_LLM_AUTH_SCHEME",
        "MY_FIRST_AGENT_LLM_REQUEST_PATH",
        "MY_FIRST_AGENT_LLM_COMPATIBILITY_MODE",
        "MY_FIRST_AGENT_LLM_MAX_TOKENS",
        "MY_FIRST_AGENT_LLM_TIMEOUT",
        "MODEL_NAME",
        "FIRST_AGENT_PROVIDER_PROFILE",
    ]

    # 复制当前 env，移除所有 provider 相关变量
    clean_env = dict(_os.environ)
    for var in _provider_env_vars:
        clean_env.pop(var, None)

    # 从 .env 加载配置值
    _dotenv_path = Path(dotenv_path)
    dotenv_vals = _load_dotenv_values_safe(_dotenv_path)

    # 将 .env 值注入 clean_env（.env 值优先于 clean_env 中的残留）
    for k, v in dotenv_vals.items():
        clean_env[k] = v

    # 如果调用方显式指定了 provider_type，也注入
    if provider_type:
        clean_env["MY_FIRST_AGENT_LLM_PROVIDER"] = provider_type

    # 使用统一配置入口诊断
    diagnostic = diagnose_provider_config_from_unified(
        dotenv_path=_dotenv_path,
        env=clean_env,
    )

    # 在 isolated 模式下，如果 .env 提供了配置值，标记为 project_dotenv
    # 而非 legacy_provider_env，因为值确实来自项目的 .env 文件
    if diagnostic.config_source in ("legacy_provider_env", "legacy_profile") and dotenv_vals:
        object.__setattr__(diagnostic, "config_source", "project_dotenv")

    return diagnostic


def _render_api_key(diagnostic: ProviderDiagnostic) -> str:
    """脱敏显示 API key 状态。

    对于 config_local / config_yaml 路径且 api_key_env 由用户显式配置时，
    显示 SET (env, redacted; source=<VAR>)，帮助用户确认来源。
    对于 legacy env/profile 路径，只显示 SET (inline, redacted)，
    不暴露 auto-detected 的 env var 名称。
    """
    if not diagnostic.api_key_present:
        return "not set"
    if (
        diagnostic.api_key_env
        and diagnostic.config_source in ("config_local", "config_yaml", "config_yaml_disabled")
    ):
        return f"SET (env, redacted; source={diagnostic.api_key_env})"
    return "SET (inline, redacted)"


def render_diagnostic_report(diagnostic: ProviderDiagnostic) -> str:
    """将 ProviderDiagnostic 渲染为人类可读的诊断报告（不包含 secret）。"""
    lines = [
        "=" * 60,
        "  Provider Config Diagnostic",
        "=" * 60,
        "",
    ]

    # Config source 行（最优先显示，让用户知道配置来自哪里）
    _cs = diagnostic.config_source
    _yaml_path = diagnostic.config_yaml_path
    if _cs in ("config_local", "config_yaml", "config_yaml_disabled") and _yaml_path:
        source_label = f"{_cs} ({_yaml_path})"
        lines.append(f"  Config source : {source_label}")
        lines.append("  Recommended   : config/config.yaml")
    elif _cs in ("legacy_profile", "legacy_provider_env"):
        _legacy_name = {
            "legacy_profile": "FIRST_AGENT_PROVIDER_PROFILE",
            "legacy_provider_env": "MY_FIRST_AGENT_LLM_PROVIDER",
        }.get(_cs, _cs)
        lines.append(f"  Config source : {_cs} ({_legacy_name})")
        lines.append("                  ⚠️  legacy fallback — not recommended")
        lines.append(
            "                  → create config/config.yaml for current setup:\n"
            "                    cp config/config.example.yaml config/config.yaml"
        )
    else:
        source_label = {
            "default_fake": "default_fake",
            "project_dotenv": "project_dotenv",
            "shell_env": "shell_env",
            "mixed": "mixed",
            "unknown": "unknown",
        }.get(_cs, _cs)
        lines.append(f"  Config source : {source_label}")

    # config.yaml 存在但检测到 legacy env/profile 被忽略
    if diagnostic.legacy_ignored:
        lines.append(
            f"  Legacy env    : ignored ({', '.join(diagnostic.legacy_ignored)} detected"
            f" but config.yaml takes precedence)"
        )

    if diagnostic.config_error:
        lines.append(f"  Config error  : {diagnostic.config_error}")

    if diagnostic.active_profile:
        profile_source_label = {
            "profile_env": "from FIRST_AGENT_PROVIDER_PROFILE (legacy)",
            "profile_yaml": "from YAML default",
            "default_fake": "default",
            "legacy": "legacy (MY_FIRST_AGENT_LLM_PROVIDER)",
        }.get(diagnostic.profile_source or "", "")
        lines.append(f"  Active profile: {diagnostic.active_profile} ({profile_source_label})")

    lines.extend([
        f"  Provider type : {diagnostic.provider_type}",
        f"  Model         : {diagnostic.model}",
        f"  Base URL      : {diagnostic.base_url}",
        f"  API key       : {_render_api_key(diagnostic)}",
        f"  .env loaded   : {'yes' if diagnostic.dotenv_loaded else 'no'}",
    ])
    if diagnostic.dotenv_path:
        lines.append(f"  .env path     : {diagnostic.dotenv_path}")
    if diagnostic.outer_env_overrides:
        lines.append(
            f"  Outer overrides: {', '.join(sorted(diagnostic.outer_env_overrides))}"
        )
    lines.extend(["", f"  Status        : {diagnostic.status.upper()}", ""])

    if diagnostic.status == "ok":
        lines.append("  结论：provider 配置无问题。")
        if diagnostic.provider_type == "fake":
            lines.append("  provider mode = fake (local only) — 不调用真实 API。")
            if diagnostic.api_key_present:
                lines.append(
                    "  检测到 API key 已配置，但当前 fake 模式不会使用该 key。"
                )
            else:
                lines.append("  当前为 fake (local only) 安全路径，无需 API key。")
            if diagnostic.config_source in (
                "config_yaml_disabled", "default_fake",
                "legacy_profile", "legacy_provider_env",
            ):
                lines.append(
                    "  如需切换到真实 LLM，复制对应示例文件并填入 api_key：\n"
                    "    cp config/examples/kimi-anthropic-compatible.config.yaml"
                    " config/config.yaml   # Kimi K2.5\n"
                    "    cp config/examples/glm-openai-compatible.config.yaml"
                    " config/config.yaml        # GLM-5\n"
                    "  然后编辑 config/config.yaml，将 api_key 替换为真实 key\n"
                    "  最后 python main.py status 验证"
                )
            else:
                lines.append(
                    "  如需切换到真实 LLM，请编辑 config/config.yaml 设置 "
                    "enabled: true 并填入 api_key。"
                )
        else:
            if diagnostic.api_key_present:
                lines.append("  配置看起来完整，但连接性需用户显式 real-provider validation。")
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
