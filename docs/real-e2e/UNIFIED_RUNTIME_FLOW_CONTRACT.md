# Unified Runtime Flow Contract

Status: active remediation contract
Date: 2026-05-22

This document replaces new Anchor framing. Historical Anchor documents may remain
as validation records, but new work must be described as Unified Runtime Flow and
Branch Behavior.

## 1. Unified Runtime Flow

The target runtime flow is:

```text
query/event
  -> core.chat / equivalent runtime entry
  -> runtime loop
  -> lifecycle / decision point
  -> branch selection
  -> RuntimeActionDispatcher
  -> subsystem handler / registry / policy
  -> evidence / trace / capability classification
  -> return to runtime loop
```

`core.chat` is the normal runtime entry. An equivalent runtime entry must be
explicitly documented before it can claim the same classification level.

After a request enters `core.chat`, fake and real must share the same business
flow. Fake and real may differ only in configuration and adapters:

- provider adapter
- store adapter
- tool adapter
- auth loader
- metadata

Provider kind is evidence metadata, not a branch selector. It must not create a
fake-only loop, real-only loop, fake dispatcher, dogfood-only main path, or
subsystem-specific runtime entry.

## 2. Standard Branch Points

A branch point is a documented runtime lifecycle decision where the runtime
selects a subsystem behavior. Branch points may exist before, inside, or after
the main model loop if the contract and evidence classification are honest.

Current branch point categories:

- pre-loop explicit Memory evaluation
- runtime loop model call and model output dispatch
- pending confirmation handling
- turn-end RuntimeAction hook
- tool execution / confirmation handling

Memory may have multiple branch points. It is not required to have one single
entry, but each branch point must state whether it is pre-loop, loop, turn-end,
or post-loop, and whether it goes through `RuntimeActionDispatcher`.

## 3. Branch Behavior Test

A branch behavior test verifies one state inside an existing capability family.
It is not a new capability milestone and must not be named as a new Anchor.

Examples:

- Tool gate `allowed`
- Tool gate `confirmation_required`
- Tool gate `blocked`
- Tool gate `not_found`
- Memory proposal `pending_review`
- Memory proposal `should_not_remember`
- Memory proposal `no_action`

Tool `allowed`, `confirmation_required`, `blocked`, and `not_found` are Tool
branch behaviors. They are not separate Anchor milestones. Negative states such
as `blocked` and `not_found` should be covered as tests, not as new plans.

## 4. Dogfood Boundary

Dogfood scripts may:

- configure a scenario
- call `core.chat`
- collect runtime-produced evidence
- write reports

Dogfood scripts must not claim real core loop E2E if they:

- construct `RuntimeActionRequest`
- call `RuntimeActionDispatcher.route` directly
- call MemoryPolicy, ToolRegistry, SkillLoader, or other subsystem APIs directly
- generate proof themselves

Direct dispatcher dogfood can be useful, but it is harness evidence. It may claim
`harness_runtime_e2e` only when target-module proof is complete. Direct subsystem
calls must classify as `subsystem_integration` or lower.

## 5. Classification Rules

`real_core_loop_runtime_e2e` requires all of the following:

- runtime action is routed from the runtime loop, not from direct dispatcher
- `dispatcher_origin == "runtime_loop"`
- `runtime_loop_invoked == true`
- source is the core loop source, currently `core_loop`
- runtime entry is `core.chat` or a documented equivalent
- lifecycle point / hook name is present
- dispatcher route/result provenance is complete
- target handler was invoked
- target module proof exists
- target catalog and target identity are valid
- result returned to parent runtime

`RuntimeActionRequest.payload` is not trusted provenance. Payload fields such as
`core_loop_invoked`, `core_entrypoint`, and `runtime_hook_name` cannot upgrade a
direct dispatcher call to `real_core_loop_runtime_e2e`.

Classification downgrade rules:

- direct dispatcher with complete target proof: `harness_runtime_e2e`
- direct dispatcher without complete target proof: `subsystem_integration` or lower
- direct subsystem call: `subsystem_integration` or lower
- event-only receipt without target proof: not runtime E2E
- handler self-reported proof: not runtime E2E

## 6. Capability Milestones

A new capability milestone is allowed only when the system gains a new externally
meaningful boundary, such as:

- a new external side-effect class
- a new durable state domain
- a new authorization boundary
- a new provider/store/tool adapter family
- a new runtime entry that is documented as equivalent to `core.chat`

Do not split capability families into endless Anchors. Tool Args, Tool Result,
Retry, Error Recovery, Multi Tool, MCP Tool, Skill, Checkpoint, Streaming, and
SubAgent work require separate explicit authorization and must not be introduced
as follow-on Anchors from current remediation.

## 7. Required Plan Header For Future Work

Every future SDD/TDD plan must answer:

```text
Is this a new capability milestone?
Is this a branch behavior test under an existing capability?
Is this a harness/subsystem-only validation?
```

If the answer is branch behavior or harness/subsystem validation, the plan must
not use Anchor framing.
