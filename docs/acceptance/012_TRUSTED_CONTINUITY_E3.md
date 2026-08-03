---
title: 012 Trusted Continuity - Real Provider E3 Protocol
type: acceptance
date: 2026-08-02
status: accepted-real-provider
---

# 012 Trusted Continuity — 真实 Provider E3

本文只描述 012 的真实 Provider 验收。离线 reference/MockTransport 是 E1/E2 证据，不能替代 E3。
E3 runner 使用 production HTTP adapter、静态 composition 和唯一 `AgentRuntime.run_turn`；临时
workspace/state root 中只执行一个 harmless file write/read，不调用 MCP、SubAgent、Scheduler 或外部
副作用工具。

## 显式配置合同

Runner 只读取以下四个名称，不搜索 `.env`、Claude/Codex 配置、shell history、Memory 或其他秘密路径：

- `FIRST_AGENT_E3_PROVIDER`：`openai_compatible` 或 `anthropic_compatible`
- `FIRST_AGENT_E3_BASE_URL`：provider base URL，不含 credential
- `FIRST_AGENT_E3_MODEL`：精确 API model name
- `FIRST_AGENT_E3_API_KEY`：credential value，只在 composition 内存中使用

示例中的 key 必须由 operator 在自己的 shell 中设置；不要把值写入本文或 receipt：

```bash
export FIRST_AGENT_E3_PROVIDER=openai_compatible
export FIRST_AGENT_E3_BASE_URL=https://provider.example
export FIRST_AGENT_E3_MODEL=exact-model-name
export FIRST_AGENT_E3_API_KEY='set-in-your-shell'

python scripts/run_012_e3.py | tee /tmp/first-agent-012-e3-receipt.json
```

Runner 不使用 ambient proxy（HTTP client `trust_env=False`），不跟随 redirect，并且只有在 durable
disclosure request 被 exact acknowledgement 后才发送第一条请求。

Kernel v1 按 `EXTENSION_CONTRACTS.md` 拒绝需要持久化 provider-specific opaque reasoning 的模式。
因此，当 `FIRST_AGENT_E3_PROVIDER=openai_compatible` 时，runner 通过 production provider config
显式发送 `thinking: {"type":"disabled"}`；默认 provider adapter 不添加该 vendor-specific 字段。
这与 DeepSeek OpenAI 格式的显式非思考模式合同一致，并避免在工具调用后引入第二条
`reasoning_content` 持久化/回放路径。Anthropic-compatible E3 不隐式改写其请求模式。

## 七条必须同时为 true 的 claim

成功 stdout 是一个单行 `first-agent-012-e3-receipt-v1` JSON，`claims` 必须包含：

1. `disclosure_zero_before_ack`
2. `direct_answer_has_no_goal`
3. `goal_persisted_before_effect`
4. `approved_effect_exactly_once`
5. `deterministic_evidence_verified_done`
6. `restart_same_goal_without_send`
7. `checkpoint_excludes_secret_header_and_system_prompt`

Receipt 只保留 provider family/model、destination digest、request count、Goal identity/revision、checkpoint
token、artifact digest 和上述 bool；不含 key、Authorization/header value、完整 system prompt、workspace
绝对路径或请求/响应正文。Runner 退出前会重新打开 checkpoint，并用 shared `GoalView` 证明同一
`VERIFIED_DONE` Goal/evidence 可只读投影且没有新增 Provider send。

## 停止标记

四项都未设置时必须准确输出：

```text
NEEDS_E3_CONFIG(stage=U8, required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)
```

部分配置或 bounded real attempt 失败时只输出一个 secret-free 类别：

```text
E3_BLOCKED(stage=U8, reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible>)
```

`NEEDS_E3_CONFIG` 和 `E3_BLOCKED` 都不是完成，也不能把 012 晋级为 real-provider accepted。

## 当前状态

- Offline reference：实现并通过（最终 test count 以 `012_EXECUTION_LOG.md` 的未截断门为准）。
- Production adapter harness：已实现；缺配置路径离线验证，不发生网络。
- Real Provider E3：**accepted**。2026-08-02 使用 official DeepSeek OpenAI endpoint 与
  `deepseek-v4-flash` 完成一次 bounded run，5 个 provider requests，七条 claim 全部为 true；
  无秘密 receipt 见 `012_TRUSTED_CONTINUITY_E3_RECEIPT.json`。
- Fresh independent review：**passed**。fresh Claude session
  `84efc22c-65ff-4506-af89-af42cb78c0e1` 基于本 receipt 与物化源码独立重跑 full gates，
  未发现 unresolved correctness/security P0/P1/P2 finding，并输出精确 marker
  `012_REVIEW_PASS`；完整记录见 `012_EXECUTION_LOG.md`。
