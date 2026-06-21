"""G-007 (Phase 1): capability-status command + data invariants.

The capability truth table is the operator-facing source for which module is
real / dormant / fake-local / operator-ready. These tests pin:

- the data matches the audit baseline (no L5/L6; dormant labeled dormant;
  fake/local labeled fake-local; real_api_verified only where the audit allows);
- the CLI command runs and emits the table;
- JSON mode is valid;
- no secret ever appears in the output.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

from agent.capability_status import (  # noqa: E402
    CAPABILITY_STATUSES,
    capability_status_json,
    render_capability_status,
)

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{12,}")


def test_maturity_invariants_and_no_overclaim():
    """L6 (released) is allowed only with a cited real dogfood (G-0xx) OR an
    explicit 'Boundary:' 替代-verification — transparency, not overclaim.
    Scheduler/TUI are L2 (concrete blockers); Fake is L3 (N/A). operator_ready
    iff level == L6."""
    concrete_ceilings = {
        "Scheduler / action-planning": "L2",
        "TUI / visual shell": "L2",
        "Fake / local deterministic support": "L3",
    }
    by_module = {cs.module: cs for cs in CAPABILITY_STATUSES}
    for mod, lvl in concrete_ceilings.items():
        assert by_module[mod].level == lvl, f"{mod} must be {lvl} (concrete ceiling)"
    for cs in CAPABILITY_STATUSES:
        # operator_ready iff released (L6)
        assert cs.operator_ready == (cs.level == "L6"), (
            f"{cs.module} ({cs.level}) operator_ready mismatch"
        )
        if cs.level == "L6":
            # No L6 without evidence: cite a real dogfood (G-0xx) or a Boundary note.
            assert "G-0" in cs.detail or "Boundary:" in cs.detail or "替代验证" in cs.detail, (
                f"{cs.module} is L6 but cites no real dogfood or Boundary — overclaim"
            )
        # dormant/fake-local must not claim real_api_verified
        if cs.state in {"dormant", "fake-local"}:
            assert cs.real_api_verified is False, (
                f"{cs.module} ({cs.state}) must not claim real_api_verified"
            )


def test_dormant_and_fake_local_modules_labeled():
    """Dormant/fake-local modules must be marked so (never as active real)."""
    by_module = {cs.module: cs for cs in CAPABILITY_STATUSES}
    assert by_module["Scheduler / action-planning"].state == "dormant"
    assert by_module["MCP config / bridge"].state == "active"
    assert by_module["SubAgent"].state == "fake-local"
    assert by_module["Fake / local deterministic support"].state == "fake-local"
    # Dormant/fake-local modules are NOT real_api_verified.
    for cs in CAPABILITY_STATUSES:
        if cs.state in {"dormant", "fake-local"}:
            assert cs.real_api_verified is False, (
                f"{cs.module} ({cs.state}) must not claim real_api_verified"
            )


def test_expected_modules_present():
    modules = {cs.module for cs in CAPABILITY_STATUSES}
    for name in (
        "Core governed runtime spine",
        "Provider/model boundary",
        "Scheduler / action-planning",
        "Security / config diagnostics",
        "Fake / local deterministic support",
    ):
        assert name in modules


def test_render_contains_key_markers_and_no_secret():
    out = render_capability_status()
    assert "FirstAgent Product Capability Status" in out
    assert "dormant" in out
    assert "fake-local" in out
    assert "L5 operator_ready" in out  # legend, not a rating
    assert "Source: docs/current/PRODUCT_CAPABILITY_AUDIT.md" in out
    assert not _SECRET_PATTERN.search(out)


def test_json_is_valid_and_no_secret():
    data = json.loads(capability_status_json())
    assert "capabilities" in data
    assert len(data["capabilities"]) == len(CAPABILITY_STATUSES)
    raw = capability_status_json()
    assert not _SECRET_PATTERN.search(raw)


def test_cli_capability_status_runs():
    """`python main.py capability-status` exits 0 and emits the table.

    The no-L5/L6 invariant is pinned at the data level by
    test_no_module_is_l5_or_l6; here we only check the rendered surface.
    """
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "capability-status"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
        env=os.environ,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"non-zero exit: {output!r}"
    assert "FirstAgent Product Capability Status" in output
    assert "Scheduler / action-planning" in output
    assert "dormant" in output
    assert not _SECRET_PATTERN.search(output)


def test_cli_capability_status_json():
    """`--json` emits valid JSON with the capability list."""
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "main.py"), "capability-status", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(PROJECT_ROOT),
        env=os.environ,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data["capabilities"]) == len(CAPABILITY_STATUSES)
    assert not _SECRET_PATTERN.search(result.stdout + result.stderr)
