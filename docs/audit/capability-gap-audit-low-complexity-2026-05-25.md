# Capability Gap Audit + Low-Complexity Remediation Selection

- Date: 2026-05-25
- Scope: First Agent capability gap audit, low-complexity safe-to-auto-run remediation selection
- Boundary: no `.env` read, no real API/LLM call, no network access, no real sessions/runs/memory episodes/private files read
- Current baseline: fake/local agent-driven rehearsal `11/11 PASS`; real provider path blocked by `ProviderAuthError 401` config/auth concern; full gate previously `3376 passed, 18 skipped, 0 failed`

## Safety Check

| Command | Result |
|---|---|
| `pwd` | `/Users/jinkun.wang/work_space/my-first-agent` |
| `git status -sb` | `## main...origin/main` |
| `git log --oneline -20` | latest `fb1ee47 docs(dogfood): add agent-driven human dogfood rehearsal report` |
| `git rev-list --left-right --count origin/main...HEAD` | `0 0` |
| `git tag --points-at HEAD` | empty |
| `git diff --stat` | empty |
| `git ls-files --others --exclude-standard` | empty |

Verdict: repo state was safe before this audit file was created.

## Current Capabilities

First Agent currently has a real shared runtime spine: `core.chat()` builds `LoopContext`, calls `loop.py`, routes model output through provider-neutral `ProviderResponse` blocks, dispatches tool calls through `ToolRegistry` / `ToolExecutor`, and emits user-facing `RuntimeEvent` output. Fake and real providers share this business path; they differ at provider adapter/config boundaries.

Implemented and usable today in fake/local mode:

- Agent loop / runner: basic loop, planning path, pending confirmation, checkpoint/resume, max-iteration guard.
- Provider abstraction: `ModelProvider` protocol, fake provider, Anthropic native/compatible, OpenAI native/compatible adapters, tool-call normalization.
- Tool calling: registry metadata, confirmation policy, execution, tool result pairing, user-visible tool result events.
- Memory: explicit retain with confirmation, list/forget shortcuts, governed snapshot injection, deterministic recall baseline, frozen consolidation foundation.
- SubAgent: L0 local deterministic delegation, parent adjudication, descriptors under `agent/subagent_system/descriptors`.
- Guardrails/HITL: tool confirmation, memory confirmation, user input requests, redacted display previews.
- Observability: runtime events, run summary event, optional trace sink, local trace recorder, dogfood/evidence reports.
- Dogfood/evals: broad fake/local tests, synthetic dogfood, gated real provider scripts, evidence label taxonomy.
- CLI/docs: startup provider banner, onboarding/help, dogfood checklist, manual record template.

## Audit Answers

1. **Already具备**: one shared local runtime path, provider protocol, tool registry/executor, fake/local memory/subagent/skill contracts, checkpoint/resume, event output, trace/run summary, dogfood evidence discipline.
2. **Still缺口**: polished CLI onboarding, one-page current source of truth, stronger run/debug summary usability, clearer manual dogfood shortest path, provider auth troubleshooting, memory recall user-perceived value, hook/MCP/subagent L1/sandbox/durable execution maturity.
3. **High-value low-complexity**: current status guide, onboarding/help text polish, dogfood next-step cleanup, run summary wording polish, redaction lint/source-of-truth guard, provider contract/docs cleanup using fake/stub tests.
4. **Important but defer**: real durable execution backend, sandbox-grade shell/network execution, SubAgent L1+ orchestration, full hook lifecycle, MCP confirmation full pipeline, RAG/embedding/plugin marketplace, real LLM memory consolidation.
5. **Needs human dogfood**: subjective startup clarity, approval wording trust, memory recall perceived usefulness, tool result visibility, debug report helpfulness, overall flow comfort.
6. **Needs real API key/auth**: real provider conversation quality, real provider tool-use across this configured endpoint/model, real streaming UX, real memory semantic quality.
7. **Do not invest now**: FakeProvider intelligence, fake subagent/memory/planner paths, broader dogfood report formats, new runtime branch points, direct-handler E2E overclaims, productizing old demo adapter paths.

## Capability Gap Table

| Capability gap | Current status | User value | Complexity | Risk | Safe-to-auto-run | Requires real API | Requires human judgement | Recommended action | Reason |
|---|---|---:|---|---|---|---|---|---|---|
| startup/provider mode clarity | Banner exists; docs still scattered | high | low | low | yes | no | partly | implement | Low-cost wording/docs/tests can reduce first-run confusion without API calls. |
| CLI help/onboarding | Helpful but still mixes evidence language and product status | high | low | low | yes | no | partly | implement | Copy-only/code-render polish, no new runtime. |
| command shortcut boundary/freeze | Allowlist and tests exist | medium | low | low | yes | no | no | docs-only | Keep frozen; do not add shortcuts. |
| memory UX visibility | `show memories`, injected event, confirmation event exist | medium | low | medium | yes | no | yes | docs-only | Small docs can clarify; perceived value needs human walkthrough. |
| memory recall user-perceived value | Deterministic store-to-snapshot baseline only | high | medium | medium | no | no | yes | defer | Needs dogfood feedback before changing architecture. |
| tool result display | `tool_result_visible` and display events exist | high | medium | medium | no | no | yes | defer | Human needs to judge if concise enough; avoid speculative UI changes. |
| tool approval wording | Confirmation event previews path/content | high | medium | medium | no | no | yes | defer | Trust/comprehension is subjective; do after manual dogfood. |
| subagent demo boundary | L0 deterministic demo explicitly marked | medium | low | low | yes | no | no | docs-only | Keep demo-only labels visible; no L1 work. |
| progress/streaming display | Fake/demo streaming and progress events exist | medium | medium | medium | no | yes for real UX | yes | defer | Real streaming and polished UX are larger than safe cleanup. |
| run summary/debug report usability | `run_summary_event` exists, terse developer-oriented | medium | low | low | yes | no | partly | implement | Small wording/status doc can improve comprehension without trace backend. |
| provider contract tests | Strong fake/stub provider tests exist | medium | low | low | yes | no | no | test-only | Add only stub contract coverage if a concrete gap appears; no real API. |
| tool-call compatibility | Anthropic/OpenAI normalization exists; provider matrix narrow | high | medium | medium | yes for fixtures | no | no | test-only | Fixture tests are safe; real matrix remains gated. |
| trace/report redaction | Docs/plans/audit/readme lint exists | high | low | low | yes | no | no | implement | Extend lint to new status/summary docs so cleanup docs stay safe. |
| dogfood report consolidation | Index exists; new rehearsal report is honest | high | low | low | yes | no | no | implement | Normalize next-step wording, do not claim human dogfood completed. |
| docs source-of-truth | README/docs/audit/plans have overlapping current status | high | low | low | yes | no | partly | implement | One current status page reduces agent/user path confusion. |
| hook lifecycle AD only | Hooks not product API | medium | low | low | yes | no | no | freeze | Do not implement; maintain deferred status. |
| MCP deferred status | MCP bridge exists gated/dry-run; real MCP off | medium | low | medium | yes | no | no | freeze | Keep explicit deferred/gated language. |
| fake provider freeze | Frozen by comments/docs; tests depend on deterministic behavior | high | low | low | yes | no | no | freeze | Any intelligence expansion would distort evidence. |
| legacy sunset | Labels exist for aliases/config/memory | medium | low | low | yes | no | no | freeze | Do not delete tonight; keep sunset markers. |
| manual dogfood preparation | Checklist/template/report exist; next path still spread | high | low | low | yes | no | yes | implement | Create shortest path, explicitly not human-complete. |
| durable execution/checkpoint/resume | Basic checkpoint/resume exists; no robust durable backend | high | high | high | no | no | yes | defer | Large architecture/product decision. |
| permission/sandbox/risk levels | Confirmation/policy metadata only, no OS sandbox | high | high | high | no | no | yes | defer | Sandbox-grade execution is out of scope. |
| handoffs/subagents | L0 local deterministic only | medium | high | high | no | maybe | yes | defer | L1+ orchestration would add product/runtime surface. |
| full hook system | AD/deferred only | low now | high | high | no | no | yes | cut | Premature extension before CLI/tool/memory UX stabilizes. |

## Selected Low-Complexity Items

Selected for this Big Loop:

1. **One-page current capability/status guide**  
   Scope: add a single current status page and link it from high-traffic docs.  
   Out of scope: moving/archive churn, broad roadmap rewrite.

2. **CLI help/onboarding polish**  
   Scope: clarify fake/local vs real, memory/tools/subagents/debug/report, real provider auth concern next step.  
   Out of scope: new commands, new runtime behavior, real API call.

3. **Run summary/debug report small polish**  
   Scope: improve user-facing run summary wording and test it.  
   Out of scope: trace backend, new report files, persistent observability.

4. **Manual dogfood preparation polish**  
   Scope: turn agent-driven rehearsal into shortest next human path; keep it clearly non-human.  
   Out of scope: doing manual dogfood, real provider retry.

5. **Redaction/source-of-truth lint cleanup**  
   Scope: ensure new current-status/remediation docs are included in redaction checks.  
   Out of scope: scanning `.env`, sessions/runs, memory episodes, private files.

Deferred despite value:

- Memory recall semantic/user-perceived quality: needs human dogfood feedback.
- Tool approval wording: needs human judgement.
- Real provider auth: blocked by external credential/config concern.
- Provider real matrix/streaming: requires real API and cost/network authorization.
- SubAgent L1/MCP/hooks/sandbox: too large and product-directional.

## AutoRun Boundary

Further AutoRun should remain cleanup-only until manual human dogfood produces concrete user friction. It should not add new runtime branch points, new fake intelligence, new subagent orchestration, new hook/MCP pipeline, or new broadly user-ready claims.
