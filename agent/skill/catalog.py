"""Strict immutable Skill catalog.

只读取显式 trust root 下的一级 Skill 目录，用严格 SafeLoader 子类解析 ``SKILL.md``
frontmatter，并冻结 descriptor / body / resource 的 identity 与 digest。

设计要点（见 ``docs/architecture/capabilities/SKILL_DESIGN.md``）：

- 不扫描默认目录（home、workspace、Coding Agent 的 ``.agents/.codex/.claude``）。
- 不执行 ``scripts/``，不 hot refresh；scan 后任一局部漂移都让旧 identity 失效。
- PyYAML 是可选依赖：未配置 root 时不导入；配置了 root 但缺失依赖时报 ``SkillDependencyError``。
- 错误信息不包含绝对路径或私有内容。
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

SKILL_FILE = "SKILL.md"
RESOURCE_DIRS = ("references", "assets")
SKILL_POLICY_VERSION = "skill-source-v1"
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_READ_CHUNK = 65536
_KNOWN_FRONTMATTER_KEYS = frozenset({
    "name", "description", "license", "compatibility", "metadata", "allowed-tools",
})


class SkillCatalogError(Exception):
    """catalog 构建或读取失败。错误信息不携带绝对路径或私有内容。"""


class SkillDependencyError(SkillCatalogError):
    """配置了 root 但可选依赖 PyYAML 缺失。"""


class SkillSchemaError(SkillCatalogError):
    """frontmatter / name / dir 合同违反，或 YAML 结构非法。"""


class SkillLimitError(SkillCatalogError):
    """文件 / node / body / resource / catalog 超限。"""


class SkillSecurityError(SkillCatalogError):
    """symlink / traversal / 非 UTF-8 / identity 漂移等安全违反。"""


@dataclass(frozen=True, slots=True)
class SkillLimits:
    max_skills: int = 64
    max_file_bytes: int = 200_000
    max_body_chars: int = 100_000
    max_resources: int = 64
    max_metadata_chars: int = 8_000
    max_resource_bytes: int = 100_000
    max_yaml_nodes: int = 2_000
    max_yaml_depth: int = 16
    max_scalar_bytes: int = 20_000

    def __post_init__(self) -> None:
        for name, value in (
            ("max_skills", self.max_skills),
            ("max_file_bytes", self.max_file_bytes),
            ("max_body_chars", self.max_body_chars),
            ("max_resources", self.max_resources),
            ("max_metadata_chars", self.max_metadata_chars),
            ("max_resource_bytes", self.max_resource_bytes),
            ("max_yaml_nodes", self.max_yaml_nodes),
            ("max_yaml_depth", self.max_yaml_depth),
            ("max_scalar_bytes", self.max_scalar_bytes),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class FileIdentity:
    """descriptor-relative 文件 identity，用于 drift 检测。不包含路径。"""

    dev: int
    ino: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SkillResourceDescriptor:
    relative_path: str
    digest: str
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class SkillDescriptor:
    """单个 Skill 的不可变描述。不持有绝对路径。"""

    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: Mapping[str, str]
    body_digest: str
    body_chars: int
    body_identity: FileIdentity | None
    # trust-root ancestor（skill 目录）identity：scan 时冻结，activation/read 重新校验，
    # 检测“保留 SKILL.md/resource inode 但替换目录”的 ancestor 替换攻击。不进 identity_digest。
    ancestor_identity: FileIdentity | None
    file_digest: str
    resource_inventory_digest: str
    resources: tuple[SkillResourceDescriptor, ...]
    policy_version: str

    @property
    def identity_digest(self) -> str:
        payload = {
            "name": self.name,
            "description": self.description,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": dict(sorted(self.metadata.items())),
            "body_digest": self.body_digest,
            "file_digest": self.file_digest,
            "resource_inventory_digest": self.resource_inventory_digest,
            "policy_version": self.policy_version,
        }
        return _digest_json(payload)


class ActivationResult(NamedTuple):
    body: str
    provenance: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SkillCatalog:
    """不可变 catalog：descriptors + 受 catalog 管控的文件读取。"""

    descriptors: tuple[SkillDescriptor, ...]
    catalog_digest: str
    limits: SkillLimits
    # name -> 已校验的 skill 目录 Path（catalog 内部使用，不进入 descriptor / event / checkpoint）。
    _paths: Mapping[str, Path] = field(default_factory=dict)

    def descriptor_for(self, name: str) -> SkillDescriptor:
        try:
            return next(descriptor for descriptor in self.descriptors if descriptor.name == name)
        except StopIteration as error:
            raise SkillSchemaError("unknown skill name") from error

    def read_activation(self, name: str) -> ActivationResult:
        descriptor = self.descriptor_for(name)
        skill_dir = self._paths[name]
        _revalidate_ancestor(descriptor, skill_dir)
        raw, current_identity = _read_regular(
            skill_dir / SKILL_FILE, self.limits.max_file_bytes
        )
        content = _decode_utf8(raw)
        _frontmatter, body = _split_frontmatter(content)
        file_digest = _sha256_bytes(raw)
        if file_digest != descriptor.file_digest:
            raise SkillSecurityError("skill content drift detected; rebuild the catalog")
        if descriptor.body_identity is not None:
            stored = descriptor.body_identity
            if (
                stored.dev != current_identity.dev
                or stored.ino != current_identity.ino
            ):
                raise SkillSecurityError(
                    "skill file identity drift detected; rebuild the catalog"
                )
        body_digest = _sha256_text(body)
        if body_digest != descriptor.body_digest:
            raise SkillSecurityError("skill body drift detected; rebuild the catalog")
        provenance: dict[str, object] = {
            "name": descriptor.name,
            "body_digest": descriptor.body_digest,
            "body_chars": descriptor.body_chars,
            "resource_inventory_digest": descriptor.resource_inventory_digest,
            "resources": tuple(
                {"path": resource.relative_path, "digest": resource.digest}
                for resource in descriptor.resources
            ),
        }
        return ActivationResult(body=body, provenance=provenance)

    def read_resource(self, name: str, relative_path: str) -> str:
        descriptor = self.descriptor_for(name)
        if not _is_allowed_resource_path(relative_path):
            raise SkillSecurityError("resource path is outside the allowed directories")
        resource = next(
            (r for r in descriptor.resources if r.relative_path == relative_path),
            None,
        )
        if resource is None:
            raise SkillSecurityError("resource is not part of the catalog inventory")
        skill_dir = self._paths[name]
        _revalidate_ancestor(descriptor, skill_dir)
        raw, current_identity = _read_regular(
            skill_dir / relative_path, self.limits.max_resource_bytes
        )
        # resource file identity（dev/ino）必须与 scan 时一致：相同内容、不同 inode 的
        # resource 替换也是 drift，不能只靠 digest 蒙混（与 activation 同一 opened-fd 合同）。
        if resource.identity is not None and (
            resource.identity.dev != current_identity.dev
            or resource.identity.ino != current_identity.ino
        ):
            raise SkillSecurityError("resource identity drift detected; rebuild the catalog")
        if _sha256_bytes(raw) != resource.digest:
            raise SkillSecurityError("resource drift detected; rebuild the catalog")
        return _decode_utf8(raw)


def build_skill_catalog(
    roots: Sequence[Path],
    *,
    limits: SkillLimits | None = None,
) -> SkillCatalog:
    """从显式 trust root 构建不可变 catalog。

    没配置 root 时返回空 catalog，且不导入可选依赖 PyYAML。
    """
    effective_limits = limits or SkillLimits()
    descriptors: list[SkillDescriptor] = []
    paths: dict[str, Path] = {}
    for root in roots:
        for descriptor, skill_dir in _iter_skill_dirs(root, effective_limits):
            if descriptor.name in paths:
                raise SkillSchemaError("duplicate skill name across roots")
            if descriptor.name in {existing.name for existing in descriptors}:
                raise SkillSchemaError("duplicate skill name across roots")
            paths[descriptor.name] = skill_dir
            descriptors.append(descriptor)
    if len(descriptors) > effective_limits.max_skills:
        raise SkillLimitError("too many skills configured")
    catalog_digest = _digest_json(
        {"descriptors": [d.identity_digest for d in descriptors], "limits": "v1"}
    )
    return SkillCatalog(
        descriptors=tuple(descriptors),
        catalog_digest=catalog_digest,
        limits=effective_limits,
        _paths=paths,
    )


def _iter_skill_dirs(root: Path, limits: SkillLimits):
    root_stat = _stat_no_follow(root)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise SkillSchemaError("skill root is not a directory")
    seen_names: set[str] = set()
    with os.scandir(root) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            if entry.is_symlink():
                raise SkillSecurityError("symlinked skill directory is not allowed")
            if not entry.is_dir(follow_symlinks=False):
                continue
            skill_file = Path(entry.path) / SKILL_FILE
            skill_file_stat = _stat_no_follow(skill_file)
            if not stat.S_ISREG(skill_file_stat.st_mode):
                # 没有 SKILL.md 的一级目录不是 Skill，跳过。
                continue
            descriptor = _build_descriptor(
                Path(entry.path), entry.name, skill_file_stat, limits
            )
            if descriptor.name in seen_names:
                raise SkillSchemaError("duplicate skill name within a root")
            seen_names.add(descriptor.name)
            yield descriptor, Path(entry.path)


def _build_descriptor(skill_dir, dir_name, skill_file_stat, limits):
    raw, body_identity = _read_regular(skill_dir / SKILL_FILE, limits.max_file_bytes)
    content = _decode_utf8(raw)
    frontmatter_str, body = _split_frontmatter(content)
    data = _parse_frontmatter(frontmatter_str, limits)
    unknown_keys = set(data) - _KNOWN_FRONTMATTER_KEYS
    if unknown_keys:
        raise SkillSchemaError("unknown frontmatter keys are not allowed")
    name = _require_string(data, "name")
    if not _NAME_PATTERN.match(name) or not 1 <= len(name) <= 64:
        raise SkillSchemaError("skill name does not match the required format")
    if name != dir_name:
        raise SkillSchemaError("skill name must equal its parent directory name")
    description = _require_string(data, "description")
    if not 1 <= len(description) <= 1024:
        raise SkillSchemaError("skill description length is out of range")
    license_value = _optional_string(data, "license")
    compatibility = _optional_string(data, "compatibility")
    if compatibility is not None and len(compatibility) > 500:
        raise SkillSchemaError("skill compatibility length is out of range")
    metadata = _extract_metadata(data.get("metadata"), limits)
    _extract_allowed_tools(data.get("allowed-tools"))
    body_chars = len(body)
    if body_chars > limits.max_body_chars:
        raise SkillLimitError("skill body exceeds the configured limit")
    resources = _scan_resources(skill_dir, limits)
    if len(resources) > limits.max_resources:
        raise SkillLimitError("skill resource count exceeds the configured limit")
    inventory_digest = _digest_json(
        [(resource.relative_path, resource.digest) for resource in resources]
    )
    ancestor_identity = _identity_from_stat(_stat_no_follow(skill_dir))
    return SkillDescriptor(
        name=name,
        description=description,
        license=license_value,
        compatibility=compatibility,
        metadata=metadata,
        body_digest=_sha256_text(body),
        body_chars=body_chars,
        body_identity=body_identity,
        ancestor_identity=ancestor_identity,
        file_digest=_sha256_bytes(raw),
        resource_inventory_digest=inventory_digest,
        resources=resources,
        policy_version=SKILL_POLICY_VERSION,
    )


def _scan_resources(skill_dir, limits):
    resources: list[SkillResourceDescriptor] = []
    for sub in RESOURCE_DIRS:
        sub_dir = skill_dir / sub
        try:
            sub_stat = os.stat(sub_dir, follow_symlinks=False)
        except FileNotFoundError:
            # references/ 或 assets/ 不存在表示该 Skill 没有可读资源，跳过。
            continue
        if stat.S_ISLNK(sub_stat.st_mode) or not stat.S_ISDIR(sub_stat.st_mode):
            raise SkillSecurityError("skill resource directory must be a real directory")
        with os.scandir(sub_dir) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                if entry.is_symlink():
                    raise SkillSecurityError("symlinked resource is not allowed")
                if not entry.is_dir(follow_symlinks=False):
                    # 只接受 references/ 与 assets/ 下的直接 regular file。
                    file_stat = _stat_no_follow(Path(entry.path))
                    if not stat.S_ISREG(file_stat.st_mode):
                        continue
                    raw, identity = _read_regular(Path(entry.path), limits.max_resource_bytes)
                    _decode_utf8(raw)  # 提前拒绝非 UTF-8 资源。
                    relative = f"{sub}/{entry.name}"
                    resources.append(
                        SkillResourceDescriptor(
                            relative_path=relative,
                            digest=_sha256_bytes(raw),
                            identity=identity,
                        )
                    )
    return tuple(resources)


def _read_regular(path: Path, max_bytes: int) -> tuple[bytes, FileIdentity]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SkillSecurityError("skill file is not a regular file")
        if st.st_size > max_bytes:
            raise SkillLimitError("skill file exceeds the configured limit")
        chunks: list[bytes] = []
        remaining = st.st_size
        while remaining > 0:
            chunk = os.read(fd, min(_READ_CHUNK, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        identity = _identity_from_stat(st)
        return b"".join(chunks), identity
    finally:
        os.close(fd)


def _identity_from_stat(st: os.stat_result) -> FileIdentity:
    return FileIdentity(
        dev=st.st_dev,
        ino=st.st_ino,
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
    )


def _revalidate_ancestor(descriptor: SkillDescriptor, skill_dir: Path) -> None:
    """重新校验 trust-root ancestor（skill 目录）identity（dev/ino）。

    检测“保留 SKILL.md/resource inode 但替换目录”的攻击：文件 identity 未变、digest 未变，
    只有目录 ancestor 变了。目录用 no-follow stat，比较 dev/ino（size/mtime 对目录无意义）。
    """
    stored = descriptor.ancestor_identity
    if stored is None:
        return
    current = _identity_from_stat(_stat_no_follow(skill_dir))
    if stored.dev != current.dev or stored.ino != current.ino:
        raise SkillSecurityError("skill directory identity drift detected; rebuild the catalog")


def _stat_no_follow(path: Path):
    try:
        return os.stat(path, follow_symlinks=False)
    except FileNotFoundError as error:
        raise SkillSchemaError("required skill path is missing") from error


def _decode_utf8(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SkillSecurityError("skill file must be valid UTF-8") from error


def _split_frontmatter(content: str) -> tuple[str, str]:
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        raise SkillSchemaError("SKILL.md must start with a frontmatter fence")
    close_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            close_index = index
            break
    if close_index is None:
        raise SkillSchemaError("skill frontmatter must be closed with a fence")
    frontmatter = "\n".join(lines[1:close_index])
    body = "\n".join(lines[close_index + 1 :])
    return frontmatter, body


def _parse_frontmatter(frontmatter_str: str, limits: SkillLimits) -> dict[str, object]:
    if not frontmatter_str.strip():
        raise SkillSchemaError("skill frontmatter must not be empty")
    yaml = _require_yaml()

    class _StrictLoader(yaml.SafeLoader):  # type: ignore[valid-type]
        def compose_node(self, parent, index):
            # PyYAML 在 compose 阶段就把 alias 解析回原节点，因此按事件类型在 compose
            # 之前拦截 AliasEvent，稳定拒绝 alias/cycle bomb。事件方法由 Parser mixin 提供。
            event = self.peek_event()
            if type(event).__name__ == "AliasEvent":
                raise SkillSchemaError("yaml aliases are not allowed in skill frontmatter")
            return super().compose_node(parent, index)

        def construct_mapping(self, node, deep=False):
            keys: set[object] = set()
            for key_node, _value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in keys:
                    raise SkillSchemaError("duplicate frontmatter key")
                keys.add(key)
            return super().construct_mapping(node, deep)

    loader = _StrictLoader(frontmatter_str)
    try:
        node = loader.get_single_node()
        if node is None:
            raise SkillSchemaError("skill frontmatter is empty")
        _enforce_node_bounds(node, limits, yaml)
        data = loader.construct_document(node)
    except SkillCatalogError:
        raise
    except yaml.YAMLError as error:
        raise SkillSchemaError("skill frontmatter is not valid yaml") from error
    finally:
        loader.dispose()
    if not isinstance(data, dict):
        raise SkillSchemaError("skill frontmatter must be a mapping")
    return data


def _enforce_node_bounds(root_node, limits: SkillLimits, yaml) -> None:
    count = 0
    stack: list[tuple[object, int]] = [(root_node, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > limits.max_yaml_nodes:
            raise SkillLimitError("too many yaml nodes in skill frontmatter")
        if depth > limits.max_yaml_depth:
            raise SkillLimitError("yaml nesting too deep in skill frontmatter")
        if isinstance(node, yaml.ScalarNode):
            if len(node.value.encode("utf-8")) > limits.max_scalar_bytes:
                raise SkillLimitError("yaml scalar exceeds the configured limit")
        elif isinstance(node, yaml.SequenceNode):
            for child in node.value:
                stack.append((child, depth + 1))
        elif isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                stack.append((key_node, depth + 1))
                stack.append((value_node, depth + 1))


def _require_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise SkillSchemaError(f"{key} must be a string")
    return value


def _optional_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillSchemaError(f"{key} must be a string")
    return value


def _extract_metadata(value: object, limits: SkillLimits) -> Mapping[str, str]:
    if value is None:
        return _frozen_map({})
    if not isinstance(value, dict):
        raise SkillSchemaError("metadata must be a mapping")
    total = 0
    frozen: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise SkillSchemaError("metadata keys and values must be strings")
        total += len(key) + len(item)
        if total > limits.max_metadata_chars:
            raise SkillLimitError("metadata exceeds the configured limit")
        frozen[key] = item
    return _frozen_map(frozen)


def _extract_allowed_tools(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise SkillSchemaError("allowed-tools must be a list")
    for item in value:
        if not isinstance(item, str):
            raise SkillSchemaError("allowed-tools entries must be strings")
    # v1 不把 allowed-tools 视为授权或预审批，仅校验形状后丢弃。


def _is_allowed_resource_path(relative_path: str) -> bool:
    if not relative_path:
        return False
    for part in relative_path.replace("\\", "/").split("/"):
        if part in ("", ".", ".."):
            return False
    for prefix in RESOURCE_DIRS:
        if relative_path == prefix or relative_path.startswith(prefix + "/"):
            return True
    return False


def _frozen_map(mapping: dict[str, str]) -> Mapping[str, str]:
    from types import MappingProxyType

    return MappingProxyType(dict(mapping))


def _require_yaml():
    try:
        import yaml
    except ImportError as error:
        raise SkillDependencyError(
            "PyYAML is required to read Skill roots; install the 'skill' extra"
        ) from error
    return yaml


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_json(value: object) -> str:
    import json

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
