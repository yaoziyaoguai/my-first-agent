# B7 Multi-Instance Readiness SDD

**创建日期**: 2026-06-01
**状态**: DRAFT
**依赖**: [b7-pre-sdd-redline-debt.md](../debt/b7-pre-sdd-redline-debt.md)
**前置**: B7 Pre-SDD Redline Cleanup (9d99bec)

---

## 0. 目标与范围

### 0.1 目标

建立 First Agent runtime 的 **multi-instance readiness**——使 runtime 在架构层面支持多个独立 session/run/instance 并行存在，但不做完整产品化多实例管理。

**最终产出**:
1. session/run/instance 三级 identity model
2. namespace 隔离（checkpoint / memory / lifecycle / MCP bridge / event log）
3. append-only structured event log（JSONL）
4. B8 Phase 6B/7 的前置依赖全部满足

### 0.2 非目标 (Out of Scope)

- **不做**多实例调度器 / 实例管理 UI / 进程级别隔离
- **不做**跨实例通信 / 共享状态 / 分布式锁
- **不做**持久化 session registry（session 由调用方创建和管理）
- **不做**TUI 默认入口激活
- **不做**B8 Phase 6B/7 implementation（仅提供前置契约）
- **不改变**单实例默认路径的行为

### 0.2b 已知限制 (Known Limitations — B7 不解决)

以下模块级单例是更深层的架构问题，需要比 B7 更大规模的 runtime 重构。B7 的 namespace 注入为它们提供了**隔离基础**，但不改变它们的生命周期：

| 限制 | 位置 | B7 提供的基础 |
|------|------|-------------|
| `state = create_agent_state(...)` 模块级单例 | `agent/core.py:221` | 不改变；多 run 复用同一 AgentState 实例。B7 只确保同一 state 内的 checkpoint/task/conversation 按 run_id 隔离 |
| `_memory_runtime = create_memory_runtime()` 模块级单例 | `agent/core.py:152` | MemoryRuntime 实例本身保持模块级，但其内部 `InMemoryMemoryStore` 通过 namespace 前缀隔离数据 |
| `_l2_trigger_guard = _L2TriggerGuard()` 模块级单例 | `agent/core.py:157` | 不改变；L2 extraction trigger 仍跨 session 共享 turn count |
| `refresh_runtime_system_prompt()` import-time 调用 | `agent/core.py:505` | 不改变；import-time 调用继续使用 `"default"` namespace，确保模块加载不依赖 session_id |

这些限制在**单进程单 session** 场景下不影响正确性。真正的多 session 并发需要将 AgentState 从模块级迁移到实例级——这是 B7 之后的架构演进方向。

### 0.3 约束

- 保持一条 main runtime path（ToolRuntimeMediator → TOOL_GATE → TOOL_INVOKE → execute_single_tool → TOOL_RESULT）
- fake/real 只是 provider/config/adapter 差异，不是不同 runtime 路径
- TUI 只是 view/launcher，不是第二 runtime
- 不调用真实 API
- 不读取 .env，不打印 secret
- 不执行 destructive command
- 不改 Python runtime core path 的语义（只注入 identity/namespace 参数）

---

## 1. Identity Model

### 1.1 三级模型

```
session
  └─ run (1:N)
       └─ instance (1:1, runtime process 内的隔离单元)
```

| 层级 | 标识符 | 生命周期 | 创建者 | 示例 |
|------|--------|---------|--------|------|
| **session** | `session_id` | CLI 进程启动 → 进程退出 | `main.py` 在 startup 时生成 | `sess-a1b2c3d4` |
| **run** | `run_id` | 一次 `chat()` 调用或一次 user turn | `core.chat()` 在入口处生成 | `run-e5f6g7h8` |
| **instance** | `instance_id` | Runtime 内一个隔离单元的 scope（可选，默认 = session_id） | 调用方注入或 session scope 默认 | `inst-i9j0k1l2` |

**关键设计决策**:
- `session_id` 在 `main.py` startup 时生成，不在 import time 生成（解决 P2-4）
- `run_id` 在 `core.chat()` 入口生成，每次用户输入产生新 run_id
- `instance_id` 默认为 `session_id`，支持未来扩展（如 TUI 内多 tab 实例）
- 所有三级 id 均为 `str` 类型，不强制 UUID 格式（允许人类可读 id）

### 1.2 RuntimeIdentity

新增不可变值对象，在 `chat()` 入口构造并注入到下游：

```python
@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    session_id: str
    run_id: str
    instance_id: str  # default = session_id
```

**注入路径**:
- `chat()` → `LoopContext` → `LoopDependencies` → `run_main_loop()`
- `ToolRuntimeMediator` 接收 `identity: RuntimeIdentity`（新增参数）
- `RuntimeActionDispatcher` 不持有 identity——identity 在 route 时从 request.payload 或 context 注入
- 现有 handler 不需要改签名——identity 通过 `RuntimeActionContext` 获取

### 1.3 现有 SESSION_ID 迁移

| 模块 | 当前 | B7 后 |
|------|------|-------|
| `agent/logger.py` | `SESSION_ID = str(uuid.uuid4())` (import-time) | 移除模块级 SESSION_ID；改为 `def get_session_id() -> str` 从 RuntimeIdentity 读取 |
| `agent/session.py` | `from agent.logger import SESSION_ID` | 从 `main.py` 传入 `session_id` 参数 |
| 各 handler 的 `session_id` 引用 | 直接 import | 从 `RuntimeActionContext` 或 `LoopContext` 获取 |

---

## 2. Namespace Model

### 2.1 命名空间层次

每个 runtime 子系统必须支持 namespace 参数，用于隔离不同 session/run/instance 的状态：

| 子系统 | 当前状态 | B7 namespace 方案 | 优先级 |
|--------|---------|-------------------|--------|
| **Checkpoint** | 单文件 `memory/checkpoint.json` | `memory/checkpoints/{session_id}/{run_id}.json` | P1-3 |
| **Lifecycle** | 模块级 `_default_lifecycle` singleton | `RuntimeIdentity` 作为 lifecycle key 前缀 | P1-1/P1-2 |
| **Memory** | `InMemoryMemoryStore` 无 namespace | store 实例化时接受 `namespace: str` 参数 | P2-1 |
| **MCP Bridge** | 模块级 `_mcp_bridge_tools_registered` | session-scoped registry，keyed by `session_id` | P2-2 |
| **Event Log** | in-memory `_action_log: list` | `sessions/{session_id}/events.jsonl` | P2-3 |
| **Action Log** | dispatcher `_action_log: list[RuntimeActionEvent]` | 新增 `flush_to_event_log()` 方法写入 JSONL | P2-3 |

### 2.2 Namespace 注入模式

所有子系统采用一致的 namespace 注入模式：**构造时注入 namespace，不依赖模块级全局**。

```python
# 模式：构造函数接收 identity 参数
class ActiveSkillLifecycle:
    def __init__(self, namespace: str = "default"):  # 已有参数，B7 兼容
        ...

# 模式：工厂函数接收 identity
def create_memory_runtime(*, namespace: str = "default") -> MemoryRuntime:
    store = InMemoryMemoryStore(namespace=namespace)
    ...

# 模式：dispatcher 不持有 namespace，由 route 时的 identity 决定
# identity 通过 RuntimeActionRequest.payload 中的 _identity 字段传递
```

### 2.3 向后兼容

所有 namespace 参数默认值为 `"default"`，确保单实例场景下行为不变。

---

## 3. Event Source Contract

### 3.1 事件模型

Runtime 产生的事件分为两类：

| 类别 | 格式 | 存储 | 用途 |
|------|------|------|------|
| **RuntimeActionEvent** | 不可变 dataclass (in-memory) | Dispatcher action_log (内存) | turn 内 evidence chain |
| **StructuredEventLog** | JSONL (append-only file) | `sessions/{session_id}/events.jsonl` | 跨 turn / 跨 run 持久化历史 |

### 3.2 JSONL Event Format

每条 event 一行 JSON，不换行：

```jsonl
{"ts":"2026-06-01T10:30:01.123Z","event_id":"evt-001","session_id":"sess-a1b2","run_id":"run-c3d4","event_type":"runtime.action.dispatched","action_type":"tool.gate","status":"rejected","payload":{"tool_name":"read_file"},"redacted":[]}
{"ts":"2026-06-01T10:30:01.456Z","event_id":"evt-002","session_id":"sess-a1b2","run_id":"run-c3d4","event_type":"runtime.action.completed","action_type":"tool.invoke","status":"executed","payload":{"tool_name":"bash","tool_output_preview":"..."},"redacted":[]}
```

**必填字段**:
- `ts`: ISO 8601 UTC timestamp
- `event_id`: 全局唯一 event id
- `session_id`: 所属 session
- `run_id`: 所属 run
- `event_type`: 事件类型（`runtime.action.dispatched` / `runtime.action.completed` / `runtime.checkpoint.saved` / ...）
- `status`: 事件状态
- `payload`: 事件负载（dict）
- `redacted`: 被 redact 的字段名列表

**写入契约**:
- Python runtime **只写不读**（append-only writer）
- TUI **只读不写**（read-only tail）
- 不允许 TUI 写入 event log（防止 TUI 成为第二 runtime）
- Event log 不是 checkpoint 替代品——checkpoint 仍然独立管理

### 3.3 Event Log Writer

```python
class EventLogWriter:
    """Append-only JSONL event log writer。"""

    def __init__(self, session_dir: Path) -> None:
        self._path = session_dir / "events.jsonl"
        self._lock = threading.Lock()  # 进程内互斥

    def append(self, event: dict[str, Any]) -> None:
        """原子追加一条 event。"""
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with self._lock:
            with open(self._path, "a") as f:
                f.write(line)
```

### 3.4 安全/Redact Policy

在执行 event log 写入前，以下字段必须 redact：

| 字段模式 | Redact 方式 | 执行阶段 |
|---------|------------|---------|
| `api_key`, `token`, `secret`, `password`, `authorization` | 替换为 `"<REDACTED>"` | EventLogWriter.append() |
| `api_key_env` | 替换为 `"<REDACTED>"` | EventLogWriter.append() |
| `bearer` header | 替换为 `"Bearer <REDACTED>"` | EventLogWriter.append() |

Redact 逻辑复用 `agent/logger.py` 中已有的 `_KEY_REDACT_RE` 和 `_BEARER_REDACT_RE` 正则。

**Redact 管道**:
1. 原始 RuntimeActionEvent 在 dispatcher 中产生（**不** redact——内存中的 evidence 需要完整字段）
2. EventLogWriter.append() 在写入文件前执行 redact
3. TUI 读取 JSONL 时，已 redact 的字段保持不变

### 3.5 Backpressure / Truncation

- Event log 单文件最大 100MB
- 超过上限时：rename 为 `events.{timestamp}.jsonl`，新建空 `events.jsonl`
- 归档文件保留最近 5 个，更旧的自动删除
- **不**做运行时 backpressure——event 写入失败不阻塞主循环（best-effort）

---

## 4. Checkpoint Namespace

### 4.1 存储方案

```
memory/
  checkpoints/
    {session_id}/
      {run_id}.json        # per-run checkpoint
      latest.json           # symlink → 最新 run 的 checkpoint
```

### 4.2 Checkpoint Schema v2

在现有 v1 schema 基础上新增 identity 字段：

```json
{
  "schema_version": "checkpoint.v2",
  "session_id": "sess-a1b2c3d4",
  "run_id": "run-e5f6g7h8",
  "created_at": "2026-06-01T10:30:01Z",
  "updated_at": "2026-06-01T10:30:05Z",
  "task": { ... },
  "conversation": { ... },
  "memory": { ... }
}
```

### 4.3 迁移路径

- `checkpoint.v1` → `checkpoint.v2`: 添加 identity 字段 + 路径迁移
- 旧 `memory/checkpoint.json` 在 B7 完成后标记为 legacy，不再写入
- 读 checkpoint 时：先查找 v2 路径，未找到则回退 v1 路径（向后兼容）
- Migration 在 `SaveCheckpointHandler` 中处理，不在 startup 中做批量迁移

### 4.4 Resume 匹配

- `resume from checkpoint` 默认恢复最新 session 的最新 run
- 支持 `--session-id` 和 `--run-id` CLI 参数精确指定
- Resume 逻辑从 `agent/session.py` 迁入 `agent/checkpoint.py`（不新增文件）

---

## 5. P1/P2 Redline Debt 映射

### 5.1 P1 项

| ID | 当前问题 | SDD 方案 | 实现文件 |
|----|---------|---------|---------|
| **P1-1** | `_active_skill` module-level dict | `ActiveSkillLifecycle` 实例化时绑定 `namespace`（已有参数），模块级 `_default_lifecycle` 改为 lazy init + session_id keyed registry | `agent/skill_system/lifecycle.py` |
| **P1-2** | `_default_lifecycle` import-time singleton | 改为 `get_default_lifecycle(session_id: str = "default")` factory function，内部使用 dict 按 session_id 缓存实例 | `agent/skill_system/lifecycle.py` |
| **P1-3** | checkpoint 单文件 + 缺 run_id | per-run checkpoint 路径 `memory/checkpoints/{session_id}/{run_id}.json` + schema v2 | `agent/checkpoint.py` |
| **P1-4** | `RuntimeActionEvent` 缺 identity 字段 | 新增 `session_id`、`run_id`、`instance_id` 字段（默认 `""` 保证向后兼容）| `agent/runtime_integration/schema.py` |

### 5.2 P2 项

| ID | 当前问题 | SDD 方案 | 实现文件 |
|----|---------|---------|---------|
| **P2-1** | `InMemoryMemoryStore` 无 namespace | store 构造时接收 `namespace: str`，内部 key 前缀为 `{namespace}:` | `agent/memory_store.py` |
| **P2-2** | MCP bridge module-level global | bridge 状态从模块级变量迁入 session-scoped dict；`run_mcp_bridge()` 接收 `session_id` 参数 | `agent/mcp_bridge.py` |
| **P2-3** | in-memory `action_log` 无 durable store | dispatcher 新增 `flush_to_event_log(writer)` 方法，在 turn-end hook 中调用；不改变现有 in-memory action_log | `agent/runtime_integration/dispatcher.py` |
| **P2-4** | `SESSION_ID` import-time generation | 移除模块级 `SESSION_ID`，改为 `main.py` startup 时生成并通过 RuntimeIdentity 注入 | `agent/logger.py` |
| **P2-5** | 004 Part B trigger 设计约束 | B7 不改变 trigger 条件——trigger 仍由 `checkpoint_save_on_turn_end` flag 控制；B7 只改变 save 的目标路径 | `agent/core.py` |
| **P2-6** | `ToolRuntimeMediator._route_gate()` 动态调用 `get_default_lifecycle()` | B7 后 `get_default_lifecycle(session_id)` 按 session_id 返回对应实例；mediator 从 `self._identity.session_id` 获取 session_id | `agent/tool_runtime_mediator.py:420-436` |

---

## 6. RuntimeActionEvent Identity 字段 (P1-4 详设)

### 6.1 新增字段

```python
@dataclass(frozen=True, slots=True)
class RuntimeActionEvent:
    event_id: str
    action_id: str
    action_type: RuntimeActionType | str
    source: str
    status: str
    evidence: Mapping[str, Any]
    parent_trace_id: str
    # B7 NEW:
    session_id: str = ""
    run_id: str = ""
    instance_id: str = ""
    timestamp: str = field(default_factory=now_iso)
```

### 6.2 Identity 传播路径

**关键安全约束**: identity 由 `dispatcher` 从 `RuntimeActionContext` 注入，**不**从 `request.payload` 读取。这防止 dogfood/harness 通过 payload 字段伪造 identity provenance。与 `dispatcher_origin` / `core_entrypoint` 的防伪模式一致。

```
main.py: session_id = str(uuid4())
  → chat(session_id=session_id)
    → run_id = str(uuid4())  # 每次 chat() 调用生成
    → RuntimeIdentity(session_id=session_id, run_id=run_id, instance_id=session_id)
    → _build_loop_context(runtime_identity=identity)
      → LoopContext.runtime_identity = identity
        → run_main_loop()
          → LoopDependencies.runtime_identity = identity  # 从 LoopContext 复制
            → _try_phase1_turn_end_runtime_action()
              → dispatcher.route_from_runtime_loop(request, identity=identity)
                → _route(request, identity=identity, ...)  # identity 来自 dispatcher 参数
                  → RuntimeActionContext(identity=identity, ...)  # 注入 context
                  → RuntimeActionEvent(session_id=identity.session_id, run_id=identity.run_id, instance_id=identity.instance_id)
```

**route_from_runtime_loop() 新增参数**:

```python
def route_from_runtime_loop(
    self,
    request: RuntimeActionRequest,
    *,
    core_entrypoint: str = "core.chat",
    runtime_hook_name: str = "loop.turn_end",
    identity: RuntimeIdentity | None = None,  # B7 NEW
) -> RuntimeActionResult:
```

**ToolRuntimeMediator 中的调用**:
mediator 在 `__init__` 时接收 `identity: RuntimeIdentity`，在 `_route_gate()` / `_route_invoke()` / `_route_result()` 中传入 `dispatcher.route_from_runtime_loop(..., identity=self._identity)`。mediator 从 `LoopDependencies` 获取 identity，与 mediator 被构造时的 turn 上下文一致。

### 6.3 单独 Route 调用方的兼容

不经过 `run_main_loop()` 的 CLI/legacy 路径（如 `CLI_SHOW_MEMORIES`）使用 `dispatcher.route()` 而非 `route_from_runtime_loop()`。这些路径产生的 RuntimeActionEvent 中 identity 字段为空字符串 `""`。

这**不是** breakage——CLI meta-command 本身就是 CLI-ONLY / DEMO-ONLY 的，不需要多实例支持。

---

## 7. Implementation Roadmap

### Slice 1: Identity Foundation (P1-4 + P2-4)

**目标**: RuntimeIdentity 值对象 + 注入路径 + SESSION_ID 迁移

**文件**:
- NEW: `agent/runtime_identity.py` — RuntimeIdentity dataclass
- MODIFY: `agent/runtime_integration/schema.py` — RuntimeActionEvent 新增 identity 字段
- MODIFY: `agent/logger.py` — 移除 import-time SESSION_ID
- MODIFY: `agent/core.py` — chat() 入口生成 RuntimeIdentity → 传入 LoopContext
- MODIFY: `agent/loop_context.py` — LoopContext 新增 runtime_identity 字段
- MODIFY: `agent/loop.py` — LoopDependencies 新增 runtime_identity；turn-end hook 传入 identity
- MODIFY: `agent/runtime_integration/dispatcher.py` — _route() 从 context 提取 identity 写入 RuntimeActionEvent
- MODIFY: `agent/session.py` — 接收显式 session_id 参数而不是 import SESSION_ID
- MODIFY: `main.py` — startup 时生成 session_id

**测试**: ~10 focused tests
**Gate**: 现有全部 tests PASS + ruff clean + git diff --check

### Slice 2: Namespace Injection (P1-1 + P1-2 + P2-1 + P2-2)

**目标**: 所有 module-level singleton 支持 namespace 隔离

**文件**:
- MODIFY: `agent/skill_system/lifecycle.py` — `_default_lifecycle` → `get_default_lifecycle(session_id)`
- MODIFY: `agent/memory_store.py` — `InMemoryMemoryStore(namespace)` 参数
- MODIFY: `agent/core.py` — `_memory_runtime` → 每次 chat() 创建或通过 namespace 隔离
- MODIFY: `agent/mcp_bridge.py` — session-scoped registry
- MODIFY: `agent/tool_runtime_mediator.py` — 接收 `runtime_identity` 参数

**测试**: ~12 focused tests
**Gate**: 现有全部 tests PASS + ruff clean

### Slice 3: Checkpoint Namespace (P1-3)

**目标**: per-run checkpoint storage + schema v2

**文件**:
- MODIFY: `agent/checkpoint.py` — per-run 路径 + v2 schema + v1 回退兼容
- MODIFY: `agent/session.py` — resume 时使用新路径
- MODIFY: `agent/core.py` — `_dispatch_checkpoint_save()` 传入 identity

**测试**: ~8 focused tests + checkpoint 兼容性测试
**Gate**: 现有 checkpoint tests PASS + v1→v2 迁移测试 PASS

### Slice 4: Event Log (P2-3)

**目标**: append-only JSONL event log + redaction

**文件**:
- NEW: `agent/event_log.py` — EventLogWriter + redact 逻辑
- MODIFY: `agent/runtime_integration/dispatcher.py` — `flush_to_event_log()` 方法
- MODIFY: `agent/loop.py` — turn-end hook 中调用 flush
- MODIFY: `main.py` — 创建 EventLogWriter 并注入

**测试**: ~8 focused tests + redaction 测试
**Gate**: 现有全部 tests PASS + ruff clean

### Slice 5: Integration & Guard Tests

**目标**: 端到端多 run 隔离验证 + contract tests

**文件**:
- NEW: `tests/test_b7_multi_instance_readiness.py` — 多 run 不交叉污染验证
- NEW: `tests/test_b7_identity_injection.py` — identity 传播链完整性验证
- NEW: `tests/test_b7_namespace_isolation.py` — checkpoint/memory namespace 隔离验证

**测试**: ~15 integration tests
**Gate**: 全部新 tests PASS + 全部回归 tests PASS

---

## 8. Safety / Redaction Policy

### 8.1 设计原则

1. **内存中不 redact** — evidence 在内存中保留完整字段用于 runtime 决策
2. **写入前 redact** — EventLogWriter 是唯一 redact 执行点
3. **TUI 只读** — TUI 只能 tail JSONL，不能写入
4. **白名单优于黑名单** — 明确列出哪些字段类型需要 redact

### 8.2 Redact 字段列表

| 字段名模式 | Redact 为 | 匹配方式 |
|-----------|----------|---------|
| `*api_key*` | `"<REDACTED>"` | 大小写不敏感 glob |
| `*token*` | `"<REDACTED>"` | 大小写不敏感 glob |
| `*secret*` | `"<REDACTED>"` | 大小写不敏感 glob |
| `*password*` | `"<REDACTED>"` | 大小写不敏感 glob |
| `*authorization*` | `"<REDACTED>"` | 大小写不敏感 glob |
| `*api_key_env*` | `"<REDACTED>"` | 大小写不敏感 glob |
| 值匹配 `Bearer *` | `"Bearer <REDACTED>"` | 正则 |
| 值匹配 `sk-*` (40+ chars) | `"<REDACTED>"` | 正则 (OpenAI key pattern) |

### 8.3 检测机制

- EventLogWriter 在写入前对所有字段名和值执行 redact 检查
- 如果 payload 中有字段被 redact，在 event 的 `redacted` 数组中记录字段名
- 单元测试验证：包含 secret-like 字段的 payload 写入后字段值必须为 `<REDACTED>`

---

## 9. Phase Transition Gates

每个 Slice 完成后必须通过以下 gate 才能进入下一个 Slice：

1. focused tests PASS（Slice-specific new tests）
2. full regression: `python -m pytest tests/ -x --timeout=60` PASS
3. ruff check: `ruff check agent/` clean
4. git diff --check clean
5. mypy/pyright: 不新增 type error
6. docs 更新（PROJECT_STATUS / PROGRESS_LEDGER）
7. commit/push

**Failed gate retry limit**: 同一 Slice 内同一 gate 失败最多 retry 2 次；第 3 次失败 → HARD_STOP。

---

## 10. HARD_STOP Conditions

- HEAD != origin/main
- 需要读取或打印 secret
- 需要处理真实私人数据
- 需要调用真实 API（除已授权的 provider）
- 需要 destructive command
- 需要新增第二 runtime
- 需要让 TUI 成为默认入口
- 同一 gate 连续失败 >= 3 次
- 回归测试大面积失败（>= 5 个不相关测试）
- context 低于 10%

---

## 附录 A: 文件变更预估

| Slice | 新增文件 | 修改文件 | 测试增量 | 代码增量 |
|-------|---------|---------|---------|---------|
| Slice 1 | 1 | 8 | ~10 | ~150 lines |
| Slice 2 | 0 | 6 | ~12 | ~200 lines |
| Slice 3 | 0 | 3 | ~8 | ~120 lines |
| Slice 4 | 1 | 3 | ~8 | ~150 lines |
| Slice 5 | 3 | 0 | ~15 | ~250 lines |
| **总计** | **5** | **20** | **~53** | **~870 lines** |

## 附录 B: B8 前置依赖满足清单

B7 交付后，以下 B8 Phase 6B/7 的前置条件将被满足：

| B8 需求 | B7 提供的契约 |
|---------|-------------|
| Phase 6B session/run/instance identity model | `RuntimeIdentity` + identity 字段传播到所有 event |
| Phase 6B evidence namespace | namespace 隔离 + per-session event log |
| Phase 6B multi-run storage | per-run checkpoint + `sessions/{session_id}/` 目录结构 |
| Phase 7 append-only event source | JSONL EventLogWriter + write-only contract |
| Phase 7 event ownership | session_id/run_id 在所有 event 中 |
| Phase 7 TUI read-only tail | TUI 只读 JSONL，不写入 |
