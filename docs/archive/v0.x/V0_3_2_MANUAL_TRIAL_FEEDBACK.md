# Runtime v0.3.2 Manual Trial Feedback

> Scope: local-first manual trial feedback loop for `my-first-agent`. This is
> not a release tag request, not a push checklist, and not a mature Agent
> platform process.

## 1. Candidate

- Candidate: v0.3.2 trial candidate.
- Baseline HEAD at feedback-loop creation: `1ebf51f`.
- Push/tag: not required for this trial. Run locally and record observations.

## 2. Trial tasks

Run these in the basic CLI shell / TUI-like stdout path:

| Task | Suggested command/input | Observe |
|---|---|---|
| Shell start/quit/restart | `python main.py --shell`, then `quit`, then restart | session/cwd/health/logs/resume/Skill experimental are visible |
| Normal final answer | Ask a simple no-tool question | final answer completes without entering `awaiting_user_input` |
| `request_user_input` wait | Ask an underspecified task | waiting state appears only through structured `request_user_input` |
| Tool success | Ask it to calculate `100*100` or read `README.md` | `tool.completed` / success text is visible |
| Tool rejection | Trigger write-file confirmation and type `n` | `tool.user_rejected`, not policy denial |
| Policy denial | Ask it to read `~/.env` or `/tmp/server.pem` | `tool.rejected`, not completed |
| Tool failure / missing file | Ask it to read a missing file | `tool.failed`, not policy denial |
| Checkpoint/resume | Interrupt during awaiting confirmation/input, then restart | resume summary is readable and does not dump raw checkpoint |
| Health | `python main.py health` and `python main.py health --json` | warnings are maintenance signals |
| Logs | `python main.py logs --tail 5` | readable summaries; no raw prompt/result/secret |

## 3. Feedback format

Record one block per issue:

```text
command:
input:
expected:
actual:
blocked: yes/no
category: v0.3.x patch / v0.4 candidate / out of scope
evidence: status line / log line / checkpoint summary / screenshot note
```

## 4. Routing rules

- **v0.3.x patch**: wording, status line clarity, log readability, health warning
  wording, resume prompt clarity, narrow local bug.
- **v0.4 candidate**: scattered state updates, unclear transition boundary,
  checkpoint schema boundary, observer/logs structure, feedback loop structure.
- **out of scope**: Reflect / Self-Correction, sub-agent, full Textual IDE,
  LangGraph, stream abort, slash command, complex topic switch.

## 5. Safety boundary

- Do not enter real secrets.
- Do not upload real private data.
- Do not commit `.env`, `sessions/`, `agent_log.jsonl`, `workspace/`,
  checkpoint files, `state.json`, `runs/`, `summary.md`, or temporary smoke files.
- Use only non-sensitive local test files.
