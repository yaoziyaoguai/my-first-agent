# D-09 — Plan 3 Manifest Fields → Deterministic Selector Wiring

**Date**: 2026-06-02
**Status**: active
**Type**: Next-stage enhancement (002 Skill Selection)
**Parent**: historical D-09 direction; current status lives in `docs/PROJECT_STATUS.md`.

## Background

Plan 3 manifest fields (`triggers`, `aliases`, `negative_triggers`, `when_to_use`,
`when_not_to_use`, `locale`) are already parsed by `validate_manifest()` into
`SkillManifest`, and `demo-note-maker/SKILL.md` already uses them. But the
deterministic `SkillSelector` does not read any of these fields — it only scores
by `name` words, `description` words, and `tags`.

This means the Plan 3 enrichment has zero effect on actual skill selection.

## Goal

Wire `triggers`, `aliases`, and `negative_triggers` into `SkillSelector` so that
skills with Plan 3 manifests get richer deterministic matching. No LLM, no
provider, no embeddings — pure keyword matching.

## Scope

### In scope

1. **SkillDescriptor**: add `triggers` and `negative_triggers` as Level 1 metadata
   (alongside existing `aliases`), so the selector can read them from the registry
2. **SkillManifest.to_descriptor()**: pass `triggers` and `negative_triggers`
3. **SkillSelector._score_descriptor()**: score `triggers` with highest keyword
   weight (exact/substring match), score `aliases` with name-like weight
4. **SkillSelector.select()**: exclude skills whose `negative_triggers` match
   any query word (blacklist)

### Out of scope (future real-env task)

- `when_to_use` / `when_not_to_use` semantic matching (needs LLM/embeddings)
- Real provider validation of non-prompt-steered activation
- `locale`-based routing

## Design

### Scoring weights

| Field | Weight | Rationale |
|-------|--------|-----------|
| Exact name | 1.0 | Unchanged, highest priority |
| Trigger exact match | 0.4 | Author-declared activation phrases |
| Name word | 0.3 | Unchanged |
| Alias match | 0.25 | Near-name identity match |
| Tag match | 0.2 | Unchanged |
| Description word | 0.15 | Unchanged |

### Trigger matching

A trigger matches if it appears as a substring (case-insensitive) in the user
query. This handles multi-word Chinese triggers like "写笔记" matching "帮我写个笔记".

```
trigger "写笔记" matches query "帮我写个笔记"  → +0.4
trigger "write note" matches query "write note please" → +0.4
```

### Alias matching

Aliases are scored like name words — each alias word that appears in the query
adds `_SCORE_NAME_WORD` (0.3).

### Negative trigger exclusion

If any negative trigger appears as a substring in the query, the skill is
excluded entirely (score = 0). This is a hard exclusion, not a penalty.

## Files

| File | Change |
|------|--------|
| `agent/skill_system/descriptor.py` | Add `triggers`, `negative_triggers` to `SkillDescriptor` |
| `agent/skill_system/selector.py` | Wire triggers/aliases/negative_triggers into scoring + exclusion |
| `tests/test_skill_selector.py` | New tests for triggers, aliases, negative_triggers |
| `tests/unit/test_skill_manifest.py` | Update M05 to expect triggers/negative_triggers in descriptor |

## Verification

```bash
python3 -m pytest tests/test_skill_selector.py tests/unit/test_skill_manifest.py -v
ruff check agent/skill_system/descriptor.py agent/skill_system/selector.py
```
