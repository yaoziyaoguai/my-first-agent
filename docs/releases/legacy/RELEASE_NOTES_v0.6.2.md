# v0.6.2 Release Notes

> 本文件状态：v0.6.2 release readiness 记录。release notes commit 与本地
> annotated tag 需要分别审计；本轮不 push commit、不 push tag。

## Summary

v0.6.2 是 Stage 2：TUI interaction layer 的最小 MVP 闭环。它只解决
paste burst / multiline input semantics 这一条产品缺口：用户把 9 行编号列表
一次性粘贴到 CLI fallback 时，输入层必须把它保留为同一个 user intent，而不是拆成
多轮输入。

学习型说明：release/tag 前不顺手做架构重构，是为了保持封版边界清晰。当前版本的
目标是把 TUI MVP 的最小行为落地并验证；`core.py` responsibility、input boundary、
display boundary、confirmation/menu selection policy、checkpoint ownership 等架构议题，
应在 v0.6.2 封版后进入单独 architecture/module debt audit，而不是混入 release commit。

## Completed

- Slice 5 tests-only characterization：`749b74d` 已 push 到 `origin/main`。
- Slice 6 minimum implementation：`195a7af` 已 push 到 `origin/main`。
- `test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent`
  已从 strict xfail 转为普通通过测试。
- paste burst / multiline input semantics 已稳定：9 行编号列表不再被拆成多个
  user intent。
- `1.` / `2.` 这类编号列表标记保留在 raw text 中，不由 input backend 误判为
  menu selection。
- Ask User / Other free-text 未被绕过；确认/菜单选择仍由 runtime/handler 层按当前
  state 解释。
- input backend 只负责读取、drain、封装输入事件，不 mutate runtime state，不写
  checkpoint，不调用模型，不执行工具。
- display layer 仍是 display-only / observation-only，不做 runtime decision。
- no sensitive read 边界保持：`.env` / `agent_log.jsonl` / `sessions` / `runs`
  未被 git track，本轮只做 git 元信息检查，不读取真实内容。

## Validation

Release readiness gate（post-push，HEAD = `195a7af`）：

- full pytest：**926 passed, 2 xfailed**
- ruff：**All checks passed**
- `git diff --check`：clean
- `origin/main...HEAD`：`0 0`
- working tree：clean
- sensitive file git tracking check：
  - `.env` 未被 git track
  - `agent_log.jsonl` 未被 git track
  - `sessions` 未被 git track
  - `runs` 未被 git track

Targeted regression closure：

- `tests/test_real_cli_regressions.py`：**7 passed**
- `tests/test_input_backends_textual.py`：**23 passed, 1 xfailed**
- `tests/test_input_backends_simple.py`：**12 passed**
- `tests/test_tui_dependency_boundaries.py`：**7 passed**
- `tests/test_display_event_contract.py`：**5 passed**
- `tests/test_user_input_contract.py`：文件不存在，按 gate 规则跳过。

## Scope-out / Known Remaining Debt

当前剩余 2 个 xfail：

1. `tests/test_hardcore_round2.py::test_user_switches_topic_mid_task`
   - 归属：XFAIL-1，user intent / topic switch governance。
   - 不阻塞 v0.6.2：它需要成熟的 topic-switch 信号源或确认流，超出 paste burst
     TUI MVP scope。
   - 建议后续 slice：topic switch inventory / explicit runtime confirmation design。
2. `tests/test_input_backends_textual.py::test_textual_shell_escape_can_cancel_running_generation`
   - 归属：XFAIL-2，Esc cancel / interruption lifecycle。
   - 不阻塞 v0.6.2：它需要 cancel_token、model stream abort、
     `generation.cancelled` RuntimeEvent 与 Textual adapter 协作，超出 paste burst
     TUI MVP scope。
   - 建议后续 slice：Esc cancel / interruption semantics inventory。

XFAIL-1 / XFAIL-2 都是已知 scope-out debt，不应在 v0.6.2 release/tag 前临时处理；
强行合并会扩大改动面，反而污染当前 TUI MVP 基线。

## Architecture / Module Review Next

TUI 目标完成后，下一阶段应进入 architecture/module debt audit，而不是跳到
Memory、sub-agent、Skill 或其他新能力。

优先审查对象：

- `core.py` responsibility：runtime orchestration 是否过胖，哪些 dispatch / loop /
  checkpoint ownership 可以继续收口。
- `user_input` / `input_backends` boundary：输入层是否只表达用户输入事件，不携带
  runtime transition。
- `display_events` boundary：display event 是否仍是 display-only，不反向触达 runtime。
- confirmation / menu selection policy：`1` / `2` / `3` 这类选择语义是否只在明确
  confirmation context 中生效。
- checkpoint ownership：哪些状态必须 durable，哪些 adapter/runtime-only 对象绝不能
  进入 checkpoint schema。
- runtime state mutation ownership：状态 mutation 是否仍集中在 runtime/handler 层，
  而不是扩散到 input/display adapter。

学习型说明：architecture review 应该是下一阶段的独立 slice。这样可以在 v0.6.2
release 基线稳定后，用 characterization tests 和 dependency-boundary tests 支撑后续
瘦身，而不是在 release notes / tag 过程中混入难以审计的重构。

## Not Included

- no Memory
- no sub-agent / handoff
- no Skill
- no Web UI
- no dashboard
- no RAG / vector
- no alternate interaction-layer naming; scope remains TUI
- no Esc cancel implementation
- no user switch topic implementation
- no architecture refactor
- no `core.py` split
- no input system rewrite
- no checkpoint schema change

## Tag Plan

- 如果 release notes commit 审计通过，下一步应先 push release notes commit 到
  `origin/main`。
- release notes commit 推送后，再创建并 push `v0.6.2` annotated tag。
- tag 前必须确认：
  1. working tree clean；
  2. `origin/main...HEAD = 0 0`；
  3. HEAD on `origin/main`；
  4. `.env` / `agent_log.jsonl` / `sessions` / `runs` 未被 git track；
  5. full pytest 仍为 **926 passed, 2 xfailed** 或仅有预期范围内变化；
  6. ruff clean；
  7. `git diff --check` clean；
  8. 没有生产代码或测试改动混入 release notes commit。
