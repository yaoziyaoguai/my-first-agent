# PR #5 后的独立审计：先让普通任务可信地完成

审计日期：2026-10-17。代码身份：`main @ 0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`。
本地 `origin/main` 与 HEAD 相同；本轮没有 fetch，因此不声称已查询远端最新状态。
范围是上一执行包的交付与本地日用链路，不是对所有可选能力或全仓安全性的穷尽认证。

## 结论

现有项目已经具备一个受控本地 Agent 的主要执行能力，不需要再靠增加 Memory、MCP、Browser、Scheduler 或并行 Agent 来凑“产品”。本轮最该补的是：**任务结果是否可信、正常任务是否不用反复催促、授权是否实际可用，以及用户安装到的版本是否就是验过的版本。**

不应把它称为“垃圾”，也不能把已有测试数量当成“已经好用”的证明。比较准确的定位是：执行、恢复和安全边界投入很多，普通用户任务的完成闭环仍有硬缺口。建议把首版收敛为 **macOS 单用户、CLI、一个明确验证的模型配置、当前本地项目中的有界任务**。其它能力保持现状，不作为本包放行条件。

## 上一执行者实际做了什么

对照上次交接 `ef06b10`，已有 35 个文件变动、5121 行新增/202 行删除；PR #5 已合入当前 main。这不是“什么都没做”，以下工作应保留，不重新实现：

| 原工作项 | 当前可确认的完成部分 | 本轮判断 |
| --- | --- | --- |
| R1 恢复 | 历史拒绝 prefix 的严格布尔/UNKNOWN 守卫、安全闭合后续未执行调用 | 保留；本轮相关 focused 通过 |
| R2 身份与输入 | coverage receipt digest、严格 checkpoint/wire 解码、权威用户原文 pin、helper 不代填 coverage | 保留；但不等于需求完整性闭合 |
| R3 撤回 | 真正准入后的进程义务撤回，经过 Runtime、证据失效和完成链 | 保留 |
| R4 可发现性 | 无参数范围命令、显示时 snapshot 绑定、旧 ID 拒绝、单次 yes 不扩权 | 保留；散文目标仍使复用入口不可用 |
| C1/C2 | writer 关闭后真实重验、恢复后的工具配对投影与 opaque continuity 组合 | 保留 |
| Provider | OpenAI/Anthropic 对 context summary 的不可信 wire framing | 当前相关测试通过；需要最终安装身份复核 |

## 按重要性排列的剩余问题

### P1-1（本包放行阻断；Oracle 列 P0）：非空的错误完成声明仍会让漏做任务进入 `VERIFIED_DONE`

- 独立反例使用公开 D04 用户任务，它明确包含 service 和 CLI。
- 只写 service，CLI 保持原字节；给一条非空的笼统 satisfied coverage，引用全部原始 fact 和当前 admitted criterion。
- 当前 Runtime 在 4 次 scripted provider 调用后进入 `verified_done`；两个外部业务检查均失败，`cli_both_names=false`。
- 精确复现与解释见 [PROBES.md](PROBES.md)。这是当前生产状态转换路径的确定性反例，不是对真实模型失败率的推测。

根因不是“没有 coverage 字段”，而是 coverage 完整性的分母仍来自同一模型缩小后的 admitted 集合。`state._require_requirement_coverage` 检查引用与结构，无法识别一条覆盖所有 source ID 的笼统陈述是否漏掉了其中的要求。现有遗漏测试只拒绝**空** coverage，随后 provider 脚本固定补写 CLI；它没有证明非空但错误的覆盖会被拦住。

处理边界：不要求 Runtime 理解任意自然语言，不做第二模型裁判、不做 D04 文件名/关键词特判、不用更长提示词冒充确定性保证。必须把“已观察到的动作证据”“逐项需求自检”“经独立验收的结果”区分开，并用本反例与完整正例检验实际状态合同。具体冻结方案见执行包，不让执行者自行选择一个容易绿的含糊解释。

### P1-2：正常任务的产品自收尾没有满足原验收，报告却已判整体闭合

公开 RESULTS 自报：E1-A 外部业务和补充 7/7 通过，但用了 40 个物理请求、17 次治理批准、2 次 limit resume，最后为 `paused_limit`，没有到 typed `VERIFIED_DONE`。E1-B 分阶段纠正/新进程恢复成功，20 个请求、5 次审批。

这些是**上一执行者的公开记录**，本轮没有读取其私有原始日志，也没有再调用真实 API。E1-B 的成功不能替代 E1-A。原 `2026-10-13-task-trust-repair/VALIDATION.md §3` 明确要求两个正例均真正完成；“安全地没完成”值得保留，但不是完成。

`scripts/run_task_trust_d04.py` 还允许 normal 模式额外注入 CORRECTION，并在 idle 时主动发“继续当前任务”（上限 3 次）。这不等于此前隐瞒了提醒次数，但它不能证明“无须催促”的正常用户旅程。最终 `evaluate_final` 对未终结样本本来会判 incomplete；过强结论主要出现在报告摘要。

Oracle 另指出两个 driver 缺陷，Codex 已在当前仓库独立复现：normal 即使 typed/业务/补充全部通过，也会因没有额外 correction 被判 incomplete；`--max-resumes` 与 `--max-consents` 没有经 `_provider_extra`/`_child` 传到子进程。见 PROBES/P3。这是有区分力的交叉审计增量，不是重复本地结论。

不能凭这份汇总将 40 次请求全部归因于 evidence freshness、模型弱或审批。没有当前逐轮分类证据，下一轮应先记录有限类别，再做对应的最小修复，而不是放大预算硬跑。

### P1-3：授权能力存在，但普通 SPEC 任务可能完全用不上

`state._goal_target_authorization_scope` 要求 exact 文件路径存在于 `goal.targets`。模型可合法把 targets 写成散文。用当前 CLI fixture 将 targets 换成“实现 SPEC.md 中要求的笔记功能”，当前文件为 `notes/idea.md`，投影得到 `(None, None)`，范围命令不产生 action，只能每次批准。

新提示诚实解释了这个限制，却没有解决交互。不能简单允许整个目录；可考虑由人对**刚显示的确切当前文件**显式选择现有有界租约，保留同 Goal/revision/workspace/tool、binding digest、60 分钟/16 次、撤销及敏感路径边界。完整复现见 PROBES。

### P2-1：最终安装证据身份没有覆盖最后的产品变动

I1/G1 的公开记录在 2026-10-15；随后仍修改 `agent/provider/normalize.py`、`agent/cli/render.py`、`main.py` 等。README/能力矩阵却用此前的 3873/41 等数字描述“当前 identity”。这些历史证据有价值，但不证明现在装出的 wheel。应只对最终修复后的支持面重建一次新候选/安装验证，不重新做七项历史能力的 promotion。

### P2-2：日用入口说明与实际支持边界不一致

日用指南的模型例子为 `deepseek-flash`，当前公开 E1 记录为 `deepseek-v4-flash`；安装示例假定 wheel 已存在，当前 README 主要按开发仓库构建。下一轮只把首版配置、安装物、证据范围和 `/new`/重启恢复的一条路径讲清楚。不把普通用户带进 016–019 的内部验收术语，也不把旧版本真实 PASS 标成当前支持保证。

## 没有足够证据，不能先算成已确认缺陷

- blocked 分支只凭 admitted 物理证据给出“应该 completion_claim”的指引，没有业务覆盖判断；与 P1-1 相关。当前尚未独立构造“真实合法 blocker 被误拒”的完整反例，不能单独宣称已复现。
- 后续 workspace mutation 会使旧 readback 失效。这是已有保守安全合同，尚不能证明它就是 E1-A 的请求消耗根因，不准为省调用直接放宽。
- Goal 原文 pin 有预算上界；尚未证明日常短任务因此不可用，不开启新记忆系统。
- 单次 POSIX/进程清理历史 flake 不等于当前仍失败。本轮两个最新相关文件共 95 项通过；这不证明永不 flaky。
- Browser 当前 D06 真实模型旅程、Scheduler 可用 host、其它平台/模型组合不在本轮证明范围。它们不是本地 CLI beta 的强制新增工作。

## 本轮本地验证

已执行 focused：

```bash
PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx --tb=short --color=no \
  tests/acceptance/test_task_trust_completion.py \
  tests/acceptance/test_task_trust_d04_driver.py \
  tests/cli/test_contextual_decisions.py \
  tests/cli/test_render.py \
  tests/kernel/test_context_budgeting.py \
  tests/kernel/test_validation_request_freshness.py \
  tests/provider/test_continuity_control.py \
  tests/continuity/test_verified_done.py \
  tests/continuity/test_checkpoint_v4.py
```

结果：310 passed，16.91s，exit 0。

追加 `tests/automation_hosts/test_posix_supervisor_cleanup.py tests/provider/test_kernel_providers.py`：95 passed，3.90s，exit 0。两组共 405 个测试；不是另有 405 个新测试。

文档内探针按实际代码执行：P1 错误完成、P2 范围缺失、P3 driver 误判/参数缺失均复现。ruff 通过。

当前源码完整门：`PYTEST_ADDOPTS='' PYTHONDONTWRITEBYTECODE=1 PIP_NO_INDEX=1 .venv/bin/python -m pytest -q -rx --tb=short --color=no` → **3897 passed, 1 skipped in 564.22s**，exit 0。不是沿用旧的 3873 成绩；本轮没有修改产品源码。没有本次 installed 或付费产品 API 证据。

skip 定点复核为 `tests/automation_hosts/test_launchd_real.py:30`：`real launchd probe requires explicit host gate`。未启用该 gate、未增加或修改登录项。最终文档检查：10 个本地链接有效、8 份 Oracle 输入/答案/身份回执哈希匹配、12 个对应公开源文件未漂移；key-like/private-key 模式零命中。三个 PROBES 代码块已从文档提取执行，均 exit 0 且复现所述当前问题；这不表示修复通过。手写文档无行尾空白，`git diff --check` 与 ruff 通过。

## Oracle 交叉审计与本地采纳

独立会话 `mfa-daily-audit-20261017-f7d29c`，实际 ARIA 为 **Power, item 5 of 5**；发送前再次确认档位，有新的已提交 conversation，答案完整捕获。会话结束后 exact Chrome PID 已退出、临时 Profile 不存在，没有手动点发送或复用旧会话。输入与答案 SHA、身份及清理回执见 [ORACLE-RECEIPT.json](ORACLE-RECEIPT.json)，原回答见 [ORACLE-ANSWER.md](ORACLE-ANSWER.md)。

采纳：三个修复包加一个交付门；明确交付对象不能被草稿省略；普通范围授权须基于已有 Runtime/人类批准绑定；normal 无 correction/催促；最终身份准确绑定。新增 driver 两项已本地重验。

没有机械照搬：Oracle 的“明确交付对象下界”是方案方向，不是已经实现/验证的通用语义解析器。WORK-PACKAGES 将其限定为当前权威文本中明确文件交付的有限规则、判别矩阵与现有 state/admission 路径，不允许扩成新平台或用多条自报声明代替。授权候选也不能来自任意 pending path。blocked 误拒仍先复现再修。

Oracle 没有本地运行 Runtime 反例或本仓库全量，仅对附件提取的 driver 纯函数作了合成检查；没有外查行业资料。本地 405 focused、3897 全量与 Runtime 探针是 Codex 本轮执行结果，不能写成 Oracle 执行成绩。最终结论不是多位模型投票，而是以实际复现与验收合同为依据。

## 产品取舍

- **做得重：** 多层状态、证据、授权、历史晋级记录和测试材料很多；每次想证明所有能力都会拖慢日用闭环。不要再造第二套治理/评测平台。
- **做得轻：** 任务完整性独立反例、无提醒的正常旅程、实际可用的文件授权、安装版本身份和普通用户入口。
- **不应变轻：** UNKNOWN 不重放、审批 exact 绑定、工具边界、当前版本证据与失败诚实性。这些是已有价值，不是为追求“流畅”可以删的障碍。

本轮只制作审计与执行资料包，不修改产品、不 commit/push，不触碰未知未跟踪 `result.phase.json`。下一位执行者按 START-HERE 的范围与当前授权推进。
