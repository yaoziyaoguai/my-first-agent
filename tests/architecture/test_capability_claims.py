from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_e3_claims_require_acceptance_records() -> None:
    """A14: docs must not positively claim a capability is accepted without a record."""
    readme = (ROOT / "README.md").read_text()
    status = (ROOT / "docs/architecture/CURRENT_CAPABILITY_STATUS.md").read_text()
    for term in ("accepted capability", "全部六项能力重接完成"):
        assert term not in readme, f"README premature: {term}"
        assert term not in status, f"STATUS premature: {term}"
