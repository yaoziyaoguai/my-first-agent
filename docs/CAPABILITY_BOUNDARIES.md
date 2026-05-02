# Capability Boundaries

本文件固定 Tool / Skill / Subagent 的边界，防止后续 Roadmap Completion 过程中把
能力系统做成新的 runtime 巨石。

## Boundary summary

- Tool = atomic execution
- Skill = local capability descriptor
- Subagent = parent-controlled delegation

## Tool

Tool 是原子执行能力，由现有 `agent.tool_registry` / `agent.tool_executor` / runtime
confirmation policy 管理。Skill/Subagent 不能直接调用或注册 tool。

## Skill

Skill 在当前 MVP 中只是 **local capability descriptor**：

- fake-first
- local-only
- explicit safe fixture/tmp path only
- no direct tool execution
- no network install
- no arbitrary code execution
- parent runtime remains in control

Skill 可以声明 `allowed-tools` 作为 metadata，但这不是执行授权。真正执行必须仍然经过
parent runtime/tool policy。

## Subagent

Subagent 在当前 MVP 中只是 **parent-controlled delegation**：

- fake-first
- local-only
- structured `DelegationRequest` / `DelegationResult`
- no real LLM/provider
- no external process
- no remote delegation
- no autonomous child tool execution
- parent runtime remains in control

Subagent profile 可以声明需要的 tools，但 request 必须由 parent policy 检查后才成立。

## Non-goals

- not a broad refactor
- no framework migration
- no LangGraph conversion
- no memory activation
- no runtime/checkpoint/tool executor rewrite
- no real external integration

## Test guard

`tests/test_capability_boundary_contract.py` 用 AST import guard 和 shared parent-policy
contract 保护本文件描述的边界。
