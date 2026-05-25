# Runtime v0.1 · B3 真实 smoke / graduation 验证 playbook

> **本文件目的**：把 Runtime v0.1 的 B3 真实 smoke 做成可复现、
> 可审计的毕业验证。B3 只验证 v0.1 最小 Runtime 是否真的跑通，
> 不新增功能，不推进 v0.2 / v0.3 backlog。
>
> **当前阶段边界**：本文档可以先被离线测试审计；离线测试不调用真实模型。
> 真正调用 Anthropic API 的 smoke 由人工执行，且必须显式准备
> `ANTHROPIC_API_KEY`。
>
> **当前状态**：B3 真实 smoke 已通过，结果记录在
> `docs/V0_1_GRADUATION_REPORT.md`。本文档保留为后续复验 playbook。

---

## 1. B3 smoke 目标

用 simple CLI 真实跑通一次最小任务：

```text
请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。
```

验证的最小 Runtime 回路：

```text
plan -> 用户确认计划 -> 工具调用（必要时确认）-> 输出结果 -> checkpoint 持久化
```

B3 不是新功能阶段。执行 smoke 时禁止借机实现 P1 feedback intent flow、
Textual backend、Skill/sub-agent、generation cancellation、复杂 topic switch、
slash command、LLM 意图分类、新工具、新 awaiting 状态或新 RuntimeEvent kind。

## 2. 前置条件

从仓库根目录执行：

```bash
pwd
test -f README.md
test -n "$ANTHROPIC_API_KEY"
test -x .venv/bin/python
```

判定：

- `pwd` 必须是仓库根目录。
- `README.md` 必须存在于仓库根目录；如果不存在，停止 smoke，记录为
  preflight 失败，不要静默改读 `tests/README.md` 或其他文件。
- `ANTHROPIC_API_KEY` 必须存在；如果不存在，停止 smoke，不要调用真实模型。
- `.venv/bin/python` 必须存在并可执行。

建议先跑离线基线：

```bash
.venv/bin/python -m ruff check agent/ tests/
.venv/bin/python -m pytest -q
```

## 3. 产物处理

`summary.md` 是 B3 smoke 的唯一预期文件产物。它是本地 smoke 产物，
已加入 `.gitignore`，默认不提交。

执行前：

```bash
test ! -e summary.md
```

如果 `summary.md` 已存在，先停止并人工决定：保留作为历史产物、改名备份，
或删除后重跑。不要让 smoke 覆盖一个来源不明的文件。

执行后：

```bash
test -f summary.md
sed -n '1,120p' summary.md
```

通过判据：

- `summary.md` 存在。
- 内容是中文总结。
- 内容来自 `README.md`，不能是空泛的模板文案。
- 除 `summary.md` 和 checkpoint / 日志类运行产物外，不应出现非预期文件改动。

## 4. 执行命令

启动 simple CLI：

```bash
.venv/bin/python main.py
```

在 CLI 中输入任务：

```text
请读取仓库根目录 README.md，并把一段中文总结写入 summary.md。
```

人工交互规则：

- 看到 plan 后，如果计划确实只包含读取 README、写入 summary.md、必要的
  最小检查，回复 `y`。
- 如果 plan 要求实现 Textual、Skill、sub-agent、复杂 topic switch、slash
  command、LLM 意图分类、generation cancellation 或其他 v0.2 / v0.3 backlog，
  回复修改意见，要求回到 B3 smoke 范围。
- 如果工具调用需要确认，只批准读取 `README.md`、写入 `summary.md`、以及
  必要的只读检查命令。
- 不批准删除重要代码、回滚 commit、push、安装依赖或访问无关路径。

## 5. 人工确认点

执行过程中逐项记录：

- Agent 是否展示了可读 plan。
- plan 确认提示是否明确要求 `y/n/修改意见`。
- tool call 与 tool result 是否有清晰边界。
- 写入 `summary.md` 前是否能看清工具名和目标路径。
- 任务完成后是否有明确完成输出。
- 如果中途进入 awaiting 状态，CLI 是否说明问题、原因和可选项。

## 6. CLI 输出契约检查

对照 `docs/CLI_OUTPUT_CONTRACT.md`，普通 CLI 输出必须满足：

- 不出现裸 checkpoint dict。
- 不出现 checkpoint conversation messages 泄漏。
- 不出现 `[DEBUG] checkpoint:`。
- 默认不出现 `REQUEST → Anthropic`。
- 默认不出现 `RESPONSE ← Anthropic`。
- 用户可见的系统级提示使用 `[系统]` 或 RuntimeEvent / DisplayEvent 渲染。
- plan、tool call、tool result、pending user input 都有清晰边界。

如果出现以上任一违规输出，B3 不通过；只允许回头修 v0.1 最小路径，
不得借机扩展 RuntimeEvent 体系或实现完整 TUI。

## 7. Checkpoint 检查

B3 需要确认 checkpoint 链路真实参与过运行。

常规检查：

```bash
test -f memory/checkpoint.json
.venv/bin/python -m json.tool memory/checkpoint.json >/dev/null
```

通过判据：

- 运行过程中或运行结束后能确认 checkpoint 被写入过。
- `memory/checkpoint.json` 如存在，必须是合法 JSON。
- checkpoint 中不应保存不可 JSON 序列化对象。
- 普通 CLI 输出不得把 checkpoint values、conversation messages 或 tool result
  原文整段裸打到 terminal。

如果完成路径会清理 checkpoint，记录清理行为，并用 CLI 输出或日志证明运行中
发生过 checkpoint save。不要为了 B3 改 checkpoint 生命周期。

## 8. 通过 / 失败判据

B3 通过必须同时满足：

- 前置条件全部通过。
- simple CLI 真实调用 Anthropic API 完成任务。
- `summary.md` 被创建，内容是基于 `README.md` 的中文总结。
- read / write / shell 三类基础能力至少在本次 smoke 或配套检查中被覆盖。
- plan -> 确认 -> 工具调用/确认 -> 输出结果 -> checkpoint 的最小回路成立。
- CLI 输出符合 `docs/CLI_OUTPUT_CONTRACT.md`。
- `.venv/bin/python -m ruff check agent/ tests/` 通过。
- `.venv/bin/python -m pytest -q` 无 RED，xfail 归类不变。

本仓库当前 B3 结果：已通过，见 `docs/V0_1_GRADUATION_REPORT.md`。

B3 失败包括：

- 缺少 `ANTHROPIC_API_KEY` 或仓库根目录 `README.md`。
- 真实模型调用失败且无法判断 Runtime 最小回路是否成立。
- Agent 写错文件、覆盖非预期文件或跳出 B3 范围。
- CLI 输出出现裸 checkpoint dict、protocol dump 或用户不可理解的确认流。
- pytest / ruff 出现 RED。

## 9. 审计记录模板

执行后在 commit 或人工记录中填写：

```text
B3 smoke date:
Commit under test:
Preflight:
Task prompt:
Plan accepted:
Tools observed:
summary.md result:
Checkpoint result:
CLI output contract:
ruff:
pytest:
Decision: PASS / FAIL
Notes:
```
