# Memory Proposal Anchor E2E — Dogfood Plan

## 1. 概述

Dogfood 脚本复用 Phase 1 已建立的模式：通过 `scripts/dogfood_phase1_real_core_loop.py` 的变体，或新建最小 dogfood runner，在 fake/real 两种模式下分别验证 Memory Proposal Anchor 全链路。

Dogfood 不是测试替代品——它是对 TDD 测试的补充，提供人类可读的端到端验证报告。

## 2. Fake mode dogfood

### 2.1 命令

```bash
# 使用 Phase 1 已有脚本（已覆盖 memory proposal）：
HOME=/private/tmp/my-first-agent-phase1-home \
  PHASE1_REPORT_PATH=/private/tmp/phase1_memory_anchor_dogfood_report.txt \
  .venv/bin/python scripts/dogfood_phase1_real_core_loop.py
```

或新建专用 memory anchor dogfood：

```bash
HOME=/private/tmp/my-first-agent-phase1-home \
  .venv/bin/python scripts/dogfood_memory_anchor_fake.py
```

### 2.2 需要用户授权

**不需要**。fake mode 是无外部副作用的确定性运行。

### 2.3 输出报告位置

`/private/tmp/phase1_memory_anchor_dogfood_report.txt`

以及对应的 `.json` 文件：`/private/tmp/phase1_memory_anchor_dogfood_report.json`

### 2.4 如何判断 PASS

全部以下条件满足：

1. `chat()` 正常完成（不抛异常）
2. dispatcher `action_log` 至少包含 1 个 event
3. event 的 `evidence_level == "real_core_loop_runtime_e2e"`
4. event 的 `core_loop_invoked == true`
5. event 的 `core_entrypoint == "core.chat"`
6. event 的 `runtime_hook_name == "loop.turn_end"`
7. event 的 `target_module_proof` 非 `None`
8. event 的 `target_module == "MemoryPolicy"`
9. event payload 的 `auto_approved == false`
10. event payload 的 `not_confirmed == true`
11. event evidence 的 `provider_kind == "fake"`
12. event evidence 的 `external_side_effects == false`
13. report `errors` 列表为空

### 2.5 如何判断 FAIL

任一条件不满足即为 FAIL。

### 2.6 如何判断 PARTIAL

- dispatcher 被调用但 evidence_level 被降级到 `harness_runtime_e2e`（说明 hook 未正确注入 `core_loop_invoked`）
- `target_module_proof` 缺失但 `dispatcher_routed == true`（说明 handler 未通过 `context.invoke_registered_target` 调用）
- memory proposal 被触发但 `pending_review != true` 且原因合理（如 non-trigger 输入返回 `no_action`）

---

## 3. Real provider smoke dogfood

### 3.1 命令

```bash
# 需要用户明确授权后运行
HOME=/private/tmp/my-first-agent-phase1-home \
  MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 \
  PHASE1_REPORT_PATH=/private/tmp/phase1_memory_anchor_real_smoke_report.txt \
  .venv/bin/python scripts/dogfood_memory_anchor_real_smoke.py
```

### 3.2 需要用户授权

**必须。**

运行前必须确认：

1. 用户已设置有效的 `ANTHROPIC_API_KEY`（通过 `.env` 或环境变量）
2. 用户理解这会发起真实 API 调用，消耗 token
3. 用户已执行 `export MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1`

授权文字模板：

```text
⚠️  Real Provider Smoke 需要你的明确授权。

这会：
- 读取项目 .env 中的 ANTHROPIC_API_KEY（不打印到日志）
- 调用 Anthropic API（会消耗 token）
- 不会写 memory episodes
- 不会 auto approve memory
- 不会写 checkpoint
- 不会执行工具

如果同意，请执行：
  export MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1

然后重新运行 dogfood 命令。
```

### 3.3 输出报告位置

`/private/tmp/phase1_memory_anchor_real_smoke_report.txt`

以及对应的 `.json` 文件。

### 3.4 如何判断 PASS

在 fake mode PASS 条件基础上，额外要求：

1. event evidence 的 `provider_kind` 非 `"fake"`（是真实 provider 标记）
2. event evidence 的 `external_side_effects == true`
3. `chat()` 返回了真实 provider 的响应（非 FakeProvider 确定性输出）
4. stdout/stderr 不含 API key（`sk-ant-` 等 pattern）
5. `payload.auto_approved == false`（真实 LLM 也不能绕过 governance）
6. `payload.not_confirmed == true`

### 3.5 如何判断 FAIL

- API 调用失败（网络、认证、配额）
- `evidence_level` 不是 `real_core_loop_runtime_e2e`
- memory proposal 被 auto approved
- API key 出现在 stdout/stderr
- `chat()` 抛异常

### 3.6 如何判断 PARTIAL

- API 调用成功但 provider response 为空或不适合记忆（`no_action`）——路径通但无可记忆内容
- 网络重试后成功但 latency 异常——路径通但不稳定

---

## 4. 不需要做的事

- **不写 repo report**。所有报告写入 `/private/tmp`，除非用户明确要求写到 `docs/` 或 `reports/`
- **不 push report**。报告是临时产物，不入 git
- **不声称 full E2E**。这是 smoke，不是 full E2E

## 5. 与现有 dogfood 脚本的关系

| 脚本 | 验证范围 | Memory Anchor 状态 |
|------|----------|-------------------|
| `scripts/dogfood_phase1_real_core_loop.py` | fake provider → core.chat → dispatcher → memory proposal | **已覆盖 fake mode** |
| `scripts/dogfood_e2e_runtime.py` | harness → dispatcher（不经过 core.chat） | harness 级，不是 memory anchor |
| (new) `scripts/dogfood_memory_anchor_real_smoke.py` | real provider → core.chat → dispatcher → memory proposal | **real smoke，待新建** |

对于 fake mode，现有 `dogfood_phase1_real_core_loop.py` 已完全覆盖 Memory Anchor 的 fake provider 验证。real smoke 需要新建脚本。

## 6. 避免 overclaim

Dogfood 报告必须明确：

```text
Memory Proposal Anchor 验证结果：PASS / FAIL / PARTIAL

已验证：
- [x] core.chat 统一入口
- [x] run_main_loop turn-end hook 触发
- [x] RuntimeActionDispatcher.route() 调用
- [x] MemoryTurnEndProposalHandler 处理
- [x] target_module_proof 存在
- [x] evidence_level 正确分类
- [x] pending_review only / no auto approve
- [x] provider_kind 正确标记

未验证（不在本锚点范围）：
- [ ] Layer 2: memory approve/confirm/retain 流程（见 SPEC §8.2）
- [ ] Layer 3: memory recall/use（见 SPEC §8.2）
- [ ] ToolRegistry 集成
- [ ] Checkpoint 集成
- [ ] SubAgent 集成
- [ ] 多 turn 对话 memory 累积
- [ ] 跨 session memory 持久化
- [ ] Full real E2E（含工具执行）

Memory E2E 完整分层路线见 SPEC §8 和 TDD §4。
```
