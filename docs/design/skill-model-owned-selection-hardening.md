# Skill Model-Owned Selection Hardening — Scope / SDD / TDD Plan

**日期**: 2026-05-30
**状态**: design — SDD/TDD plan，不包含 production code 实现
**目标**: 定义 REAL-EVIDENCE-002（Skill Selection）从 `questionable` 升级到 `credible` 的 scope、设计意图和测试计划

---

## 0. 问题陈述

REAL-EVIDENCE-002 当前状态为 `questionable`，根因：

> Skill selection 依赖确定性 keyword fallback（`select_skill_for_real_provider()`），
> 而非模型自主选择（model-owned selection）。模型没有机会决定"是否选择 skill"和
> "选择哪个 skill"——这个决定发生在 turn-end hook 中，在模型输出之后，基于用户
> 输入做关键词匹配。

具体证据链：
- `agent/loop.py:492-494`：turn-end hook 中调用 `select_skill_for_real_provider(last_user, _visible)`
- `agent/skill_selection.py`：确定性 name/tags/description 词匹配（权重 3/2/1）
- `agent/runtime_decision_frame.py:105-119`：`skill.select` branch point 标 `PARTIAL`，why_partial 写明"真实模型路径尚未验证 SKILL_SELECT dispatch 是否被模型 tool call 触发；auto-select 是 demo 机制"
- `SkillSelector`（`agent/skill_system/selector.py`）提供了更完整的评分和歧义检测，但**从未接入生产路径**

---

## 1. Current Path 分析

### 1.1 现有两条路径（都非 model-owned）

```
Path A (fake provider):  turn-end hook → 无条件选择第一个可见 skill → model_decision_metadata → SKILL_SELECT dispatch
Path B (real provider):  turn-end hook → select_skill_for_real_provider(user_input, visible_skills) → keyword matching → model_decision_metadata 或 None → SKILL_SELECT dispatch
```

两条路径都**不经过模型决策**：
- fake：完全自动，模型不参与
- real：基于用户原始输入（`last_user`）做字符串匹配，模型不参与

### 1.2 核心时序问题

```
当前时序：
  user_input → model responds (text/tool_use) → turn-end hook → keyword match → SKILL_SELECT dispatch

model-owned 目标时序：
  user_input → model sees SKILL_SELECT as an available tool → model decides to call it (or not) → structured tool_use → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → SkillSelectHandler → result
```

关键区别：model-owned 路径中，SKILL_SELECT 发生在**模型输出阶段**（模型的 tool_use），不是 turn-end hook 的 post-hoc 分类。

### 1.3 当前代码路径涉及文件

| 文件 | 角色 | 当前行为 |
|------|------|---------|
| `agent/loop.py:430-510` | turn-end hook SKILL_SELECT dispatch | 构造 payload → route via dispatcher |
| `agent/skill_selection.py` | keyword matching fallback | 确定性字符串匹配 |
| `agent/skill_system/selector.py` | 未使用的 SkillSelector | 更完善评分+歧义检测，从未接入 |
| `agent/core.py:248-295` | `_update_active_skill_from_dispatcher()` | post-loop 从 action_log 提取结果 |
| `agent/core.py:335-369` | `refresh_runtime_system_prompt()` | 注入 active_skill body 到 system prompt |
| `agent/runtime_integration/skill_action.py` | SkillRuntimeActionHandler | 校验+加载+返回 result |
| `agent/runtime_decision_frame.py:105-119` | skill.select/skill.apply branch points | 标 PARTIAL |

---

## 2. Target Path 定义

### 2.1 设计原则

1. **SKILL_SELECT 作为模型可见工具**：注册到 `get_model_visible_tools()`，让模型看到 SKILL_SELECT 的 tool schema（含 name、description、input_schema）
2. **模型自主决定调用**：模型根据 system prompt 中的 skill 列表和当前对话上下文，自主输出 `tool_use(name="SKILL_SELECT", input={...})`
3. **走标准 tool mediation 路径**：结构化 tool_use → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → SkillRuntimeActionHandler → TOOL_RESULT → result 回流入 conversation context
4. **keyword fallback 降级为兜底**：仅在模型不调用 SKILL_SELECT 时，turn-end hook 仍做 keyword matching（保持向后兼容）
5. **与 RuntimeDecisionFrame 集成**：`skill.select` branch point 反映真实的 model-owned→mediation→handler 路径

### 2.2 目标数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Model-Owned Selection Flow                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ① model-visible tools 包含 SKILL_SELECT                            │
│     ┌──────────────────────────────────────────┐                    │
│     │ name: "SKILL_SELECT"                      │                    │
│     │ description: "选择一个 Skill 来激活..."     │                    │
│     │ input_schema: {                            │                    │
│     │   skill_id: string (required)              │                    │
│     │   reason: string (optional)                │                    │
│     │ }                                          │                    │
│     └──────────────────────────────────────────┘                    │
│                                                                      │
│  ② 模型输出 structured tool_use                                      │
│     tool_use(name="SKILL_SELECT", input={"skill_id": "demo-note"})  │
│                                                                      │
│  ③ ToolRuntimeMediator 中介                                           │
│     → TOOL_GATE (skill_allowed_tools 约束)                           │
│     → TOOL_INVOKE (execute_single_tool → SkillSelectHandler)         │
│     → TOOL_RESULT (skill body loaded → conversation context)         │
│                                                                      │
│  ④ result 注入 model context                                         │
│     "Skill 'demo-note-maker' activated. [Active Skill Instructions]" │
│     作为 tool_result 回到 messages                                   │
│                                                                      │
│  ⑤ (降级路径) 模型未调用时 → turn-end keyword fallback                 │
│     保持现有 select_skill_for_real_provider() 行为                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 需要修改的组件

| 组件 | 变更 | 风险 |
|------|------|------|
| `agent/skill_system/skill_tool.py` (新文件) | 注册 SKILL_SELECT 为可调用工具，input 解析 | low — 独立模块 |
| `agent/skill_system/registry.py` | 新增 `build_skill_select_tool_schema()` 方法 | low — 只读 registry |
| `agent/skill_system/selector.py` | 接入 `SkillSelector` 作为 handler 核心选择逻辑 | low — 已存在、已测试、从未使用 |
| `agent/runtime_integration/skill_action.py` | 新增 `SkillSelectToolHandler`（工具调用 handler） | medium — 与现有 SkillRuntimeActionHandler 共存 |
| `agent/core.py` | `get_model_visible_tools()` 中加入 SKILL_SELECT schema | low — 已有类似注册模式 |
| `agent/loop.py:430-510` | keyword fallback 前检查模型是否已调用 SKILL_SELECT | medium — 需要判断"本 turn 模型是否已选 skill" |
| `agent/tool_registry.py` | 注册 SKILL_SELECT 工具 | low — 已有 register_tool 模式 |

### 2.4 不修改的组件

- `agent/skill_selection.py` — keyword fallback 保留不动
- `agent/skill_system/loader.py` — body 加载逻辑不变
- `agent/skill_system/descriptor.py` — SkillDescriptor 不变
- `agent/runtime_decision_frame.py` — branch point 定义不变（status 升级通过 evidence 触发）
- 现有 SkillRuntimeActionHandler — 保留，作为 turn-end hook 路径的 handler

---

## 3. Non-Goals（明确不做）

1. **不做 LLM-based skill 推荐**：不调用额外 LLM 来选 skill
2. **不修改 SkillDescriptor schema**：不新增模型选择所需的 metadata 字段
3. **不改变 body 加载逻辑**：SkillLoader.load_body() 保持不变
4. **不改变 _active_skill 跨 turn 生命周期**：`_update_active_skill_from_dispatcher()` 保持不变
5. **不改变 skill.apply（allowed_tools 约束）逻辑**：这只是 skill.select 的设计文档，apply 由 003 负责
6. **不做 multi-skill 并发激活**：一次只激活一个 skill
7. **不修改 003/006/007/008**：严格隔离
8. **不直接实现 production code**：本文档是 SDD/TDD plan，实现留到下一阶段

---

## 4. RED Tests（实现前必写，预期 FAIL）

### 4.1 SKILL_SELECT 工具注册测试（R01-R04）

```python
# tests/unit/test_skill_select_tool.py

def test_skill_select_is_registered_in_tool_registry():
    """R01: SKILL_SELECT 应在 TOOL_REGISTRY 中注册。"""
    from agent.tool_registry import TOOL_REGISTRY
    assert "SKILL_SELECT" in TOOL_REGISTRY

def test_skill_select_has_valid_schema():
    """R02: SKILL_SELECT schema 包含 name/description/input_schema。"""
    entry = TOOL_REGISTRY["SKILL_SELECT"]
    assert "name" in entry
    assert "description" in entry
    assert "input_schema" in entry
    assert "skill_id" in entry["input_schema"]["properties"]

def test_skill_select_not_in_model_visible_tools_yet():
    """R03: 预期 FAIL — 证明 SKILL_SELECT 尚未加入 model-visible tools。"""
    tools = get_model_visible_tools()
    tool_names = [t["name"] for t in tools]
    assert "SKILL_SELECT" not in tool_names  # RED: 当前不存在

def test_skill_select_func_exists_and_callable():
    """R04: SKILL_SELECT 的 func 应为可调用对象。"""
    entry = TOOL_REGISTRY["SKILL_SELECT"]
    assert callable(entry["func"])
```

### 4.2 Model-Owned 路径证据测试（R05-R08）

```python
# tests/runtime_integration/test_skill_model_owned_selection.py

def test_model_tool_use_skill_select_triggers_tool_gate():
    """R05: 预期 FAIL — 模型 tool_use SKILL_SELECT 应走 TOOL_GATE。"""
    # 用 FakeProvider scripted response 模拟模型输出 tool_use(name="SKILL_SELECT")
    # 验证 TOOL_GATE evidence 产生且 tool_name="SKILL_SELECT"
    ...

def test_skill_select_tool_invoke_produces_correct_result():
    """R06: 预期 FAIL — TOOL_INVOKE SKILL_SELECT 应返回 skill body。"""
    ...

def test_skill_select_tool_result_flows_to_conversation_context():
    """R07: 预期 FAIL — TOOL_RESULT 应包含 skill body 预览，回流入 messages。"""
    ...

def test_model_owned_selection_sets_active_skill():
    """R08: 预期 FAIL — 模型自主选择后，_active_skill 应被更新。"""
    ...

def test_skill_select_via_tool_runtime_mediator_not_direct_call():
    """R09: 预期 FAIL — 验证不是 direct dispatcher.route() 调用。"""
    ...

def test_skill_select_tool_use_respects_allowed_tools_constraint():
    """R10: 预期 FAIL — disallowed skill 不应被 TOOL_GATE 放行。"""
    ...
```

### 4.3 模型行为验证测试（R11-R13）

```python
def test_model_sees_skill_select_in_tool_list():
    """R11: 预期 FAIL — get_model_visible_tools() 中应包含 SKILL_SELECT。"""
    tools = get_model_visible_tools()
    tool_names = [t["name"] for t in tools]
    assert "SKILL_SELECT" in tool_names  # RED: 证明 tool schema 已就位

def test_skill_select_schema_includes_available_skills_as_enum():
    """R12: 预期 FAIL — input_schema 应包含可选 skill_id 列表（enum constraint）。"""
    entry = TOOL_REGISTRY["SKILL_SELECT"]
    props = entry["input_schema"]["properties"]["skill_id"]
    assert "enum" in props  # RED: 模型只能选注册过的 skill

def test_disallowed_skill_not_in_enum():
    """R13: 预期 FAIL — hidden/disabled skill 不应出现在 enum 中。"""
    ...
```

### 4.4 Keyword Fallback 保留测试（R14-R16）

```python
def test_keyword_fallback_still_works_when_model_did_not_select():
    """R14: 模型未调 SKILL_SELECT → turn-end hook keyword fallback 仍生效。"""
    ...

def test_model_owned_takes_priority_over_keyword_fallback():
    """R15: 模型已调 SKILL_SELECT → turn-end hook 不覆盖模型决策。"""
    ...

def test_select_skill_for_real_provider_unchanged():
    """R16: select_skill_for_real_provider() 行为不变（回归保护）。"""
    # 复用现有 test_skill_selection_real_provider.py 的 15 个测试
    ...
```

### 4.5 Evidence Chain 完整性测试（R17-R20）

```python
def test_full_evidence_chain_model_owned_selection():
    """R17: 完整 evidence chain 闭合:
    SKILL_SELECT tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT
    → _active_skill → refresh_runtime_system_prompt → [Active Skill Instructions]
    """
    ...

def test_runtime_decision_frame_reflects_model_owned_provenance():
    """R18: skill.select branch point evidence 应反映 model-owned 路径。"""
    ...

def test_model_owned_selection_is_not_no_crash_pass():
    """R19: 正向断言：skill body 非空、selected_skill_id 正确、允许工具清单匹配。"""
    ...
```

---

## 5. GREEN Tests（实现后验证，预期 PASS）

### 5.1 回归保护

| 测试文件 | 预期测试数 | 验证内容 |
|---------|-----------|---------|
| `tests/runtime_integration/test_skill_selection_real_provider.py` | 15 (现有) | keyword fallback 行为不变 |
| `tests/test_skill_selector.py` | 12+ (现有) | SkillSelector 行为不变 |
| `tests/test_skill_dogfood.py` | 20+ (现有) | skill dogfood 路径不变 |
| `tests/test_skill_tool_binding.py` | 10 (现有) | allowed_tools 约束不变 |

### 5.2 新增验证

| 测试文件（新建） | 预期测试数 | 验证内容 |
|----------------|-----------|---------|
| `tests/unit/test_skill_select_tool.py` | 8 | SKILL_SELECT 注册、schema、func callable、enum 完整性 |
| `tests/runtime_integration/test_skill_model_owned_selection.py` | 15 | model-owned 全路径：tool_use → gate → invoke → result → context |
| `tests/runtime_integration/test_skill_selection_priority.py` | 6 | model-owned vs keyword fallback 优先级 |
| `tests/unit/test_skill_select_schema_dynamic.py` | 5 | schema enum 随 registry 动态更新、hidden/disabled 排除 |

---

## 6. Validation Plan

### 6.1 分层验证策略

| 层级 | 内容 | 通过标准 |
|------|------|---------|
| L1 (unit) | SKILL_SELECT 工具注册、schema 正确性、SkillSelector 集成 | 8+ tests PASS |
| L2 (contract) | dispatcher.route() level SKILL_SELECT 全路径（FakeProvider scripted tool_use） | 15+ tests PASS |
| L3 (runtime loop) | core.chat() → ToolRuntimeMediator → SKILL_SELECT E2E（FakeProvider） | 6+ tests PASS |
| L4 (real dogfood) | 真实 provider + 真实模型自主输出 tool_use SKILL_SELECT | 8+ assertions PASS |

### 6.2 Credibility 升级判定标准

从 `questionable` 升级到 `credible` 需要同时满足：

1. **L1-L3 全部 PASS**：代码路径正确，非 direct-call
2. **L4 real provider E2E**：真实模型**自主决定**调用 SKILL_SELECT tool（非 scripted response）
3. **Evidence chain 闭合**：tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → conversation context → _active_skill → system prompt
4. **正向断言**：skill body 非空、allowed_tools 正确、选中的 skill_id 匹配
5. **RuntimeDecisionFrame** skill.select branch point evidence 从 FAKE_LOCAL_USER_PATH 升级
6. **Keyword fallback 仍生效**：模型不选时回退到 keyword matching（向后兼容）

### 6.3 不能升级为 credible 的情况

| 情况 | 处理 |
|------|------|
| 只有 L1-L3 PASS 无 L4 | 标 `partial-credible`，注明"模型自主选择待 real provider 验证" |
| 模型从不调用 SKILL_SELECT（行为限制） | 标 `partial-credible`，注明"code path ready, model behavior pending"，keyword fallback 仍是事实主路径 |
| keyword fallback 行为被破坏 | 标 `regression`，不可升级 |

---

## 7. Risk / Stop Conditions

### 7.1 技术风险

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| 模型不理解和不会调用 SKILL_SELECT | medium | keyword fallback 兜底；model-owned 是"优先路径"非"唯一路径" |
| SKILL_SELECT tool schema 过大致 context budget 紧张 | low | schema ~200 tokens，barely measurable |
| 模型幻觉：选不存在的 skill_id | low | input_schema enum 约束 + handler 内校验 |
| skill body 注入 conversation context 后模型行为异常 | low | body 截断 2000 chars（已有）|
| tool_registry 和 skill_registry skill_id 不一致 | medium | skill_select_tool 的 enum 从 skill_registry 动态读取，不硬编码 |

### 7.2 过程风险

| 风险 | 处理 |
|------|------|
| 实现侵入 003/006/007/008 | 严格 scope 控制，只改 skill.select 路径 |
| keyword fallback 行为被不小心破坏 | 15 个现有 regression tests 保护 |
| tool_registry.py 添加依赖导致循环 import | SKILL_SELECT func 延迟 import，不直接在 tool_registry.py 中导入 |

### 7.3 Hard Stops

- 实现涉及 `config/config.yaml` 或 `.env` 读写 → hard stop
- 实现改变 RuntimeDecisionFrame branch point 数量或定义 → hard stop（需要 plan-eng-review）
- 实现引入新的 runtime flow（非现有 ToolRuntimeMediator 路径）→ hard stop
- Keyword fallback 被移除或功能退化 → hard stop
- 现有测试（15 skill selection + 10 skill tool binding + 12 skill selector）出现 regression → hard stop

---

## 8. 关键设计决策（待实现阶段确认）

### D1: Model-Owned Selection 的实现形式

**推荐方案 B**：将 SKILL_SELECT 注册为 TOOL_REGISTRY 中的标准工具，让模型通过 `tool_use` block 调用。

- **方案 A**: 通过 system prompt 中的 `<skills>` 标签 instruct 模型输出特定格式
- **方案 B**: 注册 SKILL_SELECT 为 TOOL_REGISTRY 中的标准工具

方案 B 的理由：
- 复用现有的 ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT pipeline
- 与 003（allowed_tools）的集成更自然：模型只能选 allowed_tools 中允许的 skill
- tool_use 是结构化的，比文本解析可靠
- 已有 `agent/runtime_integration/tool_result_feedback.py` 处理 tool result 注入 conversation context 的模式
- skill body 作为 TOOL_RESULT 回到 messages，模型看到 "[Active Skill Instructions]" section

### D2: SkillSelector vs select_skill_for_real_provider

**推荐方案 A**：将 SkillSelector（`agent/skill_system/selector.py`）接入 SKILL_SELECT tool handler，select_skill_for_real_provider 保留为 keyword fallback。

- `SkillSelector` 已有的能力：name 精确匹配、关键词评分、歧义检测、deprecated 惩罚、confidence threshold
- `select_skill_for_real_provider()`：更简单的 keyword matching，有中文子串 fallback
- 两者场景不同：SkillSelector 用于模型传入 skill_id 时的匹配和校验；keyword fallback 用于模型不调用时从 user_input 推断

### D3: SKILL_SELECT 的 input_schema 设计

```python
TOOL_REGISTRY["SKILL_SELECT"] = {
    "name": "SKILL_SELECT",
    "description": (
        "选择一个可用的 Skill 来激活。激活后，Skill 的指令将注入系统提示，"
        "Skill 声明的工具列表将约束后续可用的工具。"
        "如果你不需要使用特定 Skill，不要调用此工具。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "要激活的 Skill 名称。",
                "enum": [...]  # 从 skill_registry.list_visible() 动态生成
            },
            "reason": {
                "type": "string",
                "description": "选择此 Skill 的原因（可选）。"
            }
        },
        "required": ["skill_id"]
    },
    "func": _skill_select_tool_func,  # 通过 dispatcher 路由到 SkillRuntimeActionHandler
}
```

### D4: 优先级规则

```
1. 模型 tool_use("SKILL_SELECT", ...) → model-owned path → 不走 keyword fallback
2. 模型未调用 SKILL_SELECT → turn-end hook keyword fallback (现有行为)
3. 用户显式 /skill <name> → 直接激活（CLI shortcut，现有行为）
```

优先级 1 的判断方式：检查本 turn 的 tool_use 中是否包含 `name="SKILL_SELECT"` 的调用。

### D5: 与 RuntimeDecisionFrame 的集成

`skill.select` branch point 的 `decision_meta` 在 model-owned path 就位后更新：

```python
"skill.select": BranchPointState(
    branch_id="skill.select",
    status=BranchPointStatus.PARTIAL,  # → CODE_PATH_COMPLETE (model-owned path ready)
    evidence_level=EvidenceLevel.FAKE_LOCAL_USER_PATH,  # → REAL_API_SMOKE (real model E2E)
    decision_meta={
        "why_partial": "model-owned SKILL_SELECT tool path code complete; "
                       "等待真实模型自主输出 tool_use SKILL_SELECT 的 real dogfood 证据; "
                       "keyword fallback 作为降级路径保留",
    },
),
```

---

## 9. 回答 8 个问题

### Q1: 当前 skill selection 走什么路径？

**A**: 两条路径都在 turn-end hook（`agent/loop.py:430-510`），模型已完成响应后才触发：
- fake provider: 无条件选择第一个可见 skill
- real provider: `select_skill_for_real_provider()` 对 `last_user` 做 keyword matching（name 权重 3 / tags 权重 2 / description 权重 1 + 中文子串 fallback）

两条路径都不经过模型决策。`SkillSelector`（`agent/skill_system/selector.py`）有更完善的评分逻辑但从未接入生产路径。

### Q2: keyword fallback 何时触发？

**A**: 每次 turn-end hook 都触发（每个 turn 末尾），但只在 real provider 路径下（`provider_kind != "fake"`）且 `_visible` 和 `last_user` 均非空时执行。匹配失败时返回 None，handler 返回 `no_suitable_skill`。在 model-owned path 就位后，keyword fallback 仅在模型本 turn 未调用 SKILL_SELECT 时触发。

### Q3: "model-owned selection" 应该是什么形式？

**A**: 将 SKILL_SELECT 注册为 TOOL_REGISTRY 中的标准工具，出现在 `get_model_visible_tools()` 返回的 tool list 中。模型在 system prompt 中看到可用的 skill 列表（已有），并看到 SKILL_SELECT tool 的 schema（新增）。模型**自主决定**是否调用、何时调用、选择哪个 skill。调用后走标准 ToolRuntimeMediator pipeline。

这是现有 003/006/007 已验证的同一个 mediation pattern：tool_use → ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT。不引入新 runtime flow。

### Q4: 如何与 RuntimeDecisionFrame 的 skill.select branch point 集成？

**A**: `skill.select` branch point 的 `execution_path` 更新为反映 model-owned → mediation → handler 路径。`evidence_level` 从 FAKE_LOCAL_USER_PATH 逐步升级（code path complete → real API smoke → production path）。不修改 branch point ID 和数量。不修改 `skill.apply` branch point（那是 003 的范围）。

### Q5: 模型自主选择的 skill 如何绑定 allowed_tools？

**A**: 模型选择的 skill_id → handler 从 SkillRegistry 加载 descriptor → descriptor.allowed_tools 作为 skill_allowed_tools 传递给 ToolRuntimeMediator（已有逻辑在 `core.py:1312-1322`）。后续 tool_use 受 TOOL_GATE 的 skill_allowed_tools 约束（003 已验证的机制）。模型选择了 skill A 后，后续 tools 被约束在 skill A 的 allowed_tools 范围内——这是一致的"模型决定 → runtime 执行约束"闭环。

### Q6: model-owned 和 keyword fallback 如何共存？

**A**: 优先级链：
1. 模型本 turn 调用了 SKILL_SELECT tool → model-owned path 生效 → keyword fallback 本轮**不触发**
2. 模型本 turn 未调用 SKILL_SELECT → keyword fallback 触发（现有行为，向后兼容）

判断模型是否调用了 SKILL_SELECT 的方式：检查本 turn 的 `ToolRuntimeMediator` 是否有 `tool_name="SKILL_SELECT"` 的 TOOL_INVOKE evidence，或检查 `_active_skill` 是否在本 turn 被更新。

两个路径共享同一个 `SkillRuntimeActionHandler`（或新增的 `SkillSelectToolHandler`），共享同一个 `_update_active_skill_from_dispatcher()` 结果消费逻辑。

### Q7: 升级到 credible 需要什么证据？

**A**: 见 Section 6.2。关键门槛是 L4 real provider E2E：真实模型**自主输出** `tool_use(name="SKILL_SELECT", input={"skill_id": "demo-note-maker"})`，完整 evidence chain 闭合（7 种 event types：tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → _active_skill → system prompt injection → model response with skill context）。

如果真实模型从不主动调用 SKILL_SELECT（模型行为限制），即使 code path 就位也只能标 `partial-credible`，不能标 `credible`。

### Q8: 需要多少 RED/GREEN 测试？

**A**: 预估：
- RED: 18-22 个（R01-R20），分 4 组：工具注册 (4)、model-owned 路径 (6)、模型行为验证 (3)、keyword fallback 保留 (3)、evidence chain (4)
- GREEN: 新增 28-34 个 + 现有 37+ 个回归保护 = 65+ 个总测试
- 另需 L4 real dogfood 脚本（类似 `scripts/real_evidence_006_subagent_real_provider.py` 的模式）验证真实模型行为

---

## 10. 文件变更预测

| 文件 | 变更类型 | 估计行数 | 说明 |
|------|---------|---------|------|
| `agent/skill_system/skill_tool.py` | **新建** | ~120 lines | SKILL_SELECT tool func + schema builder + enum 动态生成 |
| `agent/tool_registry.py` | 修改 | +3 lines | 注册 SKILL_SELECT 工具（延迟 import） |
| `agent/core.py` | 修改 | +5 lines | `get_model_visible_tools()` 中加入 SKILL_SELECT |
| `agent/runtime_integration/skill_action.py` | 修改 | +40 lines | 新增 SkillSelectToolHandler（或扩展现有 handler） |
| `agent/loop.py` | 修改 | +15 lines | keyword fallback 前检查模型是否已选 skill |
| `tests/unit/test_skill_select_tool.py` | **新建** | ~150 lines | 8 个 unit tests |
| `tests/runtime_integration/test_skill_model_owned_selection.py` | **新建** | ~350 lines | 15 个 runtime integration tests |
| `tests/runtime_integration/test_skill_selection_priority.py` | **新建** | ~180 lines | 6 个优先级 tests |
| `tests/unit/test_skill_select_schema_dynamic.py` | **新建** | ~120 lines | 5 个 schema tests |
| `scripts/real_evidence_002_skill_model_selection.py` | **新建** | ~300 lines | L4 real dogfood 验证脚本 |

总计：~3 个 production 文件新建/修改（~180 lines）+ ~4 个测试文件新建（~800 lines）+ 1 个验证脚本（~300 lines）。
