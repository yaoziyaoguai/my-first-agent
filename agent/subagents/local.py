"""Safe local Subagent profiles and delegation contracts.

Subagent MVP 只表达 parent-controlled delegation request/result：
- 只读取显式 tmp_path 或 tests/fixtures/subagents；
- 不启动真实 LLM/provider；
- 不 spawn 外部进程；
- 不允许 child 自主执行工具；
- parent runtime/tool policy 始终保留最终控制权。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Any, Mapping

import yaml


REDACTED = "<redacted>"
SENSITIVE_PATH_NAMES = frozenset({".env", "agent_log.jsonl"})
SENSITIVE_PATH_PARTS = frozenset({"sessions", "runs"})
SENSITIVE_NAME_MARKERS = ("secret", "token", "password", "credential")
SAFE_DECLARABLE_TOOLS = frozenset({"read_file", "read_file_lines"})
SAFE_MODELS = frozenset({"fake", "fixture", "none"})
UNSAFE_METADATA_PROCESS_KEYS = frozenset({"command", "entrypoint", "process", "executable"})
KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SubagentValidationIssue:
    """Subagent validation issue；message 不包含 secret 明文。"""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class SubagentPermissionPolicy:
    """Subagent 的父控执行边界。"""

    local_only: bool = True
    real_llm_delegation_allowed: bool = False
    external_process_allowed: bool = False
    autonomous_tool_execution_allowed: bool = False


@dataclass(frozen=True, slots=True)
class SubagentProfile:
    """Local subagent profile，不是运行中的 child agent。"""

    name: str
    description: str
    role: str
    model: str
    instructions: str
    allowed_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    policy: SubagentPermissionPolicy = field(default_factory=SubagentPermissionPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_tools", tuple(self.allowed_tools))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SubagentProfileResult:
    ok: bool
    profile: SubagentProfile | None = None
    errors: tuple[SubagentValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """Parent-controlled fake delegation request."""

    subagent_name: str
    task: str
    allowed_tools: tuple[str, ...]
    parent_controlled: bool = True


@dataclass(frozen=True, slots=True)
class DelegationResult:
    """Fake delegation result；summary 已 redacted。"""

    ok: bool
    request: DelegationRequest | None = None
    summary: str = ""
    errors: tuple[SubagentValidationIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class DelegationRequestResult:
    ok: bool
    request: DelegationRequest | None = None
    errors: tuple[SubagentValidationIssue, ...] = ()


class SubagentPathPolicy:
    """只允许显式 tmp_path / tests fixture profile。"""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        temp_root: Path | None = None,
    ) -> None:
        self.project_root = (
            project_root
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.temp_root = (
            temp_root
            if temp_root is not None
            else Path(tempfile.gettempdir()).resolve()
        )
        self.fixture_root = (self.project_root / "tests" / "fixtures" / "subagents").resolve()

    def validate_profile_dir(self, path: str | Path) -> SubagentValidationIssue | None:
        raw_path = Path(path)
        if (
            raw_path.name in SENSITIVE_PATH_NAMES
            or SENSITIVE_PATH_PARTS.intersection(raw_path.parts)
            or any(marker in raw_path.name.lower() for marker in SENSITIVE_NAME_MARKERS)
        ):
            return _issue("unsafe_path", "拒绝读取敏感或 secret-like subagent 路径", field="path")
        resolved = raw_path.resolve(strict=False)
        if _is_relative_to(resolved, self.fixture_root):
            return None
        if _is_relative_to(resolved, self.temp_root):
            return None
        return _issue(
            "unsafe_path",
            "Subagent MVP 只允许 tmp_path 或 tests/fixtures/subagents 下的显式 profile",
            field="path",
        )


def load_local_subagent_profile(
    profile_dir: str | Path,
    *,
    path_policy: SubagentPathPolicy | None = None,
) -> SubagentProfileResult:
    """Load a fake/local subagent profile as metadata only."""

    profile_path = Path(profile_dir)
    policy = path_policy or SubagentPathPolicy()
    path_issue = policy.validate_profile_dir(profile_path)
    if path_issue is not None:
        return SubagentProfileResult(ok=False, errors=(path_issue,))

    try:
        raw_text = (profile_path / "SUBAGENT.md").read_text(encoding="utf-8")
    except OSError:
        return SubagentProfileResult(
            ok=False,
            errors=(_issue("invalid_profile", "无法读取 SUBAGENT.md", field="SUBAGENT.md"),),
        )

    parsed, parse_error = _parse_profile_markdown(raw_text)
    if parse_error is not None:
        return SubagentProfileResult(ok=False, errors=(parse_error,))
    frontmatter, body = parsed
    validation_error = _validate_frontmatter(frontmatter, profile_path.name)
    if validation_error is not None:
        return SubagentProfileResult(ok=False, errors=(validation_error,))
    policy_error = _validate_policy(frontmatter, body)
    if policy_error is not None:
        return SubagentProfileResult(ok=False, errors=(policy_error,))

    profile = SubagentProfile(
        name=frontmatter["name"],
        description=frontmatter["description"],
        role=frontmatter["role"],
        model=frontmatter.get("model", "fake"),
        instructions=_redact_text(body),
        allowed_tools=tuple(frontmatter.get("allowed-tools", ()) or ()),
        metadata=_redact_mapping(frontmatter.get("metadata", {}) or {}),
    )
    return SubagentProfileResult(ok=True, profile=profile)


def build_delegation_request(
    profile: SubagentProfile | None,
    *,
    task: str,
    parent_allowed_tools: tuple[str, ...],
) -> DelegationRequestResult:
    """Build a parent-controlled delegation request without executing anything."""

    if profile is None:
        return DelegationRequestResult(
            ok=False,
            errors=(_issue("invalid_profile", "缺少 subagent profile"),),
        )
    parent_allowed = set(parent_allowed_tools)
    requested = set(profile.allowed_tools)
    if not requested.issubset(parent_allowed):
        return DelegationRequestResult(
            ok=False,
            errors=(_issue("policy_bypass", "subagent allowed_tools 超出 parent policy"),),
        )
    return DelegationRequestResult(
        ok=True,
        request=DelegationRequest(
            subagent_name=profile.name,
            task=_redact_text(task),
            allowed_tools=tuple(sorted(requested)),
        ),
    )


def complete_fake_delegation(
    request: DelegationRequest,
    *,
    summary: str,
) -> DelegationResult:
    """Complete fake delegation with a redacted summary; no child execution occurs."""

    return DelegationResult(
        ok=True,
        request=request,
        summary=_redact_text(summary),
    )


def format_delegation_result_for_display(result: DelegationResult) -> str:
    if not result.ok:
        return _render_issues("invalid subagent delegation", result.errors)
    request = result.request
    subagent = request.subagent_name if request is not None else "<unknown>"
    return (
        f"Subagent result: {subagent}\n"
        f"parent_controlled={request.parent_controlled if request is not None else True}\n"
        f"summary:\n{result.summary}\n"
    )


def _parse_profile_markdown(
    raw_text: str,
) -> tuple[tuple[dict[str, Any], str], SubagentValidationIssue | None]:
    lines = raw_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return ({}, ""), _issue("invalid_profile", "SUBAGENT.md 必须以 frontmatter 开头")
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return ({}, ""), _issue("invalid_profile", "SUBAGENT.md frontmatter 未闭合")
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    except yaml.YAMLError:
        return ({}, ""), _issue("invalid_profile", "frontmatter 不是合法 YAML")
    if not isinstance(frontmatter, dict):
        return ({}, ""), _issue("invalid_profile", "frontmatter 必须是 object")
    return (frontmatter, "\n".join(lines[end_index + 1:]).strip()), None


def _validate_frontmatter(
    frontmatter: Mapping[str, Any],
    dir_name: str,
) -> SubagentValidationIssue | None:
    name = frontmatter.get("name")
    if not isinstance(name, str) or not KEBAB_CASE_PATTERN.match(name):
        return _issue("invalid_profile", "subagent name 必须是 kebab-case", field="name")
    if name != dir_name:
        return _issue("invalid_profile", "subagent name 必须和目录名一致", field="name")
    for field_name in ("description", "role"):
        value = frontmatter.get(field_name)
        if not isinstance(value, str) or not value.strip():
            return _issue("invalid_profile", f"{field_name} 必须是非空字符串", field=field_name)
    allowed_tools = frontmatter.get("allowed-tools", ())
    if allowed_tools and (
        not isinstance(allowed_tools, list)
        or not all(isinstance(tool, str) for tool in allowed_tools)
    ):
        return _issue("invalid_profile", "allowed-tools 必须是字符串数组", field="allowed-tools")
    return None


def _validate_policy(
    frontmatter: Mapping[str, Any],
    body: str,
) -> SubagentValidationIssue | None:
    model = frontmatter.get("model", "fake")
    if model not in SAFE_MODELS:
        return _issue("real_llm_delegation", "Subagent MVP 不允许真实 LLM delegation", field="model")
    metadata = frontmatter.get("metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return _issue("invalid_profile", "metadata 必须是 object", field="metadata")
    metadata_keys = {str(key).lower() for key in metadata}
    if metadata_keys & UNSAFE_METADATA_PROCESS_KEYS:
        return _issue("external_process", "Subagent MVP 不允许外部进程入口", field="metadata")
    allowed_tools = tuple(frontmatter.get("allowed-tools", ()) or ())
    if any(tool not in SAFE_DECLARABLE_TOOLS for tool in allowed_tools):
        return _issue("policy_bypass", "subagent allowed-tools 不能声明未授权工具", field="allowed-tools")
    normalized_body = body.lower()
    if "subprocess" in normalized_body or "spawn" in normalized_body:
        return _issue("external_process", "Subagent body 不允许进程启动指令")
    if "real provider" in normalized_body or "real llm" in normalized_body:
        return _issue("real_llm_delegation", "Subagent body 不允许真实 provider delegation")
    if "call tool directly" in normalized_body or "execute_tool" in normalized_body:
        return _issue("policy_bypass", "Subagent 不能要求绕过 parent tool policy")
    return None


def _redact_mapping(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({
        str(key): _redact_value(str(key), value)
        for key, value in sorted(mapping.items(), key=lambda item: str(item[0]))
    })


def _redact_value(key: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(_redact_mapping(value))
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    text = str(value)
    if _is_secret_like(key, text):
        return REDACTED
    return value


def _redact_text(text: str) -> str:
    return re.sub(
        r"(?i)\b(TOKEN|API_KEY|SECRET|PASSWORD|AUTH)(\s*[:=]\s*)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        text,
    )


def _is_secret_like(key: str, value: str) -> bool:
    normalized_key = key.upper()
    normalized_value = value.lower()
    return any(marker in normalized_key for marker in ("TOKEN", "API_KEY", "SECRET", "PASSWORD", "AUTH")) or any(
        marker in normalized_value for marker in ("token", "secret", "password", "api_key", "apikey")
    )


def _render_issues(title: str, issues: tuple[SubagentValidationIssue, ...]) -> str:
    lines = [title]
    for issue in issues:
        field = f" field={issue.field}" if issue.field else ""
        lines.append(f"- {issue.code}{field}: {issue.message}")
    return "\n".join(lines) + "\n"


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> SubagentValidationIssue:
    return SubagentValidationIssue(code=code, message=message, field=field)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
