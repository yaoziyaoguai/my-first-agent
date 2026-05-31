"""Skill 注册表——runtime/session-scoped 的文件系统扫描与查询。

Phase 2 只做 metadata 发现和注册，不加载 body，不实现 selector。

设计原则（来自 RFC/SDD）：
- 不使用 module-level global singleton
- roots 必须显式传入
- 确定性文件系统扫描（排序路径）
- duplicate name fail closed
- disabled/hidden Skill 不在 visible list 中出现
- 不读取 .env、不执行 scripts、不加载 references/scripts/templates
- 不 import legacy agent.skills / agent.legacy_skills
"""
from __future__ import annotations

from pathlib import Path

from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.errors import (
    CODE_DUPLICATE_NAME,
    SkillLoadError,
)
from agent.skill_system.schema import SKILL_MD_FILENAME, load_skill_manifest


class SkillRegistry:
    """runtime/session-scoped 的 Skill 注册表。

    构造时传入显式 root 列表，discover 扫描每个 root 下包含 SKILL.md 的
    子目录，校验并提取 SkillDescriptor。不持有 state/loop/network/body。

    Usage::

        registry = SkillRegistry(roots=[Path("./skills")])
        for desc in registry.list_visible():
            print(desc.name)
    """

    def __init__(self, roots: list[Path] | None = None):
        self._roots: list[Path] = list(roots) if roots else []
        # _descriptors: name → SkillDescriptor（含 visible 和 hidden）
        self._descriptors: dict[str, SkillDescriptor] = {}
        # _manifests: name → SkillManifest（供 retriever 等需要新字段的组件使用）
        self._manifests: dict[str, object] = {}
        # _load_errors: 扫描过程中收集的 SkillLoadError（不会静默丢弃）
        self._load_errors: list[SkillLoadError] = []
        self._discover()

    # ---- public API ----

    def list_visible(self) -> list[SkillDescriptor]:
        """返回所有可见（disabled/legacy 以外）的 SkillDescriptor。

        返回顺序是确定性的：先按 root 顺序，同 root 内按目录名排序。
        """
        return [
            d
            for d in self._descriptors.values()
            if d.is_visible()
        ]

    def get_descriptor(self, name: str) -> SkillDescriptor | None:
        """按 name 查询单个 SkillDescriptor，含 hidden/disabled。

        返回 None 表示未找到。
        """
        return self._descriptors.get(name)

    def add_root(self, root: Path) -> None:
        """动态添加 skill root 并重新扫描。

        新增 root 的扫描失败不会清除已注册的 descriptors（partial success）。
        """
        self._roots.append(root)
        self._scan_root(root)

    def list_visible_manifests(self) -> list[object]:
        """返回所有可见 skill 的 SkillManifest 列表。

        供 SkillCandidateRetriever 等需要 manifest 新字段的组件使用。
        返回类型为 object 以避免循环导入（实际为 SkillManifest）。
        """
        return [
            m
            for name, m in self._manifests.items()
            if self._descriptors.get(name) and self._descriptors[name].is_visible()
        ]

    def get_load_errors(self) -> list[SkillLoadError]:
        """返回扫描过程中收集的所有 SkillLoadError。

        每次 _discover() / reset() 会清空并重新收集。
        调用方可通过此方法诊断哪些 SKILL.md 因何原因被跳过。
        """
        return list(self._load_errors)

    def reset(self) -> None:
        """清空并重新扫描所有 root——用于测试和配置变更。"""
        self._descriptors.clear()
        self._manifests.clear()
        self._load_errors.clear()
        self._discover()

    # ---- internal ----

    def _discover(self) -> None:
        """扫描所有 root，收集 Skill 元数据。"""
        self._load_errors.clear()
        for root in self._roots:
            self._scan_root(root)

    def _scan_root(self, root: Path) -> None:
        """扫描单个 root 目录下所有包含 SKILL.md 的子目录。

        只扫描直接子目录（不递归），按目录名排序以保证确定性。
        """
        resolved = root.resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"Skill root 不存在或不是目录: {resolved}")

        # 只扫描直接子目录，按名称排序保证确定性
        candidates = sorted(
            p for p in resolved.iterdir() if p.is_dir()
        )

        for skill_dir in candidates:
            manifest_path = skill_dir / SKILL_MD_FILENAME
            if not manifest_path.is_file():
                continue

            try:
                manifest = load_skill_manifest(manifest_path)
            except SkillLoadError as exc:
                self._load_errors.append(exc)
                continue
            descriptor = manifest.to_descriptor()
            self._manifests[descriptor.name] = manifest

            # duplicate name detection
            if descriptor.name in self._descriptors:
                existing = self._descriptors[descriptor.name]
                raise SkillLoadError(
                    code=CODE_DUPLICATE_NAME,
                    message=(
                        f"重复的 Skill name '{descriptor.name}': "
                        f"已注册于 {existing.root}，"
                        f"冲突路径 {descriptor.root}"
                    ),
                    path=descriptor.manifest_path,
                    recoverable=False,
                    safe_preview=f"发现重复的 Skill 名称: {descriptor.name}",
                )

            self._descriptors[descriptor.name] = descriptor
