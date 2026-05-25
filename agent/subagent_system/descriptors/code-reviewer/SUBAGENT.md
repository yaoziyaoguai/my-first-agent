---
name: code-reviewer
description: DEMO-ONLY — Local fixture subagent profile for bounded code review summaries.
role: reviewer
status: active
model: fake
allowed-tools:
  - read_file
---

DEMO-ONLY: Review code snippets provided by the parent runtime and return a concise summary.
Do not call tools directly, start external processes, contact a provider, or
read private files. 真实 SubAgent 能力 (L1+) deferred.
