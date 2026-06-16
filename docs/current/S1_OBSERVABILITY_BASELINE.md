# S1 Observability Baseline

> Authority: this file defines the S1 observability baseline selected by G-10.
> `S1_GOAL.md` remains the frozen S1 goal, and `S1_GOAL_GAP.md` remains the
> active release backlog.

## Scope

S1 observability must prove the path skeleton of one run. It is not a full
request/response archive.

The baseline is satisfied when a run's per-session `events.jsonl` can show:

- which provider path was used;
- whether tool policy/gate and tool result summary events happened;
- whether memory evidence happened when memory is used;
- whether checkpoint evidence happened;
- enough session/run/event identifiers to correlate the path without exposing
  secrets or raw provider/tool bodies.

## Required Envelope Fields

Every S1 evidence event written through `record_evidence()` must preserve this
minimal envelope:

| Field | Purpose |
|---|---|
| `schema_version` | Evidence schema compatibility marker. |
| `event_id` | Stable event correlation id for this evidence entry. |
| `session_id` | Per-session correlation key. |
| `run_id` | Runtime run correlation key when available. |
| `turn_id` | Turn correlation key when available. |
| `timestamp` | UTC event time. |
| `entry` | Runtime entry path, such as `plain`. |
| `provider_type` | Fake/real provider identity for same-spine comparison. |
| `provider_model` | Model identity or `unknown` when unavailable. |
| `subsystem` | Event family owner, such as `tool`, `memory`, `checkpoint`, or `session`. |
| `operation` | Specific operation, such as `gate_decision` or `invoke_result_summary`. |
| `phase` | Start/decision/end/error/summary phase when available. |
| `status` | Result status such as `ok`, `success`, `allowed`, `blocked`, or `error`. |
| `reason_code` | Non-sensitive reason code when an event is blocked or fails. |
| `safe_summary` | Human-readable non-sensitive summary. |
| `content_persisted` | Whether original content was persisted. |
| `content_redacted` | Whether content was redacted before persistence. |
| `sensitive` | Whether the event represents sensitive data handling. |
| `metadata` | Safe subsystem-specific metadata only. |

Source evidence: `agent/evidence_recorder.py:644` sets session/provider/run
context, `agent/evidence_recorder.py:689` builds the envelope, and
`agent/evidence_recorder.py:728` writes evidence to the global lightweight
index plus per-session `events.jsonl`.

## Required Event Families

An S1 acceptance or smoke run must make the following families observable when
that path is exercised:

| Family | Required evidence |
|---|---|
| Provider identity | A session/evidence event includes `provider_type` and `provider_model` in the envelope or safe metadata. |
| Tool gate | Tool policy/gate decisions are visible as `tool.gate_decision` or equivalent tool gate evidence. |
| Tool result | Tool execution result summaries are visible as `tool.invoke_result_summary`, using safe summaries rather than full tool output. |
| Memory | Memory recall/retain/proposal/commit/restore evidence is visible as `memory.*` when memory is used. |
| Checkpoint | Checkpoint save/resume/summary evidence is visible as `checkpoint.*` when checkpoint is used. |
| Event log safety | Per-session `events.jsonl` lines are valid JSONL, redacted before write, and bounded by truncation for long strings. |

`events.jsonl` is the preferred per-session fact source for session summaries
when present. `agent_log.jsonl` remains a global lightweight index and fallback,
not the S1 primary session evidence file.

## S1 Non-Promises

S1 observability does not require:

- persisting raw provider request/response bodies;
- persisting full tool result bodies;
- printing, moving, copying, or committing secrets;
- lossless `events.jsonl` body fidelity for pending-tool output, which remains
  deferred as TD-004;
- local trace capture as part of the default S1 release gate.

## Verification

The G-10 verification command is:

```bash
.venv/bin/python -m pytest tests/test_evidence_lifecycle_and_summary.py tests/test_b7_event_log.py -q
```

This verifies:

- envelope/session/provider propagation into per-session events;
- `events.jsonl` summary precedence over the global log when present;
- tool gate and tool result summary evidence behavior;
- memory and checkpoint evidence families covered by the lifecycle tests;
- EventLogWriter JSONL append behavior, redaction, and truncation.
