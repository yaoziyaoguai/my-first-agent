"""SubAgent V0 production routing flag (U3 — default OFF, opt-in only).

Single-purpose helper that maps the ``SUBAGENT_V0_ROUTING_ENABLED`` environment
variable to a strict boolean. The flag controls whether production CLI/NL
delegation is routed through ``RuntimeActionType.SUBAGENT_DELEGATE_V0`` (V0)
or kept on the legacy L1-attempt → inline-local path.

Contract (U2/U3 plan + Roadmap red line):

- default **off** (no env var, invalid env var, or empty string → False)
- valid truthy values: ``1``, ``true``, ``yes``, ``True``, ``TRUE``,
  ``yes``, ``on`` (case-insensitive). Anything else → False.
- missing env var → False (no raise, no default-on)
- this module is a *read* helper; production wiring is in
  ``agent.core._dispatch_or_fallback_delegation`` (U3), which calls
  ``read_v0_routing_enabled()`` exactly once per delegation.
- the flag does **not** flip the dispatcher default; it is consulted by the
  production call site only.
"""

from __future__ import annotations

import os as _os

_FLAG_ENV = "SUBAGENT_V0_ROUTING_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def read_v0_routing_enabled() -> bool:
    """Return the strict boolean value of the V0 production routing flag.

    Behaviour:

    - env var missing → ``False`` (off, no raise, no default-on)
    - env var empty string / whitespace → ``False``
    - env var in ``{"1", "true", "yes", "on"}`` (case-insensitive) → ``True``
    - any other value → ``False`` (coerced off, never raises)
    """
    raw = _os.getenv(_FLAG_ENV, "")
    if not raw:
        return False
    return raw.strip().lower() in _TRUTHY


__all__ = ["read_v0_routing_enabled"]
