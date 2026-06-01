# B7 Multi-Instance Readiness TDD Plan

**创建日期**: 2026-06-01
**依赖**: [b7-multi-instance-readiness-sdd.md](../design/b7-multi-instance-readiness-sdd.md)

---

## 0. Test Strategy

**原则**:
1. 每个 Slice 先写 RED test，再写 implementation
2. 所有新 test 必须以 focused test file 形式存在，不散落
3. 不修改已有 test 的断言语义（除非 test 本身与 B7 架构变更矛盾）
4. 回归测试必须在每个 Slice 完成后全量通过

**Test file 命名**: `tests/test_b7_{slice_name}.py`

---

## Slice 1: Identity Foundation

**Test file**: `tests/test_b7_identity_foundation.py`

### RED-1.1: RuntimeIdentity 值对象

| # | Test | 断言 |
|---|------|------|
| 1.1.1 | `test_runtime_identity_creation` | session_id/run_id/instance_id 正确存储；instance_id 默认 = session_id |
| 1.1.2 | `test_runtime_identity_frozen` | dataclass 不可变（frozen=True） |
| 1.1.3 | `test_runtime_identity_slots` | 使用 __slots__，无法动态添加属性 |

### RED-1.2: RuntimeActionEvent identity 字段

| # | Test | 断言 |
|---|------|------|
| 1.2.1 | `test_event_default_identity_empty` | 新 RuntimeActionEvent() 的 session_id/run_id/instance_id 默认为 "" |
| 1.2.2 | `test_event_with_identity` | 传入 identity 后 event.session_id == expected |
| 1.2.3 | `test_existing_event_construction_unbroken` | 现有构造方式（不传 identity 字段）仍然有效 |

### RED-1.3: SESSION_ID 迁移

| # | Test | 断言 |
|---|------|------|
| 1.3.1 | `test_logger_no_import_time_session_id` | `agent.logger` 不再有模块级 SESSION_ID 属性（或标记为 deprecated） |
| 1.3.2 | `test_session_id_generated_in_main` | main.py startup 时生成 session_id（非 import-time） |

### RED-1.4: RuntimeIdentity 注入到 LoopContext

| # | Test | 断言 |
|---|------|------|
| 1.4.1 | `test_loop_context_has_identity` | LoopContext 有 runtime_identity 字段 |
| 1.4.2 | `test_chat_injects_identity_into_loop_context` | chat() 调用后 LoopContext 包含正确的 session_id/run_id |

### RED-1.5: Identity 写入 RuntimeActionEvent

| # | Test | 断言 |
|---|------|------|
| 1.5.1 | `test_dispatcher_route_writes_identity_to_event` | route_from_runtime_loop() 产生的 event 有正确的 identity 字段 |
| 1.5.2 | `test_direct_route_identity_empty` | dispatcher.route() 产生的 event 的 identity 字段为 ""（向后兼容） |
| 1.5.3 | `test_identity_not_from_payload` | 即使 request.payload 中有 _identity，event 的 identity 也只来自 dispatcher 参数 |

---

## Slice 2: Namespace Injection

**Test file**: `tests/test_b7_namespace_injection.py`

### RED-2.1: ActiveSkillLifecycle namespace

| # | Test | 断言 |
|---|------|------|
| 2.1.1 | `test_lifecycle_namespace_isolation` | 两个不同 namespace 的 lifecycle 实例互不影响（activate skill A in ns1，ns2 仍为 None） |
| 2.1.2 | `test_get_default_lifecycle_returns_namespaced` | get_default_lifecycle(session_id="s1") != get_default_lifecycle(session_id="s2") |
| 2.1.3 | `test_get_default_lifecycle_default_backward_compat` | get_default_lifecycle() 无参数返回 "default" namespace 实例 |
| 2.1.4 | `test_lifecycle_allowed_tools_per_namespace` | ns1 activate skill 后有 allowed_tools，ns2 仍为空 |
| 2.1.5 | `test_lifecycle_to_dict_includes_namespace` | to_dict() 输出包含 namespace 字段 |

### RED-2.2: InMemoryMemoryStore namespace

| # | Test | 断言 |
|---|------|------|
| 2.2.1 | `test_store_namespace_isolation` | ns1 存入的记录 ns2 不可见 |
| 2.2.2 | `test_store_list_records_per_namespace` | list_records() 只返回本 namespace 的记录 |
| 2.2.3 | `test_store_default_namespace` | 不传 namespace 时使用 "default" |
| 2.2.4 | `test_store_forget_record_per_namespace` | ns1 的 forget 不影响 ns2 的同 key 记录 |

### RED-2.3: MCP bridge session-scoped

| # | Test | 断言 |
|---|------|------|
| 2.3.1 | `test_mcp_bridge_tools_registered_per_session` | 两个 session 的工具注册数独立 |
| 2.3.2 | `test_mcp_bridge_disabled_default_no_registry_leak` | disabled 模式不向 session registry 写入 |

### RED-2.4: Regressions

| # | Test | 断言 |
|---|------|------|
| 2.4.1 | `test_existing_skill_lifecycle_tests_pass` | 已有 skill lifecycle 测试全部通过 |
| 2.4.2 | `test_existing_memory_tests_pass` | 已有 memory store 测试全部通过 |
| 2.4.3 | `test_existing_mcp_tests_pass` | 已有 MCP bridge 测试全部通过 |

---

## Slice 3: Checkpoint Namespace

**Test file**: `tests/test_b7_checkpoint_namespace.py`

### RED-3.1: Per-run checkpoint path

| # | Test | 断言 |
|---|------|------|
| 3.1.1 | `test_checkpoint_path_includes_session_and_run` | checkpoint_path(session_id="s1", run_id="r1") → Path 包含 "s1/r1.json" |
| 3.1.2 | `test_checkpoint_save_creates_parent_dirs` | 自动创建 sessions/{session_id}/ 目录 |
| 3.1.3 | `test_two_runs_dont_overwrite` | run1 和 run2 的 checkpoint 在独立文件中 |

### RED-3.2: Schema v2

| # | Test | 断言 |
|---|------|------|
| 3.2.1 | `test_v2_schema_includes_identity` | checkpoint JSON 包含 session_id/run_id/created_at/updated_at |
| 3.2.2 | `test_v2_schema_includes_v1_fields` | v2 schema 包含 v1 所有字段（task/conversation/memory） |
| 3.2.3 | `test_v2_schema_version_field` | schema_version == "checkpoint.v2" |

### RED-3.3: v1 向后兼容

| # | Test | 断言 |
|---|------|------|
| 3.3.1 | `test_load_v1_checkpoint_does_not_crash` | 旧 memory/checkpoint.json 仍可加载 |
| 3.3.2 | `test_v1_checkpoint_missing_identity_defaults` | 加载 v1 checkpoint 时 session_id/run_id 使用默认值 |

### RED-3.4: Resume

| # | Test | 断言 |
|---|------|------|
| 3.4.1 | `test_resume_finds_latest_run` | 默认 resume 加载最新 session 的最新 run |
| 3.4.2 | `test_resume_specific_session_and_run` | 指定 session_id + run_id 时精确恢复 |

---

## Slice 4: Event Log

**Test file**: `tests/test_b7_event_log.py`

### RED-4.1: EventLogWriter

| # | Test | 断言 |
|---|------|------|
| 4.1.1 | `test_event_log_writer_append` | append() 后文件包含一行 JSON |
| 4.1.2 | `test_event_log_writer_appends_not_overwrites` | 两次 append → 文件有两行 |
| 4.1.3 | `test_event_log_writer_creates_dirs` | 自动创建父目录 |
| 4.1.4 | `test_event_log_writer_valid_jsonl` | 每行是合法 JSON，不含换行 |

### RED-4.2: Redaction

| # | Test | 断言 |
|---|------|------|
| 4.2.1 | `test_redact_api_key_in_value` | payload 中 "api_key": "sk-..." → "api_key": "<REDACTED>" |
| 4.2.2 | `test_redact_token_in_value` | payload 中 "token": "abc123" → "token": "<REDACTED>" |
| 4.2.3 | `test_redact_bearer_header` | "Authorization": "Bearer xxx" → "Authorization": "Bearer <REDACTED>" |
| 4.2.4 | `test_redact_records_field_names` | event 的 redacted 数组包含被 redact 的字段名 |
| 4.2.5 | `test_no_redact_in_memory_event` | RuntimeActionEvent 在内存中保留原始值（仅文件 redact） |

### RED-4.3: Turn-end flush

| # | Test | 断言 |
|---|------|------|
| 4.3.1 | `test_flush_writes_events_to_log` | flush_to_event_log() 将 action_log 中的 event 写入文件 |
| 4.3.2 | `test_flush_does_not_clear_action_log` | flush 后 action_log 仍在内存中（不改变现有行为） |
| 4.3.3 | `test_flush_best_effort_no_crash` | 写入失败不抛异常 |

---

## Slice 5: Integration & Guard Tests

**Test file**: `tests/test_b7_multi_instance_integration.py`

### RED-5.1: Multi-run 隔离

| # | Test | 断言 |
|---|------|------|
| 5.1.1 | `test_two_runs_independent_checkpoints` | run1 和 run2 各自 save/load 不互相覆盖 |
| 5.1.2 | `test_two_runs_independent_memory` | run1 的 memory 操作不影响 run2 |
| 5.1.3 | `test_two_runs_independent_lifecycle` | run1 的 skill activation 不影响 run2 |

### RED-5.2: Identity 传播链

| # | Test | 断言 |
|---|------|------|
| 5.2.1 | `test_full_identity_chain` | chat() → LoopContext → LoopDependencies → dispatcher route → RuntimeActionEvent，全链路 identity 一致 |
| 5.2.2 | `test_run_id_unique_per_chat_call` | 两次 chat() 调用产生不同 run_id |

### RED-5.3: Regression — 单实例行为不变

| # | Test | 断言 |
|---|------|------|
| 5.3.1 | `test_default_namespace_full_flow` | 不传 identity（default namespace）时全流程行为与 B7 前一致 |
| 5.3.2 | `test_existing_chat_api_unchanged` | chat(user_input) 最小调用签名仍有效 |

### RED-5.4: B8 契约验证

| # | Test | 断言 |
|---|------|------|
| 5.4.1 | `test_event_log_has_session_id` | JSONL 每行 event 包含 session_id 字段 |
| 5.4.2 | `test_event_log_has_run_id` | JSONL 每行 event 包含 run_id 字段 |
| 5.4.3 | `test_event_log_write_only_no_read_api` | EventLogWriter 没有 read 方法（只写） |
| 5.4.4 | `test_per_run_checkpoint_file_exists` | 每个 run 产生独立 checkpoint 文件 |

---

## Test Count Summary

| Slice | RED Tests | 预计新增 assertion 数 |
|-------|----------|---------------------|
| Slice 1 | 11 | ~33 |
| Slice 2 | 12 | ~36 |
| Slice 3 | 8 | ~24 |
| Slice 4 | 8 | ~24 |
| Slice 5 | 9 | ~27 |
| **总计** | **48** | **~144** |

---

## TDD Execution Order

每个 Slice 内按 RED 编号顺序执行：
1. 写当前 RED 的 test → 运行确认 FAIL
2. 写最小实现 → 运行确认 PASS
3. 继续下一个 RED

Slice 之间严格顺序（Slice 1 → 2 → 3 → 4 → 5），不并行。
