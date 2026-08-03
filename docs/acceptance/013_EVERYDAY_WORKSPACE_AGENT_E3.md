---
title: 013 Everyday Workspace Agent - Real Provider E3 Protocol
type: acceptance
date: 2026-08-03
status: verified
---

# 013 Everyday Workspace Agent — 真实 Provider E3

## 1. 目的

本协议验证真实用户会走的 production path：一次 non-secret setup、在空/已有目录无参数启动、自然语言
ask/discussion/file task、上下文式 disclosure/approval、重启恢复和 evidence-backed completion。

FakeProvider、ScriptedProvider、MockTransport 和直接调用内部 Runtime 只属于 E1/E2，不能冒充本 E3。

## 2. 显式配置

Runner 只读取：

- `FIRST_AGENT_E3_PROVIDER`：`openai_compatible` 或 `anthropic_compatible`
- `FIRST_AGENT_E3_BASE_URL`
- `FIRST_AGENT_E3_MODEL`
- `FIRST_AGENT_E3_API_KEY`

不搜索或读取 `.env`、Claude/Codex 配置、shell history、Memory、workspace 私有文件或其他 credential
来源。Key 只在 composition 内存中使用，不写入 profile、checkpoint、receipt、stdout 或异常正文。

```bash
export FIRST_AGENT_E3_PROVIDER=openai_compatible
export FIRST_AGENT_E3_BASE_URL=https://provider.example
export FIRST_AGENT_E3_MODEL=exact-model-name
export FIRST_AGENT_E3_API_KEY='set-in-your-shell'

.venv/bin/python scripts/run_013_e3.py
```

OpenAI-compatible provider 如需关闭 opaque thinking continuity，runner 必须通过产品支持的显式
`thinking_mode=disabled`；不能另造 provider-specific replay path。

对 `openai_compatible`，harness 的产品 setup 固定启用显式 strict 配置：
`--request-path /chat/completions --strict-tools --thinking-mode disabled`。strict 是产品的显式
opt-in profile 字段，不是 host 对 base URL/model 的启发式推断。

## 3. 隔离与网络边界

- 每次 run 使用新临时 home、state root、empty workspace 和 existing workspace。
- 只连接显式 base URL；HTTP client `trust_env=False`、不跟随 redirect、有限时、非流式。
- 真实文件 effect 仅发生在临时 workspace；不调用 shell、MCP、SubAgent、Scheduler 或外部工具。
- runner 记录 request count 和 bounded response classification，不保存请求/响应正文或 header。
- 失败 receipt 只给 secret-free 类别。

## 4. 真实场景

### E3-J1 Ask and discuss

1. 在临时 state root 运行产品 setup 并证明 profile 无 key。
2. 在 empty workspace 走无参数 composition。
3. 提交一个稳定、无工具的简单问题。
4. disclosure 前 request count 为零；上下文式确认后才发送。
5. 再提交一个开放式讨论问题。
6. 两次均无 Goal、无文件 effect、无内部协议 copy 指令。

### E3-J2 Discussion to artifact

1. 先讨论一个小主题，不建立 Goal。
2. 明确要求把结论写入唯一相对路径 `notes/idea.md`。
3. Runtime 必须先持久化 Goal，再产生 write intent。
4. runner 以 CLI 的上下文式肯定回答确认 exact approval。
5. 文件写入后 read-back，mandatory criterion 得到 deterministic evidence，Goal 为 `VERIFIED_DONE`。
6. 成功路径没有用户“继续”动作。

### E3-J3 Existing workspace and restart

1. existing workspace 预置目标文件和两个 sentinel 文件并记录 digest。
2. 要求只更新目标文件的一段明确内容。
3. 在 effect 前的 durable Goal/approval 边界关闭进程并重新 composition。
4. 重启恢复同一 Goal，在用户确认前 request/tool count 不增加。
5. 完成后目标内容满足 criterion，两个 sentinel digest 不变。

unknown-effect 的 destructive simulation 继续由离线 deterministic reference test 负责；真实 E3 不通过杀死
未知 HTTP/file effect 制造不必要风险，但 receipt 必须引用对应离线 gate。

## 5. Receipt claims

成功 stdout 为一个 `first-agent-013-e3-receipt-v1` JSON；以下 claim 必须全部为 `true`：

1. `setup_profile_is_non_secret`
2. `no_argument_start_uses_saved_profile_and_cwd`
3. `disclosure_has_zero_sends_before_contextual_ack`
4. `ask_and_discuss_create_no_goal_or_file_effect`
5. `discussion_creates_goal_only_after_artifact_request`
6. `goal_is_durable_before_file_effect`
7. `contextual_approval_binds_exact_pending_request`
8. `artifact_is_read_back_and_verified_done`
9. `restart_recovers_same_goal_without_implicit_send_or_effect`
10. `existing_workspace_sentinels_are_unchanged`
11. `successful_journeys_require_no_continue_action`
12. `default_output_exposes_no_protocol_identifier_or_secret`

Receipt 只保存 schema、provider family/model、destination digest、request counts、sanitized journey verdicts、Goal
opaque digest、artifact/sentinel digests、offline recovery gate identity 和 claims。不得保存 key、env value、
Authorization、完整 base path、绝对 workspace/state path、请求/响应正文、system prompt、文件正文或内部
checkpoint JSON。

## 6. Stop markers

四项全部缺失且 U0-U7 离线门已经闭合时：

```text
NEEDS_013_E3_CONFIG(required=FIRST_AGENT_E3_PROVIDER,FIRST_AGENT_E3_BASE_URL,FIRST_AGENT_E3_MODEL,FIRST_AGENT_E3_API_KEY)
```

部分配置或 bounded attempt 失败时：

```text
013_E3_BLOCKED(reason=<incomplete_config|auth_failed|endpoint_unreachable|rate_limit_exhausted|provider_protocol|model_incompatible>)
```

二者都是暂停态。只有 receipt 全部 claims 为 true、完整 gates Green 且 fresh reviewer 输出
`013_REVIEW_PASS`，013 才完成。

## 7. Verified receipts（2026-08-03，official DeepSeek strict）

正式验收配置（全部显式，无 host 启发式）：

- Provider：`openai_compatible` / `deepseek-v4-flash`。
- Base URL：`https://api.deepseek.com/beta`；request path：`/chat/completions`；strict tools 启用；
  `thinking_mode=disabled`。receipt 只保存 destination digest
  `041d0bb552124d18995dbded8c2bd81bfac53ada9e42e6c35cca6c834bdff3c3`。
- 官方依据：DeepSeek Tool Calls（strict mode，beta）
  <https://api-docs.deepseek.com/zh-cn/guides/tool_calls/> 与 Create Chat Completion
  <https://api-docs.deepseek.com/api/create-chat-completion/>。

**此前基于普通端点 `https://api.deepseek.com`（destination digest `7f7852e0…`，observed
`2026-08-03T05:06:02.475673+00:00`）的单次通过观察已被取代**：普通 Tool Calls 模式不在合同上
保证 arguments 与 schema 一致（schema-valid arguments 仅由 strict 模式承诺），因此不再作为 013
的验收证据。

三次连续、未插桩的正式 strict run 全部 exit `0`，`first-agent-013-e3-receipt-v1` 的 12 项 claims
全部 `true`，三条 journey 全部 `passed`：

| Run | observed_at | request total | before first disclosure ack | before existing restart |
|---|---|---|---|---|
| 1 | `2026-08-03T07:39:28.151034+00:00` | 12 | 0 | 10 |
| 2 | `2026-08-03T07:40:14.636819+00:00` | 13 | 0 | 11 |
| 3 | `2026-08-03T07:41:03.676707+00:00` | 13 | 0 | 11 |

三次 run 的公共字段完全一致：artifact digest
`2f350abac5fbf31b8b7005bc39cab4b0e7eba03a03663e5e127fff6a943e31f6`；goal opaque digest
`ea8fce4dd44df753e3b61300f66c1f017b415a1ce81e8037cad5afdf4555ca80`；sentinel digests
`config.txt=20c44b5e4abfead4f44888cb3c55f6bfe1203c29297d4c0efb566e2789d5b499`、
`notes.txt=ed04bffc50a79f25c925dd54869ad1a6ab10aabb65b81211c38069943f2f86c4`。

最新一次（Run 3）完整 receipt：

```json
{
  "schema": "first-agent-013-e3-receipt-v1",
  "observed_at": "2026-08-03T07:41:03.676707+00:00",
  "provider": {
    "family": "openai_compatible",
    "model": "deepseek-v4-flash",
    "destination_digest": "041d0bb552124d18995dbded8c2bd81bfac53ada9e42e6c35cca6c834bdff3c3"
  },
  "request_counts": {
    "total": 13,
    "before_first_disclosure_ack": 0,
    "before_existing_workspace_restart": 11
  },
  "journeys": {
    "ask_and_discuss": "passed",
    "discussion_to_artifact": "passed",
    "existing_workspace_restart": "passed"
  },
  "goal_opaque_digest": "ea8fce4dd44df753e3b61300f66c1f017b415a1ce81e8037cad5afdf4555ca80",
  "artifact_digest": "2f350abac5fbf31b8b7005bc39cab4b0e7eba03a03663e5e127fff6a943e31f6",
  "sentinel_digests": {
    "config.txt": "20c44b5e4abfead4f44888cb3c55f6bfe1203c29297d4c0efb566e2789d5b499",
    "notes.txt": "ed04bffc50a79f25c925dd54869ad1a6ab10aabb65b81211c38069943f2f86c4"
  },
  "offline_recovery_gate": "tests/reference/test_012_trusted_continuity.py::test_j2_interrupted_executing_checkpoint_requires_unknown_effect_recovery",
  "claims": {
    "setup_profile_is_non_secret": true,
    "no_argument_start_uses_saved_profile_and_cwd": true,
    "disclosure_has_zero_sends_before_contextual_ack": true,
    "ask_and_discuss_create_no_goal_or_file_effect": true,
    "discussion_creates_goal_only_after_artifact_request": true,
    "goal_is_durable_before_file_effect": true,
    "contextual_approval_binds_exact_pending_request": true,
    "artifact_is_read_back_and_verified_done": true,
    "restart_recovers_same_goal_without_implicit_send_or_effect": true,
    "existing_workspace_sentinels_are_unchanged": true,
    "successful_journeys_require_no_continue_action": true,
    "default_output_exposes_no_protocol_identifier_or_secret": true
  }
}
```

API key 仅通过 `FIRST_AGENT_E3_API_KEY` 注入 harness 子进程环境，run 结束后由宿主清除；未写入
profile、checkpoint、receipt、命令行或任何文档。

真实试跑先后暴露并已 Red/Green 闭合的模型互操作缺口：模型不知道内部 evidence ref（精确 refs 投影进
`trusted_goal`）、复用 control correlation ID（schema 要求每次新 ID + 有界 repair）、偶发畸形
tool/control JSON（零副作用有界 Runtime retry）、strict 模型模仿历史回执调用（改为 trusted SYSTEM
回执投影，见 design §7.2）。最终三张 receipt 全部来自未加诊断 monkeypatch 的原始
`scripts/run_013_e3.py`。
