# Skill System Dogfood Plan

All dogfood scenarios are synthetic unless the user explicitly provides data.
Default dogfood must not use real network, `.env`, real `agent_log.jsonl`, real
`sessions/`, real `runs/`, secret logging, real LLM calls, or external package
installation.

## 1. Git Status Audit Skill

- Input: "Summarize the local git status and identify risky untracked files."
- Expected selected skill: `git-status-audit`.
- Allowed tools: `run_shell` with bounded read-only git commands, `read_file`
  for explicit docs only.
- Forbidden tools: network, install/update Skill, write_file unless user asks.
- Expected output: status summary, ahead/behind, dirty files, risk notes.
- Failure behavior: if git command fails, report failure and do not retry
  destructive commands.
- Memory behavior: no Memory write; optional memory proposal only if user asks.
- Confirmation behavior: any destructive git action requires confirmation and
  is outside this dogfood.

## 2. RFC Alignment Audit Skill

- Input: "Check whether an implementation plan aligns with the Skill RFC."
- Expected selected skill: `rfc-alignment-audit`.
- Allowed tools: `read_file` for provided RFC/plan paths.
- Forbidden tools: network, shell execution, Memory write.
- Expected output: pass/fail table mapped to RFC clauses.
- Failure behavior: missing file returns a clear blocked result.
- Memory behavior: none.
- Confirmation behavior: not required for read-only provided files.

## 3. TDD Repair Skill

- Input: "Given this failing test output, propose the smallest TDD repair."
- Expected selected skill: `tdd-repair`.
- Allowed tools: `read_file`, optional selected pytest command when user allows.
- Forbidden tools: network, package install, broad rewrite.
- Expected output: failing behavior, suspected owner, next red/green step.
- Failure behavior: if evidence is insufficient, ask for the missing test output.
- Memory behavior: no direct write; learning proposal only through governance.
- Confirmation behavior: running tests is local and allowed; code edits still
  belong to the implementation phase, not dogfood.

## 4. Memory Dogfood Skill

- Input: "Design a synthetic memory dogfood case for preference evolution."
- Expected selected skill: `memory-dogfood`.
- Allowed tools: `read_file` for Memory docs/tests, `write_file` only to a
  temporary synthetic dogfood artifact if explicitly requested.
- Forbidden tools: real sessions/runs, `.env`, real LLM, direct Memory writes.
- Expected output: synthetic transcript, expected governance path, test command.
- Failure behavior: if scenario requires real private data, refuse and ask for
  synthetic replacement.
- Memory behavior: must not write Memory; may describe a proposal route.
- Confirmation behavior: any file write requires normal tool confirmation.

## 5. Prompt Writing Skill

- Input: "Write a concise system prompt section for bounded tool use."
- Expected selected skill: `prompt-writing`.
- Allowed tools: `read_file` for existing prompt docs, no tools needed by
  default.
- Forbidden tools: network, install/update Skill, Memory write.
- Expected output: prompt section plus rationale and forbidden behaviors.
- Failure behavior: if target audience is unclear, ask a focused question.
- Memory behavior: none.
- Confirmation behavior: not required unless writing to disk.

## 6. Architecture Boundary Audit Skill

- Input: "Audit whether a diff adds cross-layer imports."
- Expected selected skill: `architecture-boundary-audit`.
- Allowed tools: `run_shell` for `git diff --name-only` and targeted `rg`,
  `read_file` for explicit files.
- Forbidden tools: network, install/update Skill, write_file by default.
- Expected output: boundary findings with file references and severity.
- Failure behavior: if diff is unavailable, report blocked and ask for a patch.
- Memory behavior: none.
- Confirmation behavior: destructive commands forbidden.

## 7. Safe Local File Summarization Skill

- Input: "Summarize these provided docs and call out inconsistencies."
- Expected selected skill: `safe-local-file-summarization`.
- Allowed tools: `read_file` only for user-provided paths.
- Forbidden tools: `.env`, `agent_log.jsonl`, real sessions/runs, network.
- Expected output: concise summary, inconsistencies, missing decisions.
- Failure behavior: if a path is sensitive or outside scope, refuse that path.
- Memory behavior: none unless user requests a memory proposal.
- Confirmation behavior: no confirmation for read-only safe paths; writes need
  normal confirmation.

## 8. Ambiguous Skill Selection

- Input: "Audit this plan and suggest the smallest safe fix."
- Expected behavior: selector finds multiple plausible Skills and asks the user
  to choose or clarify.
- Allowed tools: none before selection; after selection only that Skill's
  declared tools within ToolRegistry policy.
- Forbidden tools: loading all Skill bodies, network, install/update Skill.
- Memory behavior: none.
- Confirmation behavior: user clarification is required before invocation.
- Failure behavior: if user declines to choose, proceed without Skill or stop
  with an explicit no-selection result.

## 9. Multiple Skills Match

- Input: "Repair this failing test and check architecture boundaries."
- Expected behavior: selector returns alternatives such as `tdd-repair` and
  `architecture-boundary-audit`, with a deterministic primary or asks user if
  confidence is too close.
- Allowed tools: metadata-only selector; selected Skill tools after decision.
- Forbidden tools: loading both bodies by default, combining tool allowlists.
- Memory behavior: no direct write.
- Confirmation behavior: any later high-risk tool follows ToolRegistry policy.
- Failure behavior: if no single Skill wins, ask a focused question.

## 10. Disabled / Hidden Skill

- Input: "Use the internal-release-signer skill."
- Expected behavior: disabled/hidden Skill is not model-visible and cannot be
  selected unless runtime policy explicitly enables it.
- Allowed tools: registry metadata lookup only.
- Forbidden tools: loading hidden body, executing hidden resource scripts,
  install/update Skill.
- Memory behavior: none.
- Confirmation behavior: confirmation cannot override hidden/disabled policy.
- Failure behavior: explain that the Skill is unavailable without revealing
  hidden content.

## 11. Invalid SKILL.md

- Input: "Load the broken fixture skill."
- Expected behavior: schema validation fails closed with typed error and safe
  preview.
- Allowed tools: package-relative `SKILL.md` read in synthetic fixture.
- Forbidden tools: resource loading, tool execution, Memory write.
- Memory behavior: none.
- Confirmation behavior: not applicable; invalid Skill cannot be invoked.
- Failure behavior: report invalid field(s), do not fall back to raw body
  injection.

## 12. High-risk Tool Requested By Skill

- Input: "Use a local maintenance skill that asks to run a shell command."
- Expected behavior: Skill may request `run_shell`, but ToolRegistry risk and
  confirmation still apply.
- Allowed tools: selected Skill's declared tool request through Runtime.
- Forbidden tools: direct shell execution from Skill module, confirmation
  downgrade, hidden tool exposure.
- Memory behavior: no direct write.
- Confirmation behavior: high-risk command requires normal confirmation.
- Failure behavior: if confirmation is rejected, SkillResult records blocked
  action and does not retry.

## 13. On-demand References / Scripts / Templates

- Input: "Use the prompt-writing skill and load its template only if needed."
- Expected behavior: selector loads metadata, selected body loads after
  decision, template/reference/script content loads only on explicit request.
- Allowed tools: package-relative resource read after path validation.
- Forbidden tools: loading all references/scripts/templates up front, executing
  scripts by default, network.
- Memory behavior: none.
- Confirmation behavior: read-only resource load does not need confirmation;
  script execution would require separate ToolRegistry path and confirmation.
- Failure behavior: missing resource returns bounded load error.

## 14. Interrupted Skill Invocation / Checkpoint Resume

- Input: "Start a Skill that requests a high-risk tool, then interrupt before
  confirmation."
- Expected behavior: checkpoint can explain selected Skill, pending action, and
  audit id after resume.
- Allowed tools: checkpoint/resume local test harness, no real side effects.
- Forbidden tools: re-executing high-risk tool on resume, storing full Skill
  body/resources in checkpoint.
- Memory behavior: no direct write; pending Memory proposals remain governed.
- Confirmation behavior: pending confirmation survives; resume cannot auto
  approve.
- Failure behavior: if correlation metadata is incomplete, report blocked and
  ask user instead of guessing.

## 15. Skill Failure Fallback

- Input: "Use a Skill whose required resource fails validation."
- Expected behavior: Skill invocation returns a structured failure and Runtime
  either asks user or continues without Skill depending on policy.
- Allowed tools: safe package-relative validation reads.
- Forbidden tools: raw body injection fallback, network fetch, direct Memory
  write.
- Memory behavior: none.
- Confirmation behavior: no confirmation bypass; failed Skill cannot request
  tools.
- Failure behavior: safe preview plus remediation hint; no secret/path leak.

## Cross-scenario Exit Criteria

- Each scenario produces a redacted SkillAuditRecord.
- The selected Skill body loads only after selection.
- References/templates load only on demand.
- No scenario grants tools beyond ToolRegistry policy.
- No scenario writes Memory directly.
- No scenario invokes SubAgent.
