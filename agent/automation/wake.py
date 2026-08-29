"""Platform-neutral wake adapter contract for 019 activation orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agent.runtime.contracts import canonical_json_digest


class WakeReadbackOutcome(StrEnum):
    ABSENT = "absent"
    INSTALLED = "installed"
    DRIFT = "drift"
    UNKNOWN = "unknown"


class WakeInstallOutcome(StrEnum):
    INSTALLED = "installed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class WakeRemoveOutcome(StrEnum):
    REMOVED = "removed"
    BUSY = "busy"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WakeReadbackV1:
    outcome: WakeReadbackOutcome
    requested_policy_digest: str
    installed_policy_digest: str | None
    adapter_projection_digest: str | None


@dataclass(frozen=True, slots=True)
class WakeInstallResultV1:
    outcome: WakeInstallOutcome
    requested_policy_digest: str
    adapter_projection_digest: str | None


@dataclass(frozen=True, slots=True)
class WakeRemoveResultV1:
    outcome: WakeRemoveOutcome
    requested_policy_digest: str
    adapter_projection_digest: str | None


class WakeAdapter(Protocol):
    @property
    def configured_policy_digest(self) -> str: ...

    def readback(self, policy_digest: str) -> WakeReadbackV1: ...

    def install(self, policy_digest: str) -> WakeInstallResultV1: ...

    def remove(self, policy_digest: str) -> WakeRemoveResultV1: ...


class DeterministicWakeAdapter:
    """Protocol adapter with closed install outcomes and no OS integration."""

    def __init__(
        self,
        *,
        next_install_outcome: WakeInstallOutcome = WakeInstallOutcome.INSTALLED,
        next_remove_outcome: WakeRemoveOutcome = WakeRemoveOutcome.REMOVED,
        after_install: Callable[[], None] | None = None,
        worker_running: Callable[[], bool] | None = None,
        policy_digest: str = "8" * 64,
    ) -> None:
        _require_digest(policy_digest)
        self._configured_policy_digest = policy_digest
        self._installed_policy_digest: str | None = None
        self._next_install_outcome = next_install_outcome
        self._next_remove_outcome = next_remove_outcome
        self._after_install = after_install
        self._worker_running = worker_running or (lambda: False)
        self._install_count = 0
        self._remove_count = 0

    @property
    def configured_policy_digest(self) -> str:
        return self._configured_policy_digest

    @property
    def install_count(self) -> int:
        return self._install_count

    @property
    def remove_count(self) -> int:
        return self._remove_count

    def readback(self, policy_digest: str) -> WakeReadbackV1:
        _require_digest(policy_digest)
        if policy_digest != self._configured_policy_digest:
            return WakeReadbackV1(
                outcome=WakeReadbackOutcome.DRIFT,
                requested_policy_digest=policy_digest,
                installed_policy_digest=self._configured_policy_digest,
                adapter_projection_digest=_projection_digest(
                    self._configured_policy_digest
                ),
            )
        installed = self._installed_policy_digest
        if installed is None:
            outcome = WakeReadbackOutcome.ABSENT
            projection = None
        elif installed == policy_digest:
            outcome = WakeReadbackOutcome.INSTALLED
            projection = _projection_digest(installed)
        else:
            outcome = WakeReadbackOutcome.DRIFT
            projection = _projection_digest(installed)
        return WakeReadbackV1(
            outcome=outcome,
            requested_policy_digest=policy_digest,
            installed_policy_digest=installed,
            adapter_projection_digest=projection,
        )

    def install(self, policy_digest: str) -> WakeInstallResultV1:
        _require_digest(policy_digest)
        self._install_count += 1
        if policy_digest != self._configured_policy_digest:
            return WakeInstallResultV1(
                outcome=WakeInstallOutcome.UNKNOWN,
                requested_policy_digest=policy_digest,
                adapter_projection_digest=None,
            )
        outcome = self._next_install_outcome
        if outcome is WakeInstallOutcome.INSTALLED:
            self._installed_policy_digest = policy_digest
            projection = _projection_digest(policy_digest)
            if self._after_install is not None:
                self._after_install()
        else:
            projection = None
        return WakeInstallResultV1(
            outcome=outcome,
            requested_policy_digest=policy_digest,
            adapter_projection_digest=projection,
        )

    def remove(self, policy_digest: str) -> WakeRemoveResultV1:
        _require_digest(policy_digest)
        self._remove_count += 1
        if policy_digest != self._configured_policy_digest:
            return WakeRemoveResultV1(
                outcome=WakeRemoveOutcome.UNKNOWN,
                requested_policy_digest=policy_digest,
                adapter_projection_digest=None,
            )
        outcome = (
            WakeRemoveOutcome.BUSY
            if self._worker_running()
            else self._next_remove_outcome
        )
        if outcome is WakeRemoveOutcome.REMOVED:
            self._installed_policy_digest = None
            projection = _projection_digest(policy_digest)
        else:
            projection = None
        return WakeRemoveResultV1(
            outcome=outcome,
            requested_policy_digest=policy_digest,
            adapter_projection_digest=projection,
        )


def _projection_digest(policy_digest: str) -> str:
    return canonical_json_digest(
        {"adapter": "deterministic_wake_v1", "policy_digest": policy_digest}
    )


def _require_digest(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("policy_digest must be bare hex64")
