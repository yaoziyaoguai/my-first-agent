# Runtime v0.3 Manual Smoke Result

> 本文件记录 v0.3 release 前后的人工 smoke 结果，对应 `docs/V0_3_PLANNING.md`
> §4 完成标准第 3 条「至少一次真实人工 smoke」。

---

## 1. Smoke 范围

人工 smoke 覆盖以下 v0.3 落地能力：

- M1 启动屏（session header / health 单行 / resume 三态 / Skill experimental 文案）
- M2 `python main.py health` 与 `python main.py health --json`
- M3 启动屏 Skill 文案不再印 `/reload_skills`
- M4 `python main.py logs` tail / filter / 兜底脱敏
- 主对话循环（fake provider 默认 + anthropic provider 真实任务）

环境：本地 macOS Darwin，commit baseline `3aa32fe` (tag `v0.3.0`) →
patch `03d2347` 之后。命令均通过 `.venv/bin/python` 执行。

---

## 2. 结果摘要

| 场景 | 命令/操作 | 预期 | 实际 | 结论 |
|---|---|---|---|---|
| 启动屏 | `echo quit \| python main.py` | session header / health 单行 / resume 三态 / Skill experimental 字样 / 无 `/reload_skills` | 一致 | ✅ |
| 健康人类报告 | `python main.py health` | 每项 check 含 `current_value` / `path` / `risk` / `action`；warn/error 展开 | 一致 | ✅ |
| 健康 JSON | `python main.py health --json` | schema 稳定，含 `overall` + `checks.<name>.{status,...}` | 一致 | ✅ |
| 日志摘要 | `python main.py logs --tail 50` | 单行紧凑、隐藏 runtime_observer、无 raw secret | 一致 | ✅ |
| 日志过滤 | `python main.py logs --tool calculate` / `--event tool_executed` | 过滤生效，损坏行不崩 | 一致 | ✅ |
| 真实任务 | "5 天武汉宜昌旅游规划" via anthropic provider | final answer 完成任务 | **触发 protocol bug**（详见 §3） | ❌ → ✅ 已修复 |

---

## 3. 触发的 v0.3 patch · final answer / request_user_input 协议边界

### 3.1 现象

任务："5 天武汉宜昌旅游规划"。模型完成规划后，final answer 末尾写：

> 需要我帮你调整某些天数，或者提供更具体的酒店/餐厅推荐吗？

但**同一轮**响应里调用了 `mark_step_complete`。Runtime 按结构化信号正确
推进步骤、完成任务、清理 checkpoint，并输出「好的，任务已完成。」用户
体验：**问了我又不等**。

### 3.2 根因

- Runtime 状态机本身正确：`handle_tool_use_response` 按 `mark_step_complete`
  阈值推进，**不读** assistant 文本，正确依赖结构化信号。
- 漏洞在 prompt 层：`config.SYSTEM_PROMPT` 完全没声明：
  1. `request_user_input` 是 Runtime **唯一**识别的「等待用户输入」信号；
  2. final answer / `mark_step_complete` 同一轮**不要**写「需要我…吗？」
     这种待应答追问；
  3. 真正需要补充信息时**必须**调用 `request_user_input`，不要把追问混在
     final answer 里；
  4. 礼貌收尾应用「如后续需要调整，可以继续告诉我」类**非等待式陈述**。

模型不知道这条边界，所以即便 Runtime 正确，用户感受到的协议依然是断的。

### 3.3 修复（不是关键词 hack）

- 扩展 `config.SYSTEM_PROMPT` 末尾「## 用户输入与任务收尾协议」段，
  4 条规则 + ✅/❌ 正反例对照。
- `agent/model_output_resolution.py` 中
  `BLOCKING_USER_INPUT_PATTERNS` / `NON_BLOCKING_FOLLOWUP_PATTERNS`
  上方补 docstring，明确登记为 v0.1 历史兜底，**不再扩张**。
- 新建 `tests/test_final_answer_user_input_separation.py` 7 项协议级回归：
  prompt 必含语义关键词组合 / pattern 上限守护 / resolver 跨层一致性 /
  非等待式 closing phrase 识别。
- commit: `03d2347 fix(runtime): separate final answer from user-input requests`

### 3.4 为什么不是关键词 hack

- 没有新增任何关键词到 `BLOCKING_USER_INPUT_PATTERNS`；
- 没有为旅游场景硬编码任何业务句式；
- 测试用 size cap (≤23 / ≤22) 守护 pattern 列表不会回退成关键词黑名单；
- 测试断言的是「prompt 含语义关键词组合」「resolver 跨层一致」等结构化
  契约，而非具体那句中文。

### 3.5 验证

- `pytest tests/test_final_answer_user_input_separation.py -q` → 7 passed
- 全量 `pytest -q` → 676 passed, 3 xfailed（无回归）
- `ruff check agent/ tests/ llm run_logger.py main.py` → All checks passed
- 现有 `tests/test_meta_tool.py::test_request_user_input_clears_stale_mark_step_complete`
  已守护「同响应混合时 request_user_input 优先 + 步骤推进被压制」。

---

## 4. 防泄漏审计

`git ls-files` 复核：

```
.env.example                  # 模板，OK
memory/episodes/*.jsonl       # 学习记录，本地知识库
memory/rules/*.md             # 规则文档
其余源码 / 测试 / docs
```

**未提交**（受 `.gitignore` 保护）：`.env` / `state.json` / `summary.md` /
`agent_log.jsonl` / `runs/` / `sessions/` / `workspace/`（除已纳入的样例）。

`tests/test_gitignore_runtime_artifacts.py` 通过；
`tests/test_final_answer_user_input_separation.py` 等新增测试不打印任何
secret / raw prompt / raw completion。

---

## 5. 结论

v0.3 在 M1-M4 + cross-layer guards + final answer / request_user_input
协议边界 patch 全部完成后，已经达到 release readiness。

- 真实人工 smoke 通过（含一处协议层 bug 的发现 → 修复 → 复测闭环）
- pytest 全绿（676 passed, 3 永久 xfail，全部归属 v0.4+）
- ruff 0 错
- 防泄漏审计通过
