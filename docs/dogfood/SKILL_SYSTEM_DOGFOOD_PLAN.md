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

## Cross-scenario Exit Criteria

- Each scenario produces a redacted SkillAuditRecord.
- The selected Skill body loads only after selection.
- References/templates load only on demand.
- No scenario grants tools beyond ToolRegistry policy.
- No scenario writes Memory directly.
- No scenario invokes SubAgent.
