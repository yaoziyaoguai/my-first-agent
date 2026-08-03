"""012 delivery controls 必须可执行，且不能退化为自写 manifest。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_012_delivery_controls_are_materialized() -> None:
    assert (ROOT / "scripts" / "verify_012_materialized_tree.py").is_file()
    assert (ROOT / "docs" / "implementation" / "012_DELIVERY_SEAL.json").is_file()


def test_012_verifier_rejects_generate_mode() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_012_materialized_tree.py"),
            "--generate",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
