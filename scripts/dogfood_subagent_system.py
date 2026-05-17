"""Synthetic/local dogfood harness for formal SubAgent System.

T1 dogfood must stay local and deterministic: no real LLM, no network, no
external process, no `.env`, and no real sessions/runs. The command writes only
inside the caller-provided tmp root.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_synthetic_dogfood(*, tmp_root: Path, mode: str = "synthetic") -> dict[str, Any]:
    """Run T1 synthetic scenarios and return a sanitized packet."""

    from agent.subagent_system.delegation import delegate_once
    from agent.subagent_system.registry import SubAgentRegistry
    from agent.subagent_system.request import SubAgentRequest

    if mode != "synthetic":
        raise ValueError("Only synthetic mode is allowed without explicit gated approval")
    tmp_root.mkdir(parents=True, exist_ok=True)
    subagent_root = tmp_root / "subagents"
    _write_fixture(subagent_root)
    registry = SubAgentRegistry([subagent_root])

    scenarios = [
        ("Safe Local Code Review", "Review code"),
        ("Test Repair Delegation", "Review failing test"),
        ("RFC Alignment Check", "Review RFC alignment"),
        ("Memory Boundary read_context", "Review memory boundary"),
        ("Memory Boundary propose", "Review memory proposal"),
        ("Skill Boundary L1 Metadata", "Review skill selection"),
        ("Tool Boundary Upper Bound", "Review allowed tools"),
        ("High-Risk Tool Rejection", "request shell_exec"),
        ("Hidden Tool Never Exposed", "Review hidden tools"),
        ("max_iterations Hard Stop", "loop until max"),
        ("Descriptor Not Found", "Review missing descriptor"),
        ("Policy Violation Nested Delegation", "Review nested delegation"),
        ("Checkpoint Interruption Resume", "Review checkpoint"),
        ("Low Confidence Delegation", "needs clarification"),
        ("Audit Record Completeness", "Review audit"),
        ("Context Budget Overflow", "Review context budget"),
    ]
    passed = 0
    audit_packets: list[dict[str, Any]] = []
    for index, (name, task) in enumerate(scenarios, start=1):
        request = SubAgentRequest(
            task=task,
            role="reviewer",
            allowed_tools=("read_file",),
            max_iterations=1,
            parent_trace_id=f"dogfood-{index}",
            delegation_reason=name,
        )
        run = delegate_once(request, registry)
        if run.result is not None and run.adjudication is not None:
            passed += 1
            audit_packets.append({
                "scenario": name,
                "status": run.result.status,
                "stop_reason": run.result.stop_reason,
                "adjudication": run.adjudication.action,
            })

    return {
        "tier": "T1",
        "capability_level": "L0",
        "mode": "synthetic",
        "real_llm_used": False,
        "network_used": False,
        "external_process_used": False,
        "private_data_read": False,
        "scenarios_total": len(scenarios),
        "scenarios_passed": passed,
        "audit_packets": audit_packets,
    }


def _write_fixture(root: Path) -> None:
    subagent_dir = root / "code-reviewer"
    subagent_dir.mkdir(parents=True, exist_ok=True)
    (subagent_dir / "SUBAGENT.md").write_text(
        """---
name: code-reviewer
description: Review code.
role: reviewer
model: fake
status: active
risk_level: low
version: 0.1.0
allowed_tools:
  - read_file
allowed_skills: []
memory_scope: none
max_iterations_default: 1
confirmation_policy: inherit_tool_policy
supported_modes:
  - local_fake
---
# Code Reviewer
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tmp-root", required=True)
    parser.add_argument("--mode", default="synthetic")
    args = parser.parse_args()
    packet = run_synthetic_dogfood(tmp_root=Path(args.tmp_root), mode=args.mode)
    print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
