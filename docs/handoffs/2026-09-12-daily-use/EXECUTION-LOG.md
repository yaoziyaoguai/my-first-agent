# S1＋S2 执行日志

执行日期：2026-09-12 至 2026-09-13。执行者：Codex（未使用 Claude Code）。S3 未启动。

## 基线

- 起始 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`，`main` 相对记录的 `origin/main` ahead 7。
- 工作树开始时已有多项用户改动；本次未 reset、commit、push，也未读取/修改未跟踪 `tui/` 运行数据。
- 先按资料包读取 S1/S2 入口与架构合同；只扩展既有 CLI/TUI adapter、file tool family、closed evidence projection。

## F3 / F4：CLI 显示安全与生命周期

1. Red：`MODEL_TEXT_DELTA` 中 ESC/bidi 控制符原样到达终端 sink。
2. Green：仅在终端显示边界调用 `terminal_text(..., allow_newlines=True)`；内部原始文本继续用于最终答案去重，不进入 checkpoint/context 的是原始协议内容。
3. Red：同一 renderer 连续两轮时旧 `_streamed_answer` 泄漏；同一 action 文本→工具→文本时不同 provider response 混在同一缓存。
4. Green：缓存按 `(conversation_id, run_id, revision, causation_id)` 分段，并在权威 `render_result` 后清空。
5. Red：同步非流式调用提交后没有任何即时反馈。
6. Green：进入唯一 `runtime.run_turn` 前显示准确的 `Working...`，不伪造阶段、百分比或实时 tool 事件。

聚焦结果：S1 renderer/provider/event/packaging 组 `144 passed`；早先不含 packaging 的组 `138 passed`。

## F5：产物确认无需手抄摘要

1. Red：process-produced artifact 在文件尚不存在时要求 `/approve-artifact <sha256> ...`；普通用户无法知道未来 SHA。
2. Green：`ResolveApproval.defer_artifact_confirmation` 只批准生成 effect，不准入文件 criterion；错 Goal criterion 仍拒绝。
3. Red：不存在 `confirm_file`；预览后的文件漂移无法形成“看内容后确认”的完整路径。
4. Green：新增受治理 `confirm_file`，在现有 `ToolRuntime` 内执行 bounded/no-follow/private-path 检查，展示当前 UTF-8 内容，绑定 snapshot/digest，并在 invoke 前重验。
5. Red：普通 write/edit 审批只显示 path 和 byte count。
6. Green：审批预览显示 exact proposed content；edit 同时显示 old/new 与 resulting content。终端允许换行，但 ESC/C1/bidi 等仍按 literal display 转义。
7. CLI/TUI 普通 approve 现在表示“批准生成、稍后确认内容”；高级 `/approve-artifact` 保持兼容。

## F1：完成声明的证据范围

1. 源码复核记录在 `S2-EVIDENCE-DECISION.md`：file digest、process receipt、sandbox receipt 均是精确结构证据，不是通用语义真值。
2. Red：共享 Goal projection 没有 evidence scope，CLI 也无法纠正模型可能过宽的完成措辞。
3. Green：`GoalView.verification_scope` 只从 passing closed oracle 和可信 predicate 生成，不复述模型 criterion prose；CLI/TUI 共用同一 scope 文案，并明确不独立证明数值/语义正确。
4. 启动状态把 `verified done` 改为 `evidence complete`，避免把内部状态名包装成通用正确性承诺。
5. 未新增 LLM judge、语义评分器或强制所有任务运行进程。

## 已执行检查

- 新增 Red 均先观察到预期失败，再最小 Green。
- S2 evidence/UI/file 最终聚焦回归：`256 passed`。
- S1 CLI/provider/event/packaging 回归：`144 passed`。
- 新增 process→confirm obligation 与 `confirm_file` read-back 用例：`4 passed`。
- touched-file Ruff：通过。
- `git diff --check`：通过。
- 首次全仓在受限工具沙箱中得到 `3367 passed, 11 skipped, 25 failed, 12 errors`；失败均落在主机进程身份、macOS Seatbelt、本地回环监听及两条已改变的旧合同。两条旧合同已按新语义更新并通过；其余 35 条在主机环境重跑全部通过。
- 修复后最终全仓主机门禁：`3412 passed, 3 skipped in 372.44s`，exit 0。
- Full Ruff：`All checks passed!`。

最终全仓 gate 与最终结果见 `RESULTS.md`；该文件在最终 gate 后更新。
