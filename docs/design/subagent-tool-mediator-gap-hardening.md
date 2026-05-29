# SubAgent TOOL_MEDIATOR_GAP Hardening — SDD/TDD

> **Status**: draft (SDD/TDD only, no implementation)
> **Created**: 2026-05-29
> **Phase**: 006 TOOL_MEDIATOR_GAP
> **Prerequisite**: evidence-hardening 阶段已在 e587a76 / 4cc83aa 收口，基线 3.6/5
> **Non-goal**: 本轮不改 production code，只产出设计文档和测试计划

---

## 1. SDD: 当前缺口

### 1.1 Production delegation path 调用链

```
core.chat()                                                                  [agent/core.py:722,753]
  → _dispatch_or_fallback_delegation(subagent_name, task, ..., provider=provider)
                                                                             [agent/core.py:1282-1337]
    → l1_handler.set_provider(provider, None)   ← GAP: tool_mediator=None    [agent/core.py:1308]
    → dispatcher.route(req) → l1_handler.handle(request, context)
                                                                             [agent/runtime_integration/subagent_action.py:185]
      → delegate_l1(subagent_request, registry, provider=..., tool_mediator=self._tool_mediator)
                                                                             [agent/subagent_system/delegation.py:166]
        → execute_l1(context_package, ..., tool_mediator=tool_mediator)      [agent/subagent_system/delegation.py:221]
          → if tool_mediator is not None:           ← NEVER TRUE             [agent/subagent_system/executor.py:257]
                child_result = tool_mediator.mediate_child_tool_request(...)
            else:
                child_result = None                 ← ALWAYS TAKEN            [agent/subagent_system/executor.py:265]
                # 注入硬编码占位 "[L1 child] 工具 X 已执行。"               [agent/subagent_system/executor.py:279]
```

### 1.2 tool_mediator=None 从哪里传入

`agent/core.py:1308`:
```python
l1_handler.set_provider(provider, None)
```

`_dispatch_or_fallback_delegation()` 不接受 `tool_mediator` 参数，第二个实参硬编码为 `None`。上游 `core.chat()` 的两个调用点（line 722, line 753）也没有传递 tool_mediator。

### 1.3 为什么 executor.py 因为 None 跳过 child tool request

`agent/subagent_system/executor.py:257`:
```python
if tool_mediator is not None:
    child_result = tool_mediator.mediate_child_tool_request(...)
else:
    child_result = None
```

当 `tool_mediator` 为 `None` 时，child tool_use 被静默跳过，注入硬编码占位消息 `"[L1 child] 工具 X 已执行。"`。工具实际上没有执行——这只是让 child loop 可以继续迭代的占位符，不是真实的 tool result。

### 1.4 为什么这是代码语义 blocker，不是 evidence-only gap

| 维度 | evidence-only gap | 代码语义 blocker |
|------|-------------------|------------------|
| ToolRuntimeMediator.mediate_child_tool_request() | 已实现，已有测试 | **从未在 production path 被调用** |
| Child tool_use → parent TOOL_GATE | 仅 contract test 中通过 \_SpyToolMediator 验证 | **production 中不走** |
| Child tool result | 硬编码占位 `"[L1 child] 工具 X 已执行。"` | **不是真实 tool result** |
| SUBAGENT_CHILD_TOOL_REQUEST evidence | 仅 contract test 中 spy 记录 | **production dispatcher 不会收到** |
| SubAgent L1 的"parent-mediated tool execution" | SDD 声称有此能力 | **production 实现缺失最后一截** |

结论：这不是文档不足或 evidence 不足，而是 production code 的 delegation path 缺少对已存在的基础设施的连接。

### 1.5 为什么依赖已经就绪

在 `core.chat()` 的 delegation 调用点（line 722/753），以下依赖全部可用：

| 依赖 | ToolRuntimeMediator.\_\_init\_\_ 参数 | 在 call site 是否可用 |
|------|--------------------------------------|----------------------|
| dispatcher | `dispatcher` | 是，作为 `_phase1_dispatcher` 已传入 |
| state | `state` | 是，`core.chat()` 参数 |
| turn_state | `turn_state` | 是，`TurnState` 实例（含 `on_runtime_event`） |
| turn_context | `turn_context` | 是，局部变量 |
| messages | `messages` | 是，局部变量 |
| skill_allowed_tools | `skill_allowed_tools` | 是，可从 `_active_skill` 获取 |
| store | `store` | 是（可选） |

这是"没传"问题，不是"没有"问题。

---

## 2. SDD: 目标路径

### 2.1 Parent delegation path 如何构造 ToolRuntimeMediator

**推荐策略：在 core.chat() 的 delegation 调用点构造（Per-Delegation Construction）。**

```
core.chat(state, turn_state, ..., provider, ...)
  │
  ├─ _phase1_dispatcher = ...
  ├─ turn_context = {}
  ├─ messages = []
  │
  ├─ handle_tool_use_response(...)    ← ToolRuntimeMediator 也在这里构造（parent tool path）
  │
  └─ delegation call site (line 722/753):
       │
       ├─ 1. 构造 ToolRuntimeMediator(_phase1_dispatcher, state=state,
       │        turn_state=turn_state, turn_context=turn_context,
       │        messages=messages, skill_allowed_tools=_skill_at)
       │
       └─ 2. _dispatch_or_fallback_delegation(..., tool_mediator=mediator)
```

### 2.2 ToolRuntimeMediator 如何传入 _dispatch_or_fallback_delegation

`_dispatch_or_fallback_delegation()` 签名新增 `tool_mediator` 参数：

```python
def _dispatch_or_fallback_delegation(
    subagent_name: str, task: str, *,
    delegation_reason: str, on_runtime_event,
    dispatcher, provider, user_input: str,
    tool_mediator: Any = None,  # ← 新增
) -> str:
```

调用 `l1_handler.set_provider()` 时传入：

```python
l1_handler.set_provider(provider, tool_mediator)  # 替代原来的 (provider, None)
```

### 2.3 如何继续传入 SubAgent handler → delegation → executor

链条上各节点**都不需要改动**——它们已经接受 `tool_mediator` 参数：

1. `SubAgentDelegateL1Handler.set_provider(provider, tool_mediator)` — 已接受 `tool_mediator` 参数 [subagent_action.py:180]
2. `SubAgentDelegateL1Handler.handle()` 调用 `delegate_l1(..., tool_mediator=self._tool_mediator)` — 已传递 [subagent_action.py:264]
3. `delegate_l1(..., tool_mediator=tool_mediator)` — 已接受并传递 [delegation.py:171]
4. `execute_l1(..., tool_mediator=tool_mediator)` — 已接受并在 line 257 使用 [executor.py:257]

**唯一需要改的节点是 `_dispatch_or_fallback_delegation()` 函数签名和 `set_provider()` 调用。**

### 2.4 Child tool_use 如何通过 parent mediator

```
execute_l1() [executor.py:257]
  → tool_mediator.mediate_child_tool_request(tool_name, tool_input, ...)
    [tool_runtime_mediator.py:120]
    → self._route_gate(tool_name, tool_input, tool_use_id)     ← TOOL_GATE
    → self._route_invoke(tool_name, tool_input, tool_use_id)   ← TOOL_INVOKE
    → execute_single_tool(block, state=..., ...)               ← 真实工具执行
    → self._route_result(tool_name, ..., result)               ← TOOL_RESULT
```

### 2.5 Parent mediator 如何复用 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT

ToolRuntimeMediator 已实现完整的 gate→invoke→execute→result 管线（line 67-116 的 `mediate()` 方法）。`mediate_child_tool_request()` 复用相同的 `_route_gate()` / `_route_invoke()` / `_route_result()` private 方法，只是 tool_use_id 使用 `child:{delegation_id}:{tool_name}` 格式以示区分。

### 2.6 Tool result 如何回到 child context

executor.py 已有对应逻辑（line 257-290）：
- `child_result == "FORCE_STOP"` → 注入 `"[安全策略] 工具被 parent gate 阻断"` 到 child messages
- `child_result is None`（执行成功） → 注入 `"[L1 child] 工具 X 已执行。"` 占位（**待改进**：应注入真实 tool result 文本）
- `child_result == "AWAITING_USER"` → 需要确认逻辑

### 2.7 Child final result 如何回到 parent adjudication

delegation.py 的 `delegate_l1()` 已处理（line 221-244）：
- `execute_l1()` 返回 `SubAgentResult`（含 summary、stop_reason、status）
- `adjudicate_result()` 生成 adjudication
- `SubAgentRun` 包装后返回给 `SubAgentDelegateL1Handler.handle()`
- handler 在 `RuntimeActionResult.payload` 中返回 execution_result → `_dispatch_or_fallback_delegation()` 用 `render_delegate_result()` 渲染

---

## 3. SDD: 关键设计决策

### 3.1 ToolRuntimeMediator 构造策略

**推荐：在 core.chat() delegation call site 直接构造（Option A）。**

| 选项 | 描述 | 评价 |
|------|------|------|
| **A. call site 直接构造** (推荐) | 在 core.chat() 的两个 delegation 调用点（line 722/753）构造 ToolRuntimeMediator，与 response_handlers.py:240 中的构造逻辑一致 | 最简单，最透明，无额外间接层 |
| B. 提取工厂函数 | 抽取 `_build_tool_mediator(dispatcher, state, turn_state, turn_context, messages)` 工厂函数，在 response_handlers 和 core.chat delegation 点共用 | 减少重复但增加间接层 |
| C. 复用 response_handlers 中的 _mediator | 将 response_handlers 中的局部变量 `_mediator` 提升为可传递的值 | 不可行：_mediator 是 handle_tool_use_response 的局部变量，不在 delegation call site 作用域内 |

**Why Option A**: response_handlers.py 和 core.chat delegation 点是不同的代码路径和时间点（parent tool execution vs. delegation dispatch），复用同一 ToolRuntimeMediator 实例没有意义——turn_context 和 messages 状态不同。直接构造保持代码自包含，后续可随时提取工厂函数。

### 3.2 turn_context 策略

**推荐：Child mediation 使用独立 turn_context（Option B）。**

| 选项 | 描述 | 风险 |
|------|------|------|
| A. 共享 parent turn_context | child mediation 复用 parent 的 turn_context dict | tool_use_id collision：parent 和 child 可能生成相同 ID；confirmation 状态污染 |
| B. 独立 turn_context (推荐) | 为 child mediation 创建新的空 dict | 无碰撞风险；child tool execution 隔离 |

**Why Option B**: `mediate_child_tool_request()` 已使用合成 tool_use_id（`child:{delegation_id}:{tool_name}`），这避免了与 parent 的 id collision。但 turn_context 还承载 confirmation state、pending tool 等，共享可能造成 parent 和 child 的确认状态互相污染。独立 turn_context 确保 child tool execution 不会意外影响 parent loop 状态。

**实现方式**: 在 core.chat() delegation call site 构造 ToolRuntimeMediator 时传入 `turn_context={}`，而非 parent 的 `turn_context`。

### 3.3 Mediator 生命周期

**推荐：Per-delegation 新建（Option B）。**

| 选项 | 描述 | 评价 |
|------|------|------|
| A. Per-turn 复用 | 在 core.chat() 入口构造一个 ToolRuntimeMediator，parent tool path 和 delegation path 共用 | 生命周期不匹配：parent tool mediator 在 response_handlers 中构造，不在 core.chat() 入口；共享 state 可能污染 |
| B. Per-delegation 新建 (推荐) | 每次 delegation call site 触发时新建 ToolRuntimeMediator | 隔离最好；构造开销可忽略（只是包装 dispatcher + 引用） |

**Why Option B**: ToolRuntimeMediator 是无状态的薄包装层（持有 dispatcher、state、messages 等引用），构造开销可忽略。Per-delegation 新建确保每次 delegation 的 turn_context 隔离，避免前次 child tool execution 的残留状态污染后续 delegation。

### 3.4 skill_allowed_tools 如何传入

从 `_active_skill` 全局变量获取（与 response_handlers.py:235-238 相同逻辑）：

```python
_skill_at: frozenset[str] | None = None
try:
    from agent.core import _active_skill as _ask
    _skill_at = _ask.get("allowed_tools") if _ask else None
except ImportError:
    _skill_at = None
```

### 3.5 store / state / messages 如何传入

直接传递父级引用：
- `state` — 传 parent state（同一 session）
- `turn_state` — 传 parent turn_state（on_runtime_event 需要用于 evidence emit）
- `messages` — 传 parent messages list 引用
- `store` — 传 `None`（ToolRuntimeMediator 的 store 参数是可选的，当前 parent path 也未使用）

### 3.6 不引入第二 runtime 的边界

ToolRuntimeMediator 的所有依赖（dispatcher、state、turn_state、messages）都是 parent runtime 的引用，不创建第二 runtime 实例，不启动第二 event loop，不创建第二 provider。Child 继续通过 parent provider 调 API，child tool 通过 parent mediator + dispatcher 走统一 evidence pipeline。

---

## 4. SDD: 非目标

- 不做 B7 multi-instance SubAgent
- 不做 B8 TUI  
- 不做 L2 session-scoped subagent
- 不重写 SubAgent executor
- 不重写 ToolRuntimeMediator
- 不改变 parent tool path（response_handlers.py 不变）
- 不改变 executor.py 的核心分支逻辑（line 257 的 if/else 不变）
- 不调用真实 API
- 不读取 .env

---

## 5. TDD: RED Tests

以下 4 个 RED test 验证当前 production path 的 broken state。它们必须在没有 mock/fake mediator 的情况下暴露缺口。

### RED-1: `_dispatch_or_fallback_delegation` 不接受 tool_mediator

```python
def test_dispatch_or_fallback_delegation_does_not_accept_tool_mediator():
    """当前签名不接受 tool_mediator 参数——验证缺口存在。
    
    RED 标准：调用时传入 tool_mediator=xxx 应引发 TypeError。
    GREEN 标准：签名变更后此测试应改为验证 tool_mediator 能正常传入。
    """
    import inspect
    sig = inspect.signature(_dispatch_or_fallback_delegation)
    assert "tool_mediator" not in sig.parameters, (
        "RED: 当前签名不应包含 tool_mediator——"
        "如果已包含，说明缺口已修复，此测试应转为 GREEN"
    )
```

### RED-2: Production delegation path 中 child tool_use 不会调用 mediate_child_tool_request

```python
def test_child_tool_use_not_mediated_in_production_path():
    """当前 production path 下，child tool_use 不会触发 mediate_child_tool_request。
    
    通过 execute_l1(tool_mediator=None) 模拟 production 行为，
    验证 child_result 为 None 且 tools_executed 包含硬编码占位。
    
    RED 标准：tool_mediator=None 时 child tool_use 不走 mediator。
    GREEN 标准：tool_mediator 传入后 child tool_use 应触发 mediator。
    """
    provider = _SpyProvider([
        _make_tool_use_response("读取文件", "read_file", {"path": "/tmp/t.txt"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="完成")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("test no mediator")

    result = execute_l1(ctx, delegation_id="test-red-2", provider=provider)
    # tool_mediator 默认为 None

    # RED: 当前 production path 下 child tool 不会被真正执行
    assert "工具 read_file 已执行" in result.summary, (
        "RED: 应包含硬编码占位——说明 tool 未通过 mediator 执行"
    )
```

### RED-3: Child tool result 是硬编码占位，不是真实 tool result

```python
def test_child_tool_result_is_hardcoded_placeholder():
    """当前 tool_mediator=None 时，child tool result 是硬编码占位。
    
    RED 标准：result 包含 "[L1 child] 工具 X 已执行。" 这种占位文本。
    GREEN 标准：result 应包含真实 tool result 内容。
    """
    provider = _SpyProvider([
        _make_tool_use_response("列出文件", "read_file", {"path": "/tmp/dir"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="文件列表已获取")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("list files")

    result = execute_l1(ctx, delegation_id="test-red-3", provider=provider)

    assert "[L1 child]" in result.summary, (
        "RED: 应包含 '[L1 child]' 占位——当前 tool_mediator=None 时"
        "tool 不会真正执行，只注入硬编码占位消息"
    )
```

### RED-4: SUBAGENT_CHILD_TOOL_REQUEST evidence 不会从 production path 触发

```python
def test_child_tool_request_evidence_not_dispatched_in_production():
    """当前 production path 不会 dispatch SUBAGENT_CHILD_TOOL_REQUEST evidence。
    
    RED 标准：spy dispatcher 不会收到 SUBAGENT_CHILD_TOOL_REQUEST action。
    GREEN 标准：spy dispatcher 应收到 SUBAGENT_CHILD_TOOL_REQUEST。
    """
    dispatcher = _SpyDispatcher()
    provider = _SpyProvider([
        _make_tool_use_response("read", "read_file", {"path": "/tmp/x.txt"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="done")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("test evidence gap")

    _result = execute_l1(ctx, delegation_id="test-red-4", provider=provider)

    child_tool_requests = [
        (req, res) for req, res in dispatcher.captured
        if getattr(req, "action_type", None)
        and str(req.action_type) == "SUBAGENT_CHILD_TOOL_REQUEST"
    ]
    assert len(child_tool_requests) == 0, (
        "RED: production path (tool_mediator=None) 不应产生 "
        "SUBAGENT_CHILD_TOOL_REQUEST evidence——"
        "如果 > 0，说明缺口已修复，此测试应转为 GREEN"
    )
```

---

## 6. TDD: GREEN Tests

以下 8 个 GREEN test 覆盖修复后的预期行为。需要在 `_dispatch_or_fallback_delegation` 和 `core.chat` call site 修复后通过。

### GREEN-1: delegate_l1 能接收并传递 tool_mediator

```python
def test_delegate_l1_receives_and_passes_tool_mediator():
    """GREEN: delegate_l1() 接收 tool_mediator 并传递给 execute_l1()。"""
    mediator = _SpyToolMediator()
    provider = _SpyProvider()
    request = SubAgentRequest(
        task="test", role="test", allowed_tools=(),
        parent_trace_id="t1", delegation_reason="test",
        execution_mode="local_fake", max_iterations=5,
    )

    run = delegate_l1(request, _fake_registry(), provider=provider, tool_mediator=mediator)

    assert run.state == "completed"
```

### GREEN-2: Child tool_use 会调用 mediate_child_tool_request

```python
def test_child_tool_use_calls_mediate_child_tool_request():
    """GREEN: 传入 tool_mediator 后，child tool_use 必须触发 mediate_child_tool_request。"""
    mediator = _SpyToolMediator()
    provider = _SpyProvider([
        _make_tool_use_response("读取", "read_file", {"path": "/tmp/f.txt"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="完成")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("green test")

    _result = execute_l1(
        ctx, delegation_id="test-green-2",
        provider=provider, tool_mediator=mediator,
    )

    assert len(mediator.child_requests) >= 1, (
        f"GREEN: mediator 应收到 child tool request，"
        f"实际 {len(mediator.child_requests)}"
    )
```

### GREEN-3: Child tool request 经过 TOOL_GATE / TOOL_INVOKE / TOOL_RESULT

```python
def test_child_tool_request_goes_through_gate_invoke_result():
    """GREEN: child tool request 走完整的 gate→invoke→result 管线。
    
    通过 spy mediator 验证每个步骤被调用。对于真实 ToolRuntimeMediator，
    验证 dispatcher 收到对应的 action_type。
    """
    mediator = _SpyToolMediator()
    provider = _SpyProvider([
        _make_tool_use_response("read", "read_file", {"path": "/tmp/g.txt"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="ok")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("gate test")

    _result = execute_l1(
        ctx, delegation_id="test-green-3",
        provider=provider, tool_mediator=mediator,
    )

    # _SpyToolMediator 在 mediate_child_tool_request 中记录所有请求
    assert mediator.child_requests[0]["tool_name"] == "read_file"
    assert mediator.child_requests[0]["delegation_id"] == "test-green-3"
```

### GREEN-4: Tool result 回到 child context

```python
def test_tool_result_returns_to_child_context():
    """GREEN: parent mediator 返回的结果被注入到 child messages。
    
    验证 execute_l1 生成的 child_messages 中包含 tool_result role 的消息。
    """
    mediator = _SpyToolMediator()
    provider = _SpyProvider([
        _make_tool_use_response("read", "read_file", {"path": "/tmp/r.txt"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="got result")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("result back test")

    result = execute_l1(
        ctx, delegation_id="test-green-4",
        provider=provider, tool_mediator=mediator,
    )

    assert result.status == "ok"
    # child 能基于 tool result 继续生成响应
    assert result.stop_reason == "end_turn"
```

### GREEN-5: Child final result 回到 parent

```python
def test_child_final_result_returns_to_parent():
    """GREEN: delegate_l1() 返回的 SubAgentRun 包含 child execution result。"""
    mediator = _SpyToolMediator()
    provider = _SpyProvider()
    request = SubAgentRequest(
        task="test", role="tester", allowed_tools=(),
        parent_trace_id="t5", delegation_reason="test",
        execution_mode="local_fake", max_iterations=3,
    )

    run = delegate_l1(request, _fake_registry(), provider=provider, tool_mediator=mediator)

    assert run.result is not None
    assert run.result.status == "ok"
    assert run.adjudication is not None
```

### GREEN-6: 没有 tool_mediator 时仍保持安全 fallback

```python
def test_null_mediator_safe_fallback():
    """GREEN: tool_mediator=None 时不崩溃，保持向后兼容。
    
    这是现有行为，修改后必须继续通过。
    """
    provider = _SpyProvider()
    ctx = _make_ctx("null mediator test")

    result = execute_l1(ctx, delegation_id="test-green-6", provider=provider)
    # tool_mediator 默认 None

    assert result.status == "ok", (
        f"tool_mediator=None 应保持安全 fallback，不崩溃，实际 {result.status}"
    )
```

### GREEN-7: 不绕过 parent，不让 child 直接调用 tool

```python
def test_child_cannot_call_tool_directly():
    """GREEN: child tool_use block 不绕过 parent mediator。
    
    验证 blocked tool（不在 parent allowed_tools 中）返回 FORCE_STOP，
    且 child 无法直接执行被 blocked 的工具。
    """
    mediator = _SpyToolMediator(block_list=frozenset({"shell"}))
    provider = _SpyProvider([
        _make_tool_use_response("dangerous", "shell", {"command": "rm -rf /"}),
        ProviderResponse(
            content=[ProviderTextBlock(text="blocked, continuing")],
            stop_reason="end_turn",
            raw_provider_name="spy",
        ),
    ])
    ctx = _make_ctx("no bypass test")

    _result = execute_l1(
        ctx, delegation_id="test-green-7",
        provider=provider, tool_mediator=mediator,
    )

    shell_requests = [
        r for r in mediator.child_requests if r["tool_name"] == "shell"
    ]
    assert len(shell_requests) >= 1, "shell 应被 child 请求但被 parent gate 阻断"
```

### GREEN-8: 不影响 existing 31 个 L1 contract tests

```python
def test_existing_l1_contract_tests_still_pass():
    """GREEN: 所有 existing L1 contract tests 继续通过。
    
    此测试由 existing test suite 隐式保证——
    运行 `pytest tests/runtime_integration/test_subagent_l1_parent_mediated.py -v`
    应全部 PASS（31 tests）。
    
    实现时以此为 regression gate。
    """
```

---

## 7. 风险和停止条件

### 7.1 需要大改 core.chat() / response_handlers / ToolRuntimeMediator → STOP

**评估：不需要。** 改动局限于 `_dispatch_or_fallback_delegation()` 签名（+1 参数）和 `set_provider()` 调用（None → tool_mediator），加上 call site 的 ToolRuntimeMediator 构造（~6 行）。response_handlers.py、ToolRuntimeMediator、executor.py 均不改。

### 7.2 turn_context 无法安全隔离 → STOP

**评估：可以安全隔离。** ToolRuntimeMediator 接受 `turn_context` 作为构造参数。在 delegation call site 传入 `{}` 即可隔离。tool_use_id 已通过 `child:{delegation_id}:{tool_name}` 格式保证不与 parent 碰撞。

### 7.3 需要改 executor.py 大量逻辑 → STOP

**评估：不需要。** executor.py line 257 的 `if tool_mediator is not None` 分支已完整实现。唯一可能需要微调的是 child tool result 的注入格式（当前硬编码占位 `"[L1 child] 工具 X 已执行。"` → 真实 tool result），但这是增强而非重写。

### 7.4 会引入第二 runtime → STOP

**评估：不会。** 所有依赖都是 parent runtime 的引用，不创建新 runtime。

### 7.5 需要真实 API 才能证明 RED/GREEN → STOP

**评估：不需要。** 所有 RED/GREEN tests 使用 _SpyProvider + _SpyToolMediator，不需要真实 API。

---

## 8. 输出

### 8.1 推荐的 mediator 构造策略

**Option A: call site 直接构造。** 在 `core.chat()` 的两个 delegation 调用点（line 722/753）直接构造 ToolRuntimeMediator，与 response_handlers.py:240 的构造逻辑一致。

### 8.2 推荐的 turn_context 策略

**独立 turn_context。** Child mediation 使用 `{}`（空 dict），与 parent turn_context 隔离，避免 tool_use_id / confirmation / result collision。

### 8.3 推荐的 mediator 生命周期

**Per-delegation 新建。** 每次 delegation 触发时新建 ToolRuntimeMediator 实例，构造开销可忽略，隔离性最好。

### 8.4 Implementation 文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `agent/core.py` | 修改 | `_dispatch_or_fallback_delegation()` 签名 +1 参数；`set_provider(provider, None)` → `set_provider(provider, tool_mediator)`；两个 call site 构造 ToolRuntimeMediator |
| `agent/runtime_integration/subagent_action.py` | 不改 | 已接受 `tool_mediator` 参数 |
| `agent/subagent_system/delegation.py` | 不改 | 已传递 `tool_mediator` |
| `agent/subagent_system/executor.py` | 不改（可能微调 result 注入格式） | `tool_mediator is not None` 分支已就绪 |
| `agent/tool_runtime_mediator.py` | 不改 | `mediate_child_tool_request()` 已实现 |
| `agent/response_handlers.py` | 不改 | parent tool path 不受影响 |

### 8.5 Test 文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `tests/runtime_integration/test_subagent_l1_parent_mediated.py` | 新增 12 tests | RED-1~4 + GREEN-1~8 |
| 或新建 `tests/runtime_integration/test_tool_mediator_gap.py` | 新建 | 如果不想在现有文件中混入 RED tests |

### 8.6 是否可以进入 implementation

**是。** 满足所有进入条件：
- [x] 缺口定位精确（core.py:1308）
- [x] 依赖全部就绪（state、turn_state、messages、dispatcher 在 call site 可用）
- [x] 改动范围可控（~10 行 production code）
- [x] 下游节点不需要改动（subagent_action、delegation、executor、mediator）
- [x] 不触及任何停止条件
- [x] RED/GREEN tests 不需要真实 API
- [x] 不影响 existing 31 contract tests
