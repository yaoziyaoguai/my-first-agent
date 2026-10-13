"""Run one external business grader against a materialized candidate workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from coding_scenario_grader import grade_scenario


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario_id")
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    checks = grade_scenario(args.scenario_id, args.candidate)
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "schema_version": 1,
                "scenario_id": args.scenario_id,
                "scenario_contract_pass": passed,
                "business_completed": passed,
                "independent_checks": checks,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
