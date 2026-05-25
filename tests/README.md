# tests/

## 怎么跑

```bash
# 跑全部（推荐日常）
.venv/bin/pytest

# 看详细用例名
.venv/bin/pytest -v

# 只跑某一个文件
.venv/bin/pytest tests/test_provider_contract.py -v

# 跑到第一个失败就停
.venv/bin/pytest -x
```

## 测试分类与证据标签 (RT-16)

**标签规则：文件名和 docstring 必须诚实反映测试层级，不把 handler test 写成 E2E。**

| 层级 | 标签 | 覆盖范围 | 例子 |
|------|------|---------|------|
| Unit | 无特殊标签 | 单个函数/模块，mock 外部依赖 | `test_fake_provider_decision.py` |
| Integration | `integration` | 多个模块协作，无需真实 API | `test_provider_contract.py` |
| Handler | `handler` / `direct` | 单个 handler/dispatcher 行为 | `test_confirm_handlers.py` |
| E2E | `e2e`（仅在文件名中） | 全链路：入口 → core.chat → loop → 输出 | `test_first_usable_task_e2e.py` |
| Dogfood | `dogfood` | 手动/脚本验证，非自动化 CI | `scripts/dogfood_*.py` |
| Characterization | `characterization` | 保护当前行为不变，非验证正确性 | `test_command_boundary_characterization.py` |

**关键区分：**
- **Handler test** = 测试单个 handler 函数的输入/输出（如 `handle_tool_gate`），不经过 `core.chat()`
- **E2E test** = 测试完整 unified runtime flow（`core.chat()` → `loop.py` → `response_handlers` → `tool_executor`），经过统一入口
- Handler test 文件不应命名为 `*_e2e.py` 或在 docstring 中声称自己是 E2E

## 添加测试的原则

1. **被生产翻车过的每一类 bug，都值得一条回归用例**——否则同样的 bug 会再回来。
2. **测试的 docstring 要写清"这是在防什么"**——半年后别人（或你自己）读到能立刻明白。
3. **fake client 的 canned response 顺序要和真实调用顺序一致**——`FakeProvider` 会在响应用完时抛明确的错误。
4. **测试命名用现在时动词**："do X"、"return Y when Z"——不要用"test_feature_1"。
5. **不要给 handler test 起 E2E 名字**——handler test 是 handler test，E2E 是 E2E（RT-16）。

## 当前测试规模

全量 pytest（不含需要真实 API 的 opt-in tests）约 3380+ passed。核心覆盖：
- `tests/test_provider_contract.py` — provider adapter contract + dispatcher evidence parity
- `tests/test_command_boundary_characterization.py` — CLI meta-command 边界回归
- `tests/test_fake_provider_decision.py` — FakeProvider deterministic tool matching
- `tests/test_subagent_user_facing.py` — SubAgent delegation/registry/presentation
- `tests/test_memory_interaction.py` — memory inline confirmation + pending retain queue
- `tests/runtime_integration/` — Phase 1 dispatcher/handler/evidence 单元测试
- `tests/smoke/` — 端到端冒烟测试
