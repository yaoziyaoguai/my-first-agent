"""Memory store 的不可变合同类型。"""

from __future__ import annotations

from dataclasses import dataclass


class MemoryStoreError(RuntimeError):
    """Memory store 操作违反。错误信息不携带 store 路径或完整 inventory。"""


class MemoryBusyError(MemoryStoreError):
    """effect 前无法在 deadline 内取得锁（known-not-executed）。"""


class MemoryCasMismatchError(MemoryStoreError):
    """store/record revision 或 content digest 前置条件不匹配。"""


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    record_id: str
    workspace_scope_digest: str
    content: str
    content_digest: str
    created_at: float
    updated_at: float
    revision: int
    source_fact_id: str | None = None
    origin: str | None = None
    admission_binding_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.record_id or not self.workspace_scope_digest:
            raise ValueError("record identity fields must not be empty")
        if self.revision < 0:
            raise ValueError("record revision must be non-negative")
        provenance = (self.source_fact_id, self.origin, self.admission_binding_digest)
        if any(value is not None for value in provenance) and not all(
            isinstance(value, str) and value for value in provenance
        ):
            raise ValueError("record provenance must be complete when present")


@dataclass(frozen=True, slots=True)
class ProviderTrustProfile:
    """非秘密的 provider 信任 profile identity，绑定 store header。"""

    profile_id: str
    provider_family: str
    destination: str

    def __post_init__(self) -> None:
        if not self.profile_id or not self.provider_family or not self.destination:
            raise ValueError("provider trust profile fields must not be empty")
