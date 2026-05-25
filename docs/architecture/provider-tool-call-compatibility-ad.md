# AD: Provider Tool-Call Compatibility

**Status**: accepted (2026-05-25)
**Scope**: provider adapter normalization boundary
**Type**: Architecture Decision

## Context

First Agent 通过 `agent/provider/` 层适配多种模型 provider（Anthropic 官方 API、Anthropic-compatible HTTP endpoints、OpenAI-compatible 等）。不同 provider 在工具调用格式上存在差异：

1. **流式 vs 非流式**: Anthropic 官方 SDK 支持 streaming tool_use；DashScope/kimi 等兼容 endpoint 的 Anthropic-style 接口不支持 streaming，只通过 `create()` 返回完整响应
2. **Tool 名称 namespace**: kimi-k2.5 @ DashScope 返回 `echo_task_summary`，去掉注册时的 `demo.` 前缀；其他 provider 行为待验证
3. **响应格式**: 官方 SDK 返回 Python objects，HTTP 兼容 endpoint 返回 dicts
4. **Tool input 编码**: 部分实现将 tool input 序列化为 JSON string

## Decision

### 1. 内部统一 ToolUseBlock

`agent/provider/protocol.py` 中的 `ToolUseBlock(frozen=True)` 是 **唯一的工具调用内部表示**：

```python
@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
```

Tool Pipeline（tool_executor.py / tool_registry.py）只消费 `ToolUseBlock`，不知道 provider 原始格式。

### 2. Provider Adapter 负责格式归一化

每个 provider adapter 负责把自身 response 格式归一化为 `ProviderResponse`：
- `normalize_anthropic_response()` — 处理 Anthropic-style dict/object 双形态
- `_normalize_tool_input()` — 处理 JSON-encoded string input
- 未来 `normalize_openai_response()` — 处理 OpenAI-style tool_calls

Tool Pipeline **禁止**感知 provider-specific format。所有 format normalization 必须在 `agent/provider/` 内完成。

### 3. Tool 名称后缀匹配是通用归一化

`_normalize_tool_name()` 使用后缀匹配（`reg_name.endswith(f".{name}")`）找回完整 tool 名称：

- **不是** kimi-specific hack — 任何 Anthropic-compatible provider 都可能做 namespace stripping（Anthropic 规范本身并不强制 namespace 前缀）
- 后缀匹配是确定性算法，不会产生歧义：如果多个注册名匹配同一个后缀，返回 None（fail-closed）
- 该函数位于 `tool_registry.py`（而不是 provider 层），作为 registry 的通用防御层：`execute_tool`、`needs_tool_confirmation`、`execute_single_tool` 的入口处统一调用

### 4. 流式/非流式差异由 call_model 处理

`model_call.py` 是 provider streaming capability 的唯一差异点：
- 流式 provider：走 `provider.stream()` → emit text deltas + tool_requested
- 非流式 provider：走 `provider.create()` → 检测 tool_use → emit tool_requested + text

两个分支最终产出相同的 RuntimeEvent 序列。Tool Pipeline 不感知此差异。

### 5. 何时允许 normalization / 何时禁止

| 行为 | 允许 | 原因 |
|------|------|------|
| Response format 归一化（dict → object） | ✅ | provider adapter 职责 |
| Tool input JSON string → dict | ✅ | Anthropic spec 要求 input 为 object |
| Tool name suffix matching | ✅ | 通用防御，不针对特定 provider |
| 硬解析普通文本为 tool_use | ❌ | 伪造工具调用，破坏证据链 |
| Runtime 内写 provider 特判 | ❌ | Tool Pipeline 必须 provider-agnostic |
| 为单个 provider 改 ToolUseBlock 语义 | ❌ | 破坏内部契约 |
| 绕过 Tool Pipeline 直接处理 tool result | ❌ | 破坏统一 runtime flow |

## Consequences

### 正面

- Tool Pipeline 保持 provider-agnostic，新增 provider 不需要修改核心路径
- 后缀匹配作为 registry-level defense，对所有 provider 均生效
- 流式/非流式差异封装在 `model_call.py` 一个文件中

### 风险

- 后缀匹配可能被两个不同 namespace 的 tool 歧义命中（已通过 fail-closed 缓解：歧义时返回 None，工具不可用）
- 非流式 provider 不返回 intermediate text deltas，用户体验略差于流式（已知 tradeoff，不在此 AD 解决）
- DashScope 未来可能改变 namespace 行为（外部分风险，通过 `_normalize_tool_name` 的确定性算法 + contract tests 缓解）

### 后续测试要求

- `tests/test_tool_name_normalization.py` — 覆盖后缀匹配、精确匹配、歧义、无匹配
- `tests/test_normalize_anthropic_response.py` — 覆盖 dict/object 双形态 + tool_use 提取
- `tests/test_model_call.py` — 覆盖 streaming / non-streaming 两条路径的 event 序列
- Dogfood E2E contract: 每个新增 provider type 必须通过 `scripts/dogfood_real_provider_e2e.py` 的四项测试

## Alternatives Considered

### A. 在 Tool Pipeline 中处理 tool name normalization

拒绝 — 破坏 pipeline purity，使 tool 执行感知 provider 细节。

### B. Provider adapter 注册时改写 tool name

拒绝 — tool name 是 registry 属性，不是 provider 属性。后缀匹配在 registry 层做一次比在每个 provider adapter 中重复更简单。

### C. 强制所有 provider 使用 namespace 前缀

拒绝 — Anthropic API 规范不强制 namespace，跨 provider 移植性才是正确目标。

## References

- `agent/provider/protocol.py` — ToolUseBlock / ProviderResponse 定义
- `agent/provider/normalize.py` — normalize_anthropic_response
- `agent/tool_registry.py` — _normalize_tool_name
- `agent/model_call.py` — 流式/非流式分支
- `scripts/dogfood_real_provider_e2e.py` — E2E contract tests
- `docs/dogfood/real-provider-e2e-report.json` — 4/4 PASS with kimi-k2.5 @ DashScope
