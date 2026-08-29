"""Closed macOS composition boundary for the portable 019 management CLI."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

from agent.automation.cli import run_cli
from agent.automation.composition import AutomationControlCoreV1

_REASONS = frozenset(
    {
        "browser_unavailable",
        "credential_unavailable",
        "host_composition_failed",
        "host_profile_unavailable",
        "launchd_unavailable",
        "provider_unavailable",
        "sandbox_unavailable",
        "supervisor_unavailable",
    }
)


class MacOSHostCLIUnavailableError(RuntimeError):
    """Trusted composition could not provide one closed host capability."""

    def __init__(self, reason_code: str) -> None:
        if reason_code not in _REASONS:
            raise ValueError("macOS CLI reason is not closed")
        self.reason_code = reason_code
        super().__init__(reason_code)


def run_macos_cli(
    argv: Sequence[str] | None = None,
    *,
    core_factory: Callable[[], AutomationControlCoreV1],
    write_fn: Callable[[str], None] = print,
) -> int:
    """Build one trusted host composition, then use the portable typed dispatcher."""

    try:
        core = core_factory()
        if not isinstance(core, AutomationControlCoreV1):
            raise TypeError("core_factory returned the wrong interface")
    except MacOSHostCLIUnavailableError as error:
        reason = error.reason_code
    except Exception:
        reason = "host_composition_failed"
    else:
        return run_cli(argv, core=core, write_fn=write_fn)
    write_fn(
        json.dumps(
            {"code": "needs_019_config", "reason": reason},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2


def main() -> int:
    def unavailable() -> AutomationControlCoreV1:
        raise MacOSHostCLIUnavailableError("host_profile_unavailable")

    return run_macos_cli(core_factory=unavailable)


__all__ = [
    "MacOSHostCLIUnavailableError",
    "run_macos_cli",
]
