# Memory Next Stage Architecture Plan

**创建日期**: 2026-05-10
**性质**: 纯架构设计文档，不包含实现代码
**范围**: Agent-suggested memory + External MemoryProvider adapter 的统一架构设计
**状态**: Phase 2 已完成，Phase 3 待设计

---

## 1. 当前 Memory v1 基线

### 1.1 已完成的模块

Memory Kernel v1 已形成完整的最小闭环：

```
user_text
  → DeterministicMemoryPolicy.decide()
    → RETAIN / UPDATE / FORGET / REJECT / NO_OP / CLARIFY
  → MemoryConfirmationRequest (5 种 choice)
  → MemoryRuntime.evaluate_user_text() → CONFIRMATION_REQUIRED
  → core.py CONFIRMATION_REQUIRED 分支 → pending_user_input_request
  → 用户选择 (1-5 或自由文本)
  → handle_memory_confirmation_reply()
    → parse → resolve_confirmation → MemoryOperationIntent → MemoryAuditSummary
    → MemoryStore.apply_operation_intent() → MemoryRecord
  → MemoryRuntime.snapshot_for_prompt()
    → build_memory_snapshot_from_store() → MemorySnapshot
    → build_memory_section() → build_system_prompt()
```

### 1.2 已具备的能力

| 能力 | 状态 | 关键文件 |
|------|------|----------|
| user-initiated explicit memory (remember/记住) | ✅ | `memory_policy.py` |
| 两阶段确认 (evaluate → CONFIRMATION_REQUIRED → resolve) | ✅ | `memory_runtime.py` |
| 5 种 choice: accept / edit / session_only / reject / other | ✅ | `memory_confirmation.py` |
| 复用 awaiting_user_input + pending_user_input_request | ✅ | `memory_interaction.py` |
| approved memory snapshot → prompt | ✅ | `memory_snapshot_generator.py` |
| sensitive memory blocking (secret/password/token) | ✅ | `memory_policy.py:_classify_sensitivity` |
| prompt injection 拦截 | ✅ | `memory_policy.py:_looks_like_prompt_injection` |
| observer evidence (confirmation.* 事件) | ✅ | `confirm_handlers.py:_emit_confirmation_observer_event` |
| MemoryRecord 预留字段 (memory_type/source_type/approval_status/metadata) | ✅ | `memory_store.py` |
| MemoryCandidate.metadata 通用扩展点 | ✅ | `memory_contracts.py` |

### 1.3 明确未实现

| 未实现项 | 说明 |
|----------|------|
| agent-suggested memory | 只有 user-initiated explicit retain |
| external MemoryProvider | 只有 fake/local InMemoryMemoryStore |
| persistence | store 是进程内 dict，重启丢失 |
| semantic recall / vector DB / embedding | 不做，不在 scope |
| reflection / consolidation | 不做，不在 scope |
| episodic / procedural memory | MemoryRecord 预留字段但未使用 |
| 真实 recall/retrieval | snapshot 只是 deterministic list + filter |
| TUI 按钮/菜单渲染 | 文本选项列表，用户输入数字 |
| checkpoint schema 变更 | TaskState 字段未变 |

### 1.4 关键边界约束（不可破坏）

这些约束来自 Memory v1 的已有设计，后续任何扩展都必须遵守：

1. **不新增 pending status** — 复用 `awaiting_user_input` + `pending_user_input_request`，通过 `awaiting_kind` 区分
2. **不改 checkpoint schema** — `pending_user_input_request` 是 `dict[str, Any]`，新增 `_` 前缀 key 不需要 schema migration
3. **prompt_builder 只消费 MemorySnapshot** — 不直接读 store，不做 retrieval decision
4. **policy → confirmation → operation → audit → store 链不可跳过** — 任何来源的 memory 必须走完整治理链
5. **外部 provider 不能绕过本地 policy** — 来自 `docs/MEMORY_ARCHITECTURE.md` 安全原则 #7
6. **不读取 .env** — provider key 通过 local config 机制，不展开 env secret

---

## 2. Agent-suggested Memory 设计

### 2.1 核心原则

> agent-suggested memory **不是自动写入 memory**。
> 它只是自动生成 MemoryCandidate，然后**必须走用户确认**。

Agent 的建议权仅限于"提出候选"，永远不能代替用户做 retain/update/forget 决定。

### 2.2 触发时机

Agent **只能**在以下时机建议记忆：

| 时机 | 说明 | 优先级 |
|------|------|--------|
| **task boundary** | 当前 plan 的所有 step 执行完毕、用户确认 task done 时 | 最高 |
| **coding session 结束** | 用户说"今天就到这里"或类似结束信号时 | 高 |
| **用户显式触发** | 用户说"帮我总结一下这次的经验"时 | 按需 |
| **重复偏好被检测到** | 同一偏好被用户显式声明 ≥ 3 次时（跨会话或同会话） | 中 |

Agent **不能**在以下时机建议：

- 任务执行中途（step 之间）
- 工具调用返回后立即建议
- 模型每次 response 后都建议
- 用户正处于确认流程时（plan/step/tool/memory confirmation）
- 错误/异常发生后立即建议（除非是 bug fix lesson）

### 2.3 候选来源

| 来源 | 示例 | 对应 memory_type |
|------|------|-----------------|
| 当前对话中的显式偏好 | "我喜欢用 pytest 而不是 unittest" | semantic |
| coding session 结果 | "这次重构花了 2 小时，因为要先理解旧代码" | episodic |
| 重复用户偏好 (≥3 次) | 用户连续 3 次要求"不要写 docstring" | semantic |
| project rule | "这个项目禁止使用 any type" | procedural |
| bug fix lesson | "上次 null pointer 是因为忘记检查 Optional" | episodic |
| architecture decision | "我们选了 Protocol 而不是 ABC 因为更轻量" | semantic |

### 2.4 分类体系

沿用 MemoryRecord 已预留的 `memory_type` 字段：

| memory_type | 含义 | 典型内容 | 稳定性 |
|-------------|------|----------|--------|
| `semantic` | 事实、偏好、知识 | "用户喜欢 pytest"、"项目用 Python 3.12" | 高 |
| `episodic` | 经验、事件、决策 | "上次重构花了 2h，因为旧代码耦合重" | 中 |
| `procedural` | 规则、流程、约束 | "修改 checkpoint 前必须先跑边界测试" | 高 |

### 2.5 反打扰机制

agent-suggested memory 最大的风险不是技术问题，而是**骚扰用户**。以下机制全部是硬约束：

| 机制 | 规则 | 实现方式 |
|------|------|----------|
| **频率限制** | 每 session 最多 3 次 agent-suggested confirmation | runtime 内计数器 |
| **confidence threshold** | 确定性 heuristic 的 confidence 必须 ≥ 某个阈值 | `MemoryCandidate.confidence` 字段已有 (0.0-1.0) |
| **去重** | 与已有 store 中 content 高度相似的 candidate 跳过 | 基于 content hash / 编辑距离 |
| **task boundary only** | 不在任务中途弹出 | 触发时机约束（见 §2.2） |
| **"不再询问此类"** | 用户可对某类 suggestion 静默 | 用户偏好记录在 store 中，`source_type="user_preference"` |
| **静默降级** | 低于阈值的 candidate 写入 observer event 但不展示 | `memory.agent_suggested_candidate_skipped` 事件 |

### 2.6 复用现有 Memory Interactive Confirmation

agent-suggested memory 不创建新的确认机制，完全复用现有两阶段流程：

```
Agent-suggested flow:
  1. heuristic/deterministic candidate generator → MemoryCandidate
     - source_type = "agent_suggested" (在 metadata 中)
     - memory_type = semantic/episodic/procedural
     - confidence = 0.6-0.9 (根据 heuristic 强度)
  2. MemoryPolicy.decide() 评估 candidate
     - 对 agent_suggested candidate，policy 返回 RETAIN + requires_user_confirmation=True
  3. MemoryConfirmationRequest 构造
     - question 文案区别于 user_initiated：
       "我注意到你多次提到喜欢用 pytest，要长期记住这个偏好吗？"
  4. 用户确认：复用现有 5 种 choice
     - ACCEPT / EDIT_AND_ACCEPT / SESSION_ONLY / REJECT / OTHER
  5. resolve_confirmation → operation intent → audit → store
     - 与 user_initiated 完全一致
```

**与 user_initiated 的差异仅在于**：
- `source_type` 字段值：`"agent_suggested"` vs `"explicit_user_request"`
- confirmation question 的文案模板不同
- candidate 生成方式不同（heuristic vs 显式命令解析）

### 2.7 敏感信息与 Prompt Injection 防护

agent-suggested candidate 与 user_initiated candidate **共享同一套 policy 安全检查**：

- `_classify_sensitivity()`: 检测 secret/password/token/key 等关键词
- `_looks_like_prompt_injection()`: 检测 prompt injection pattern
- 敏感 candidate → `MemoryDecisionType.REJECT`，不进入 confirmation
- 被拒绝的 candidate 仅记录 `memory.agent_suggestion_blocked` observer 事件

额外防护：
- agent-suggested candidate **永远不能**绕过 `requires_user_confirmation=True`
- 即使 confidence=1.0，也**不能**自动 accept

### 2.8 第一阶段最小实现

Phase 2（Phase 1 是 planning only）的最小实现范围：

```
agent/memory_agent_suggested.py  (~150 行)

class AgentSuggestedCandidateGenerator:
    def generate_candidates(
        self,
        conversation_summary: str,      # 当前会话摘要
        existing_store: MemoryStoreProtocol,  # 去重参考
        user_preferences: dict,         # "不再询问此类" 偏好
    ) -> list[MemoryCandidate]:
        """确定性 heuristic 生成候选，不使用 LLM"""
        ...
```

heuristic 规则（确定性，不需要 LLM）：
1. **重复偏好检测**：同一模式在 conversation_summary 中出现 ≥ 3 次 → semantic candidate
2. **显式 project rule**：用户说"这个项目规定/禁止/必须..." → procedural candidate
3. **bug fix pattern**：用户说"上次就是因为...这次要注意..." → episodic candidate
4. **架构决策**：用户说"我们选了/决定用..." → semantic candidate

### 2.9 绝不能现在做

| 禁止项 | 原因 |
|--------|------|
| LLM 自动提取 candidate | 引入非确定性、成本、延迟、prompt injection 风险 |
| 自动 accept（跳过 confirmation） | 违反核心安全原则 |
| 在任务中途弹出 suggestion | 骚扰用户 |
| 基于工具调用结果自动生成 candidate | 工具结果可能含敏感信息 |
| episodic memory 自动时间线 | 需要 reflection/consolidation，是 Phase 5 的内容 |
| procedural memory 自动执行 | Skill 系统负责，不是 Memory 的职责 |
| 无上限的 suggestion | 用户会关闭整个功能 |

---

## 3. External MemoryProvider Adapter 设计

### 3.1 核心原则

> local MemoryRuntime / MemoryPolicy 是 authority。
> external provider 只是 storage / retrieval backend。
> external recall 是 untrusted input。
> external write 不能绕过 local confirmation。

### 3.2 Provider Protocol

```python
# agent/memory_provider.py (Phase 3 新增)

class MemoryProviderHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"

@dataclass(frozen=True, slots=True)
class ProviderRecallResult:
    """外部 provider 的 recall 原始结果，未经本地 policy 处理。"""
    candidates: tuple[MemoryCandidate, ...]
    provider_name: str
    query_context: str
    item_count: int
    latency_ms: int | None = None

@dataclass(frozen=True, slots=True)
class ProviderWriteRequest:
    """本地已确认的 record，请求写入外部 provider。"""
    record: MemoryRecord
    provider_name: str
    operation: str  # "retain" | "update" | "delete"

@dataclass(frozen=True, slots=True)
class ProviderWriteResult:
    success: bool
    provider_name: str
    provider_record_id: str | None = None
    error_message: str | None = None

class MemoryProviderProtocol(Protocol):
    """外部 MemoryProvider 的最小协议。

    这不是 store 的替代品，而是 store 的 optional backend。
    provider 不接触 policy、confirmation、audit、runtime。
    """

    def recall(
        self,
        query_context: str,
        *,
        scope: MemoryScope | None = None,
        max_items: int = 10,
    ) -> ProviderRecallResult:
        """从外部 provider 召回候选 memory。"""

    def write(self, request: ProviderWriteRequest) -> ProviderWriteResult:
        """将本地已确认的 record 写入外部 provider。"""

    def delete(self, record_id: str) -> ProviderWriteResult:
        """从外部 provider 删除 record。"""

    def health(self) -> MemoryProviderHealth:
        """检查 provider 可用性。"""
```

### 3.3 本地 MemoryStore 与外部 MemoryProvider 的分工

| 职责 | MemoryStore (本地) | MemoryProvider (外部) |
|------|-------------------|----------------------|
| policy decision | ✅ authority | ❌ 不参与 |
| user confirmation | ✅ authority | ❌ 不参与 |
| operation audit | ✅ authority | ❌ 不参与 |
| prompt snapshot | ✅ 本地 records 直接可用 | ❌ 需过 sanitizer |
| 持久化 | ✅ 本地 store（未来可接 SQLite/JSON） | ✅ optional backend |
| 跨会话 recall | ✅ 本地 store（同进程） | ✅ 跨设备/跨进程 |
| 语义搜索 | ❌ 不做 | ✅ 未来可接 |
| 数据所有权 | ✅ 用户完全控制 | ⚠️ 取决于 provider |

**关键设计：双写模型**

```
confirmed MemoryRecord
  → MemoryStore.apply_operation_intent()  ← 本地 authoritative write
  → MemoryProvider.write(record)          ← 外部 optional write (best-effort)
```

本地 store write 是 authoritative，provider write 是 best-effort。
provider write 失败不影响本地 store 状态，不阻塞用户操作。

### 3.4 Mem0 / LangChain / Zep 接在哪一层

```
┌─────────────────────────────────────────────────────┐
│ MemoryRuntime (policy + confirmation + audit)       │
│                                                     │
│  MemoryStoreProtocol (本地 authoritative)           │
│    ├── InMemoryMemoryStore (当前)                    │
│    └── (未来) SQLiteMemoryStore / JSONFileStore      │
│                                                     │
│  MemoryProviderProtocol (外部 optional backend)     │
│    ├── FakeMemoryProvider (测试)                     │
│    ├── Mem0Adapter (implement MemoryProviderProtocol)│
│    ├── LangChainAdapter                               │
│    ├── ZepAdapter                                     │
│    └── CustomHttpProvider                             │
└─────────────────────────────────────────────────────┘
```

所有外部 provider 都通过实现 `MemoryProviderProtocol` 接入，**不进 core.py、不进 memory_runtime.py、不进 policy**。每个 provider adapter 是独立模块，可以单独测试、单独配置、单独开关。

### 3.5 外部 Provider 返回的 Memory 能不能直接进 Prompt

**不能。** 必须经过以下管道：

```
ProviderRecallResult (untrusted)
  → MemoryProviderSanitizer.sanitize()
    → 截断过长内容
    → 敏感词过滤
    → scope 校验
    → prompt injection 检测
  → MemoryCandidate (source_type="imported")
  → MemoryPolicy.decide() → 评估是否需要确认
  → 若需确认 → MemoryConfirmationRequest → 用户确认 → approved
  → 若无需确认（低风险 imported memory） → 标记为 imported_auto_approved
  → MemorySnapshot → prompt_builder
```

关键约束：
- 外部 recall 的 raw 内容**永远不直接**进入 prompt
- 外部 recall 的每条 candidate 必须标记 `source="external_provider"` 和 `provider_name`
- 外部 recall 结果默认 `sensitivity=MEDIUM`（比本地 LOW 更保守）

### 3.6 外部 Provider 写入是否必须走本地 Confirmation

**必须。** 流程：

```
外部 provider 想写入的触发方式：
  A. agent-suggested candidate → 用户确认 → 本地 store + 外部 provider
  B. user-initiated explicit retain → 用户确认 → 本地 store + 外部 provider
  C. external recall imported candidate → 用户确认 → 本地 store + 外部 provider

不存在：
  D. external provider 直接写入本地 store  ← 不允许
  E. external provider 绕过确认写入       ← 不允许
```

### 3.7 Forget / Update / Delete 同步

**策略：Local-first，best-effort sync**

```
Forget 流程：
  1. 用户触发 forget
  2. MemoryPolicy.decide() → FORGET
  3. MemoryConfirmationRequest → 用户确认
  4. MemoryStore.apply_operation_intent(FORGET) → 本地删除
  5. MemoryProvider.delete(record_id) → best-effort 外部删除
     - 成功：memory.external_delete_completed
     - 失败：memory.external_delete_failed (不阻塞，记录 observer event)

Update 流程：
  1. 用户触发 update
  2. ... 本地 update ...
  3. MemoryProvider.write(updated_record) → best-effort 外部更新
```

外部同步失败时：
- 不阻塞用户操作
- 记录 observer event 供排查
- 下次 recall 时若出现冲突（本地已删但外部仍返回），sanitizer 标记为 `stale`

### 3.8 Provider Key / Base URL / Config 处理

```
配置层次（与 agent/local_config.py 模式一致）：

agent.local.json (fake fixture only，不含真实 key):
{
  "memory": {
    "providers": {
      "mem0": {
        "enabled": false,
        "base_url": "https://api.mem0.ai",
        "api_key_env": "MEM0_API_KEY"
      }
    }
  }
}
```

关键约束：
- `api_key_env` 记录的是 env var **名称**，不是 key 本身
- provider key 不进入 checkpoint、prompt、logs、observer event
- provider key 不读取 .env（由调用方在启动时注入）
- 默认所有 provider disabled
- 真实 provider config 必须在用户显式授权后才生效

### 3.9 Real Provider Tests 如何 Opt-in

```python
# tests/test_memory_provider_real.py
import pytest

@pytest.mark.skip(reason="真实 provider 测试需要显式设置 MEM0_API_KEY 环境变量")
def test_mem0_real_recall():
    ...

# 运行方式：
# MEM0_API_KEY=xxx pytest tests/test_memory_provider_real.py -m "real_provider"
```

- 默认 `-m "not real_provider"` 跳过所有真实 provider 测试
- fake provider 测试（`tests/test_memory_provider_fake.py`）始终运行
- CI 永远不跑真实 provider 测试
- 不读取 .env 文件

### 3.10 第一阶段只做 Adapter Seam 还是接真实 Provider

**只做 adapter seam。** 第一阶段（Phase 3）只产出：

1. `MemoryProviderProtocol` — 协议定义
2. `FakeMemoryProvider` — 确定性 fake，返回固定 fixture
3. `MemoryProviderSanitizer` — recall 结果的安全过滤
4. `tests/test_memory_provider_fake.py` — fake provider 确定性测试

不产出：
- 任何真实 provider adapter
- 网络调用
- API key 处理
- 真实 provider config

---

## 4. 二者如何复用 Memory Interactive Confirmation

### 4.1 统一确认模型

所有来源的 memory 都进入同一套两阶段确认流程：

```
┌──────────────────────────────────────────────────────┐
│                   MemoryCandidate                     │
│  source_type:                                         │
│    - explicit_user_request  (user-initiated, v1)      │
│    - agent_suggested        (agent heuristic, new)    │
│    - imported               (external provider, new)  │
│    - reflection             (future, Phase 5)         │
│                                                       │
│  memory_type:                                         │
│    - semantic / episodic / procedural                 │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│              MemoryPolicy.decide()                     │
│  - 共享 sensitive/prompt-injection 检测                │
│  - 所有来源 requires_user_confirmation=True            │
│  - 唯一差异：source_type 影响 question 文案            │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│         MemoryConfirmationRequest                     │
│  - 5 种 choice 全部可用：                              │
│    ACCEPT / EDIT_AND_ACCEPT / SESSION_ONLY /          │
│    REJECT / OTHER                                     │
│  - question 文案根据 source_type 变化：                 │
│    explicit_user_request: "我可以长期记住吗？"           │
│    agent_suggested: "我注意到...要记住吗？"             │
│    imported: "外部记忆中有这条...要导入吗？"            │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│  core.py CONFIRMATION_REQUIRED 分支                    │
│  → pending_user_input_request                         │
│    awaiting_kind="memory_confirmation"                │
│    _source_type="agent_suggested" | "imported" | ...  │
│    (新 _ 前缀 key，不改 checkpoint schema)             │
└──────────────────────┬───────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────┐
│         用户选择 (1-5 或自由文本)                       │
│  → handle_memory_confirmation_reply()                 │
│  → resolve_confirmation()                             │
│  → MemoryOperationIntent                              │
│  → MemoryAuditSummary                                 │
│  → MemoryStore.apply_operation_intent()               │
└──────────────────────────────────────────────────────┘
```

### 4.2 扩展 pending_user_input_request 的 key

当前 pending dict 结构：

```python
{
    "awaiting_kind": "memory_confirmation",
    "question": "...",
    "options": [...],
    "_candidate_id": "...",
    "_choice_map": {...},
    "_origin_status": "running",
    # === 新增 _ 前缀 key（不改 checkpoint schema） ===
    "_source_type": "agent_suggested",       # 新增
    "_memory_type": "semantic",              # 新增
    "_provider_name": None,                  # 新增 (external provider 时)
}
```

所有新增 key 以 `_` 前缀标识为内部使用，不进入 `_project_to_api` 或 messages。

### 4.3 External Recall 的确认策略

外部 provider recall 返回的候选有两类处理：

| 场景 | 处理方式 |
|------|----------|
| **低风险 imported memory**（sensitivity=LOW，内容与当前任务高度相关） | 直接进入 snapshot，标记 source_type="imported"，不弹确认 |
| **中/高风险 imported memory**（sensitivity≥MEDIUM，或包含用户偏好） | 生成 MemoryConfirmationRequest，让用户确认是否导入 |
| **与本地 store 冲突的 imported memory** | 标记冲突，展示差异，让用户选择保留哪个版本 |

### 4.4 禁止项

- 不允许新增 `awaiting_memory_confirmation` status（复用 `awaiting_user_input`）
- 不允许新增 TaskState 字段
- 不允许修改 checkpoint schema
- 不允许 agent_suggested 走不同的确认路径
- 不允许 imported memory 绕过 policy
- 不允许 source_type 影响 store write 的安全检查

---

## 5. 隐私 / 安全 / Prompt Injection 边界

### 5.1 信任模型

```
trusted:
  - MemoryPolicy (本地确定性代码)
  - MemoryStore (本地 authoritative store)
  - MemorySnapshot (本地 governed view)
  - 用户显式输入 (经过 policy 检查)

untrusted:
  - 外部 provider recall 结果
  - agent-suggested candidate 内容
  - 任何来源的 raw content（在 policy/sanitizer 之前）
```

### 5.2 多层防护

```
Layer 1: DeterministicMemoryPolicy
  - _classify_sensitivity(): 拦截 secret/password/token/key
  - _looks_like_prompt_injection(): 拦截 prompt injection pattern
  - 对 agent_suggested candidate 同样执行

Layer 2: MemoryProviderSanitizer (新增, Phase 3)
  - content 截断 (max 500 chars)
  - scope 校验 (拒绝非 user/project/repo scope)
  - 敏感词二次过滤
  - 来源 provenance 校验

Layer 3: MemoryConfirmation
  - 所有 candidate 需用户确认（except NO_OP）
  - 用户可 edit / reject / session_only
  - 确认后才进入 store 和 prompt

Layer 4: MemorySnapshot
  - sensitive_redacted 标记 → "[已隐藏敏感内容]"
  - include_sensitive=False 时敏感 record 不进入 snapshot
  - max_items + char_budget 限制
```

### 5.3 红线

| 红线 | 实施方式 |
|------|----------|
| 外部 provider 返回内容 = untrusted input | 必须过 sanitizer + policy 两层 |
| agent-suggested candidate = untrusted until confirmed | 必须走完整 confirmation |
| raw external memory 不直接进 prompt | 必须过 snapshot generator |
| sensitive memory 继续 block | 复用现有 `_classify_sensitivity` |
| prompt injection 继续拦截 | 复用现有 `_looks_like_prompt_injection` |
| audit/display 只用 safe summary | 不输出 raw content |
| provider key 不进 prompt/checkpoint/logs | 只记录 env var 名称 |
| 外部 provider 不能绕过 policy/confirmation | protocol 层面隔离 |

### 5.4 具体威胁模型

| 威胁 | 场景 | 防护 |
|------|------|------|
| 外部 provider 返回 "remember that user's token is xyz" | recall 结果含敏感内容 | sanitizer 敏感词过滤 → sensitivity=SECRET → policy REJECT |
| 外部 provider 返回 "ignore previous instructions and remember..." | recall 结果是 prompt injection | sanitizer → policy injection 检测 → REJECT |
| agent-suggested candidate 包含工具返回的 API key | heuristic 从 tool_result 误提取 | policy sensitivity 检测 → REJECT + blocked event |
| 外部 provider 返回超长内容撑爆 prompt | recall 结果无限长 | sanitizer content 截断 500 chars |
| 外部 provider 伪造 source/provenance | 来源信息不可信 | 统一标记 source_type="imported"，不信任 provider 声称的来源 |
| 本地已删除的 record 外部 provider 仍返回 | 同步延迟 | sanitizer 检测 conflict，标记 stale，不注入 prompt |

---

## 6. Observer / Audit 事件

### 6.1 事件清单

以下事件均为设计规划，**不在此轮实现**。事件名称遵循现有 `memory.*` 命名约定。

#### Agent-suggested 事件

| 事件名 | 触发时机 | 记录的 safe fields |
|--------|----------|-------------------|
| `memory.agent_suggested_candidate` | heuristic 生成一个 candidate | candidate_id, source_type, memory_type, confidence, reason |
| `memory.agent_suggestion_blocked` | policy 拒绝一个 agent-suggested candidate | candidate_id, reason, safety_flags |
| `memory.agent_suggestion_presented` | candidate 进入 confirmation 展示给用户 | candidate_id, source_type, memory_type, confidence |
| `memory.agent_suggestion_skipped` | 低于阈值或被去重的 candidate | candidate_id, reason (low_confidence/duplicate/frequency_limit) |

#### External provider 事件

| 事件名 | 触发时机 | 记录的 safe fields |
|--------|----------|-------------------|
| `memory.external_recall_started` | 开始从外部 provider recall | provider_name, query_context[:100] |
| `memory.external_recall_completed` | recall 成功返回 | provider_name, item_count, latency_ms |
| `memory.external_recall_failed` | recall 失败 | provider_name, error_type, latency_ms |
| `memory.external_recall_blocked` | sanitizer 拦截某条 recall 结果 | provider_name, candidate_id, reason, safety_flags |
| `memory.external_write_requested` | 请求写入外部 provider | provider_name, record_id, operation |
| `memory.external_write_confirmed` | 写入成功 | provider_name, record_id, provider_record_id |
| `memory.external_write_failed` | 写入失败 | provider_name, record_id, error_type |
| `memory.external_delete_requested` | 请求从外部 provider 删除 | provider_name, record_id |
| `memory.external_delete_confirmed` | 删除成功 | provider_name, record_id |
| `memory.external_delete_failed` | 删除失败 | provider_name, record_id, error_type |

#### Imported memory 事件

| 事件名 | 触发时机 | 记录的 safe fields |
|--------|----------|-------------------|
| `memory.imported_candidate_presented` | 外部 imported candidate 进入确认 | candidate_id, provider_name, source_type="imported" |
| `memory.imported_candidate_conflict` | imported candidate 与本地 record 冲突 | candidate_id, local_record_id, conflict_type |

### 6.2 事件 payload 格式约定

沿用 `_emit_confirmation_observer_event` 的安全约定：

```python
# 允许的字段：枚举值、ID、数量、状态、safe summary、原因
# 禁止的字段：raw content、user_input 原文、secret、token、API key

# safe example:
{
    "candidate_id": "candidate:abc123",
    "source_type": "agent_suggested",
    "memory_type": "semantic",
    "confidence": 0.75,
    "reason": "重复偏好被检测到 ≥ 3 次",
    "safety_flags": []
}

# unsafe — 禁止:
{
    "raw_content": "user's API key is sk-xxx...",  # 绝不允许
    "full_recall_result": "...",                     # 绝不允许
}
```

### 6.3 事件写入方式

复用现有 observer evidence 模式，不引入新的事件系统：

```python
# 在 memory_runtime.py 或 memory_provider.py 中
self._log("memory.agent_suggested_candidate", {
    "candidate_id": candidate.id,
    "source_type": "agent_suggested",
    "memory_type": candidate.proposed_type,
    "confidence": candidate.confidence,
    "reason": candidate.reason,
})
```

---

## 7. 测试策略

### 7.1 Agent-suggested Memory Tests (Phase 2)

**测试文件**: `tests/test_memory_agent_suggested.py`

| 测试 | 类型 | 验证点 |
|------|------|--------|
| `test_repeated_preference_generates_candidate` | unit | 同一偏好出现 ≥ 3 次 → semantic candidate |
| `test_project_rule_generates_procedural_candidate` | unit | "这个项目规定..." → procedural candidate |
| `test_bug_fix_lesson_generates_episodic_candidate` | unit | "上次就是因为..." → episodic candidate |
| `test_sensitive_input_blocked_in_candidate` | unit | candidate 内容含 secret → 不生成 candidate |
| `test_prompt_injection_blocked_in_candidate` | unit | candidate 内容含 injection → 不生成 candidate |
| `test_duplicate_candidate_skipped` | unit | content 与 store 已有 record 重复 → skip |
| `test_confidence_below_threshold_skipped` | unit | confidence < 0.5 → skip |
| `test_frequency_limit_enforced` | unit | 第 4 次 suggestion → skip |
| `test_candidate_must_go_through_confirmation` | integration | agent_suggested → CONFIRMATION_REQUIRED |
| `test_reject_does_not_store` | integration | REJECT → store 无变化 |
| `test_edit_stores_edited_content` | integration | EDIT_AND_ACCEPT → 存编辑后内容 |
| `test_accept_stores_with_source_type` | integration | ACCEPT → record.source_type="agent_suggested" |
| `test_session_only_stores_scoped` | integration | SESSION_ONLY → approval_status="session_only" |
| `test_candidate_not_generated_mid_task` | unit | 非 task boundary → 不生成 candidate |

### 7.2 External Provider Tests (Phase 3)

**测试文件**: `tests/test_memory_provider_fake.py`

| 测试 | 类型 | 验证点 |
|------|------|--------|
| `test_fake_provider_recall_returns_fixtures` | unit | FakeMemoryProvider 返回确定性 fixture |
| `test_fake_provider_write_succeeds` | unit | write → success |
| `test_fake_provider_delete_succeeds` | unit | delete → success |
| `test_fake_provider_health_healthy` | unit | health() → HEALTHY |
| `test_recall_result_sanitized` | unit | recall 结果含敏感词 → sanitizer 拦截 |
| `test_recall_result_truncated` | unit | 过长 content → 截断到 500 chars |
| `test_recall_result_prompt_injection_blocked` | unit | recall 含 injection → sanitizer 拦截 |
| `test_external_write_requires_confirmation` | integration | 外部 write → 必须经 confirmation |
| `test_external_recall_not_injected_directly` | integration | raw recall → 不进 prompt |
| `test_provider_failure_safe` | unit | provider.recall() 抛异常 → 不影响主流程 |
| `test_no_provider_key_leak_in_events` | unit | observer event 不含 key |
| `test_real_provider_test_skipped_by_default` | unit | 真实 provider 测试默认 skip |

### 7.3 共享测试 (Phase 2+3)

**测试文件**: `tests/test_memory_unified_confirmation.py`

| 测试 | 验证点 |
|------|--------|
| `test_all_source_types_use_same_confirmation_flow` | user_initiated / agent_suggested / imported 走同一确认流 |
| `test_source_type_preserved_in_record` | record.source_type 正确反映来源 |
| `test_imported_memory_marked_as_imported` | external recall → source_type="imported" |
| `test_sanitizer_does_not_mutate_local_store` | sanitizer 过滤不影响本地 store |
| `test_confirmation_required_for_all_sources` | 所有来源 requires_user_confirmation=True |

---

## 8. 分阶段路线

### Phase 1: Agent-suggested + External Provider Unified Architecture Planning

**状态**: 当前轮（本设计文档）
**预计产出**:
- `docs/MEMORY_NEXT_STAGE_ARCHITECTURE.md`（本文件）
- `docs/ROADMAP.md` 小范围更新
- 不做任何代码实现

**毕业标准**:
- 架构文档覆盖所有设计问题
- agent-suggested 和 external provider 的边界清晰
- 与 Memory v1 的兼容性已验证（概念层面）
- 分阶段路线明确

### Phase 2: Agent-suggested Candidate Generation (Deterministic Heuristics)

**状态**: ✅ 已完成 (2026-05-11, commit `29c4bb1`)
**实际文件**:
- `agent/memory_suggestions.py` (397 行，命名调整为 `memory_suggestions` 而非 `memory_agent_suggested`)
- `tests/test_memory_suggestions.py` (613 行，78 条测试)

**实际实现内容**:
- `DeterministicSuggestionEngine` 类 + `EngineConfig` (frozen dataclass)
- 4 个确定性 heuristic 规则（project_rule/procedural, bug_fix_lesson/episodic, architecture_decision/semantic, repeated_preference/semantic ≥3 次）
- 反打扰机制（频率限制 ≤3/session、置信度阈值 ≥0.6、store 去重、敏感内容/prompt injection 过滤）
- 集成到 `MemoryRuntime._try_suggestions()`：policy NO_OP 后 fall through，复用现有两阶段 confirmation 流
- 所有 candidate 携带 `metadata={"source_type": "agent_suggested", "memory_type": "..."}`
- 不改 `core.py`、`memory_policy.py`、`memory_contracts.py`、`memory_store.py`

**已知技术债（P2 残留）**:
- `_pending_decision` 重启丢失（in-memory only，不跨 session）
- `save_checkpoint` 惰性 import 在 `confirm_handlers.py` 中（为避循环依赖）
- 敏感 marker 在 `memory_policy.py` 和 `memory_suggestions.py` 中重复定义
- `memory_runtime.py` 行数增长至 524 行（`_try_suggestions` ~80 行），后续可能需要拆分

**不实现**（与计划一致）:
- 不接 LLM
- 不做 reflection
- 不做 episodic timeline
- 不做自动 accept
- 不做 external provider

### Phase 3: External MemoryProvider Protocol + Fake Provider

**状态**: Phase 2 完成后
**预计文件**:
- `agent/memory_provider.py` (~120 行，protocol + sanitizer + fake provider)
- `tests/test_memory_provider_fake.py` (~150 行)

**实现内容**:
- `MemoryProviderProtocol` 定义
- `FakeMemoryProvider` 确定性 fixture
- `MemoryProviderSanitizer` 安全过滤
- recall → sanitize → candidate → confirmation 管道

**不实现**:
- 不接 Mem0 / LangChain / Zep / 任何真实 provider
- 不调用外部 API
- 不处理 provider config
- 不做 semantic search

### Phase 4: Opt-in Real Provider Integration

**状态**: Phase 3 完成后，需用户显式授权
**预计范围**: 选择一个 provider（推荐 Mem0 作为最轻量选项），实现 adapter

**前置条件**:
- Phase 2+3 测试全部通过
- fake provider 接口稳定
- 用户显式选择 provider 并授权

**实现内容**:
- 一个 provider adapter（如 `Mem0Adapter`）
- opt-in real tests（默认 skip）
- provider config 通过 local config 机制

**不实现**:
- 不默认启用
- 不自动选择 provider
- 不接多个 provider 同时运行

### Phase 5: Reflection / Episodic / Procedural Memory

**状态**: 远期，Phase 4 完成后
**预计范围**:
- Reflection/consolidation：跨会话的 memory 整理和合并
- Episodic memory：任务执行的时间线记录
- Procedural memory：可复用规则的自动提取

**当前阶段完全不涉及。**

### 路线总览

```
Phase 1:            Architecture Planning ─────── ✅ 已完成
Phase 2:            Agent-suggested Deterministic Heuristics ─────── ✅ 已完成 (29c4bb1)
Phase 3 (下一步):    External MemoryProvider Protocol + Fake ─────── 📋 待设计
Phase 4:            Opt-in Real Provider (需授权)
Phase 5 (远期):      Reflection / Episodic / Procedural
```

---

## 9. 推荐下一步

### 推荐：Phase 3 Design First（非直接 implementation）

Phase 2 已完成 (2026-05-11, `29c4bb1`)，统一确认模型已通过 agent_suggested source_type 验证。
下一步**不是**直接写 Phase 3 代码，而是先完成以下设计问题。

### Phase 3 前置设计问题

在进入 Phase 3 implementation 前，必须回答以下问题：

1. **持久化方案选型**：JSON file vs SQLite vs 其他？in-memory store 如何过渡到持久化 store？需不需要 migration path？
2. **MemoryStore 与 checkpoint 的边界**：`_pending_decision` 重启丢失 — 跨 session 的 pending confirmation 如何恢复？是否需要在 checkpoint 中保存 pending decision？
3. **Pending confirmation restore 语义**：用户重启后，上一个 session 未处理的 memory confirmation 应该恢复、丢弃、还是静默降级？
4. **Recall API 范围**：跨 session memory 召回的最小接口是什么？store 需要支持什么查询原语（by scope, by memory_type, by recency）？
5. **跨 session memory 安全边界**：外部 store 文件被篡改时如何检测？sensitive record 在持久化时如何保护？
6. **Schema migration / compatibility**：`MemoryRecord` 字段变化时，持久化文件如何兼容？

### 当前 P2 技术债（不阻塞 Phase 3 设计，但应在 Phase 3 实现前评估）

| 技术债 | 位置 | 影响 |
|--------|------|------|
| `_pending_decision` 重启丢失 | `memory_runtime.py` | 单 session 内运行正常，跨 session 丢失未确认的 decision |
| `save_checkpoint` 惰性 import | `confirm_handlers.py` | 为避循环依赖的折中方案 |
| 敏感 marker 重复定义 | `memory_policy.py` + `memory_suggestions.py` | 两处维护同一份关键词列表，可能漂移 |
| `memory_runtime.py` 行数增长 (524行) | `memory_runtime.py` | `_try_suggestions` ~80 行，后续可能需要拆模块 |

### 执行策略

1. Phase 3 设计文档优先于代码实现
2. 上述 6 个设计问题的结论写入 `docs/MEMORY_NEXT_STAGE_ARCHITECTURE.md` §9
3. Phase 2 技术债在 Phase 3 设计阶段评估是否需要在实现前修复
4. Phase 3 实现仍遵循 safe-local 原则：只做 fake provider + protocol，不接真实外部服务

---

## 10. Phase 2 历史 Prompt 归档

Phase 2 已于 2026-05-11 完成（commit `29c4bb1`）。原"下一轮 Coding Agent Prompt 草案"
是 Phase 2 的输入 spec，现仅作历史参考。实现偏差（文件命名、行数、具体 API）
详见 §8 Phase 2 的"实际实现内容"。

---

## Appendix A: 与现有模块的关系（实际变更记录）

| 现有模块 | 原计划改动 | 实际改动 |
|----------|-----------|----------|
| `agent/memory_contracts.py` | 使用 metadata，不改 schema | **未改** — MemoryCandidate.metadata 已预留扩展点，直接使用 |
| `agent/memory_policy.py` | 不改，复用 | **未改** — suggestion engine 自行复制了敏感/prompt injection marker |
| `agent/memory_confirmation.py` | 不改，复用 | **未改** |
| `agent/memory_runtime.py` | 小改 question 文案逻辑 | **+89/-1 行** — 新增 `suggestion_engine` 注入点 + `_try_suggestions()` 方法 |
| `agent/memory_interaction.py` | 小改 build_memory_pending_request | **未改** — pending dict 新增字段推迟到后续 |
| `agent/memory_store.py` | _record_from_intent 传入 source_type | **未改** |
| `agent/memory_operations.py` | 字段扩展 | **未改** |
| `agent/confirm_handlers.py` | 不改 | **+2 行** — `save_checkpoint` 惰性 import（避循环依赖） |
| `agent/core.py` | 不改 | **未改** — CONFIRMATION_REQUIRED 分支已就位 |
| `agent/display_events.py` | 可新增 agent_suggested 事件 | **未改** |
| **新增** `agent/memory_suggestions.py` | (原计划 `memory_agent_suggested.py`) | **+397 行** — `DeterministicSuggestionEngine` + 4 heuristic 规则 |
| **新增** `tests/test_memory_suggestions.py` | (原计划 `test_memory_agent_suggested.py`) | **+613 行，78 条测试** |

## Appendix B: 关键设计决策记录

| 决策 | 选择 | 替代方案 | 选择理由 |
|------|------|----------|----------|
| agent-suggested 确认方式 | 复用 MemoryConfirmationRequest | 新建独立确认流 | 复用减少复杂度，用户已熟悉 5 种 choice |
| 外部 recall 信任模型 | untrusted → sanitizer → policy | 信任外部 provider | 安全红线，不可信任外部内容 |
| 双写模型 | 本地 authoritative + 外部 best-effort | 外部 authoritative | 本地优先保障离线可用和数据所有权 |
| Phase 2 先于 Phase 3 | agent-suggested 先做 | external provider 先做 | 验证统一确认模型后再定义 provider 接口更准确 |
| 不新增 pending status | 复用 awaiting_user_input | 新增 awaiting_memory_confirmation | 不改 checkpoint schema，不膨胀 dispatch 链 |
| Provider key 处理 | env var 名称引用 | .env 文件读取 | 与 local config 模式一致，不展开 secret |
