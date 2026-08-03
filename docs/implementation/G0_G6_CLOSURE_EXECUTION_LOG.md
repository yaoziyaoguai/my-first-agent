# G0–G6 Closure Execution Log

本日志由 General Agent Completion executor（Claude Code session）在 009 sealed candidate 的
隔离后继副本中连续执行 G0–G6 后写入，供下一次独立 promotion review 核对。它不是 E3 acceptance，
也不替代独立 review receipt。

## Baseline 与工作边界

- baseline commit：`7d935ac`（009 sealed candidate 的 pinned baseline）。
- 全量基线起点：322 passed。
- 未 commit、push、tag 或修改 remote；未读取 secret/private/runtime 数据。
- 每个单元遵循准确 Red → 最小 Green → focused/full tests → materialized `--content` gate →
  truth-claim 同步；ordinary entry digest 随文件改动同步，control doc 改动后 seal_state 重置为
  None（executor 不重封，待独立 reviewer 重封）。

## 各单元闭合记录

| 单元 | 闭合内容 | 关键 oracle |
|---|---|---|
| G0 / N1 | delivery console-entrypoint origin 显式断言 | `assert_console_entrypoint_origin`：`first-agent`/`first-agent-schedule` 在 prefix/bin、owner-regular、target `main:<fn>`、prefix-first 环境 `--help` 端到端加载；content gate 新增 `console entrypoint origin ok` |
| G0 / N2 | TUI event loss/duplicate/reorder 注入 oracle | advisory 事件流（含误导 kind/payload）经 loss/duplicate/reorder 注入后 authoritative checkpoint revision、`save_count`、projection actions 与 provider call 全不变 |
| G0 / 文档 | `CURRENT_CAPABILITY_STATUS.md` TUI "submit-only" 过时表述修正 | — |
| G1 Skill | invoke/read 前复验 trust-root identity：body+resource+ancestor identity/digest（同一 opened fd）；bounded metadata disclosure | resource 同内容 inode 替换 drift；skill 目录 ancestor 替换 drift；model-visible surface 不泄露绝对 root/body |
| G2 MCP | spawn 前 executable/ancestor/cwd identity+digest 复验（`revalidate_spawn_identity`）；持续 stderr drain + bounded（`stderr_drainer`）；process 为 None 时安全 clear latch | chatty stderr flood 不死锁且不进 result；approval 后 executable 内容替换 pre-spawn `spawn_identity_drift` NOT_EXECUTED；ancestor/cwd drift |
| G3 Memory | strict no-coercion durable load（`_parse_document`：revision/timestamp 精确类型，禁止 int()/float()）；identity-safe owner-only bounded read（单一 O_NOFOLLOW fd + UID + size 上限） | 字符串/缺失 revision/timestamp 拒绝；超限 store 文件 bounded read 拒绝 |
| G4 SubAgent | fault matrix 闭合：structural `ProviderDeadlineCapability` eligibility、single-use termination receipt（UNCONFIRMED 覆盖 normalization→parent recovery）、exact handoff、parent recovery | supported fake provider 满足 contract；unsupported provider fail closed；confirmed nonterminal=executed/is_error |
| G5 Scheduler | `conversation_busy` 与 `checkpoint_conflict` 同一 one-shot reconciliation；canonical UTC 整秒 round-trip（拒绝 fractional/offset） | conversation_busy reload 一次重交 seq-1；fractional/offset form 拒绝 |
| G6 TUI | recovery 成功/失败纯键盘 dispatch（s/f） | 按 s/f 派发 `ResolveUnknownToolOutcome`(MARK_SUCCEEDED/MARK_FAILED) 绑定 authoritative state |

## Materialized verification（E2M）

G0–G6 结束后从 exact successor manifest materialize 的 `--content` gate：

```
content gate: non-editable install ok
content gate: origin ok
content gate: console entrypoint origin ok
content gate: deny-network enforced via sandbox-exec
content gate: ruff passed
content gate: pytest passed (347 passed)
content gate: ALL CHECKS PASSED
```

deny-network 在 sandbox-exec 边界内；ruff/pytest 及后代均在该边界内；非阻断 P0/P1 无遗留。
`--content` 不校验 control seal_state；control doc 改动后 seal_state 重置为 None，待独立 reviewer
重跑 materialized content gate 后重新封存。

## 残留与 E3 状态

- 本日志记录 G0–G6 executor 闭合时的状态（pre-review）。其后的独立 G0–G7 promotion review
  已完成（见 `docs/implementation/009_G0_G7_PROMOTION_REVIEW.md`）：reviewer 亲自重跑 materialized
  `--content` gate、`--check-membership`、`--control-seal`、`git diff --check` 与 ruff 全部通过，
  并把 Minimal Runtime Kernel、MCP、Memory、Scheduler、Skill、TUI 提升为 `locally-verified`；
  SubAgent 保持 `safe-unavailable + E3-blocked`。当前 claim 以 `CURRENT_CAPABILITY_STATUS.md`
  与该 review receipt 为准。
- E3 reference task 全部 pending：Skill/MCP/Memory/Scheduler/TUI 的真实 provider reference task，
  以及 SubAgent 的 bounded child review。
- SubAgent 额外受限于无满足 `ProviderDeadlineCapability`（hard-deadline）的真实 provider；按设计
  HTTP adapters 不满足该 contract，保持 `safe-unavailable`，不得伪造 eligibility。
- 产品 provider 配置（credential env、base-url、model）在本次 executor 环境中缺失（仅按名称探测
  存在性，未读取任何值）。
