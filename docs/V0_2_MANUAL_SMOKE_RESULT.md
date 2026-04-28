# v0.2 RC 人工 Smoke 验收结果

本文件记录 Runtime v0.2 RC 在 commit `d7d2494` 之上完成的真实 main.py + Anthropic
端到端人工验收结论。配套自动化覆盖见 `tests/test_cli_output_ux.py`（18 tests），
契约定义见 `docs/CLI_OUTPUT_CONTRACT.md` §8.1，RC 决策见 `docs/V0_2_RC_DECISION.md`。

## 1. 验收结论

**v0.2 RC 没有 blocking 问题，可进入下一阶段。**

四类工具结局（success / failure / policy-rejected / user-rejected）在 CLI 上文案
互不混淆，安全拒绝路径不再被伪装成「执行完成」，resume 流不会因 idle 残留
checkpoint 强制 prompt。

## 2. 已通过的核心场景

| # | 场景 | 触发输入 | 实际 UI |
|---|---|---|---|
| 1 | 真实成功 | `算 21+21` | `tool.completed` + `执行完成。` + 结果 `42` |
| 2 | 工具失败 | `读取 /tmp/xxx.txt`（不存在） | `tool.failed` + `执行失败。` + 具体错误，**不再误报「执行完成」**，也不和安全拒绝混淆 |
| 3 | 项目外路径写入 | `写入 ~/v0_2_outside_test.txt` | 即使用户确认 `y`，依旧被工具内部安全检查拒绝，**没有真的写到项目外** |
| 4 | 敏感文件读取 | `读取 /tmp/server.pem` | `tool.rejected` + `被安全策略拒绝：...`，**不再误报「用户连续拒绝多次操作」**，也不泄漏文件内容 |
| 5 | 当前目录 user reject | 当前目录 write_file 触发确认时输入 `n` | `tool.user_rejected` + `用户拒绝执行，已跳过。` |
| 6 | feedback 触发 re-plan + cancel | 反馈「写到 tmp 下」→ 模型重新规划为 `/tmp/helloworld.txt` → 输入 `n` | feedback 走 `tool.user_rejected`（`用户未批准，改为提供反馈意见。`），re-plan 后再次 confirm，第二次 `n` 正常取消 |
| 7 | clean restart | 退出后重启 `main.py` | **没有裸 checkpoint dict 输出**，idle 残留被静默清理，直接进入对话 |

## 3. 仍保留的非阻塞观察项

以下项目在本轮人工验收中观察到，**不属于 v0.2 RC blocking**，留给后续 milestone：

- **`workspace_lint` 健康检查 warning**：启动时偶有 warning，不影响主流程。
- **`log_size` 健康检查 warning**：`agent_log.jsonl` 体量已 80MB+ / 18w+ 行，
  本轮已复核未发现真实 secret 泄漏（`grep sk-ant-[A-Za-z0-9_]{20,}` = 0），
  但需要后续引入日志轮转。
- **`session_accumulation` 健康检查 warning**：`sessions/` 已累积 100+ 快照，
  全部在 `.gitignore` 内，暂无 retention 策略。
- **Skill 提示文案偏强**：当前 system prompt 中 Skill 相关引导措辞偏强势，
  容易让模型反复尝试调用，可在后续微调，**不是 v0.2 blocking**。
- **基础 TUI**：仍是后续 milestone，本轮只覆盖 plain CLI 输出契约。
- **`/tmp/...` 写入路径**：本轮覆盖了 `/tmp/server.pem` 读取拒绝；写入到
  `/tmp/...` 的项目外路径行为可在后续补一次自动化或人工 smoke。

## 4. 不做的事（边界声明）

为避免 v0.2 RC 收口期间被误带入新功能，明确以下不在范围：

- 不引入 Reflect / Self-Correction / LLM judge / self-evaluation。
- 不引入 Skill / sub-agent / topic switch / slash command。
- 不引入 generation cancellation / Esc cancel / 完整 Textual TUI。
- 不重写 agent runtime 主循环，不大改日志系统。

## 5. push 前 review 建议

- 把本地 39+ commits 用 `git log --oneline origin/main..HEAD` 过一遍，
  按 milestone（M2..M7）确认每个 commit 的 scope。
- 重点检查最近 4 个 RC 收口 commit 的 diff：
  `110b3ab → 2bc82cb → 0ee3210 → d7d2494`。
- 确认 `.gitignore` 仍然覆盖 `agent_log.jsonl / sessions/ / runs/ / state.json /
  summary.md / .env / .venv`，并 `git ls-files | grep -E '...'` 复核。
- 不要 squash：每个 commit 都对应一个独立可回滚的语义点。
