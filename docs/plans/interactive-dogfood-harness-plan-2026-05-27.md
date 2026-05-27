# Interactive Dogfood Harness Plan

**日期**: 2026-05-27
**状态**: completed — Phase 1-3 done, 14/14 PASS fake/local, 见 `docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md`
**基于**: 全局审计 Loop 3 推荐、PROJECT_STATUS next recommended loop

## 1. 为什么现在做

当前 real API dogfood（20 cases, 19 non-failing）有两个根本限制：

1. **多数 case 是 direct provider call**，不经完整 agent runtime
2. **零覆盖交互式路径**：y/n confirmation、resume、interrupt、tool/memory confirmation、checkpoint reload

这意味着当前 dogfood 无法证明用户最常遇到的交互模式是正常工作的。审计明确建议：在扩大 real API dogfood 前，必须先用 fake/local harress 建立交互式覆盖。

## 2. 核心原则

- **Fake-first**：默认使用 FakeProvider，不调用真实 API
- **Subprocess 驱动**：通过 `subprocess.Popen` 启动 `python main.py`，stdin 写入用户输入，stdout/stderr 读取输出
- **结构化断言**：每个 case 验证 expected output fragment、expected event type、expected state change，不只验证非空
- **不依赖真实 API**：所有 fake case 在无网络环境中可运行
- **Real API 为 opt-in**：仅在用户显式授权 + 设置 `enabled: true` 时运行

## 3. Case Matrix

### I-CONFIRM: y/n confirmation

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I01 | 工具确认 accept | "write a demo note" → y | tool 执行；输出包含 "created" 或 "written" |
| I02 | 工具确认 deny | "write a demo note" → n | tool 不执行；输出包含 "cancelled" 或 "skipped" |
| I03 | 记忆确认 accept | 先 retain 一段内容 → y | memory store 包含 retain 的内容 |
| I04 | 记忆确认 deny | 先 retain 一段内容 → n | memory store 不含 retain 的内容 |

### I-RESUME: checkpoint resume

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I05 | resume 后继续 | 输入一句话 → quit → 重新启动 → 继续 | session 恢复，上下文保留 |
| I06 | resume 后不继续 | 输入一句话 → quit → 重新启动 → 选 n | 开始新 session |

### I-INTERRUPT: Ctrl+C / interrupt

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I07 | 对话中 interrupt | 输入长 prompt → Ctrl+C | graceful handling，不 crash，不丢 session |
| I08 | interrupt 后可恢复 | interrupt 后继续输入 | agent 正常响应 |

### I-TOOL: tool confirmation 边界

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I09 | 高风险工具默认需确认 | 触发高风险工具 | 出现 confirmation prompt |
| I10 | 低风险工具无需确认 | 触发低风险工具 | 直接执行，无 confirmation |

### I-MEMORY: memory confirmation 边界

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I11 | retain → recall 闭环 | 要求记住 → 确认 → 新对话召回 | 召回内容包含记住的信息 |
| I12 | retain → forget 闭环 | 记住 → 忘记 → 尝试召回 | 不再出现已忘记内容 |

### I-STREAM: streaming/progress

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I13 | fake streaming chunk | 输入任意 prompt | 收到进度事件或分段输出（FakeProvider deterministic chunking） |
| I14 | 长响应不超时 | 触发较长响应 | 30s 内完成，无 timeout |

### I-SANITY: 安全/边界

| ID | Case | Input | Expected |
|----|------|-------|----------|
| I15 | empty response detection | 触发可能空响应的路径 | 不应返回完全空串 |
| I16 | 过长输入 | 超长 prompt | 合理截断或拒绝，不 crash |
| I17 | 特殊字符 | 含特殊字符的输入 | 正常处理，不 crash |
| I18 | 连续快速输入 | 3 条连续消息 | 全部正常处理 |

## 4. Expected Evidence

每个 case 输出：

```json
{
  "case_id": "I01",
  "status": "PASS | FAIL | CONCERN | BLOCKED",
  "duration_ms": 1234,
  "stdout_fragments": ["expected fragment 1", "expected fragment 2"],
  "events_observed": ["TOOL_EXECUTED", "MEMORY_PROPOSED"],
  "state_assertions": {
    "memory_store_size": 1,
    "session_exists": true
  },
  "errors": []
}
```

## 5. Implementation Phases

### Phase 1: Harness Scaffold（1 个脚本）

- 新增 `scripts/dogfood_interactive_harness.py`
- 功能：subprocess 管理、stdin 写入、stdout 读取、超时控制、exit code 捕获
- 不依赖真实 API
- 输入：case spec (YAML/JSON)
- 输出：structured results + console report
- 参考：`scripts/real_api_dogfood_sweep.py` 的结构，但用 subprocess 替代直接调用

### Phase 2: Fake-first Cases（实现 I01-I18）

- 所有 18 个 case 用 FakeProvider 实现
- 每个 case 有独立 spec：prompt、input sequence、expected output fragments、timeout
- 运行：`python scripts/dogfood_interactive_harness.py --mode fake`
- Gates：18/18 fake cases PASS

### Phase 3: Real API Opt-in（授权后）

- 仅当用户显式授权 + `config/config.yaml` 中 `enabled: true` 时运行
- 运行：`python scripts/dogfood_interactive_harness.py --mode real`
- 先跑小样本（I01-I06），逐步扩展
- 不过度调用真实 API

## 6. Harness Design

```
dogfood_interactive_harness.py
  ├── CaseSpec: prompt, inputs[], expected[], timeout_s
  ├── SubprocessRunner: Popen, stdin.write, stdout.read, poll, kill
  ├── CaseEvaluator: check output fragments, events, state
  ├── ReportGenerator: JSON + console summary
  └── main(): load specs → run cases → evaluate → report
```

### SubprocessRunner 关键行为

- 启动：`python main.py`（非交互式 stdin 模式或 `--shell` 模式待定）
- 超时：每个 case 30s，`kill()` 后标记 TIMEOUT
- 编码：UTF-8，ignore decode errors
- 环境：fake provider 默认，隔离 HOME（可选）
- 不在 subprocess 中读取 `.env` 或真实 config

### CaseEvaluator 判定规则

- PASS：所有 expected fragments 在 stdout 中找到 + 无 crash
- CONCERN：部分 fragments 缺失但无 crash
- FAIL：crash、timeout、exit code != 0
- BLOCKED：subprocess 无法启动

## 7. Gates

- `ruff check scripts/dogfood_interactive_harness.py`
- `python scripts/dogfood_interactive_harness.py --mode fake`（全部 18 case）
- `git diff --check`
- 不跑 full pytest（除非改动触及其他测试）

## 8. Stop Conditions

- subprocess 无法启动（环境问题）
- FakeProvider scripted scenario 不支持 case 所需行为
- 需要修改 runtime 核心逻辑（不是 harness 能解决的）
- 需要真实 API（除非用户显式授权 Phase 3）
- 读取/打印真实 API key

## 9. 不变更

- 不修改 `agent/core.py`、`agent/loop.py`
- 不修改 provider/config
- 不新增 RuntimeActionType 或 branch point
- 不修改 FakeProvider behavior
- 不新增第二条 runtime flow

## 10. References

- [全局审计 Loop 3 建议](../audit/global-readonly-audit-2026-05-27.md#loop-3interactive-dogfood-harness)
- [Real API dogfood sweep](real-api-full-dogfood-remediation-plan-2026-05-26.md)
- [PROJECT_STATUS](../PROJECT_STATUS.md)
