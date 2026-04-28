# Runtime v0.2 Release Notes

发布候选：`d98718c` 之上 + 本轮 release 收口（`python main.py health` 子命令、
RELEASE_NOTES、最终防泄漏 + 健康维护文档）。

> v0.2 是 Runtime 的「**安全边界 + 输出契约 + 离线 LLM 处理 + 人工 smoke 闭环**」
> 阶段，故意不做完整 TUI、不做 Skill 成熟化、不做 sub-agent、不做
> Reflect/Self-Correction、不做 generation cancellation。

---

## 1. 已完成能力

### Runtime 主线
- **状态机不变量**：`docs/RUNTIME_STATE_MACHINE.md`
  + `tests/test_runtime_state_machine_invariants.py`（315 行）。
- **事件边界**：`docs/RUNTIME_EVENT_BOUNDARIES.md`
  + `tests/test_runtime_event_boundaries.py`（249 行）。
- **checkpoint / resume**：`docs/CHECKPOINT_RESUME_SEMANTICS.md`
  + `agent/session.py::_checkpoint_has_actionable_resume`，idle 残留启动时
  静默清理，actionable 状态显示 `状态：<status>`。
- **错误恢复 + loop guard**：`docs/RUNTIME_ERROR_RECOVERY.md` + 不变量测试。
- **工具/result 链路**：`tool_executor` 三类分类
  （`executed` / `failed` / `rejected_by_check`）+ `confirm_handlers` 用户拒绝
  显式 `tool.user_rejected` 显示事件。
- **工具安全边界**：项目外路径写入拦截、敏感文件读拒绝、shell 黑名单与
  fork bomb 正则、未注册工具名归类为 failed（v0.2 RC P0/P1 系列修复）。

### CLI 输出契约
- `docs/CLI_OUTPUT_CONTRACT.md` §8.1 四类工具结局表：
  | 类别 | event | 文案 |
  |---|---|---|
  | 真实成功 | `tool.completed` | 执行完成。 |
  | 工具失败 | `tool.failed` | 执行失败。 |
  | 安全策略拒绝 | `tool.rejected` | 被安全策略拒绝：... / 已被工具内部安全检查拒绝。 |
  | 用户拒绝 | `tool.user_rejected` | 用户拒绝执行，已跳过。/ 用户未批准，改为提供反馈意见。 |

### LLM Processing（v0.2 M2-M5）
- 离线 fake provider 默认路径，anthropic provider 安全配置/preflight。
- `process` / `scan` / `status` / `preflight` 子命令；`status --run-id` 查询。
- provider 错误分类：missing_config / auth_error / rate_limited /
  network_error / timeout / bad_response / unknown_provider / provider_error。
- 文档：`docs/LLM_PROVIDER_CONFIG.md`、`docs/LLM_AUDIT_STATUS_SCHEMA.md`、
  `docs/LLM_PROVIDER_LIVE_SMOKE.md`、`docs/LLM_PROCESSING_CAPABILITY_MATRIX.md`。
- raw prompt / completion / api key / base_url 原值不入日志。

### Smoke
- 自动 smoke：`tests/test_v0_2_rc_automated_smoke.py`、
  `tests/test_v0_2_rc_p1_negative.py`、`tests/test_security_baseline.py`、
  `tests/test_v0_1_smoke_playbook.py`、`tests/test_cli_output_ux.py`。
- 人工 smoke：`docs/V0_2_MANUAL_SMOKE_PLAYBOOK.md` 全程通过，结果记录在
  `docs/V0_2_MANUAL_SMOKE_RESULT.md`（7 类核心场景）。

### 健康检查
- 现有：workspace_lint / backup_accumulation / log_size /
  session_accumulation 四项。
- v0.2 release 新增：`python main.py health` 独立子命令，可脱离主对话
  循环单独运行，**不引入新检查逻辑**。
- 维护说明：`docs/V0_2_HEALTH_MAINTENANCE.md`。

---

## 2. 不包含的能力（v0.2 故意不做）

| 能力 | 原因 / 归属 |
|---|---|
| 完整 Textual TUI / 多面板 / event replay | v0.3 高级 TUI |
| 基础 TUI / CLI UX 加强（M7） | 已部分落地（输出契约、resume 文案），完整 panel 留 v0.3 |
| Skill 子系统正式化 | 当前提示文案偏强，标记为非阻塞观察项 |
| sub-agent 协作 | 后续 milestone |
| Reflect / Self-Correction / LLM judge | 不在 Runtime v0.x 范围 |
| `generation.cancelled` RuntimeEvent + Esc cancel | v0.2 cancel 生命周期 + v0.3 Esc 集成 |
| paste burst / bracketed paste | v0.3 高级 TUI |
| 复杂 topic switch / slash command | 已撤销，见 `205c4cf` |
| 真实 LLM live smoke 自动化 | 仍是手动开关（`--live`），不在自动化范围 |

---

## 3. 永久 xfail（3 个）

每个都明确归属 + 解锁条件：

1. `tests/test_state_invariants.py::...`（v0.2 输入语义治理）
2. `tests/test_input_backends_textual.py::test_textual_shell_escape_can_cancel_running_generation`
   （v0.2 cancel 生命周期 + v0.3 TUI Esc 集成）
3. `tests/test_real_cli_regressions.py::test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent`
   （v0.3 高级 TUI · paste burst）

---

## 4. 健康 warning（非阻塞）

| warning | 当前值 | 处理路径 |
|---|---|---|
| `workspace_lint` | 7 .py / 4 lint 错误 | 人工 review，详见 `docs/V0_2_HEALTH_MAINTENANCE.md` §1 |
| `log_size` | `agent_log.jsonl` ≈ 96MB | 手动 archive，文档 §2 |
| `session_accumulation` | `sessions/` 125 个快照 | 手动 archive，文档 §3 |

无任何一项是 v0.2 blocking。

---

## 5. 测试与质量门禁

```
ruff check agent/ tests/ llm run_logger.py main.py    # All checks passed
pytest -q                                              # 576+ passed, 3 xfailed
```

---

## 6. 防泄漏审计结论

- `git ls-files` 不含 `.env / state.json / runs/ / sessions/ /
  agent_log.jsonl / workspace/ / memory/checkpoint`。
- `.env.example` 仅占位注释，无真实 key。
- diff 中 `-----BEGIN PRIVATE KEY-----` 命中均为 `sensitive_file` 检测模式
  字符串，非泄漏。
- `agent_log.jsonl` 复核：`sk-ant-[A-Za-z0-9_]{20,}` = **0 hits**。
- 由 `tests/test_gitignore_runtime_artifacts.py` 8 条 parametrized 测试
  在 CI/本地长期守护 .gitignore 关键条目。

---

## 7. 发布建议

- tag 名：`v0.2.0`
- 推送命令（**待你确认后人工执行**）：
  ```bash
  git push origin main
  git tag -a v0.2.0 -m "Runtime v0.2: safety boundaries + output contract + offline LLM processing"
  git push origin v0.2.0
  ```
- **v0.2 blocking：无。**
