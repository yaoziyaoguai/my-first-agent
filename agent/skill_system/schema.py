"""SKILL.md frontmatter 解析与校验。

Phase 1 只解析 metadata（YAML frontmatter）和 body 分离，不加载
references/scripts/templates（Phase 3 的 progressive disclosure 范围）。

设计原则（来自 RFC/SDD）：
- invalid SKILL.md fail closed
- duplicate / missing required fields fail closed
- 不执行任何代码、不访问网络、不读取 .env
- secret-like 值在 raw_frontmatter 中 redact 处理后才能进入审计
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent.skill_system.descriptor import (
    CONFIRMATION_POLICIES,
    MEMORY_SCOPES,
    RISK_LEVELS,
    SKILL_STATUSES,
    SkillManifest,
    SkillResourceManifest,
)
from agent.skill_system.errors import (
    CODE_INVALID_CONFIRMATION,
    CODE_INVALID_MEMORY_SCOPE,
    CODE_INVALID_NAME,
    CODE_INVALID_RESOURCE,
    CODE_INVALID_RISK_LEVEL,
    CODE_INVALID_STATUS,
    CODE_MISSING_DESCRIPTION,
    CODE_MISSING_FRONTMATTER,
    CODE_MISSING_NAME,
    CODE_MISSING_STATUS,
    CODE_MISSING_VERSION,
    CODE_PARSE_ERROR,
    CODE_SECRET_DETECTED,
    SkillLoadError,
)

# ---- 常量 ----

# SKILL.md 文件名
SKILL_MD_FILENAME = "SKILL.md"

# name 字段合法字符：小写字母、数字、连字符、下划线
_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# version 字段宽松 semver 校验
_VALID_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")

# 必填字段列表
_REQUIRED_FIELDS = ("name", "description", "version", "status")

# ---- Secret 检测 ----

# 常见 secret 前缀/模式（不穷举，只覆盖高频误用）
# 使用 [A-Za-z0-9_-] 以覆盖含连字符的 token 格式（如 sk-proj-..., sk-ant-api-...）
_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-[A-Za-z0-9_-]{20,}", "openai_api_key"),
    (r"ghp_[A-Za-z0-9]{20,}", "github_pat"),
    (r"gho_[A-Za-z0-9]{20,}", "github_oauth"),
    (r"ghu_[A-Za-z0-9]{20,}", "github_user_token"),
    (r"ghs_[A-Za-z0-9]{20,}", "github_server_token"),
    (r"ghr_[A-Za-z0-9]{20,}", "github_refresh_token"),
    (r"xox[bpras]-[A-Za-z0-9-]+", "slack_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"-----BEGIN\s*(RSA|EC|DSA|OPENSSH|PGP)\s*PRIVATE KEY-----", "private_key_pem"),
    (r"[A-Za-z0-9+/]{40,}={0,2}", "long_base64_like"),
]

# redact 后的替换值
_REDACTED_PLACEHOLDER = "<REDACTED>"


def _detect_secret(value: str) -> str | None:
    """检测字符串是否包含疑似 secret 模式。返回匹配的类别名或 None。"""
    for pattern, category in _SECRET_PATTERNS:
        if re.search(pattern, value):
            return category
    return None


def _redact_value(value: object) -> object:
    """递归 redact 可疑 secret 值。对于 dict/list，递归处理；对字符串检测替换。"""
    if isinstance(value, str):
        if _detect_secret(value):
            return _REDACTED_PLACEHOLDER
        return value
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


# ---- SKILL.md 解析 ----

def parse_skill_md(file_path: Path) -> tuple[dict[str, object], str]:
    """从 SKILL.md 文件中分离 YAML frontmatter 和 markdown body。

    返回 (raw_frontmatter_dict, body_string)。
    body 在当前 phase 不加载语义，仅返回字符串。

    Raises:
        SkillLoadError: 解析失败或 frontmatter 缺失
    """
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillLoadError(
            code=CODE_PARSE_ERROR,
            message=f"无法读取 SKILL.md: {exc}",
            path=file_path,
            recoverable=True,
            safe_preview="Skill 文件无法读取",
        ) from exc

    # 提取 YAML frontmatter
    if not raw_text.startswith("---"):
        raise SkillLoadError(
            code=CODE_MISSING_FRONTMATTER,
            message="SKILL.md 必须以 YAML frontmatter (---) 开头",
            path=file_path,
            recoverable=False,
            safe_preview="Skill 文件缺少必需的 YAML 头部",
        )

    # 找到第二个 --- 作为 frontmatter 结束标记
    rest = raw_text[3:]  # 跳过开头的 ---
    # 允许 \n--- 或直接 ---（兼容 frontmatter 末尾没有换行的情况）
    end_idx = rest.find("\n---")
    if end_idx == -1:
        end_idx = rest.find("---")
    if end_idx == -1:
        raise SkillLoadError(
            code=CODE_MISSING_FRONTMATTER,
            message="SKILL.md frontmatter 未正确闭合（缺少第二个 ---）",
            path=file_path,
            recoverable=False,
            safe_preview="Skill 文件 YAML 头部格式错误",
        )

    frontmatter_text = rest[:end_idx]
    body_text = rest[end_idx + 4:].lstrip("\n")

    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise SkillLoadError(
            code=CODE_PARSE_ERROR,
            message=f"YAML frontmatter 解析失败: {exc}",
            path=file_path,
            recoverable=False,
            safe_preview="Skill YAML 头部解析失败",
        ) from exc

    if not isinstance(frontmatter, dict):
        raise SkillLoadError(
            code=CODE_PARSE_ERROR,
            message="YAML frontmatter 必须解析为 dict/mapping",
            path=file_path,
            recoverable=False,
            safe_preview="Skill YAML 头部格式错误",
        )

    return frontmatter, body_text


# ---- Schema 校验 ----

def _parse_optional_str(raw: dict[str, object], key: str) -> str | None:
    """从 raw frontmatter 中提取可选字符串字段。

    空字符串视为 None，多行 YAML 字符串自动 strip。
    """
    value = raw.get(key)
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _parse_str_list(raw: dict[str, object], key: str) -> tuple[str, ...]:
    """从 raw frontmatter 中提取字符串列表字段。

    非 list 类型值静默返回空 tuple（向后兼容）。
    """
    value = raw.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(
        str(item).strip()
        for item in value
        if isinstance(item, (str, int, float)) and str(item).strip()
    )


def validate_manifest(
    raw: dict[str, object],
    skill_root: Path | None = None,
    manifest_path: Path | None = None,
) -> SkillManifest:
    """校验 raw frontmatter dict 并构造 SkillManifest。

    Phase 1 只校验 metadata 字段，不加载 references/scripts/templates 内容。

    Raises:
        SkillLoadError: 缺少必填字段、无效值、或检测到 secret
    """

    # --- 1. 必填字段检查 ---
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            code_map = {
                "name": CODE_MISSING_NAME,
                "description": CODE_MISSING_DESCRIPTION,
                "version": CODE_MISSING_VERSION,
                "status": CODE_MISSING_STATUS,
            }
            raise SkillLoadError(
                code=code_map.get(field, "MISSING_FIELD"),
                message=f"缺少必填字段: {field}",
                path=manifest_path,
                recoverable=False,
                safe_preview=f"Skill 缺少必填字段: {field}",
            )

    # --- 2. name 校验 ---
    name = str(raw["name"]).strip()
    if not name or not _VALID_NAME_RE.match(name):
        raise SkillLoadError(
            code=CODE_INVALID_NAME,
            message=f"无效的 Skill name: '{name}'——须为小写字母、数字、连字符、下划线，以字母开头",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 名称格式无效",
        )

    # --- 3. description 校验 ---
    description = str(raw["description"]).strip()
    if not description:
        raise SkillLoadError(
            code=CODE_MISSING_DESCRIPTION,
            message="description 不能为空",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 缺少描述",
        )

    # --- 4. version 校验 ---
    version = str(raw.get("version", "")).strip()
    if not version or not _VALID_VERSION_RE.match(version):
        raise SkillLoadError(
            code=CODE_MISSING_VERSION,
            message=f"无效或缺失的 version: '{version}'——需要语义化版本如 0.1.0",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 版本号格式无效",
        )

    # --- 5. status 校验 ---
    status = str(raw.get("status", "")).strip()
    if status not in SKILL_STATUSES:
        raise SkillLoadError(
            code=CODE_INVALID_STATUS,
            message=f"无效的 status: '{status}'——允许值: {sorted(SKILL_STATUSES)}",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 状态值无效",
        )

    # --- 6. risk_level 校验 ---
    risk_level = str(raw.get("risk_level", "low")).strip()
    if risk_level not in RISK_LEVELS:
        raise SkillLoadError(
            code=CODE_INVALID_RISK_LEVEL,
            message=f"无效的 risk_level: '{risk_level}'——允许值: {sorted(RISK_LEVELS)}",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 风险等级值无效",
        )

    # --- 7. confirmation_policy 校验 ---
    confirmation_policy = str(
        raw.get("confirmation_policy", "inherit_tool_policy")
    ).strip()
    if confirmation_policy not in CONFIRMATION_POLICIES:
        raise SkillLoadError(
            code=CODE_INVALID_CONFIRMATION,
            message=f"无效的 confirmation_policy: '{confirmation_policy}'",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill 确认策略值无效",
        )

    # --- 8. memory_scope 校验 ---
    memory_scope = str(raw.get("memory_scope", "none")).strip()
    if memory_scope not in MEMORY_SCOPES:
        raise SkillLoadError(
            code=CODE_INVALID_MEMORY_SCOPE,
            message=f"无效的 memory_scope: '{memory_scope}'——允许值: {sorted(MEMORY_SCOPES)}",
            path=manifest_path,
            recoverable=False,
            safe_preview="Skill Memory 范围值无效",
        )

    # --- 9. tags 校验 ---
    tags_raw = raw.get("tags", [])
    if not isinstance(tags_raw, list):
        tags_raw = []
    tags: tuple[str, ...] = tuple(
        str(t).strip() for t in tags_raw if isinstance(t, (str, int, float)) and str(t).strip()
    )

    # --- 10. allowed_tools 校验 ---
    tools_raw = raw.get("allowed_tools", [])
    if not isinstance(tools_raw, list):
        tools_raw = []
    allowed_tools: tuple[str, ...] = tuple(
        str(t).strip() for t in tools_raw if isinstance(t, str) and t.strip()
    )

    # --- 11. owner 校验 ---
    owner = str(raw.get("owner", "")).strip()

    # --- 12. resources 校验 ---
    resources_raw = raw.get("resources", {})
    if not isinstance(resources_raw, dict):
        resources_raw = {}
    resources = _validate_resources(resources_raw, manifest_path)

    # --- 13. Secret 检测——在 raw_frontmatter 上做 redact ---
    redacted_frontmatter = _redact_value(raw)
    # 检测是否有字段值被 redact 了（但 name/description 等非敏感字段除外）
    for key in ("name", "description", "version", "status", "tags", "allowed_tools", "owner"):
        if key in raw and _redact_value(raw[key]) == _REDACTED_PLACEHOLDER:
            raise SkillLoadError(
                code=CODE_SECRET_DETECTED,
                message=f"字段 '{key}' 包含疑似 secret 的值",
                path=manifest_path,
                recoverable=False,
                safe_preview="Skill 配置中包含不可接受的值",
            )

    # --- 14. 构造 SkillManifest ---
    return SkillManifest(
        name=name,
        description=description,
        version=version,
        status=status,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        tags=tags,
        allowed_tools=allowed_tools,
        memory_scope=memory_scope,  # type: ignore[arg-type]
        root=skill_root,
        manifest_path=manifest_path,
        confirmation_policy=confirmation_policy,  # type: ignore[arg-type]
        owner=owner,
        resources=resources,
        raw_frontmatter=redacted_frontmatter,  # type: ignore[arg-type]
        # ── Plan 3 manifest foundation 新字段 ──
        when_to_use=_parse_optional_str(raw, "when_to_use"),
        when_not_to_use=_parse_optional_str(raw, "when_not_to_use"),
        triggers=_parse_str_list(raw, "triggers"),
        negative_triggers=_parse_str_list(raw, "negative_triggers"),
        aliases=_parse_str_list(raw, "aliases"),
        locale=_parse_optional_str(raw, "locale"),
    )


def _validate_resources(
    raw: dict[str, object],
    manifest_path: Path | None = None,
) -> SkillResourceManifest:
    """校验 resources 块。

    每项必须是 list[str]；path 不能包含 .. 遍历逃逸。
    本 phase 只校验格式，不实际读取文件。
    """
    allowed_keys = {"references", "scripts", "templates", "tests", "dogfood"}
    result: dict[str, tuple[str, ...]] = {}

    for key in allowed_keys:
        value = raw.get(key, [])
        if not isinstance(value, list):
            raise SkillLoadError(
                code=CODE_INVALID_RESOURCE,
                message=f"resources.{key} 必须是 list",
                path=manifest_path,
                recoverable=False,
                safe_preview=f"Skill resources.{key} 格式无效",
            )

        paths: list[str] = []
        for item in value:
            item_str = str(item).strip()
            if not item_str:
                continue
            # 禁止路径逃逸
            if ".." in Path(item_str).parts:
                raise SkillLoadError(
                    code=CODE_INVALID_RESOURCE,
                    message=f"resources.{key} 包含不安全的路径: {item_str}",
                    path=manifest_path,
                    recoverable=False,
                    safe_preview="Skill resouce 路径无效",
                )
            paths.append(item_str)

        result[key] = tuple(paths)

    # 检查是否声明了不认识的 resource key
    for key in raw:
        if key not in allowed_keys:
            raise SkillLoadError(
                code=CODE_INVALID_RESOURCE,
                message=f"resources 包含未知 key: {key}",
                path=manifest_path,
                recoverable=False,
                safe_preview="Skill resources 声明了无效字段",
            )

    return SkillResourceManifest(**result)


def load_skill_manifest(skill_md_path: Path) -> SkillManifest:
    """便捷入口：读取 + 解析 + 校验 SKILL.md，返回 SkillManifest。

    这是 Phase 1 的主入口。后续 Phase 的 loader/registry 都通过此函数
    获得已校验的 manifest。
    """
    raw, _body = parse_skill_md(skill_md_path)
    return validate_manifest(
        raw,
        skill_root=skill_md_path.parent,
        manifest_path=skill_md_path,
    )
