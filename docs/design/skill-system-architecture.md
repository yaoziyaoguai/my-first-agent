# Skill System Architecture

日期：2026-05-27
状态：current — 描述 Skill 系统当前架构、边界和已知限制

---

## 1. 架构概览

Skill 系统位于 `agent/skill_system/`，提供渐进式能力发现和受控调用。

### 核心组件

| 模块 | 职责 |
|------|------|
| `schema.py` | SkillDescriptor — name/version/status/tags/keywords/tool_bindings |
| `registry.py` | SkillRegistry — 加载和查询 skills/ 目录下的 descriptor |
| `selector.py` | SkillSelector — 基于模型输出的 skill 匹配 |
| `loader.py` | SkillLoader — 加载 skill 内容和 metadata |
| `invocation.py` | SkillInvocation — request/result flow 管理 |
| `tool_binding.py` | skill→tool 绑定关系管理 |
| `descriptor.py` | descriptor 格式和解析 |
| `prompt_section.py` | system prompt 中的 skill 信息展示 |
| `presentation.py` | CLI/TUI 展示格式化 |
| `memory_boundary.py` | Skill 对 Memory 的访问边界 |
| `checkpoint.py` | Skill 执行的 checkpoint 边界 |

### 执行流

```
模型输出 → SkillSelector 匹配 → SKILL_SELECT dispatch → SkillRuntimeActionHandler
→ SkillLoader 加载 → SkillInvocation 执行 → SkillInvocationResult 回流 parent
```

---

## 2. Runtime 集成

### SKILL_SELECT dispatch

loop.py turn-end hook 通过 RuntimeActionDispatcher 分发 SKILL_SELECT：

```
loop.py → dispatcher.route(request) → SkillRuntimeActionHandler
```

SkillRuntimeActionHandler 的职责：
1. 校验 `available_skill_metadata` 一致性（防止 phantom skill）
2. 定位已注册 skill
3. 通过 SkillLoader 加载内容
4. 返回 SkillInvocationResult（不执行工具、不写 Memory）

### LoopDependencies 中的 skill_registry

`LoopDependencies.skill_registry` 在 turn-end hook 构建 SKILL_SELECT payload 时，
填充 `available_skill_metadata`。Skill 本身不拥有 Agent loop——调用是 request/result flow。

---

## 3. 已知限制

### 3.1 Real API 未验证 (P2)

Skill 系统的所有测试使用 fake provider。Skill selection 由 FakeProvider 的
scripted response 触发，不经过真实 LLM 的 skill 选择流程。

Real API 下需要验证：
- 真实 LLM 是否能正确选择 skill（基于 system prompt 中的 skill metadata）
- Skill descriptor 格式是否对 LLM 充分可见和可理解
- Skill 选择错误时的 graceful degradation

### 3.2 Legacy skills 并存 (P3)

`agent/legacy_skills/` 和 `agent/skill_system/` 两套体系并存：
- `legacy_skills/`：隔离的历史材料，仅 installer/updater 工具引用
- `skill_system/`：当前活跃的 skill 系统
- `agent/skills/__init__.py`：tombstone，引导到 skill_system

当前状态：
- `legacy_skills/` 不被 runtime 路径 import（仅在 `agent/tools/install_skill.py`
  和 `agent/tools/update_skill.py` 中作为 wrapper 引用）
- 这些 wrapper 是显式的，不会在默认 tool 注册路径中被加载
- 清理时机：当 skill_system 的 install/update 流程完成时

---

## 4. 边界隔离

Skill 系统实施以下边界：

- **不拥有 Agent loop** — Skill 调用是 request/result flow，不控制 loop 生命周期
- **不直接执行工具** — Skill 通过 tool_binding 声明工具需求，由 ToolRegistry 执行
- **不直接写 Memory** — Skill 的 memory 操作通过 memory_boundary 间接执行
- **有 checkpoint boundary** — Skill 执行前后 checkpoint 由 parent runtime 管理

---

## 5. 参考

- 当前状态入口：`docs/PROJECT_STATUS.md`
- 当前审计入口：`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- 能力边界定义：`docs/CAPABILITY_BOUNDARIES.md`
- SubAgent 边界架构：`docs/design/subagent-boundary-architecture.md`
- SkillRuntimeActionHandler：`agent/runtime_integration/skill_action.py`
