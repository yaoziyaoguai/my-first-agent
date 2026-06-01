# B7 Multi-Instance Readiness Implementation Plan

**创建日期**: 2026-06-01
**依赖**: [b7-multi-instance-readiness-sdd.md](../design/b7-multi-instance-readiness-sdd.md) + [b7-multi-instance-tdd-plan.md](b7-multi-instance-tdd-plan.md)

---

## Implementation Units

### U1: RuntimeIdentity 值对象 (Slice 1)

**File**: `agent/runtime_identity.py` (NEW)
**Execution note**: test-first

```python
@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    session_id: str
    run_id: str
    instance_id: str  # default = session_id (set in __post_init__)
```

**Verification**: RED 1.1.1-1.1.3 全部 PASS

---

### U2: RuntimeActionEvent identity 字段 (Slice 1)

**File**: `agent/runtime_integration/schema.py`
**Execution note**: test-first — 必须保证向后兼容（默认值 "")

新增字段：
```python
session_id: str = ""
run_id: str = ""
instance_id: str = ""
```

**Verification**: RED 1.2.1-1.2.3 全部 PASS + 已有 schema tests PASS

---

### U3: SESSION_ID 迁移 (Slice 1)

**Files**:
- `agent/logger.py` — 移除 `SESSION_ID = str(uuid.uuid4())`；保留 redact 正则
- `agent/session.py` — `init_session()` 接收显式 `session_id: str` 参数，不再 import SESSION_ID
- `main.py` — startup 时 `session_id = str(uuid4())`，传入 `init_session(session_id=session_id)`

**Verification**: RED 1.3.1-1.3.2 PASS + main.py 启动不报错

---

### U4: LoopContext + LoopDependencies identity 注入 (Slice 1)

**Files**:
- `agent/loop_context.py` — 新增 `runtime_identity: RuntimeIdentity | None = None` 字段
- `agent/loop.py` — LoopDependencies 新增 `runtime_identity` 字段
- `agent/core.py` — `chat()` 入口生成 RuntimeIdentity，传入 `_build_loop_context()`；`_run_main_loop()` 从 `loop_ctx.runtime_identity` 复制到 `LoopDependencies`

**chat() 变更**:
```python
def chat(user_input: str, *, session_id: str | None = None, ...) -> str:
    _session_id = session_id or str(uuid4())
    _run_id = str(uuid4())
    _identity = RuntimeIdentity(
        session_id=_session_id,
        run_id=_run_id,
        instance_id=_session_id,
    )
    _loop_ctx = _build_loop_context(..., runtime_identity=_identity)
```

**Verification**: RED 1.4.1-1.4.2 PASS

---

### U5: Dispatcher identity 传播 (Slice 1)

**Files**:
- `agent/runtime_integration/dispatcher.py`:
  - `route_from_runtime_loop()` 新增 `identity: RuntimeIdentity | None = None` 参数
  - `_route()` 新增 `identity` 参数
  - `RuntimeActionContext` 新增 `identity: RuntimeIdentity | None = None` 字段
  - `RuntimeActionEvent` 构造时从 `identity` 复制 session_id/run_id/instance_id

**Verification**: RED 1.5.1-1.5.3 PASS

---

### U6: ActiveSkillLifecycle namespace (Slice 2)

**File**: `agent/skill_system/lifecycle.py`
**Execution note**: `__init__` 已有 `namespace` 参数，B7 主要改模块级 registry

改动：
- 新增 `_lifecycle_registry: dict[str, ActiveSkillLifecycle] = {}`
- `get_default_lifecycle(session_id: str = "default")` → 按 session_id 查找/创建 lifecycle
- `_default_lifecycle` 模块级变量标记为 deprecated（保留向后兼容）
- 移除 `to_dict()` / `restore_from_dict()` 中的 namespace 字段（已有）

**Verification**: RED 2.1.1-2.1.5 PASS + 已有 lifecycle tests PASS

---

### U7: InMemoryMemoryStore namespace (Slice 2)

**File**: `agent/memory_store.py`
**Execution note**: 最小改动——内部 key 前缀

改动：
- `__init__(self, *, namespace: str = "default")` 新增参数
- 内部 dict 的 key 从 `record.id` 改为 `f"{namespace}:{record.id}"`
- `list_records()` 只返回匹配 namespace 的记录
- `remove_record()` 只在 namespace 内删除

**Verification**: RED 2.2.1-2.2.4 PASS

---

### U8: MCP bridge session-scoped (Slice 2)

**File**: `agent/mcp_bridge.py`
**Execution note**: 最小改动——模块级变量改为 dict

改动：
- `_mcp_bridge_tools_registered: int = 0` → `_mcp_bridge_registry: dict[str, int] = {}`
- `set_mcp_bridge_result(count, session_id="default")` → 按 session_id 存储
- `is_mcp_active(session_id="default")` → 按 session_id 查询
- `get_mcp_bridge_tools_registered(session_id="default")` → 按 session_id 查询

**Verification**: RED 2.3.1-2.3.2 PASS + 已有 MCP bridge tests PASS

---

### U9: Checkpoint per-run path + schema v2 (Slice 3)

**File**: `agent/checkpoint.py`
**Execution note**: 保留 v1 回退兼容

改动：
- 新增 `checkpoint_path(session_id: str, run_id: str) -> Path`:
  `PROJECT_DIR / "memory" / "checkpoints" / session_id / f"{run_id}.json"`
- `CHECKPOINT_PATH` 保留为 v1 legacy 路径
- `save_checkpoint(state, *, session_id="", run_id="", source="")`:
  - 如果 session_id/run_id 非空 → 写 v2 路径 + v2 schema
  - 如果为空 → 写 v1 路径 + v1 schema（向后兼容）
- `load_checkpoint(*, session_id="", run_id="")`:
  - 如果 session_id/run_id 非空 → 读 v2 路径
  - 如果为空 → 读 v1 路径（回退）
- Schema v2 在 v1 基础上新增 `schema_version`, `session_id`, `run_id`, `created_at`, `updated_at`

**Verification**: RED 3.1.1-3.4.2 PASS + 已有 checkpoint tests PASS

---

### U10: EventLogWriter (Slice 4)

**File**: `agent/event_log.py` (NEW)
**Execution note**: test-first, 不改变现有 dispatcher action_log

```python
class EventLogWriter:
    def __init__(self, session_dir: Path) -> None: ...
    def append(self, event: dict[str, Any]) -> None:
        # 1. redact secret fields
        # 2. append JSON line to events.jsonl
```

Redact 逻辑复用 `agent/logger.py` 中的 `_KEY_REDACT_RE` / `_BEARER_REDACT_RE`。

**Verification**: RED 4.1.1-4.2.5 PASS

---

### U11: Dispatcher flush_to_event_log (Slice 4)

**Files**:
- `agent/runtime_integration/dispatcher.py` — 新增 `flush_to_event_log(writer: EventLogWriter) -> int` 方法
- `agent/loop.py` — turn-end hook 中调用 `flush_to_event_log()`（如果 writer 存在）

**Verification**: RED 4.3.1-4.3.3 PASS

---

### U12: main.py EventLogWriter 注入 (Slice 4)

**File**: `main.py`

改动：
- startup 时创建 `EventLogWriter(session_dir=.../sessions/{session_id})`
- 注入到 LoopContext（新增 `event_log_writer` 字段）
- 不改变现有 main loop 流程

---

### U13: ToolRuntimeMediator identity 注入 (Slice 2 补充)

**File**: `agent/tool_runtime_mediator.py`

改动：
- `__init__` 新增 `identity: RuntimeIdentity | None = None` 参数
- `_route_gate()` / `_route_invoke()` / `_route_result()` 中传入 `identity=self._identity`
- `_route_gate()` 中的 `get_default_lifecycle()` 调用改为 `get_default_lifecycle(session_id=self._identity.session_id)`（如果 identity 非空）

**Verification**: 已有 mediator tests PASS + lifecycle namespace tests PASS

---

### U14: Integration tests (Slice 5)

**Files**:
- `tests/test_b7_identity_foundation.py` (NEW, ~11 tests)
- `tests/test_b7_namespace_injection.py` (NEW, ~12 tests)
- `tests/test_b7_checkpoint_namespace.py` (NEW, ~8 tests)
- `tests/test_b7_event_log.py` (NEW, ~8 tests)
- `tests/test_b7_multi_instance_integration.py` (NEW, ~9 tests)

**Verification**: 48/48 new tests PASS + full regression PASS

---

## File Manifest

| File | Action | Slice |
|------|--------|-------|
| `agent/runtime_identity.py` | CREATE | 1 |
| `agent/runtime_integration/schema.py` | MODIFY | 1 |
| `agent/logger.py` | MODIFY | 1 |
| `agent/session.py` | MODIFY | 1 |
| `agent/loop_context.py` | MODIFY | 1 |
| `agent/loop.py` | MODIFY | 1,4 |
| `agent/core.py` | MODIFY | 1,3 |
| `agent/runtime_integration/dispatcher.py` | MODIFY | 1,4 |
| `agent/skill_system/lifecycle.py` | MODIFY | 2 |
| `agent/memory_store.py` | MODIFY | 2 |
| `agent/mcp_bridge.py` | MODIFY | 2 |
| `agent/tool_runtime_mediator.py` | MODIFY | 2 |
| `agent/checkpoint.py` | MODIFY | 3 |
| `agent/event_log.py` | CREATE | 4 |
| `main.py` | MODIFY | 1,4 |
| `tests/test_b7_identity_foundation.py` | CREATE | 5 |
| `tests/test_b7_namespace_injection.py` | CREATE | 5 |
| `tests/test_b7_checkpoint_namespace.py` | CREATE | 5 |
| `tests/test_b7_event_log.py` | CREATE | 5 |
| `tests/test_b7_multi_instance_integration.py` | CREATE | 5 |

**总计**: 5 CREATE + 14 MODIFY = 19 files

---

## Execution Order

```
U1 (RuntimeIdentity) → U2 (Event identity) → U3 (SESSION_ID) → U4 (LoopContext)
    → U5 (Dispatcher) → U6 (Lifecycle) → U7 (MemoryStore) → U8 (MCP bridge)
    → U13 (Mediator) → U9 (Checkpoint) → U10 (EventLogWriter) → U11 (Flush)
    → U12 (main.py) → U14 (Integration tests)
```

Slice 边界：
- **Slice 1 gate**: U1-U5 完成 + tests PASS + ruff clean
- **Slice 2 gate**: U6-U8 + U13 完成 + tests PASS + ruff clean
- **Slice 3 gate**: U9 完成 + tests PASS + ruff clean
- **Slice 4 gate**: U10-U12 完成 + tests PASS + ruff clean
- **Slice 5 gate**: U14 完成 + full regression PASS + docs update

---

## Rollback

每个 Slice 独立 commit。如果 Slice N 的 gate 失败且无法在 2 次 retry 内修复：
1. `git stash` 当前 Slice 的未提交改动
2. 记录失败原因到 PROGRESS_LEDGER
3. HARD_STOP
