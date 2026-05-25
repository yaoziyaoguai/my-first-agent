# Runtime v0.3.2 Trial Run Report

> Status note: this is a local-first learning runtime prototype trial report,
> not a mature Agent platform release note. The current shell is a basic CLI
> shell / TUI-like stdout experience, not a full Textual IDE. Skill remains an
> experimental / demo-level prompt scaffold.

## 1. Current candidate

- Candidate: v0.3.2 Local Trial Candidate on `main`.
- Scope: local trial readiness for the basic CLI shell, health, logs,
  checkpoint/resume, output contract, and safety display boundaries.
- Release posture: suitable for one real local trial pass before deciding on a
  `v0.3.2` tag.

## 2. Automated coverage

Covered by unit/integration tests or non-interactive smoke:

- `python main.py health`
- `python main.py health --json`
- `python main.py logs --tail 5`
- `python main.py --shell` startup/quit path
- CLI argument wiring for `health`, `logs`, and `--shell`
- README/checklist command drift checks
- final answer / `request_user_input` protocol boundary
- tool outcome distinction: success, policy denial, user rejection, tool failure
- pending tool resume preview masking
- RuntimeEvent / DisplayEvent / InputIntent / retired CommandResult boundary checks
- checkpoint persistence limited to durable state and conversation messages
- logs viewer masking for tokens, API keys, private-key markers, and raw content
- health warnings treated as maintenance warnings, not automatic cleanup failures

## 3. Manual-only coverage

These paths should stay manual for v0.3.2 because they need a real provider,
natural interaction timing, or human judgement about output clarity:

- Natural final-answer quality: run a normal planning/chat task and confirm the
  final answer reads as complete without implying the runtime is still waiting.
- Real `request_user_input` behaviour: ask an intentionally underspecified task
  and observe whether the runtime shows a clear waiting prompt only through the
  structured request path.
- Real checkpoint/resume interruption: stop during an awaiting confirmation or
  awaiting input state, restart, and confirm the resume prompt is readable.
- End-to-end tool confirmation flow: trigger a write-file confirmation, approve
  once and reject once, and check the screen-level distinction.
- Human readability of status lines: observe whether state/current step/pending
  tool lines help during a multi-step task.

Failure feedback format:

```text
现象：
命令/输入：
期望：
实际：
是否阻塞：yes/no
建议归类：v0.3.2 blocking / v0.3.x patch / v0.4 planning
```

## 4. Findings

- No v0.3.2 blocking issue is currently recorded.
- The candidate is ready for a real local trial, but not for claiming mature
  IDE, platform, Skill runtime, Reflect, or sub-agent capabilities.
- Health/logs/checkpoint warnings are observability and maintenance signals.
  They do not delete `agent_log.jsonl`, `sessions/`, checkpoint, or workspace
  data automatically.

## 5. v0.3.2 blocking issues

None known after the automated readiness pass.

## 6. v0.3.x patch candidates

- Tune wording if manual trial finds status lines or resume prompts unclear.
- Add more narrow smoke tests if one of the manual-only paths becomes reliably
  scriptable without a real LLM.
- Keep health/logs actions discoverable without adding automatic cleanup.

## 7. v0.4 planning candidates

These are planning candidates only, not current features:

- Light Event-driven State Transition boundary pass.
- Continue converging RuntimeEvent / DisplayEvent / retired CommandResult
  boundaries.
- Harden checkpoint schema boundaries with more explicit typed contracts.
- Make observer/logs more structured while keeping raw content out of stdout.
- Systematize the local trial feedback loop.

v0.4 should not start with LangGraph, sub-agent runtime, Reflect /
Self-Correction, a full Textual IDE, complex cancellation, slash commands, or a
one-shot runtime rewrite. First stage should add tests and type/data-structure
boundaries, then migrate scattered state updates gradually.

## 8. Release recommendation

Do not tag immediately from this report alone. Run one human local trial with
the checklist, classify any findings, then choose between a small v0.3.x patch
or tagging `v0.3.2`.
