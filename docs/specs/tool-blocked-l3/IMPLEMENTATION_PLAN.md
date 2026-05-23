# Implementation Plan: Tool Gate blocked L3

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)
Parent TDD: [TDD.md](TDD.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. 执行路径

本轮改动仅新增测试文件，零生产代码改动：

```
新增文件:
  tests/runtime_integration/test_tool_blocked_l3.py  (唯一产物)

不改动:
  agent/ 下所有模块 — 零改动
  tests/runtime_integration/ 已有文件 — 零改动
```

## B. 实现步骤

### Step 1: 创建测试文件骨架

参照 `test_tool_gate_not_found_l3.py` 的 pattern：
- `_PipelineSpy` 类（包裹 dispatcher，捕获 route_from_runtime_loop 调用）
- `FakeProvider`（不调真实 LLM API）
- 隔离 HOME 路径

### Step 2: 实现 T1 — shell-like blocked L3

```python
def test_t1_core_chat_shell_like_tool_blocked_l3():
    """core.chat() 传入 tool_gate_tool_name="bash" → TOOL_GATE rejected + L3"""
    # 1. 构建 _PipelineSpy(dispatcher)
    # 2. 调用 chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy,
    #              tool_gate_tool_name="bash")
    # 3. 断言 TOOL_GATE result:
    #    - status == "rejected"
    #    - evidence_level == "real_core_loop_runtime_e2e"
    #    - dispatcher_origin == "runtime_loop"
    #    - decision == "rejected"
    #    - rejection_reason == "shell-like tool is out of scope"
    #    - risk_level == "high"
    # 4. 断言 TOOL_INVOKE 不触发
    # 5. 断言 TOOL_RESULT 不触发
```

### Step 3: 实现 T2 — _ prefix blocked L3

```python
def test_t2_core_chat_underscore_tool_blocked_l3():
    """_blocked_tool 注册到 TOOL_REGISTRY → gate rejected + L3"""
    # 1. @register_tool(name="_blocked_tool", ...) 装饰空函数，注册到 TOOL_REGISTRY
    # 2. 构建 _PipelineSpy(dispatcher)
    # 3. 调用 chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy,
    #              tool_gate_tool_name="_blocked_tool")
    # 4. 断言 TOOL_GATE result:
    #    - status == "rejected"
    #    - evidence_level == "real_core_loop_runtime_e2e"
    #    - decision == "rejected"
    #    - rejection_reason == "internal tool is not in tool gate allowlist"
    # 5. 断言 TOOL_INVOKE 不触发
```

### Step 4: 实现 T3 — L2 downgrade

```python
def test_t3_direct_dispatcher_route_blocked_is_l2():
    """直接 dispatcher.route → L2，payload 伪造无效"""
    # 参照 test_tool_gate_not_found_l3.py::T3 pattern
```

### Step 5: 实现 T4 — no real API

```python
def test_t4_no_real_api_or_env_access():
    """隔离 HOME，验证不读 .env / 不调真实 API"""
```

### Step 6: 运行验证

```bash
HOME=/tmp/isolated-test-home .venv/bin/python -m pytest tests/runtime_integration/test_tool_blocked_l3.py -v
HOME=/tmp/isolated-test-home .venv/bin/python -m pytest tests/runtime_integration/ -q
```

## C. 风险分析

| 风险 | 可能 | 缓解 |
|------|------|------|
| T2 的 register_tool 污染 TOOL_REGISTRY 全局状态 | 中 | 在测试函数内注册，确保不影响其他测试；或使用 monkeypatch |
| _blocked_tool 误命中 _FORBIDDEN_TOOL_NAMES | 否 | "_blocked_tool" 不在 frozenset({"bash", "shell", "run_shell"}) |
| TOOL_REGISTRY 注册后残留影响其他测试 | 中 | 注册在测试函数作用域内，pytest fixture teardown 清理 |

## D. Open Decision

**T2 工具注册方式**：使用 `@register_tool` 在测试函数内注册，还是使用 pytest fixture？

推荐：在测试函数内直接调用 `register_tool`（非装饰器形式），或使用装饰器定义在测试函数内部的局部函数，确保作用域限定。

## E. Review Checklist

- [x] 零生产代码改动
- [x] 不新增 RuntimeActionType
- [x] 不新增 handler
- [x] 不新增 runtime flow
- [x] 测试只依赖现有 core.chat() + dispatcher + phase1_hook 基础设施
- [x] 可以进入实现
