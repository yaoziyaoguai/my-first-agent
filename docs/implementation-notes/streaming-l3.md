# Streaming L3 实现笔记

Date: 2026-05-24

## 关键发现

`call_model()`（`agent/model_call.py`）已支持 streaming：当 `provider.supports_streaming=True` 时，自动调用 `provider.stream()` 并收集事件。流式事件只是没有存储并传递给 turn-end hook。

## 架构决策

**无需新增 branch point。** 流式事件数据已存在于 `call_model()` 中，只需：

1. 在 `call_model()` 中增加 `_streaming_events_out` 参数，将收集的事件外传
2. 在 `_run_main_loop()` 中创建共享列表，通过 lambda wrapper 传递
3. 在 `LoopDependencies` 中增加 `streaming_events` 字段
4. 在 turn-end hook 中序列化事件并 dispatch `STREAMING_PROVIDER_CALL`

## 实现清单

| 文件 | 变更 |
|---|---|
| `agent/model_call.py` | 新增 `_streaming_events_out` 参数，收集事件后外传 |
| `agent/core.py` | `_call_model` 签名增加 `_streaming_events_out`；`_run_main_loop` 创建共享列表并通过 lambda wrapper 传递；deps 增加 `streaming_events` + `provider_supports_streaming` |
| `agent/loop.py` | `LoopDependencies` 增加 `streaming_events: list` 字段；turn-end hook 增加 STREAMING_PROVIDER_CALL dispatch block |
| `agent/runtime_integration/phase1_hook.py` | 注册 StreamingProviderCallHandler |
| `agent/runtime_integration/streaming_provider.py` | 增加空事件防御检查（handler 不再对空列表调用 `collect_stream_response`） |

## 测试

`tests/runtime_integration/test_streaming_l3.py`：4 个 L3 测试，全部使用 FakeProvider 和 spy dispatcher。

- **T1**：turn-end hook → STREAMING_PROVIDER_CALL L3 evidence chain（`route_from_runtime_loop` 路径，`target_module=="StreamingProtocol"`，`target_catalog_allowed=True`，真实流式事件）
- **T2**：payload 中 `provider_supports_streaming=True`
- **T3**：流式事件序列化正确（含 final event 和 text_delta）
- **T4**：无真实 API/env 访问（`provider_external_call=False`）

## 关键技术细节

### Lambda wrapper（core.py）

`_call_model` 是模块级函数，无法闭包访问 `_run_main_loop` 的局部变量。解决方式：

```python
call_model=lambda ts, lc, _out=_streaming_events: _call_model(
    ts, lc, _streaming_events_out=_out
),
```

### 空事件防御

handler 在 events 列表为空时返回 `context.not_supported()`，不调用 `collect_stream_response()`（该函数在事件为空时会抛出 `ProviderResponseError`）。
