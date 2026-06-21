"""R-G04: trial-only approval harness for non-interactive real-provider trials.

Default OFF. When ``FIRSTAGENT_TRIAL_APPROVAL_POLICY=safe`` is set, auto-approves only
safe-allowlist tools operating on workspace/demo or /tmp paths. Every auto-approval is
logged to evidence. Does NOT affect the default interactive CLI confirmation flow.

Safety contract:
- Default OFF (env var must be explicitly set to "safe").
- Only safe-allowlist tools (write_file, read_file, edit_file — no shell/exec/fetch).
- Only safe paths (workspace/*, /tmp/* — no system/home/config paths).
- Every auto-approval logged to evidence_recorder (audit trail).
- Never approves tools with dangerous substrings (shell/exec/fetch/subprocess/eval).

Wiring: the main.py confirmation block can call ``can_trial_approve`` + ``record_trial_approval``
to auto-approve without the interactive prompt. The wiring requires interactive-CLI regression
testing (the confirmation block is ~60 lines of prompt/classify/handle logic); the safety
module + tests here are the test-only first step.
"""

from __future__ import annotations

import os
from typing import Any

# Safe tool allowlist: file I/O only (no shell/exec/fetch/external).
_TRIAL_SAFE_TOOLS = frozenset({"write_file", "read_file", "edit_file"})

# Safe path prefixes (sandbox only — no system/home/config paths).
_TRIAL_SAFE_PATH_PREFIXES = ("workspace/", "/tmp/", "/private/tmp/")

# Dangerous tool name substrings — always rejected even if in allowlist.
_TRIAL_DANGEROUS_SUBSTRINGS = (
    "shell",
    "exec",
    "fetch",
    "subprocess",
    "eval",
    "import",
    "delete",
    "remove",
)


def is_trial_approval_enabled() -> bool:
    """True only when FIRSTAGENT_TRIAL_APPROVAL_POLICY=safe is explicitly set."""

    return os.environ.get("FIRSTAGENT_TRIAL_APPROVAL_POLICY", "").lower() == "safe"


def _extract_path(tool_input: dict[str, Any]) -> str:
    """Extract the file path from common tool input field names."""

    return str(
        tool_input.get("path")
        or tool_input.get("file_path")
        or tool_input.get("target")
        or ""
    )


def can_trial_approve(tool_name: str, tool_input: dict[str, Any]) -> bool:
    """Return True only if the tool+path pass ALL safety checks AND trial mode is on.

    Checks (all must pass):
    1. Trial mode enabled (env var).
    2. Tool name not dangerous (no shell/exec/fetch/etc substrings).
    3. Tool in safe allowlist (write_file/read_file/edit_file only).
    4. Path is under a safe prefix (workspace/ /tmp/ only).
    """

    if not is_trial_approval_enabled():
        return False
    lowered = tool_name.lower()
    if any(ds in lowered for ds in _TRIAL_DANGEROUS_SUBSTRINGS):
        return False
    if tool_name not in _TRIAL_SAFE_TOOLS:
        return False
    path = _extract_path(tool_input or {})
    if not path:
        return False
    return any(path.startswith(p) for p in _TRIAL_SAFE_PATH_PREFIXES)


def record_trial_approval(tool_name: str, tool_input: dict[str, Any]) -> None:
    """Log the trial auto-approval to the evidence recorder (audit trail).

    Records: subsystem=trial, operation=auto_approved, the tool name, and the
    policy name. Does not log the tool input content (safe-summary only).
    """

    try:
        from agent.evidence_recorder import record_evidence

        record_evidence(
            subsystem="trial",
            operation="auto_approved",
            phase="decision",
            status="ok",
            safe_summary=f"trial policy auto-approved {tool_name}",
            metadata={"tool": tool_name, "policy": "safe"},
        )
    except Exception:
        # Evidence recording failure must not block the trial flow.
        pass
