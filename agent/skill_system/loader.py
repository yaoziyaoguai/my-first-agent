"""Skill Loader——progressive disclosure 的 body/resource 加载器。

设计原则（来自 RFC Sec 5 / SDD Sec 5）：
- Level 1: metadata 由 registry 返回，不通过 loader
- Level 2: body 仅在 Skill 被选中后加载
- Level 3: references/scripts/templates/tests/dogfood 仅按需加载
- loader 不执行代码、不访问网络、不 pip install、不读 .env
- 资源路径不能逃逸出 skill 目录
- hidden/disabled Skill 的 body 不默认加载
- 大文件资源不默认加载
"""
from __future__ import annotations

from pathlib import Path

from agent.skill_system.errors import (
    CODE_INVALID_RESOURCE,
    CODE_UNSAFE_PATH,
    SkillLoadError,
)
from agent.skill_system.registry import SkillRegistry
from agent.skill_system.schema import parse_skill_md

# 允许的 resource 子目录（Level 3）
_ALLOWED_RESOURCE_DIRS = frozenset({
    "references",
    "scripts",
    "templates",
    "tests",
    "dogfood",
})

# 默认最大资源文件大小（字节）
_DEFAULT_MAX_RESOURCE_BYTES = 100 * 1024  # 100 KB


class SkillLoader:
    """Progressive disclosure loader——按需加载 body 和 resource。

    Usage::

        registry = SkillRegistry(roots=[...])
        loader = SkillLoader(registry)
        body = loader.load_body("my-skill")           # Level 2
        ref = loader.load_resource("my-skill", "references", "guide.md")  # Level 3
    """

    def __init__(
        self,
        registry: SkillRegistry,
        max_resource_bytes: int = _DEFAULT_MAX_RESOURCE_BYTES,
    ):
        self._registry = registry
        self._max_resource_bytes = max_resource_bytes
        # body 缓存: name -> body str
        self._bodies: dict[str, str] = {}
        # 已加载资源追踪: name -> set of "category/path"
        self._loaded_resources: dict[str, set[str]] = {}
        # 最高加载 level 追踪: name -> int (2 或 3)
        self.loaded_levels: dict[str, int] = {}

    # ---- Level 2: body loading ----

    def load_body(self, name: str) -> str:
        """加载已选中 Skill 的 SKILL.md body。

        必须先有 descriptor 且 visible；hidden/disabled Skill 拒绝加载。
        结果缓存，重复调用返回缓存值。
        """
        descriptor = self._registry.get_descriptor(name)
        if descriptor is None:
            raise SkillLoadError(
                code="SKILL_NOT_FOUND",
                message=f"Skill '{name}' 未在 registry 中找到",
                recoverable=False,
                safe_preview=f"Skill '{name}' 不存在",
            )

        if not descriptor.is_visible():
            raise SkillLoadError(
                code="SKILL_HIDDEN",
                message=f"Skill '{name}' 状态为 {descriptor.status}，body 不可加载",
                path=descriptor.manifest_path,
                recoverable=False,
                safe_preview=f"Skill '{name}' 不可用",
            )

        # 缓存命中
        if name in self._bodies:
            return self._bodies[name]

        # 解析 SKILL.md 获取 body
        if descriptor.manifest_path is None:
            raise SkillLoadError(
                code="NO_MANIFEST",
                message=f"Skill '{name}' 没有 SKILL.md 路径",
                recoverable=False,
                safe_preview=f"Skill '{name}' 配置异常",
            )

        _, body = parse_skill_md(descriptor.manifest_path)
        self._bodies[name] = body
        self.loaded_levels[name] = max(self.loaded_levels.get(name, 1), 2)
        return body

    # ---- Level 3: on-demand resource loading ----

    def load_resource(
        self,
        skill_name: str,
        category: str,
        resource_path: str,
    ) -> str:
        """按需加载 Skill 的单个资源文件。

        Args:
            skill_name: Skill name
            category: 资源类别（references/scripts/templates/tests/dogfood）
            resource_path: 相对于 category 目录的资源路径

        Raises:
            SkillLoadError: 路径不安全、类别无效、文件过大、或文件不存在
        """
        descriptor = self._registry.get_descriptor(skill_name)
        if descriptor is None:
            raise SkillLoadError(
                code="SKILL_NOT_FOUND",
                message=f"Skill '{skill_name}' 未在 registry 中找到",
                recoverable=False,
                safe_preview=f"Skill '{skill_name}' 不存在",
            )

        if category not in _ALLOWED_RESOURCE_DIRS:
            raise SkillLoadError(
                code=CODE_INVALID_RESOURCE,
                message=f"不允许的资源类别: {category}，允许值: {sorted(_ALLOWED_RESOURCE_DIRS)}",
                recoverable=False,
                safe_preview="请求了无效的资源类别",
            )

        if descriptor.root is None:
            raise SkillLoadError(
                code="NO_ROOT",
                message=f"Skill '{skill_name}' 没有 root 路径",
                recoverable=False,
                safe_preview=f"Skill '{skill_name}' 配置异常",
            )

        # 规范化路径并校验
        normalized = Path(resource_path)
        if normalized.is_absolute():
            raise SkillLoadError(
                code=CODE_UNSAFE_PATH,
                message=f"资源路径不能是绝对路径: {resource_path}",
                recoverable=False,
                safe_preview="资源路径无效",
            )

        # 禁止路径逃逸
        parts = normalized.parts
        if ".." in parts or any(p.startswith(".") and p not in (".",) for p in parts if p.startswith(".")):
            if ".." in parts:
                raise SkillLoadError(
                    code=CODE_UNSAFE_PATH,
                    message=f"资源路径包含路径逃逸: {resource_path}",
                    recoverable=False,
                    safe_preview="资源路径无效",
                )
            # .env 明确阻止
            if normalized.name == ".env" or ".env" in parts:
                raise SkillLoadError(
                    code=CODE_UNSAFE_PATH,
                    message=f"禁止读取 .env 文件: {resource_path}",
                    recoverable=False,
                    safe_preview="不允许的操作",
                )

        # 构造完整路径
        full_path = (descriptor.root / category / normalized).resolve()

        # 二次确认解析后的路径仍在 skill root 内
        try:
            full_path.relative_to(descriptor.root.resolve())
        except ValueError:
            raise SkillLoadError(
                code=CODE_UNSAFE_PATH,
                message=f"资源路径逃逸出 skill 目录: {resource_path} → {full_path}",
                recoverable=False,
                safe_preview="资源路径无效",
            )

        if not full_path.is_file():
            raise SkillLoadError(
                code="RESOURCE_NOT_FOUND",
                message=f"资源文件不存在: {full_path}",
                path=full_path,
                recoverable=True,
                safe_preview="请求的资源文件不存在",
            )

        # 大小检查
        file_size = full_path.stat().st_size
        if file_size > self._max_resource_bytes:
            raise SkillLoadError(
                code="RESOURCE_TOO_LARGE",
                message=f"资源文件过大: {file_size} bytes (max: {self._max_resource_bytes})",
                path=full_path,
                recoverable=False,
                safe_preview="资源文件过大，拒绝加载",
            )

        # 读取内容
        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SkillLoadError(
                code="RESOURCE_READ_ERROR",
                message=f"无法读取资源文件: {exc}",
                path=full_path,
                recoverable=True,
                safe_preview="资源文件读取失败",
            ) from exc

        # 追踪
        resource_key = f"{category}/{resource_path}"
        self._loaded_resources.setdefault(skill_name, set()).add(resource_key)
        self.loaded_levels[skill_name] = max(
            self.loaded_levels.get(skill_name, 1), 3
        )
        return content

    # ---- 审计 ----

    def get_audit_record(self, skill_name: str) -> dict[str, object]:
        """生成单个 Skill 的加载审计记录。"""
        loaded = self._loaded_resources.get(skill_name, set())
        return {
            "skill_name": skill_name,
            "loaded_level": self.loaded_levels.get(skill_name, 0),
            "loaded_resources": sorted(loaded),
            "body_loaded": skill_name in self._bodies,
        }
