"""Safe local Skill capability descriptors.

这个模块把 Stage 5 Skill MVP 限定为 fake/local/fixture descriptor：
- 只读取调用方显式传入的 tmp_path 或 tests/fixtures/skills；
- 不读取真实用户 skill 目录，也不扫描默认 `skills/`；
- 不下载、不安装、不执行任意代码；
- skill 只能声明 capability / instructions / allowed_tools，不能绕过 parent policy。
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
SAFE_DECLARABLE_TOOLS = frozenset({
    "read_file",
    "read_file_lines",
    "write_file",
    "edit_file",
    "request_user_input",
})
UNSAFE_METADATA_EXECUTION_KEYS = frozenset({
    "entrypoint",
    "command",
    "script",
    "scripts",
    "executable",
})
UNSAFE_METADATA_NETWORK_KEYS = frozenset({
    "source_url",
    "install_url",
    "download_url",
    "repository",
})
KEBAB_CASE_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SkillValidationIssue:
    """结构化 skill validation issue；message 不包含 secret 明文。"""

    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class SkillPermissionPolicy:
    """Skill 的父级策略边界。

    Skill MVP 只声明允许边界；真正 tool execution 仍必须由 parent runtime/tool
    policy 裁决，skill 自己没有执行权。
    """

    local_only: bool = True
    direct_tool_execution_allowed: bool = False
    network_install_allowed: bool = False
    arbitrary_code_execution_allowed: bool = False


@dataclass(frozen=True, slots=True)
class SkillCapabilityDescriptor:
    """Local skill capability descriptor，不是可执行 plugin。"""

    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    policy: SkillPermissionPolicy = field(default_factory=SkillPermissionPolicy)

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_tools", tuple(self.allowed_tools))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class SkillDescriptorResult:
    """Skill descriptor loading result；只保存 redacted descriptor。"""

    ok: bool
    descriptor: SkillCapabilityDescriptor | None = None
    errors: tuple[SkillValidationIssue, ...] = ()


class SkillPathPolicy:
    """Stage 5 safe path policy：只允许 tmp_path 和 tests/fixtures/skills。"""

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
        self.fixture_root = (self.project_root / "tests" / "fixtures" / "skills").resolve()

    def validate_skill_dir(self, path: str | Path) -> SkillValidationIssue | None:
        raw_path = Path(path)
        if (
            raw_path.name in SENSITIVE_PATH_NAMES
            or SENSITIVE_PATH_PARTS.intersection(raw_path.parts)
            or any(marker in raw_path.name.lower() for marker in SENSITIVE_NAME_MARKERS)
        ):
            return _issue("unsafe_path", "拒绝读取敏感或 secret-like skill 路径", field="path")

        resolved = raw_path.resolve(strict=False)
        if _is_relative_to(resolved, self.fixture_root):
            return None
        if _is_relative_to(resolved, self.temp_root):
            return None
        return _issue(
            "unsafe_path",
            "Skill MVP 只允许 tmp_path 或 tests/fixtures/skills 下的显式 skill",
            field="path",
        )


def load_local_skill_descriptor(
    skill_dir: str | Path,
    *,
    path_policy: SkillPathPolicy | None = None,
) -> SkillDescriptorResult:
    """Load a local fixture skill as metadata only.

    函数只解析 `SKILL.md` 文本，不执行其中任何命令，也不注册 tool。
    """

    skill_path = Path(skill_dir)
    policy = path_policy or SkillPathPolicy()
    path_issue = policy.validate_skill_dir(skill_path)
    if path_issue is not None:
        return SkillDescriptorResult(ok=False, errors=(path_issue,))

    try:
        raw_text = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return SkillDescriptorResult(
            ok=False,
            errors=(_issue("invalid_manifest", "无法读取 SKILL.md", field="SKILL.md"),),
        )

    parsed, parse_error = _parse_skill_markdown(raw_text)
    if parse_error is not None:
        return SkillDescriptorResult(ok=False, errors=(parse_error,))

    frontmatter, body = parsed
    validation_error = _validate_frontmatter(frontmatter, skill_path.name)
    if validation_error is not None:
        return SkillDescriptorResult(ok=False, errors=(validation_error,))

    policy_error = _validate_policy(frontmatter, body)
    if policy_error is not None:
        return SkillDescriptorResult(ok=False, errors=(policy_error,))

    descriptor = SkillCapabilityDescriptor(
        name=frontmatter["name"],
        description=frontmatter["description"],
        instructions=_redact_skill_text(body),
        allowed_tools=tuple(frontmatter.get("allowed-tools", ())),
        metadata=_redact_mapping(frontmatter.get("metadata", {})),
    )
    return SkillDescriptorResult(ok=True, descriptor=descriptor)


def format_skill_descriptor_for_display(result: SkillDescriptorResult) -> str:
    """Render a skill descriptor safely for CLI/evidence output."""

    if not result.ok or result.descriptor is None:
        lines = ["invalid local skill"]
        lines.extend(
            f"- {error.code} field={error.field}: {error.message}"
            if error.field
            else f"- {error.code}: {error.message}"
            for error in result.errors
        )
        return "\n".join(lines) + "\n"

    descriptor = result.descriptor
    tools = ", ".join(descriptor.allowed_tools) if descriptor.allowed_tools else "<none>"
    return (
        f"Skill: {descriptor.name}\n"
        f"description: {descriptor.description}\n"
        f"allowed_tools: {tools}\n"
        f"local_only: {descriptor.policy.local_only}\n"
        f"direct_tool_execution_allowed: "
        f"{descriptor.policy.direct_tool_execution_allowed}\n"
        f"instructions:\n{descriptor.instructions}\n"
    )


def _parse_skill_markdown(
    raw_text: str,
) -> tuple[tuple[dict[str, Any], str], SkillValidationIssue | None]:
    lines = raw_text.split("\n")
    if not lines or lines[0].strip() != "---":
        return ({}, ""), _issue("invalid_manifest", "SKILL.md 必须以 frontmatter 开头")
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        return ({}, ""), _issue("invalid_manifest", "SKILL.md frontmatter 未闭合")
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:end_index])) or {}
    except yaml.YAMLError:
        return ({}, ""), _issue("invalid_manifest", "SKILL.md frontmatter 不是合法 YAML")
    if not isinstance(frontmatter, dict):
        return ({}, ""), _issue("invalid_manifest", "frontmatter 必须是 object")
    return (frontmatter, "\n".join(lines[end_index + 1:]).strip()), None


def _validate_frontmatter(
    frontmatter: Mapping[str, Any],
    dir_name: str,
) -> SkillValidationIssue | None:
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not KEBAB_CASE_PATTERN.match(name):
        return _issue("invalid_manifest", "skill name 必须是 kebab-case", field="name")
    if name != dir_name:
        return _issue("invalid_manifest", "skill name 必须和目录名一致", field="name")
    if not isinstance(description, str) or not description.strip():
        return _issue("invalid_manifest", "skill description 必须是非空字符串", field="description")
    allowed_tools = frontmatter.get("allowed-tools", ())
    if not allowed_tools:
        return None
    if not isinstance(allowed_tools, list) or not all(
        isinstance(tool, str) for tool in allowed_tools
    ):
        return _issue("invalid_manifest", "allowed-tools 必须是字符串数组", field="allowed-tools")
    return None


def _validate_policy(
    frontmatter: Mapping[str, Any],
    body: str,
) -> SkillValidationIssue | None:
    metadata = frontmatter.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, Mapping):
        return _issue("invalid_manifest", "metadata 必须是 object", field="metadata")
    metadata_keys = {str(key).lower() for key in metadata}
    if metadata_keys & UNSAFE_METADATA_NETWORK_KEYS:
        return _issue("unsafe_network", "Skill MVP 不允许网络安装或远程来源", field="metadata")
    if metadata_keys & UNSAFE_METADATA_EXECUTION_KEYS:
        return _issue("unsafe_execution", "Skill MVP 不允许任意代码入口", field="metadata")
    allowed_tools = tuple(frontmatter.get("allowed-tools", ()) or ())
    if any(tool not in SAFE_DECLARABLE_TOOLS for tool in allowed_tools):
        return _issue("policy_bypass", "skill allowed-tools 不能声明未授权工具", field="allowed-tools")

    normalized_body = body.lower()
    if "curl " in normalized_body or "wget " in normalized_body or "http://" in normalized_body or "https://" in normalized_body:
        return _issue("unsafe_network", "Skill body 不允许网络安装或远程访问")
    if "subprocess" in normalized_body or "os.system" in normalized_body or "exec(" in normalized_body:
        return _issue("unsafe_execution", "Skill body 不允许代码执行指令")
    if "install_skill" in normalized_body or "call tool directly" in normalized_body:
        return _issue("policy_bypass", "Skill 不能要求绕过 parent tool policy")
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


def _redact_skill_text(text: str) -> str:
    redacted = re.sub(
        r"(?i)\b(TOKEN|API_KEY|SECRET|PASSWORD|AUTH)(\s*[:=]\s*)([^\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        text,
    )
    return redacted


def _is_secret_like(key: str, value: str) -> bool:
    normalized_key = key.upper()
    normalized_value = value.lower()
    return any(marker in normalized_key for marker in ("TOKEN", "API_KEY", "SECRET", "PASSWORD", "AUTH")) or any(
        marker in normalized_value for marker in ("token", "secret", "password", "api_key", "apikey")
    )


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
) -> SkillValidationIssue:
    return SkillValidationIssue(code=code, message=message, field=field)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
