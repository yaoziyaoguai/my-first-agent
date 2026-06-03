# Runtime v0.3 Release Notes

> v0.3 是 Runtime 的 **usability 阶段**：在 v0.2 已稳定的安全边界与输出契约
> 之上，让 Agent 在「人工日常使用 + 长期维护」两个场景上更可读、更可观测。
> v0.3 **不是**新能力大爆炸，故意不做 Reflect / sub-agent / 完整 Textual /
> Skill 平台 / generation cancellation / 复杂 topic switch / slash command 复活。

发布候选：tag `v0.3.0` (`3aa32fe`) + 后续 v0.3 patch（final answer /
request_user_input 协议边界修复）。

---

## 1. 已交付能力

### M1 · Basic CLI Shell MVP
- `agent/cli_renderer.py` 纯函数渲染 session header / resume status / status line / health 摘要
- `agent/session.py::summarize_session_status` 返回脱敏摘要 dict
- 启动屏结构化：`Runtime v0.3 M1 shell` banner + session id + cwd + health 单行 + Skill experimental 文案 + resume 三态
- 兼容口径：v0.2 输出契约（4 类 tool outcome 文案）保持不变
- 测试：`tests/test_cli_renderer.py` (13) + `tests/test_session_summary_and_header.py` (10) + `tests/test_v0_3_shell_completeness.py` (14)
- 文档：`docs/V0_3_BASIC_SHELL_USAGE.md`、`docs/CLI_OUTPUT_CONTRACT.md` §12-§13

### M2 · Health Maintenance 可视化
- `python main.py health` 结构化人类可读报告（每项 check 含 `current_value` / `path` / `risk` / `action`）
- `python main.py health --json` 机器可读 JSON，schema 稳定
- workspace_lint warn 时给出具体 ruff 错误码与文件路径
- **Runtime 永不自动归档/删除** `agent_log.jsonl` / `sessions/` / `workspace/`
- 文档：`docs/V0_2_HEALTH_MAINTENANCE.md` 仍是手动维护命令清单的来源

### M3 · Skill 体系坦诚化
- 启动屏不再印 `'/reload_skills' 重新加载 skill`（slash command 历史上**没有 handler**，纯属误导）
- 启动屏改印「Skill 是实验性能力（v0.3 M3 状态澄清）」
- 文档：`docs/V0_3_SKILL_SYSTEM_STATUS.md` 写清「Skill 是什么 / 不是什么」
- **没有**实现：slash command 解析器、Skill 级 tool 权限白名单、activation policy、skill marketplace

### M4 · Observer / Logs 可读性
- `python main.py logs` 默认 tail 50 + 隐藏 runtime_observer（占 ~86% 噪声）
- 过滤：`--tail` / `--session` / `--event` / `--tool` / `--include-observer`
- 单行紧凑摘要（不展示 raw content / raw result / system_prompt 正文）
- 损坏 jsonl 行不崩，跳过并报计数
- 兜底脱敏：`sk-ant-` / `BEGIN PRIVATE KEY` / `api_key=…` → `[REDACTED]`
- M2 health log_size action 联动指向 `python main.py logs --tail 100`
- 文档：`docs/V0_3_OBSERVER_LOGS.md`

### v0.3 finalize round · cross-layer guards
- `tests/test_v0_3_shell_completeness.py` 守护 banner、4 类 outcome 文案、
  health/logs 入口三处一致、resume 不裸 dict、logs 无 protocol dump、
  tool confirmation 参数预览不泄露 secret

### v0.3 patch · final answer / request_user_input 协议边界
- 触发：人工 smoke「5 天武汉宜昌旅游规划」发现模型在 final answer 写
  待应答追问 + 同轮 `mark_step_complete`，用户感受「问了又不等」
- 根因：`config.SYSTEM_PROMPT` 未声明「`request_user_input` 是 Runtime 唯一
  等待信号」「final answer 不要混入待应答追问」
- 修法（**不是关键词 hack**）：扩展 SYSTEM_PROMPT 协议契约 + 锁死历史 keyword
  patterns 不再扩张 + 7 项协议级回归测试
- commit: `03d2347 fix(runtime): separate final answer from user-input requests`
- 详见 `docs/V0_3_MANUAL_SMOKE_RESULT.md` §3 与 `docs/CLI_OUTPUT_CONTRACT.md` §14

---

## 2. 测试与质量

- `ruff check agent/ tests/ llm run_logger.py main.py` → All checks passed
- `pytest -q` → **676 passed, 3 xfailed**

3 个永久 xfail 全部归属明确（不属于 v0.3 范围）：

| xfail | 归属 |
|---|---|
| `test_user_switches_topic_mid_task` | v0.2 输入语义治理（complex topic switch） |
| `test_textual_shell_escape_can_cancel_running_generation` | v0.2 cancel 生命周期 + v0.3 TUI Esc 集成 |
| `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` | v0.3 高级 TUI（paste burst） |

---

## 3. 防泄漏审计

`git ls-files` 复核命令：

```bash
git ls-files | grep -E '(\.env$|state\.json$|summary\.md$|agent_log\.jsonl$|^runs/|^sessions/)'
```

预期输出为空（`.env.example` 是模板，可被忽略）。本次 release 通过。

`tests/test_gitignore_runtime_artifacts.py` 持续守护：`.env` / `state.json` /
`runs/` / `sessions/` / `agent_log.jsonl` 等运行时产物**不可**被 git 跟踪。

新增测试 `tests/test_final_answer_user_input_separation.py` 不打印任何 secret /
raw prompt / raw completion / response body。

---

## 4. v0.3 显式不做（继续推迟）

- ❌ Reflect / Self-Correction / LLM judge
- ❌ sub-agent / multi-agent 协作
- ❌ 完整 Textual 多面板 / timeline viewer / event replay / 快捷键
- ❌ generation cancellation（cancel_token + stream abort + Esc cancel）
- ❌ 复杂 topic switch（已撤销过一次，不要复活）
- ❌ slash command 体系
- ❌ Skill marketplace / Skill lifecycle 完整化
- ❌ 真实 LLM live smoke 自动化（仍是 `--live` 手动开关）
- ❌ HTTP transport 重写、新 provider 接入
- ❌ 健康检查 metric → Prometheus / Grafana 等 SRE pipeline
- ❌ keyword 黑名单扩张（v0.3 patch 已锁死历史 patterns 上限）

后续如需，请进入 v0.4 planning（`docs/V0_4_PLANNING.md`），不要写成 v0.3 已完成。

---

## 5. 升级与人工 smoke

升级路径：v0.2.0 → v0.3.0 + patch。无破坏性接口变更。CLI 输出契约
向后兼容（4 类 tool outcome 文案完全不变）。

人工 smoke 详见 `docs/V0_3_MANUAL_SMOKE_RESULT.md`。
