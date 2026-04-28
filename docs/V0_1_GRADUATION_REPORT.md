# Runtime v0.1 · Graduation Smoke Report

> **结论**：Runtime v0.1 已满足「最小 Agent Runtime 跑起来」阶段毕业标准。
> 本报告只记录 v0.1 graduation smoke 事实，不声明 v0.2 / v0.3 能力已完成。

---

## 1. 验证对象

- Commit under test: `ccbe13b docs(runtime): add v0.1 smoke README preflight`
- Smoke task:

```text
请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。
```

- Smoke 产物：`summary.md`
- 产物处理：`summary.md` 是本地 smoke 产物，已加入 `.gitignore`，不纳入版本控制。

## 2. Secret / .env 处理

执行真实 smoke 前做了 secret-safe 检查：

- `.env` 存在。
- `.env` 已被 git ignore。
- 只确认 `.env` 中存在 `ANTHROPIC_API_KEY` 变量名；未输出 key 明文。
- 通过 `set -a; source .env; set +a` 将变量加载到命令环境。
- 重新检查 `ANTHROPIC_API_KEY` 非空后才执行真实 API smoke。

未提交 `.env`，未提交任何 secret。

## 3. 真实 API Smoke 过程

第一次在普通 sandbox 网络环境中启动 simple CLI 后，真实模型连接失败，错误类型为
Anthropic API connection error。随后按权限流程在允许网络访问的命令环境中重跑。

第二次真实 smoke 成功：

1. 启动 simple CLI：`.venv/bin/python main.py`
2. 输入固定任务：读取仓库根目录 `README.md` 并写中文总结到 `summary.md`
3. Agent 生成两步 plan：
   - 读取 `README.md`
   - 基于 README 内容生成中文总结并写入 `summary.md`
4. 人工确认 plan：回复 `y`
5. 工具链路：
   - `read_file` 读取 `README.md`
   - `write_file` 写入 `summary.md`
6. 人工确认写文件工具调用：回复 `y`
7. Agent 输出任务完成提示
8. 退出 CLI：`quit`

## 4. CLI 输出契约检查

对照 `docs/CLI_OUTPUT_CONTRACT.md`，本次 smoke 的普通 CLI 输出检查结果：

- 未观察到裸 checkpoint dict。
- 未观察到 checkpoint conversation messages 泄漏到终端。
- 未观察到 `[DEBUG] checkpoint:`。
- 默认未观察到 `REQUEST → Anthropic`。
- 默认未观察到 `RESPONSE ← Anthropic`。
- plan 展示可读，确认提示明确。
- tool call / tool result 边界清晰。
- `write_file` 调用前展示了路径和内容预览，并等待人工确认。

## 5. Checkpoint 行为

- smoke 完成后 `memory/checkpoint.json` 不存在，说明完成路径没有残留断点文件。
- `agent_log.jsonl` 中存在本次 session `31cbfe0a-78a8-4997-96b9-1aa7931232a5`
  的多条 `checkpoint_saved` 记录，包括：
  - `awaiting_plan_confirmation`
  - `running`
  - `awaiting_tool_confirmation`，`pending_tool_name=write_file`
  - `done`

结论：checkpoint 链路参与了真实运行；完成后没有留下未完成任务断点。

## 6. Smoke 产物检查

`summary.md` 已生成，内容为基于根目录 `README.md` 的中文总结，覆盖：

- 项目定位：学习型 Agent Runtime 原型
- Runtime v0.1 的最小 loop
- B1 / B2 / B3 状态
- 测试运行方式
- v0.1 非目标

`summary.md` 不作为稳定源文件提交。

## 7. 自动化验证

真实 smoke 后重新运行：

```bash
.venv/bin/python -m ruff check agent/ tests/
.venv/bin/python -m pytest -q
```

结果：

- ruff: pass
- pytest: `279 passed, 3 xfailed`

## 8. xfail 归属

当前 3 个 xfailed 保持原归属：

| 测试 | 归属 |
|---|---|
| `tests/test_hardcore_round2.py::test_user_switches_topic_mid_task` | v0.2 输入语义治理 |
| `tests/test_input_backends_textual.py::test_textual_shell_escape_can_cancel_running_generation` | v0.2 cancel 生命周期 + v0.3 TUI Esc 集成 |
| `tests/test_real_cli_regressions.py::test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent` | v0.3 高级 TUI（paste burst） |

这些 xfail 不阻塞 v0.1 graduation。

## 9. Graduation 判定

v0.1 毕业标准判定：

| 标准 | 判定 |
|---|---|
| simple CLI 端到端跑通 README -> `summary.md` | ✅ 通过 |
| 至少 3 类基础工具可用 | ✅ read / write / shell 基线由测试与 smoke gate 覆盖 |
| 最小状态区分存在 | ✅ 由状态与主循环测试覆盖 |
| checkpoint 写入 + 加载 roundtrip | ✅ 测试通过；真实 smoke 中 checkpoint save 被记录 |
| `pytest` 无 RED，xfail 明确归类 | ✅ `279 passed, 3 xfailed` |
| 最小 CLI/TUI 输出契约冻结并遵守 | ✅ B2 文档 + 回归测试 + 真实 smoke 输出检查 |

**最终结论**：Runtime v0.1 已毕业。下一步只能进入 v0.2 planning / engineering，
不得把 v0.2 / v0.3 backlog 写成 v0.1 已完成。
