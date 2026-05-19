"""Filesystem-backed SubAgent registry.

Registry 是 runtime/session scoped：调用者显式传入 roots，实例只持有本次
session 的 descriptor index。这里不加载 body、不访问网络、不读取真实用户
agent 目录，也不提供 module-level global singleton。
"""

from __future__ import annotations

from pathlib import Path

from agent.subagent_system.descriptor import (
    SUBAGENT_MD_FILENAME,
    SubAgentDescriptor,
    load_subagent_descriptor,
)
from agent.subagent_system.errors import SubAgentLoadError


class SubAgentRegistry:
    """Deterministic descriptor registry for formal SubAgent System."""

    def __init__(self, roots: list[Path] | tuple[Path, ...] | None = None) -> None:
        self._roots = tuple(Path(root) for root in (roots or ()))
        self._descriptors: dict[str, SubAgentDescriptor] = {}
        self._load_errors: list[SubAgentLoadError] = []
        self.reload()

    def list_visible(self) -> tuple[SubAgentDescriptor, ...]:
        return tuple(descriptor for descriptor in self._descriptors.values() if descriptor.is_visible())

    def get_descriptor(self, name: str) -> SubAgentDescriptor | None:
        return self._descriptors.get(name)

    def find_by_role(self, role: str) -> tuple[SubAgentDescriptor, ...]:
        return tuple(descriptor for descriptor in self.list_visible() if descriptor.role == role)

    def is_registered(self, name: str) -> bool:
        return name in self._descriptors

    def get_load_errors(self) -> list[SubAgentLoadError]:
        """返回扫描过程中收集的所有 SubAgentLoadError。

        每次 reload() 会清空并重新收集。
        """
        return list(self._load_errors)

    def reload(self) -> None:
        """Re-scan explicit roots, preserving deterministic path order."""

        self._descriptors = {}
        self._load_errors.clear()
        for root in self._roots:
            self._scan_root(root)

    def _scan_root(self, root: Path) -> None:
        resolved = root.resolve(strict=False)
        if not resolved.exists():
            raise FileNotFoundError(f"SubAgent root does not exist: {resolved}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"SubAgent root is not a directory: {resolved}")

        for child in sorted(path for path in resolved.iterdir() if path.is_dir()):
            manifest_path = child / SUBAGENT_MD_FILENAME
            if not manifest_path.is_file():
                continue
            try:
                descriptor = load_subagent_descriptor(manifest_path)
            except SubAgentLoadError as exc:
                self._load_errors.append(exc)
                continue
            if descriptor.name in self._descriptors:
                raise SubAgentLoadError(
                    code="DUPLICATE_NAME",
                    message="Duplicate SubAgent name",
                    path=descriptor.manifest_path,
                    recoverable=False,
                    safe_preview=f"Duplicate SubAgent name: {descriptor.name}",
                )
            self._descriptors[descriptor.name] = descriptor

