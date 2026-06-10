# Capability Boundaries — Skill / SubAgent / Tool

**日期**: 2026-05-27
**状态**: current — 定义 skill/subagent/tool 三者能力边界

---

## 核心定义

**Tool = atomic execution** — 单一、可审计的操作单元。Tool 执行后返回确定结果，不拥有 loop、不调用 LLM、不做规划。

**Skill = local capability descriptor** — 本地能力描述符，提供渐进式能力发现。Skill 不拥有 Agent loop，调用是 request/result flow。不直接执行工具，不直接写 Memory。

**Subagent = parent-controlled delegation** — 父 runtime 控制下的委托执行。Parent 发起、adjudicate 结果、控制作用域。当前为 L0 deterministic executor，不涉及真实 LLM 调用。

---

## 不变式 (Invariants)

### Parent control

**parent runtime remains in control** — 所有能力入口最终归 parent runtime 调度。Skill 和 SubAgent 是 parent 的受控分支点，不是独立 runtime。

### Execution boundaries

- **no direct tool execution** — Skill/SubAgent 不能绕过 ToolRegistry 和 confirmation 管线直接执行工具
- **no real LLM/provider** — L0 模式下 Skill/SubAgent 不调用真实 LLM；升级到 L1+ 需显式 provider governance
- **no external process** — SubAgent L0 硬阻止 shell/external process
- **fake-first** — 所有能力先在 fake provider 下验证，real API 路径需显式 opt-in
- **local-only** — SubAgent 不访问网络、不创建外部进程

### Refactoring constraint

**not a broad refactor** — 能力边界加固是行为保持型变更，不引入新能力类型、不重写核心架构。

---

## 参考

- 当前状态入口：`docs/PROJECT_STATUS.md`
- 当前审计入口：`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- SubAgent 边界架构：`docs/design/subagent-boundary-architecture.md`
- Skill 系统架构：`docs/design/skill-system-architecture.md`
