# 002 Skill Selection — SDD / Architecture vNext

日期: 2026-05-31
状态: design — SPEC/SDD 阶段，不包含 production code 实现
目标: 定义 002 Skill Selection 从 partial-credible 到 credible 的完整架构设计

---

## 0. Contract Header（UNIFIED_RUNTIME_FLOW_CONTRACT §7）

```
Is this a new capability milestone?  NO — skill.select 是已有 branch point，这是 branch behavior 精化
Is this a branch behavior test?       YES — 在 skill.select 下新增 turn-start selection / structured selection phase / active_skill lifecycle
Is this harness/subsystem-only?       NO — 涉及 runtime flow 变更（turn-end → turn-start 时序迁移）
```

---

## 1. 问题陈述

### 1.1 当前根因

002 的 `partial-credible` 状态根因不是"测试不足"，而是 **skill selection 架构未收敛**：

| 维度 | 当前状态 | 为什么不够 |
|------|---------|-----------|
| **时序** | turn-end hook 事后补救 | 模型完成响应后才选 skill——skill 对模型本轮推理过程不可见 |
| **匹配** | 确定性关键词（name/tags/description） | 中文子串 bigram fallback——字符串 trick，不是语义理解 |
| **决策权** | runtime 代替模型做选择 | 模型仅在 fake provider 下被 scripted response 模拟为"调用 SKILL_SELECT" |
| **路由信息** | description + tags 仅两项 | 没有 when_to_use / triggers / negative examples / aliases |
| **SkillSelector** | 已实现更完善评分+歧义检测 | 从未接入生产路径——`select_skill_for_real_provider()` 绕过它 |

### 1.2 Plan 2 为什么被拒绝

`docs/design/skill-model-owned-selection-hardening.md`（"Plan 2"）的核心方案——注册 SKILL_SELECT 为 TOOL_REGISTRY 工具——解决了"模型能否自主调用 SKILL_SELECT"的代码路径问题。但 **Plan 2 standalone path is rejected**，原因：

1. **时序问题未解决**: SKILL_SELECT 仍是 turn 内工具调用，skill body 注入在下一轮 system prompt。skill 对模型当前 turn 的推理不可见。
2. **路由信息不足**: 模型只有 `name + description + tags` 三元组，不足以做出正确的 skill 路由判断。
3. **keyword fallback 仍是主力路径**: 如果模型不主动调用 SKILL_SELECT，系统退回关键词匹配——这是 partial-credible 的核心缺陷。
4. **不构成独立终点**: Plan 2 只能让 002 达到 "code path complete with model-owned tool call"，不能达到 credible——时序和路由问题仍是 blocker。

**Plan 2 中有价值的部分保留为 Plan 3 manifest foundation**:
- manifest metadata 扩展
- aliases
- trigger examples
- negative examples
- multilingual metadata
- when_to_use / when_not_to_use
- risk / confirmation metadata

### 1.3 架构决策

**Plan 3 selected as target architecture.**
**Plan 2 standalone path rejected.**
**Plan 2 metadata retained only as Plan 3 foundation.**

---

## 2. Target Architecture（Plan 3）

### 2.1 核心思路

Skill selection 从 turn-end hook 事后补救 → turn-start 结构化选择阶段。Plan 3 的核心是：**runtime-managed active_skill lifecycle**，skill 选择发生在 model response 之前。

```
Plan 3 target runtime path:

  user_input
    → candidate skill retrieval (Phase 2)
    → turn-start structured skill selection phase (Phase 3)
    → model outputs select_skill / no_skill
    → runtime activates active_skill (Phase 4)
    → model responds with active_skill context
    → allowed_tools enforced by ToolRuntimeMediator (Phase 5)
    → evidence recorded (Phase 6)
    → fallback / failure / no_skill handled explicitly
```

### 2.2 Target Runtime Flow（完整）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Plan 3 — Skill Selection Runtime Flow                   │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ TURN START                                                       │     │
│  │                                                                   │     │
│  │  1. user_input 进入 core.chat()                                   │     │
│  │  2. SkillCandidateRetriever.retrieve(user_input, registry)        │     │
│  │     → 基于 aliases / trigger examples / lexical matching          │     │
│  │     → 返回 top-K candidates (或空列表)                            │     │
│  │  3. build_skill_selection_prompt(candidates)                       │     │
│  │     → 注入 candidates 路由信息到 system prompt                     │     │
│  │     → 模型看到: name, description, when_to_use, triggers           │     │
│  │                                                                   │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                              ↓                                            │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ SELECTION PHASE (model response 前)                               │     │
│  │                                                                   │     │
│  │  4. 模型输出: select_skill(skill_id) 或 no_skill                  │     │
│  │     select_skill 走 ToolRuntimeMediator:                          │     │
│  │       TOOL_GATE → TOOL_INVOKE → SkillSelectToolHandler            │     │
│  │       → TOOL_RESULT → skill body → conversation context           │     │
│  │                                                                   │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                              ↓                                            │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ ACTIVE SKILL LIFECYCLE                                            │     │
│  │                                                                   │     │
│  │  5. runtime 激活 active_skill:                                     │     │
│  │     - skill_id, body, allowed_tools 记录                          │     │
│  │     - 跨 turn 持久化 (multi-turn until task complete)             │     │
│  │     - deactivate 条件：task complete / 模型切换 skill / 用户取消  │     │
│  │                                                                   │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                              ↓                                            │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ MAIN LOOP (普通 ReAct main loop 保留)                             │     │
│  │                                                                   │     │
│  │  6. 模型响应（含 active_skill context）                            │     │
│  │  7. allowed_tools enforced by ToolRuntimeMediator / TOOL_GATE     │     │
│  │  8. 后续 tool_use → TOOL_GATE 检查 skill_allowed_tools            │     │
│  │                                                                   │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                              ↓                                            │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ FALLBACK / FAILURE                                                │     │
│  │                                                                   │     │
│  │  9a. 模型输出 no_skill → 无 active_skill，正常 ReAct 继续         │     │
│  │  9b. candidate retrieval 空 → 不注入 selection prompt             │     │
│  │  9c. selection 失败 → keyword safety fallback (仅 safety net)     │     │
│  │  9d. evidence 覆盖: selection entered / candidates built          │     │
│  │      / model selection received / active_skill applied            │     │
│  │      / allowed_tools bound / no_skill / fallback / failure        │     │
│  │                                                                   │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│                                                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.3 关键架构原则

1. **Skill selection 发生在 model response 前**，不是 turn-end fallback。
2. **Model-owned SKILL_SELECT 保留为兼容证据路径**，但不是唯一主机制。turn-start selection phase 是主机制。
3. **Runtime-managed active_skill lifecycle 是 Plan 3 核心**——跨 turn 持久化，有明确 activate/deactivate 契约。
4. **allowed_tools enforcement 仍由 ToolRuntimeMediator / TOOL_GATE 负责**，不允许绕过。
5. **普通 ReAct main loop 保留**——Plan 3 是 planning branch / skill branch 的 runtime extension，不是第二 runtime。
6. **Evidence 必须覆盖 8 种场景**: selection entered / candidates built / model selection received / active_skill applied / allowed_tools bound / no_skill / fallback / failure。
7. **Keyword fallback 降级为 safety fallback only**——不作为主 selection path。
8. **Turn-end hook 不作为主 selection path**——降级为 safety fallback 的触发点。

### 2.4 与 Unified Runtime Flow Contract 的对齐

Plan 3 不引入新 branch point。变更集中在 `skill.select` branch point 内部：

```
变更前 execution_path (当前 PARTIAL):
  loop.turn_end → dispatcher → SkillSelectHandler
  → model_decision_metadata 校验 → result (success/rejected)

变更后 execution_path (Plan 3):
  turn-start → SkillCandidateRetriever.retrieve(user_input)
  → candidates → selection prompt injected into system prompt
  → model outputs select_skill / no_skill
  → (select_skill) ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE
  → SkillSelectToolHandler → TOOL_RESULT → active_skill lifecycle
  → skill body → conversation context → ToolRuntimeMediator allowed_tools
  → (no_skill) 正常 ReAct 继续
  → (fallback) turn-end keyword safety fallback
```

---

## 3. Phase Decomposition

### Phase 0: SDD / Architecture Review Only

- **目标**: 设计审查通过，确认 Plan 3 为目标架构。
- **改动范围**: 本文档 + PROGRESS_LEDGER.md。
- **明确不做**: 任何 production code、test、dogfood。
- **tests**: 无。
- **dogfood**: 无。
- **gates**: git diff --check, rg 口径检查（无 Plan 2 standalone / Plan 3 增量 / 002 credible 等误导表述）。
- **rollback / failure**: 设计审查未通过 → 回退 SDD 修正。
- **是否需要用户决策**: 是 — 6 个决策问题（见 §8.4）。

### Phase 1: Plan 3 Manifest Foundation

- **目标**: 扩展 SkillManifest schema，为 Plan 3 runtime 提供路由元数据基础。**这是 Plan 3 的 manifest foundation，不是 Plan 2 implementation。**
- **改动范围**:
  - `agent/skill_system/descriptor.py`: SkillManifest 新增字段（全部 optional）
  - `agent/skill_system/schema.py`: validate_manifest 兼容新字段
  - 现有 SKILL.md 文件（`skills/*/SKILL.md`）: 补充 routing metadata
- **明确不做**:
  - 不注册 SKILL_SELECT 为 TOOL_REGISTRY 工具（Phase 3）
  - 不实现 SkillCandidateRetriever（Phase 2）
  - 不实现 selection prompt injection（Phase 3）
  - 不修改 loop.py / core.py runtime 路径
  - 不让 002 标 credible（manifest alone ≠ credible）
- **tests**: M01-M06（manifest 扩展 RED tests，见 §7.1）
- **dogfood**: 无——manifest 变更通过 schema validation tests 验证
- **gates**:
  - `python -m pytest tests/unit/test_skill_manifest.py -v`（新建）
  - `python -m pytest tests/test_skill_schema.py -v`（现有，回归）
  - ruff check
  - git diff --check
- **rollback / failure**: manifest 字段设计有问题 → 回退 schema 修正，不影响 runtime
- **是否需要用户决策**: 否——字段范围已在 §8.4 Q3 确认

### Phase 2: Candidate Skill Retrieval

- **目标**: 实现 SkillCandidateRetriever，基于 aliases / trigger examples / lexical matching 返回候选列表。**不依赖 BM25 或 embedding。**
- **改动范围**:
  - `agent/skill_system/retriever.py` NEW: SkillCandidateRetriever
    - Pass 1: trigger 精确匹配（权重最高）
    - Pass 2: alias 匹配
    - Pass 3: name/description/tags 关键词匹配
    - Pass 4: negative trigger 惩罚
    - 输出: top-K candidates (或空列表)
  - `agent/skill_system/registry.py`: 暴露 `list_visible_with_manifest()` 供 retriever 使用
- **明确不做**:
  - 不实现 BM25——BM25 作为 optional enhancement，不在 Phase 2 scope
  - 不实现 embedding——embedding deferred to future enhancement
  - 不注入 candidates 到 system prompt（Phase 3）
  - 不修改 runtime loop（Phase 3）
- **tests**: R01-R05（retriever RED tests，见 §7.2）
- **dogfood**: retriever unit-level validation（FakeProvider scripted, 不调真实 API）
- **gates**:
  - `python -m pytest tests/unit/test_skill_retriever.py -v`（新建）
  - ruff check
  - git diff --check
- **rollback / failure**: retriever 准确率低 → 调整 scoring weights，不影响 runtime
- **是否需要用户决策**: 否——BM25/embedding 已明确为后续 enhancement

### Phase 3: Turn-Start Structured Skill Selection Phase

- **目标**: 在 turn-start 将 candidates 路由信息注入 system prompt；模型输出 select_skill / no_skill 决定；select_skill 走 ToolRuntimeMediator pipeline。
- **改动范围**:
  - `agent/skill_system/prompt_section.py`: 新增 `build_skill_selection_section(candidates)`
  - `agent/prompt_builder.py`: turn-start 调用 retriever → 注入 selection section
  - `agent/skill_system/skill_tool.py` NEW: SKILL_SELECT 注册为 TOOL_REGISTRY 标准工具
  - `agent/runtime_integration/skill_action.py`: 新增 SkillSelectToolHandler（tool_use handler）
  - `agent/core.py`: get_model_visible_tools() 加入 SKILL_SELECT
  - `agent/loop.py`: turn-start skill selection phase 插入（在 model call 前）
- **明确不做**:
  - 不实现 active_skill lifecycle（Phase 4）
  - 不修改 turn-end keyword fallback 行为
  - 不让 selection phase 成为阻塞 gate——no_skill 时正常继续 ReAct
- **tests**: T01-T08 + E01-E06 + S01-S06（见 §7.3）
- **dogfood**: FakeProvider scripted tool_use 验证 selection phase → mediation → handler 路径
- **gates**:
  - `python -m pytest tests/runtime_integration/test_skill_turn_start_selection.py -v`
  - `python -m pytest tests/unit/test_skill_select_tool.py -v`
  - ruff check + git diff --check
- **rollback / failure**:
  - selection prompt 格式导致模型行为退化 → 调整 prompt 格式
  - 模型频繁输出无效 skill_id → enum constraint 加固
  - runtime 可配置 `skill_selection_enabled=False` 跳过 Phase 3
- **是否需要用户决策**: 否——Q1 (SKILL_SELECT role) 和 Q2 (selection phase) 已在 §8.4 确认

### Phase 4: Runtime-Managed active_skill Lifecycle

- **目标**: active_skill 跨 turn 持久化，有明确 activate/deactivate/switch 语义。**这是 Plan 3 的核心差异化能力。**
- **改动范围**:
  - `agent/skill_system/lifecycle.py` NEW: ActiveSkillLifecycle
    - `activate(skill_id, body, allowed_tools)` → active_skill state
    - `deactivate()` → 清除 active_skill
    - `switch(new_skill_id)` → deactivate + activate
    - `is_active()` → bool
    - `get_active()` → ActiveSkill | None
    - deactivate 触发条件: task complete / 模型选择新 skill / 用户显式取消 / checkpoint resume 清除
  - `agent/core.py`: 替换 module-level `_active_skill` dict → ActiveSkillLifecycle instance
  - checkpoint: active_skill 状态纳入 checkpoint save/resume
- **明确不做**:
  - 不实现 multi-instance namespace（B7）
  - 不实现 session/run scope（B7）
  - 不实现 per-instance skill registry（B7）
- **tests**: L01-L06（lifecycle RED tests，见 §7.4）
- **dogfood**: FakeProvider multi-turn scenario——激活 skill → 跨 turn 保持 → deactivate
- **gates**:
  - `python -m pytest tests/unit/test_active_skill_lifecycle.py -v`
  - `python -m pytest tests/runtime_integration/test_skill_lifecycle_runtime.py -v`
  - ruff check + git diff --check
- **rollback / failure**: lifecycle 状态 bug → 回退到 module-level dict（向后兼容），不阻塞 runtime
- **是否需要用户决策**: 否——Q4 lifecycle mode 已在 §8.4 确认

### Phase 5: ToolRuntimeMediator allowed_tools Integration

- **目标**: active_skill.allowed_tools 通过 ToolRuntimeMediator → TOOL_GATE 强制实施。**这个能力在 003 hardening 中已有部分验证，Phase 5 将其与 Plan 3 active_skill lifecycle 正式连接。**
- **改动范围**:
  - `agent/tool_runtime_mediator.py`: mediate() 从 active_skill lifecycle 读取 allowed_tools（替代当前 _active_skill dict）
  - `agent/runtime_integration/tool_gate.py`: ToolGateHandler 接收 allowed_tools 来源标记
  - evidence: tool_gate 标记 `allowed_tools_source="active_skill_lifecycle"`
- **明确不做**:
  - 不修改 TOOL_GATE disposition 逻辑（allowed/rejected/confirmation_required 不变）
  - 不修改 tool registry 注册逻辑
- **tests**: A01-A04（allowed_tools integration tests，见 §7.5）
- **dogfood**: FakeProvider scripted——激活 skill → 使用 allowed tool → 被允许；使用 disallowed tool → 被拒绝
- **gates**:
  - `python -m pytest tests/runtime_integration/test_skill_allowed_tools.py -v`
  - ruff check + git diff --check
- **rollback / failure**: allowed_tools binding 失败 → fallback 到空 allowed_tools（所有工具可用），记录 evidence
- **是否需要用户决策**: 否——Q5 allowed_tools source 已在 §8.4 确认

### Phase 6: Evidence Chain + Real Provider Dogfood

- **目标**: 真实模型验证 Plan 3 全链路——从 turn-start selection phase 到 active_skill lifecycle 到 allowed_tools enforcement。**002 是否达到 credible 在此 phase 判定。**
- **改动范围**:
  - `scripts/real_evidence_002_plan3_dogfood.py` NEW: real provider dogfood script
  - evidence 覆盖 8 种场景（selection entered / candidates built / model selection received / active_skill applied / allowed_tools bound / no_skill / fallback / failure）
  - `docs/dogfood/real-evidence-002-plan3-results.json`: 结果文件
- **明确不做**:
  - 不修改 production code（dogfood script only）
  - 不标注 MODEL_BEHAVIOR_CONCERN 为 credible
- **tests**: D01-D08（dogfood assertions，见 §7.6）
- **dogfood**: 本轮就是 dogfood phase
- **gates**:
  - `python scripts/real_evidence_002_plan3_dogfood.py`（real API）
  - `python -m pytest tests/unit/test_skill_manifest.py tests/unit/test_skill_retriever.py tests/unit/test_skill_select_tool.py tests/unit/test_active_skill_lifecycle.py tests/runtime_integration/test_skill_turn_start_selection.py tests/runtime_integration/test_skill_lifecycle_runtime.py tests/runtime_integration/test_skill_allowed_tools.py -v`
  - ruff check + git diff --check
- **rollback / failure**: 真实模型行为不稳定 → 002 保持 partial-credible，记录 MODEL_BEHAVIOR_CONCERN
- **是否需要用户决策**: 是——002 最终状态判定（credible / credible-with-caveats / partial-credible）

### Phase 7: B7-Ready Namespace Extension Points

- **目标**: 在 Plan 3 架构中预留 B7 扩展点，不实现 B7。确保 B7 可以在不破坏 Plan 3 的前提下扩展 multi-instance / session scope / checkpoint scope。
- **改动范围**:
  - `agent/skill_system/lifecycle.py`: ActiveSkillLifecycle 接口预留 `namespace` 参数（Phase 7 前默认为 "default"）
  - `agent/skill_system/registry.py`: SkillRegistry 接口预留 `scope` 参数
  - 设计文档: B7 extension point specification
- **明确不做**:
  - 不实现 multi-instance namespace（B7）
  - 不实现 session/run scope（B7）
  - 不实现 checkpoint scope（B7）
  - 不实现 per-instance skill registry（B7）
  - 不开始 B7 implementation
- **tests**: extension point interface tests——验证预留参数存在且不影响现有行为
- **dogfood**: 无
- **gates**: ruff check + git diff --check
- **rollback / failure**: extension point 设计阻碍 Phase 1-6 正常路径 → 移除 extension point
- **是否需要用户决策**: 否

---

## 4. Data Model Changes

### 4.1 SkillManifest 扩展字段（Phase 1）

```python
@dataclass(frozen=True)
class SkillManifest:
    # ── 现有字段（不变）──
    name: str
    description: str
    version: str
    status: SkillStatus
    risk_level: RiskLevel
    tags: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    memory_scope: MemoryScope
    confirmation_policy: ConfirmationPolicy
    owner: str
    resources: SkillResourceManifest

    # ── Plan 3 manifest foundation 新增字段（全部 optional）──
    when_to_use: str | None = None
    when_not_to_use: str | None = None
    triggers: tuple[str, ...] = ()
    negative_triggers: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    locale: str | None = None
```

### 4.2 SKILL.md frontmatter 扩展示例

```yaml
name: demo-note-maker
description: 围绕 demo 工具创建本地任务笔记
version: 0.1.0
status: active
risk_level: low
allowed_tools: [demo.echo_task_summary, demo.write_demo_note]
tags: [demo, note, local]
memory_scope: none
# ── Plan 3 manifest foundation 新增 ──
when_to_use: >
  用户需要记录任务、创建待办、写笔记、做备忘时选择此 skill。
  适用于对话中产生需要持久化的信息时。
when_not_to_use: >
  不要用于代码编辑、git 操作、文件系统操作——这些是通用能力，不是 note 的职责。
triggers:
  - "写笔记"
  - "记录任务"
  - "待办"
  - "备忘"
  - "记个笔记"
  - "make a note"
  - "create a note"
negative_triggers:
  - "写代码"
  - "git commit"
aliases:
  - "note"
  - "笔记"
  - "demo-note"
locale: zh-CN
```

### 4.3 向后兼容

- 所有新增字段 optional（默认 None/空 tuple）
- `validate_manifest()` 不要求新字段存在
- 旧 SKILL.md 不加新字段不报错——routing 质量自然降低，但不阻塞
- `SkillDescriptor.is_visible()` 行为不变

---

## 5. Component Design

### 5.1 SkillCandidateRetriever（Phase 2，新建）

```python
# agent/skill_system/retriever.py

@dataclass(frozen=True)
class SkillCandidate:
    skill_name: str
    score: float
    match_reason: str          # "trigger_exact", "alias_match", "keyword_match"
    matched_terms: tuple[str, ...]

class SkillCandidateRetriever:
    """Turn-start skill 候选检索器。

    基于 aliases / trigger examples / lexical matching 做候选评分。
    不使用 BM25 或 embedding（保留为后续 enhancement）。
    """

    def retrieve(self, user_input: str, registry: SkillRegistry,
                 top_k: int = 5) -> list[SkillCandidate]:
        ...

    def _score_by_triggers(self, user_input_lower: str,
                           manifest: SkillManifest) -> float:
        """Pass 1: 精确 trigger 匹配（权重 3.0）."""

    def _score_by_aliases(self, user_input_lower: str,
                          manifest: SkillManifest) -> float:
        """Pass 2: alias 匹配（权重 2.0）."""

    def _score_by_keywords(self, user_input_words: set[str],
                           manifest: SkillManifest) -> float:
        """Pass 3: name/description/tags 关键词匹配（权重 1.0）."""

    def _penalize_negative(self, user_input_lower: str,
                           manifest: SkillManifest) -> float:
        """负例惩罚：negative_triggers 命中 → 得分归零."""
```

### 5.2 SkillSelectToolHandler（Phase 3，新增）

```python
# agent/runtime_integration/skill_action.py 扩展

class SkillSelectToolHandler:
    """处理模型的 tool_use(name="SKILL_SELECT", input={...}) 调用。

    走标准 ToolRuntimeMediator pipeline:
      model tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
    """

    def handle(self, tool_input: dict, context: ToolContext) -> ToolResult:
        skill_id = tool_input["skill_id"]
        # 1. 校验 skill_id 存在且可见
        # 2. 加载 skill body
        # 3. 通知 ActiveSkillLifecycle.activate()
        # 4. 返回包含 skill body 的 tool_result
```

### 5.3 Selection Prompt Section（Phase 3，扩展 prompt_section.py）

```python
def build_skill_selection_section(candidates: list[SkillCandidate],
                                   registry: SkillRegistry) -> str:
    """为 system prompt 生成 skill selection section。

    格式:
      ## Skill Selection

      The following skills may help with the user's request.
      To activate a skill, use the select_skill tool.
      If no skill is needed, respond normally without calling select_skill.

      ### demo-note-maker
      - Description: 围绕 demo 工具创建本地任务笔记
      - Use when: 用户需要记录任务、创建待办、写笔记、做备忘
      - Triggers: 写笔记, 记录任务, 待办, 备忘
    """
```

### 5.4 ActiveSkillLifecycle（Phase 4，新建）

```python
# agent/skill_system/lifecycle.py

@dataclass(frozen=True)
class ActiveSkill:
    skill_id: str
    body: str
    allowed_tools: tuple[str, ...]
    activated_at: float  # time.time()
    activated_by: str    # "model_selection" | "keyword_fallback" | "cli_command"

class ActiveSkillLifecycle:
    """Runtime-managed active_skill lifecycle。

    Plan 3 核心——跨 turn 持久化的 active_skill 状态管理。
    """

    def activate(self, skill_id: str, body: str,
                 allowed_tools: tuple[str, ...],
                 activated_by: str) -> ActiveSkill: ...

    def deactivate(self) -> None: ...

    def switch(self, skill_id: str, body: str,
               allowed_tools: tuple[str, ...],
               activated_by: str) -> ActiveSkill: ...

    def is_active(self) -> bool: ...

    def get_active(self) -> ActiveSkill | None: ...

    # B7 extension point (Phase 7)
    def activate_in_namespace(self, namespace: str, ...) -> ActiveSkill: ...
```

---

## 6. B7 / B8 Boundaries

### 6.1 Plan 3 does NOT wait for B7/B8

002 的 Plan 3 实现不依赖 B7/B8。002 可以先做 single-instance skill selection。

### 6.2 B7 Scope（明确隔离）

B7 只扩展以下能力，当前不进入：

- **multi-instance namespace**: 每个 sub-agent instance 有自己的 skill registry
- **session / run scope**: active_skill 的 scope 从 multi-turn 扩展到 session/run
- **checkpoint scope**: active_skill 状态的 checkpoint 序列化/反序列化
- **per-instance skill registry**: 每个 instance 可加载不同 skill set

Phase 7 预留命名空间扩展点（`namespace` / `scope` 参数），不实现。

### 6.3 B8 Scope（明确隔离）

B8 只处理以下能力，当前不进入：

- **TUI 展示**: skill selection candidates 的可视化列表
- **用户交互**: CLI `/skill` 命令、交互式 skill 选择 UI
- **skill selection / activation 可视化**: active skill 状态指示器

### 6.4 当前状态

- **不进入 B7/B8**
- **不开始 implementation**
- **002 可以独立于 B7/B8 达到 credible**

---

## 7. TDD / Test Plan

### 7.1 Phase 1 RED Tests — Manifest Foundation（M01-M06）

| ID | 测试 | 断言 |
|----|------|------|
| M01 | `test_new_manifest_fields_default_to_none()` | when_to_use / when_not_to_use / triggers / negative_triggers / aliases / locale 默认 None/空 |
| M02 | `test_triggers_parsed_as_list()` | SKILL.md `triggers: [a, b, c]` → tuple |
| M03 | `test_old_skill_md_without_new_fields_passes_validation()` | 不带新字段的旧 SKILL.md 仍通过 validate_manifest |
| M04 | `test_when_to_use_preserved_in_raw_frontmatter()` | when_to_use 完整保留，可审计 |
| M05 | `test_aliases_included_in_descriptor()` | SkillDescriptor.aliases 可访问 |
| M06 | `test_new_fields_redacted_in_audit()` | raw_frontmatter 敏感字段被 redact |

### 7.2 Phase 2 RED Tests — Candidate Retrieval（R01-R05）

| ID | 测试 | 断言 |
|----|------|------|
| R01 | `test_retriever_returns_empty_for_no_match()` | 无关输入 → 空列表 |
| R02 | `test_trigger_exact_match_scores_highest()` | user_input 精确命中 trigger → 最高分 |
| R03 | `test_alias_match_scores_second()` | alias 命中 → 次高分 |
| R04 | `test_negative_trigger_zeroes_score()` | negative_triggers 命中 → 得分归零 |
| R05 | `test_retriever_respects_top_k()` | 返回 ≤K 个候选，按 score 降序 |

### 7.3 Phase 3 RED Tests — Turn-Start Selection（T01-T08 + E01-E06 + S01-S06）

**Tool registration (T01-T08)**:
| ID | 测试 | 断言 |
|----|------|------|
| T01 | `test_skill_select_registered_in_tool_registry()` | "SKILL_SELECT" in TOOL_REGISTRY |
| T02 | `test_skill_select_is_model_visible()` | get_model_visible_tools() 包含 SKILL_SELECT |
| T03 | `test_skill_select_schema_has_skill_id_enum()` | input_schema enum 非空 |
| T04 | `test_skill_select_enum_excludes_disabled()` | disabled/hidden 不在 enum |
| T05 | `test_skill_select_valid_id_succeeds()` | 合法 skill_id → result.ok=True |
| T06 | `test_skill_select_invalid_id_fails()` | 不存在的 skill_id → result.ok=False |
| T07 | `test_skill_select_produces_tool_gate_evidence()` | TOOL_GATE evidence 含 tool_name |
| T08 | `test_skill_select_produces_tool_invoke_evidence()` | TOOL_INVOKE evidence 含 handler |

**Evidence chain (E01-E06)**:
| ID | 测试 | 断言 |
|----|------|------|
| E01 | `test_full_evidence_chain_selection()` | selection entered → candidates built → model selection → active_skill applied |
| E02 | `test_evidence_distinguishes_selection_vs_fallback()` | selection 和 fallback 有不同 evidence 标记 |
| E03 | `test_fallback_not_triggered_when_selection_succeeds()` | selection 成功 → fallback 不触发 |
| E04 | `test_no_skill_continues_normal_react()` | no_skill → 正常 ReAct，不 crash |
| E05 | `test_selection_not_direct_call()` | dispatcher_origin == "runtime_loop" |
| E06 | `test_active_skill_updated_via_dispatcher()` | _active_skill 从 dispatcher action_log 更新 |

**Selection phase (S01-S06)**:
| ID | 测试 | 断言 |
|----|------|------|
| S01 | `test_selection_section_injected_when_candidates_exist()` | system prompt 含 selection section |
| S02 | `test_selection_section_absent_when_no_candidates()` | 无候选时不注入 |
| S03 | `test_selection_section_includes_when_to_use()` | 每个候选含 when_to_use |
| S04 | `test_selection_section_includes_triggers()` | 每个候选含 triggers（top 5） |
| S05 | `test_selection_phase_before_model_call()` | selection prompt 在 model call 前注入 |
| S06 | `test_selection_phase_not_blocking()` | selection 失败不阻塞 main loop |

### 7.4 Phase 4 RED Tests — active_skill Lifecycle（L01-L06）

| ID | 测试 | 断言 |
|----|------|------|
| L01 | `test_activate_creates_active_skill()` | activate() → is_active() == True |
| L02 | `test_deactivate_clears_active_skill()` | deactivate() → is_active() == False |
| L03 | `test_switch_replaces_active_skill()` | switch() → new skill_id / body / allowed_tools |
| L04 | `test_active_skill_persists_across_turns()` | core.chat() turn1 激活 → turn2 is_active() == True |
| L05 | `test_active_skill_deactivates_on_task_complete()` | task complete → deactivate |
| L06 | `test_lifecycle_included_in_checkpoint()` | checkpoint save/load 含 active_skill state |

### 7.5 Phase 5 RED Tests — allowed_tools Integration（A01-A04）

| ID | 测试 | 断言 |
|----|------|------|
| A01 | `test_allowed_tools_from_active_skill_lifecycle()` | TOOL_GATE 从 lifecycle 读取 allowed_tools |
| A02 | `test_allowed_tool_passes_gate()` | allowed tool → TOOL_GATE allowed |
| A03 | `test_disallowed_tool_blocked_by_gate()` | disallowed tool → TOOL_GATE rejected |
| A04 | `test_no_active_skill_no_tool_restriction()` | 无 active_skill → 所有工具可用 |

### 7.6 Phase 6 RED Tests — Dogfood Assertions（D01-D08）

| ID | 断言 |
|----|------|
| D01 | selection entered evidence 产生 |
| D02 | candidates built evidence 产生（top-K 非空） |
| D03 | model selection received evidence 产生（模型输出 select_skill） |
| D04 | active_skill applied evidence 产生 |
| D05 | allowed_tools bound evidence 产生 |
| D06 | no_skill evidence 产生（模型输出 no_skill 的 case） |
| D07 | fallback evidence 产生（safety fallback 触发的 case） |
| D08 | failure evidence 产生（selection 失败的 case） |

### 7.7 GREEN Tests（回归保护）

| 测试文件 | 预期数 | 验证内容 |
|---------|--------|---------|
| `tests/runtime_integration/test_skill_selection_real_provider.py` | 15 | keyword fallback 行为不变 |
| `tests/test_skill_selector.py` | 12+ | SkillSelector 行为不变 |
| `tests/test_skill_dogfood.py` | 20+ | skill dogfood 路径不变 |
| `tests/runtime_integration/test_skill_l3.py` | 现有 | L3 evidence 测试不变 |
| `tests/runtime_integration/test_skill_model_owned_selection.py` | 15 | I1-I15 不变 |

---

## 8. Review Packet

### 8.1 Architecture Decision Summary

| Decision | Status |
|----------|--------|
| Plan 3 selected as target architecture | **ACCEPTED** |
| Plan 2 standalone path | **REJECTED** |
| Plan 2 metadata retained as Plan 3 foundation | **ACCEPTED** |
| Q1-Q6 user decisions | **CONFIRMED** (2026-05-31, see §8.4) |
| Architecture design review | **PASSED** (2026-05-31, see §8.7) |
| Implementation | **NOT STARTED** |
| Production code changed | **NO** |
| Tests changed | **NO** |
| B7/B8 started | **NO** |
| 002 status | **partial-credible** (until implementation + dogfood pass) |
| Next step | **TDD RED tests plan → Phase 1 M01-M06** |

### 8.2 Design Soundness

| 维度 | 评估 | 说明 |
|------|------|------|
| **与 Contract 一致性** | PASS | 不新增 branch point / capability milestone，skill.select 内做 branch behavior 扩展 |
| **单一 runtime 路径** | PASS | Plan 3 是 planning branch / skill branch 的 runtime extension，不是第二 runtime |
| **普通 ReAct main loop 保留** | PASS | Plan 3 在 turn-start 注入 selection phase，不替代 ReAct |
| **向后兼容** | PASS | 旧 SKILL.md 不报错，keyword fallback 保留为 safety fallback |
| **渐进式交付** | PASS | 7 phases，每 phase 有明确退出标准，不要求一步到位 |
| **B7/B8 隔离** | PASS | Phase 7 仅预留扩展点，不实现 |

### 8.3 Risk Assessment

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 模型不主动调用 select_skill | 中 | 002 无法升级到 credible | turn-start routing injection (Phase 3) 提升调用率；safety fallback 兜底 |
| 新 manifest 字段维护负担 | 低 | skill 作者需写更多 metadata | 全部 optional；不写也能正常工作 |
| selection prompt 增加 context budget | 低 | token 消耗增加 | top-K=5，每个候选 routing info 截断 |
| selection phase 增加 latency | 低 | 每次 turn 多一次 retriever 调用 | retriever 纯内存计算，无 I/O |

### 8.4 用户决策点（CONFIRMED）

以下问题已在 2026-05-31 由用户确认。**Plan 3 selected as target architecture. Plan 2 standalone rejected. Plan 2 metadata retained only as Plan 3 foundation.**

---

**Q1: SKILL_SELECT future role → CONFIRMED: C**

> **C. both: runtime selection action primary + ordinary tool compatibility path**

选择 C 而非推荐 B 的理由：保留普通工具兼容路径提供防御性——如果 turn-start selection phase 因任何原因未触发（例如 prompt injection 失败、retriever 返回空但模型后续自行识别出 skill），模型仍可通过标准 tool_use 路径调用 SKILL_SELECT。两个路径收敛到同一 ToolRuntimeMediator pipeline 和 ActiveSkillLifecycle.activate()，不构成双主路径。

架构影响：
- SKILL_SELECT 需要同时注册为 selection phase runtime action 和 TOOL_REGISTRY 普通工具
- 两条路径共享同一个 SkillSelectToolHandler
- Evidence 需要区分 `activated_by="selection_phase"` 和 `activated_by="tool_use_compatibility"`
- TDD 需补充双路径收敛测试（见 §8.7 审查发现 #3）

---

**Q2: Selection phase → CONFIRMED: B**

> **B. turn-start primary + turn-end safety fallback**

与推荐一致。turn-start selection phase 为主路径，turn-end keyword fallback 降级为 safety net。

---

**Q3: Candidate retrieval → CONFIRMED: A**

> **A. aliases / trigger examples / lexical first**（BM25 optional future, embedding deferred）

与推荐一致。纯词法匹配，不引入 BM25 或 embedding 依赖。

---

**Q4: active_skill lifecycle → CONFIRMED: B**

> **B. multi-turn until task complete**

与推荐一致。跨 turn 保持 active_skill，task complete / 模型切换 / 用户取消时 deactivate。

---

**Q5: allowed_tools source → CONFIRMED: C**

> **C. manifest declares, runtime validates/enforces**

用户选择 C（manifest declares + runtime enforces），注意 SDD 原推荐为 A 且描述相同——选项标签 A/C 在不同版本间可能不一致。已确认：manifest 声明 allowed_tools，runtime 通过 ToolRuntimeMediator/TOOL_GATE 强制实施。

架构影响：
- 与推荐方案实质一致（manifest declares + runtime enforces）
- Phase 5 设计无需调整
- 对应测试 A01-A04 不变

---

**Q6: Fallback policy → CONFIRMED: A**

> **A. safety fallback only**

与推荐一致。keyword fallback 仅 high confidence + 无歧义时触发，不作为主路径。

---

### 8.5 Scope Boundaries（明确不做）

- **不做 LLM-based skill 推荐** — 不调用额外 LLM 选 skill
- **不做 skill 自动安装/更新** — 独立 RFC
- **不做 multi-skill 并发激活** — 单 skill 单 turn
- **不做 SkillSelector 替换** — SkillSelector 和 select_skill_for_real_provider 共存
- **不修改 003/004/005/006/007/008** — 严格 scope 隔离
- **不进入 B7/B8** — 仅 002，Phase 7 预留扩展点
- **不直接 implementation** — 本文档是 SPEC/SDD
- **不让 002 标 credible** — 仅 SPEC/SDD 阶段，credible 需 Phase 6 dogfood

### 8.6 Next Steps

1. ~~**Architecture design review** (当前 gate) — 用户确认 6 个决策问题~~ ✅ PASSED (2026-05-31, see §8.7)
2. **TDD RED tests plan formalization** — 补充 §8.7 审查发现 #8 的双路径收敛测试
3. **Phase 1 TDD RED tests (M01-M06)** — manifest foundation 测试先行
4. **Implementation loop** — 每 phase GREEN → refactor
5. **Real provider dogfood** — Phase 6 真实模型验证
6. **Credibility判定** — Phase 6 通过后 002 可标 credible

### 8.7 Architecture Design Review Outcome

**日期**: 2026-05-31
**审查范围**: §8.2 Design Soundness + 9 项用户指定审查点 + Q1-Q6 决策一致性
**结论**: **PASS** — Plan 3 架构设计通过审查，无阻塞性问题。1 项 TDD 补充建议（非阻塞）。

---

#### 审查点 #1: Plan 3 是否真的能闭合 002 当前 caveats

**判定**: PASS

002 当前 5 个根因维度（§1.1）的闭合分析：

| 根因维度 | 当前缺陷 | Plan 3 方案 | 闭合? |
|---------|---------|------------|------|
| 时序 | turn-end hook 事后补救 | turn-start selection phase（Phase 3） | ✅ |
| 匹配 | 中文 bigram fallback | SkillCandidateRetriever: trigger/alias/lexical（Phase 2） | ✅ |
| 决策权 | runtime 替模型选 | 模型通过 select_skill 自主选择（Phase 3） | ✅ |
| 路由信息 | description + tags 仅两项 | when_to_use/triggers/aliases/negative_triggers（Phase 1） | ✅ |
| SkillSelector | 从未接入生产路径 | SkillCandidateRetriever 替代 select_skill_for_real_provider 作为主路径 | ✅ |

**结论**: Plan 3 闭合了所有 5 个根因维度。闭合质量取决于 Phase 6 real provider dogfood 验证——如果模型频繁不调用 select_skill，safety fallback 会成为事实主路径（见 #6），届时 002 仍为 partial-credible。

---

#### 审查点 #2: turn-start selection phase 是否会破坏现有 ReAct loop

**判定**: PASS

Plan 3 的 turn-start injection 是 **additive injection point**，不是 replacement：

```
Before (current):
  turn_start → build_system_prompt → model_call → tool_exec → turn_end

After (Plan 3):
  turn_start → retriever → selection_prompt_injection → model_call → [select_skill?] → tool_exec → turn_end
                                                    ↑
                                             injection point
```

- ReAct main loop 结构不变（model → tool → model → tool）
- Selection phase 失败（retriever 返回空、模型输出 no_skill）→ 正常 ReAct 继续
- Selection phase 成功 → skill body 注入下一轮 system prompt → 仍走 ReAct loop
- S01-S06 中的 S05/S06 专门验证"不阻塞 main loop"

**结论**: 不破坏 ReAct loop。selection phase 注入发生在 model call 之前的 prompt 构建阶段，不影响 ReAct 的 observe→plan→act 循环。

---

#### 审查点 #3: runtime selection action + ordinary compatibility tool 是否会造成双主路径

**判定**: PASS（附 TDD 补充建议）

Q1=C 选择了两条路径：selection phase runtime action（主路径）和 TOOL_REGISTRY compatibility tool（兼容路径）。

**为什么不是双主路径**：
- 两条路径共享同一 SkillSelectToolHandler（Phase 3）
- 两条路径走同一 ToolRuntimeMediator pipeline（TOOL_GATE → TOOL_INVOKE → TOOL_RESULT）
- 两条路径收敛于同一 ActiveSkillLifecycle.activate()（Phase 4）
- Evidence 通过 `activated_by` 字段区分来源（`"selection_phase"` vs `"tool_use_compatibility"`）

**TDD 补充建议**（非阻塞）：
- §7.3 需新增 S07: `test_selection_phase_and_compatibility_tool_converge_to_same_lifecycle()` — 验证两条路径激活的 ActiveSkill 对象等价
- §7.3 需新增 E07: `test_evidence_distinguishes_selection_phase_vs_compatibility()` — 验证 activated_by 字段正确区分来源

---

#### 审查点 #4: multi-turn active_skill lifecycle 是否安全

**判定**: PASS

安全性分析：

| 关注点 | 分析 | 状态 |
|--------|------|------|
| 跨 turn 状态一致性 | ActiveSkillLifecycle 是单例，state 不可变（frozen dataclass） | ✅ |
| 过期 skill context | deactivate 条件明确：task complete / 模型切换 / 用户取消 | ✅ |
| checkpoint 一致性 | active_skill 纳入 checkpoint save/resume（Phase 4, L06） | ✅ |
| 并发/多实例 | Phase 7 前仅 single-instance，B7 namespace 预留扩展点 | ✅ |
| 状态泄漏 | deactivate() 清除所有 active_skill 引用 | ✅ |
| switch 原子性 | switch() = deactivate() + activate()，中间无裸露状态 | ✅ |

**结论**: multi-turn lifecycle 安全。关键保障是明确的 deactivate 触发条件和 checkpoint 集成。

---

#### 审查点 #5: allowed_tools manifest declares / runtime validates/enforces 是否边界清晰

**判定**: PASS

边界分析（Q5=C 确认）：

```
┌─────────────────────────────────────────────────────────┐
│ DECLARATION (manifest — skill 作者维护)                  │
│                                                         │
│ SKILL.md frontmatter → SkillManifest.allowed_tools      │
│ validate_manifest() 检查格式                              │
│ SkillRegistry 存储                                       │
│                                                         │
│ 作者说："我需要这些工具"                                    │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ ENFORCEMENT (runtime — 系统保证)                          │
│                                                         │
│ ActiveSkillLifecycle.get_active().allowed_tools          │
│   → ToolRuntimeMediator.mediate()                        │
│     → TOOL_GATE                                          │
│       → allowed (tool in allowed_tools)                  │
│       → rejected (tool not in allowed_tools)             │
│       → confirmation_required (inherit_tool_policy)      │
│                                                         │
│ 系统保证："我只给你这些工具"                                 │
└─────────────────────────────────────────────────────────┘
```

- Declaration 和 enforcement 之间有 SkillManifest → ActiveSkillLifecycle 的单向数据流
- Runtime 不修改 manifest（immutable frozen dataclass）
- Manifest 不感知 runtime enforcement 细节
- 003 hardening 已验证此模式

**结论**: 边界清晰。declaration 和 enforcement 各司其职，无交叉依赖。

---

#### 审查点 #6: safety fallback 是否不会重新变成事实主路径

**判定**: PASS（设计层面），实际取决于 Phase 6 dogfood 验证

设计层面的防护：

| 防护层 | 机制 | 效果 |
|--------|------|------|
| 触发时机 | fallback 仅在 turn-end 触发，selection phase 在 turn-start 先执行 | selection phase 优先 |
| 触发条件 | 仅 high confidence + 无歧义 | 低匹配不激活 |
| Evidence 区分 | `activated_by="keyword_fallback"` vs `"selection_phase"` | 可审计，可度量 |
| 退化检测 | Phase 6 D07 验证 fallback 触发频率 | 如果 fallback 频率 > selection，触发 MODEL_BEHAVIOR_CONCERN |
| 架构约束 | keyword fallback 不是主路径——SDD 明确声明 | 防止口径退化 |

**风险**: 如果 Phase 6 dogfood 显示 fallback 触发频率显著高于 selection phase，说明 turn-start injection 未能有效引导模型调用 select_skill。此时 002 不能标 credible——这是正确的门禁行为。

**结论**: 设计层面防护充分。实际退化检测依赖 Phase 6 evidence。

---

#### 审查点 #7: 是否会影响 Memory / MCP / SubAgent / Scheduler / Checkpoint

**判定**: PASS

子系统影响分析：

| 子系统 | 影响 | 说明 |
|--------|------|------|
| **Memory** | 无影响 | active_skill.memory_scope 已在 SkillManifest 中定义，Plan 3 不改变其行为 |
| **MCP** | 无影响 | MCP bridge 是 startup-only 操作（per REAL-EVIDENCE-005），与 per-turn selection phase 无交互 |
| **SubAgent** | 无影响（Phase 7 前） | Plan 3 仅 single-instance；B7 SubAgent namespace 在 Phase 7 预留扩展点，不实现 |
| **Scheduler** | 无影响 | ActionPlan-based scheduler 是独立 code path（008），skill selection 不涉及 plan execution |
| **Checkpoint** | 正向影响 | Phase 4 L06: active_skill 状态纳入 checkpoint save/resume，增强了恢复能力 |

**结论**: Plan 3 是 additive change，不影响现有子系统。Checkpoint 获得正向增强。

---

#### 审查点 #8: 是否需要在 implementation 前补 TDD RED tests

**判定**: PASS（§7 测试计划充分，附 1 项补充建议）

§7 现有测试计划：M01-M06（6）+ R01-R05（5）+ T01-T08（8）+ E01-E06（6）+ S01-S06（6）+ L01-L06（6）+ A01-A04（4）+ D01-D08（8）+ 62+ regression = **111+ tests**。

补充建议（非阻塞——可在 TDD 阶段补充）：

| 补充 ID | 测试 | 原因 |
|---------|------|------|
| S07 | `test_selection_phase_and_compatibility_tool_converge` | Q1=C 双路径收敛验证 |
| E07 | `test_evidence_distinguishes_selection_vs_compatibility` | Q1=C evidence 来源区分 |
| R06 | `test_retriever_penalizes_low_quality_candidates` | retriever 返回空列表的场景丰富化 |

**结论**: 现有测试计划覆盖充分。3 项补充为 Q1=C 专门测试，不影响 Phase 1 启动。

---

#### 审查点 #9: 是否还有必须用户拍板的问题

**判定**: PASS（无剩余决策点）

Q1-Q6 已全部确认。Phase 1-6 的 scope/gates/rollback 策略已明确。B7/B8 边界清晰。以下不是需要用户决策的问题，而是实现阶段的正常判断：
- retriever scoring weights 具体数值 → 实现时 tuning
- selection prompt 精确措辞 → 实现时 iteration
- deactivate 的 "task complete" 判定逻辑 → 实现时设计

**结论**: 无需用户进一步决策。可以进入 TDD RED tests。

---

#### 最终审查结论

| 审查点 | 判定 |
|--------|------|
| #1 闭合 002 caveats | ✅ PASS |
| #2 不破坏 ReAct loop | ✅ PASS |
| #3 双路径不分裂 | ✅ PASS（附 TDD 补充建议） |
| #4 multi-turn lifecycle 安全 | ✅ PASS |
| #5 allowed_tools 边界清晰 | ✅ PASS |
| #6 safety fallback 不喧宾夺主 | ✅ PASS（需 Phase 6 dogfood 验证） |
| #7 不影响子系统 | ✅ PASS |
| #8 TDD RED tests 充分 | ✅ PASS（附 3 项补充建议） |
| #9 无剩余用户决策 | ✅ PASS |

**Overall: PASS** — Plan 3 架构设计通过审查。阻塞问题: 0。TDD 补充建议: 3 项（非阻塞，见 #3 和 #8）。

**下一步**: 按 AutoRun Architecture Extension Loop，进入 TDD RED tests plan — 以 Phase 1 manifest foundation 测试（M01-M06）为起点。

---

## 9. Implementation Notes（占位——实现阶段填写）

- 实际变更文件清单
- 回退记录
- 设计偏离
- Upgrade notes

---

## 10. 参考

- [UNIFIED_RUNTIME_FLOW_CONTRACT](../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)
- [ENGINEERING_WORKFLOW](../dev/ENGINEERING_WORKFLOW.md)
- [SKILL_SYSTEM_SDD](SKILL_SYSTEM_SDD.md) — 当前 skill 系统 SDD
- [skill-system-architecture](skill-system-architecture.md) — 当前架构文档
- [skill-model-owned-selection-hardening](skill-model-owned-selection-hardening.md) — **Plan 2 hardening plan (SUPERSEDED — Plan 2 standalone rejected; metadata retained as Plan 3 foundation)**
- [RuntimeDecisionFrame](../../agent/runtime_decision_frame.py) — skill.select / skill.apply branch points
- 002 当前状态: `docs/PROJECT_STATUS.md`
- 002 进度历史: `docs/PROGRESS_LEDGER.md`
