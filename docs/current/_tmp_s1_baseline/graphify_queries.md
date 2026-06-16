# Graphify queries used (S1 baseline audit)

中间产物。记录本轮用 Graphify 做的 discovery 查询及其用途。Graphify 仅用于定位，
所有结论回到真实源码核验。

| Query | 目的 | 主要落点（已源码核验） |
|---|---|---|
| `graphify query "where is the CLI entrypoint and the main agent runtime loop ..."` | 定位入口/loop | main.py:637/335/195, core.py:763, session.py |
| `graphify query "inside core.chat how is the model provider resolved and where is provider.create called ..."` | provider 解析点 | core.py:763, core_contexts.py:53, model_call.py |
| `graphify query "where is provider.create called to produce the model response inside the runtime loop"` | 模型调用点（曾命中 history roadmap，已忽略） | model_call.py:66/83/92, core.py:1369 |
| `graphify query "multi-step task plan state progress tracking mark step complete task ledger"` | 任务状态/进度 | state.py:192, transitions.py:639, task_runtime.py:48 |
| `graphify query "tool result appended to conversation context and recorded in evidence ..."` | tool result 流转 | tool_runtime_mediator.py, dispatcher.py, conversation_events.py:116 |

备注：一次 provider 查询返回的 Start 节点是 `docs/history/.../CURRENT_ARCHITECTURE_REPAIR_ROADMAP.zh.md` 等历史节点，
已按"历史文档非 routing authority"忽略，改以源码为准。
