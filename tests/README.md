# tests/

> 本周（2026-04）从 3.5/2.5 开始爬 Tier 4 的第一块砖：集成测试 + 单元测试。

## 怎么跑

```bash
# 跑全部（推荐日常）
.venv/bin/pytest

# 看详细用例名
.venv/bin/pytest -v

# 只跑某一个文件
.venv/bin/pytest tests/test_main_loop.py -v

# 跑到第一个失败就停
.venv/bin/pytest -x
```

## 文件组织

| 文件 | 覆盖什么 |
|---|---|
| `conftest.py` | `FakeAnthropicClient`、`fresh_state` fixture、构造 `FakeResponse` 的 helper |
| `test_context_builder.py` | `build_execution_messages` / `build_planning_messages` 的 messages 结构不变量 |
| `test_tool_pairing.py` | `tool_use ↔ tool_result` 配对契约（序列化 / 占位 / 压缩切点） |
| `test_state_invariants.py` | `reset_task` 清字段的完整性 + "新增字段必须加进 allowlist" 的护栏 |
| `test_main_loop.py` | `chat()` 主循环：单步 / 工具循环 / 限流兜底 / 多 tool_use 占位 |
| `test_confirmation_flow.py` | 计划确认 / 工具确认的 y/n/feedback 三分支 + 幂等 |
| `test_checkpoint_roundtrip.py` | checkpoint 保存/恢复的 roundtrip + 旧 checkpoint 兼容 + 大 tool_result 截断 |
| `test_memory_and_tools.py` | `compress_history` 触发条件 + tool_registry 三种确认模式 + 异常兜底 |
| `test_semantics.py` | `is_current_step_completed` / `advance_current_step_if_needed` / `append_control_event` 的语义规则 |

## 本周这组测试能捕获到的 bug（做防御的**真实**损失）

- assistant 消息丢 tool_use 块 → 下轮 API 400
- 多 tool_use 阻断时其余块没补占位 → 下轮 API 400
- 压缩切点切断 tool_use/tool_result 配对 → 下轮 API 400
- `reset_task` 漏清某个字段（比如 `pending_tool`）→ 跨任务状态残留
- 工具抛异常没兜底 → 悬空 tool_use → 下轮 API 400
- 语义事件（"用户接受当前计划"）退化成裸 y/n → 模型困惑
- checkpoint 恢复时漏字段 → 限流计数被重置，mutex 失效
- 模型连续返回相同 tool_use → 限流兜底是否触发（对应上周 Kimi 死循环现场）

## 添加测试的原则

1. **被生产翻车过的每一类 bug，都值得一条回归用例**——否则同样的 bug 会再回来。
2. **测试的 docstring 要写清"这是在防什么"**——半年后别人（或你自己）读到能立刻明白。
3. **fake client 的 canned response 顺序要和真实调用顺序一致**——`FakeAnthropicClient` 会在响应用完时抛明确的 `AssertionError`，不会让你误以为"测试通过"。
4. **测试命名用现在时动词**："do X"、"return Y when Z"——不要用"test_feature_1"。

## 已知 xfail 的用例

- `test_step_block_skipped_when_status_done`——`build_execution_messages` 当前代码不检查 `status=='done'`。已用 `pytest.xfail` 显式标记为"已知缺口"。后续要么加回防御，要么保证进 done 的瞬间 reset_task。

## 未来要加的测试（按 ROADMAP）

- Property-based testing（hypothesis）——给 `_find_safe_split_index` 喂随机 messages，断言"永远不产生悬空配对"。
- 状态机全路径覆盖——枚举 `task.status` 所有转换，每条边一个用例。
- Prompt caching 生效验证——测 cache_read_input_tokens 是否随预期增长。
- Cost 追踪准确性——测 state.task.cost_usd 累加逻辑。
