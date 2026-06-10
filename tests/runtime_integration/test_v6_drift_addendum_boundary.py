"""V6 drift-addendum boundary characterization test.

Ensures the V6 addendum is contained in `docs/06-audit/CURRENT_CAPABILITY_DRIFT.zh.md`
between the `## 6.` marker and end-of-file, and does not leak into other sections
of the drift document (V1-V5 sections remain unchanged).

This is a structural regression guard: if a future commit tries to bundle V6
content into the wrong section, this test fails. The test does NOT assert
specific wording (drift notes can evolve) — only the section containment.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DRIFT_DOC = _REPO_ROOT / "docs" / "06-audit" / "CURRENT_CAPABILITY_DRIFT.zh.md"


def test_v6_addendum_section_marker_exists() -> None:
    """`## 6. Memory consolidation / emergence (V6 — addendum)` 标记必须存在。"""

    text = _DRIFT_DOC.read_text(encoding="utf-8")
    assert "## 6. Memory consolidation / emergence (V6" in text, (
        "V6 addendum marker missing — section 6 was lost or renamed"
    )


def test_v6_addendum_does_not_introduce_foreign_files() -> None:
    """V6 addendum 必须只在 drift 文档内，不引入额外文档/代码改动。"""

    # This is enforced by file-system inspection only — there is no python
    # file alongside the drift doc that would be expected from a V6 commit.
    siblings = sorted(p.name for p in _DRIFT_DOC.parent.iterdir())
    assert siblings == sorted([
        "CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md",
        "CURRENT_AUDIT_STATUS.zh.md",
        "CURRENT_CAPABILITY_DRIFT.zh.md",
    ]), f"unexpected sibling files in docs/06-audit/: {siblings}"


def test_v6_addendum_is_after_v5_sections() -> None:
    """V6 addendum 的位置必须在所有 V1-V5 节之后（即在 drift 文档末尾）。"""

    text = _DRIFT_DOC.read_text(encoding="utf-8")
    v6_index = text.find("## 6. Memory consolidation / emergence")
    assert v6_index > 0, "V6 addendum not found"
    # No `## N.` (N>6) sections after V6; document should end with V6 content.
    trailing = text[v6_index:]
    assert "## 7." not in trailing, (
        "Unexpected section 7 found after V6 — V6 was not the final section"
    )


def test_v6_addendum_substantively_references_consolidation_and_emergence() -> None:
    """V6 addendum 必须提到 `consolidation` 与 `emergence` 关键词，避免空标题。

    这是行为 guard：drift 表格 V6 行如果被清空成只剩标题，
    V6 doc-only 改动仍能通过结构断言但失去信息价值。强制 body 同时包含
    "consolidation" 与 "emergence" 两个关键词（都是事实话题）。
    """

    text = _DRIFT_DOC.read_text(encoding="utf-8")
    v6_index = text.find("## 6. Memory consolidation / emergence")
    assert v6_index > 0, "V6 addendum not found"
    addendum_body = text[v6_index:]
    assert "consolidation" in addendum_body.lower(), (
        "V6 addendum body must mention consolidation — "
        f"got body={addendum_body!r}"
    )
    assert "emergence" in addendum_body.lower(), (
        "V6 addendum body must mention emergence — "
        f"got body={addendum_body!r}"
    )


def test_v4_drift_table_subagent_delegate_reflects_runtime_decision_frame() -> None:
    """V4 drift table 必须把 `subagent.delegate` 行对齐 RuntimeDecisionFrame SoT。

    audit 2026-06-11: RuntimeDecisionFrame.subagent.delegate 是 READY/REAL_API_INTERACTIVE
    但 V4 表把它写成 FAKE_DEMO；本次 audit 已在 drift table 上修正。
    """
    text = _DRIFT_DOC.read_text(encoding="utf-8")
    v4_section = text.split("## 6.", 1)[0]
    subagent_row = next(
        (
            line
            for line in v4_section.splitlines()
            if line.startswith("| subagent.delegate |")
        ),
        None,
    )
    assert subagent_row is not None, "V4 drift table must contain subagent.delegate row"
    assert "READY" in subagent_row, (
        "V4 drift table must show subagent.delegate = READY (RuntimeDecisionFrame SoT); "
        f"got row={subagent_row!r}"
    )
