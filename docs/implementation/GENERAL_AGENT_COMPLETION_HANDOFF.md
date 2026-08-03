# General Agent Completion — Claude Executor Handoff

## 1. Objective

在当前 009 sealed candidate 的后继隔离副本中，连续完成 `my-first-agent`
通用 Agent v1。不要停在“已有实现”“测试数量增加”或“文档已完成”。

最终产品应当：

- 只有一个 production model/tool loop：`AgentRuntime.run_turn`。
- 由 `ContextManager` 独占模型可见上下文选择。
- 由 `KernelToolRuntime` 独占 capability callable 调用。
- 通过同一条 policy、approval、checkpoint、recovery 路径使用文件工具、
  Skill、MCP、Memory 和 SubAgent。
- 由 Scheduler 作为 external caller、TUI 作为 typed action/event/result adapter。
- 能在真实本地 reference task 中证明六项能力有用户价值。
- 保留稳定扩展边界，不恢复旧实现，不增加第二套 loop。

这里的 loop engineering 是 Claude Code 的外部开发方式，不是产品 capability。
不得创建 `CodingLoop`、repo-local supervisor、第二套 Runtime 或自我开发功能。

## 2. User authorization

- 用户授权 Claude Code 在本隔离副本中以最大工程权限修改代码、测试和文档。
- 用户已撤销“禁止真实 E3”的限制。
- 用户将在确实需要产品 provider 时提供 API endpoint、API key 和 model。
- 在配置缺失前，继续完成所有不依赖该配置的代码、fault matrix、materialized
  verification 和本地 reference task，不得提前停止。
- 不读取、复制、输出或提交任何现有 secret/private/runtime 数据。
- 不修改 `/Users/jinkun.wang/work_space/my-first-agent` 原工作目录。
- 不 commit、push、tag 或修改 remote。

## 3. Baseline

- 后继副本创建后的全量基线：`322 passed`。
- 009 sealed 只证明候选交付可信，不代表 capability 完成。
- 当前没有 capability 是 `locally-verified` 或 `accepted`。
- `docs/architecture/CURRENT_CAPABILITY_STATUS.md` 和
  `docs/implementation/009_INDEPENDENT_REVIEW.md` 是当前缺口入口。

## 4. Continuous work queue

按依赖顺序连续执行。每项都遵循准确 Red → 最小 Green → fault matrix →
materialized-tree verification → claim 同步。一个单元通过后自动进入下一个，
不要等待用户逐项回复。

### G0 — Close retained 009 residuals

1. N1：显式验证 `first-agent` 与 `first-agent-schedule` console entrypoint
   来自临时 non-editable install，而不是 dirty tree。
2. N2：为 TUI 增加 event loss、duplicate、reorder 注入 oracle，证明 advisory
   event 不改变 authoritative checkpoint/control。
3. 修正 `CURRENT_CAPABILITY_STATUS.md` 中仍称 TUI 为 submit-only 的过时表述。

### G1 — Skill closure

- 在 invoke/read 前重新验证 trust-root identity、目录名、frontmatter name 和 digest。
- 完成安全 metadata disclosure。
- 覆盖漂移、unknown metadata、no-follow、oversize、resource replacement 与错误边界。
- 完成 operator-approved local Skill reference task。

### G2 — MCP closure

- 完整、确定、revision-bound 的调用 preview。
- 冻结 executable、argv、environment 和 server identity。
- transport、pagination、output、time、process group 全部有界。
- 完成 execution receipt、timeout/unknown outcome、cleanup 和 durable safety latch matrix。
- 使用无敏感数据的用户批准本地 stdio MCP server 完成真实 reference task。

### G3 — Memory closure

- strict durable snapshot、owner-only/no-follow store 和 revision CAS。
- preview 必须绑定完整 mutation、store revision 和 memory identity。
- 覆盖 corruption、concurrent writer、stale approval、budget/ranking 和 recall failure。
- conversation A 明确 remember，conversation B 在同 workspace/profile 召回并应用。

### G4 — SubAgent closure

- 保持 child 复用同一个 `AgentRuntime`，不得创建第二套 loop。
- 实现结构化 provider eligibility、hard total deadline、termination receipt、
  exact handoff 和 parent recovery。
- unsupported provider 继续 fail closed；不得用安全拒绝冒充正向能力。
- 产品 provider 配置可用后，完成 bounded child review reference task。

### G5 — Scheduler closure

- calendar-valid canonical UTC occurrence identity。
- duplicate fire、concurrent first fire、`conversation_busy`、checkpoint conflict
  和一次 bounded reconciliation。
- needs-human handoff 后由 CLI/TUI 完成 resolution，duplicate 再次触发时报告
  authoritative terminal state，不能增加 provider/effect count。
- 完成 benign external occurrence reference task。

### G6 — TUI closure

- 完成纯键盘 submit、approve、reject、recovery success/failure、resume、cancel。
- restart/reopen 只从 checkpoint 投影，零额外 provider/tool call。
- 与 CLI 使用相同 typed action、checkpoint、result 和 lifecycle close stack。
- 完成 CLI/TUI parity reference task。

### G7 — Product-wide verification and real use

- 真实 provider 下完成多轮对话、上下文预算、文件工具、approval 和 recovery。
- 逐项运行六个 E3 reference task并记录可复核的结果与限制。
- 从 exact successor manifest materialize，执行 non-editable install、entrypoint
  origin、deny-network automated gates、Ruff 和全量 pytest。
- 更新 README、current status、operator/reference-task 文档，删除过时完成声明。

## 5. Working rules

- 先读对应 capability design/plan 和 production code，再写准确 Red。
- 修复行为，不用 source-shape、mock-only、安全拒绝或总测试数替代正向证据。
- 一次只处理当前 queue item，但完成后立即进入下一项。
- 遇到普通测试失败、实现困难或 reviewer finding，自己定位、修复并重验。
- 不顺手增加新 capability，不恢复 legacy，不创建 compatibility fallback、
  service locator、dynamic plugin manager 或 dormant feature flag。
- Graphify、Understand Anything 只能作为 Coding Agent 辅助，不能进入产品 manifest。
- 不读取 `.env`、credential、旧 Memory、MCP、Skill、SubAgent 私有目录或真实日志。

## 6. Required checks

每个单元运行 focused tests。每个 capability closure 至少运行：

```bash
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
```

最终还要运行 successor materialized-tree/content gate。超时、截断、unknown exit、
skip/xfail 替代或仅 dirty-tree 通过都不算成功。

## 7. Stop and report protocol

不要因为完成一份文档、一个 happy path 或一个 capability 就停止。

只有以下情况可以结束 executor：

1. 所有不依赖外部产品配置的实现与验证已完成，并输出
   `GENERAL_AGENT_EXECUTOR_READY_FOR_REVIEW`；或
2. 只剩真实 provider E3 且缺少配置，输出
   `GENERAL_AGENT_NEEDS_E3_CONFIG`，并只列所需的环境变量名、endpoint 类型、
   model contract 和要执行的 reference task；不得索取或回显 key 值；或
3. 存在无法通过代码解决的真实 destructive/product decision blocker，输出
   `GENERAL_AGENT_BLOCKED`，附复现证据和已尝试方案。

`GENERAL_AGENT_EXECUTOR_READY_FOR_REVIEW` 不等于 accepted。随后必须由新的
Claude session 独立审查；任何有效 finding 都返回 executor 修复，直到独立 reviewer
确认全部门通过。

## 8. E3 execution result (2026-07-25)

本会话作为真实 E3 executor，在用户授权配置下完成七项 capability 的 reference task
（Kernel / Skill / MCP / Memory / SubAgent / Scheduler / TUI），全部 pass，bounded
证据见 `docs/acceptance/records/2026-07-25-*.md`。provider 为 `anthropic_compatible`、
`glm-5.2` @ `open.bigmodel.cn/api/anthropic`，credential 由子进程经 `ANTHROPIC_AUTH_TOKEN`
读取（值未进入 repo/log/record）。所有 effect 写入 mktemp 临时目录并清理。

E3 暴露并修复一个产品 bug：`main.py` 的 `--mcp-safety-state` 路径原用
`resolve(strict=True)`，首次 CLI 使用 MCP 即 `FileNotFoundError` 启动失败（latch 惰性
创建）。Named Red + 最小 Green（`resolve(strict=False)`）已合入，`tests/mcp/` 全绿。

按 promotion rule，晋级 `accepted` 仍需非实现 session 的独立 review；executor 不自封
`accepted`，claim 维持 `locally-verified`。`CURRENT_CAPABILITY_STATUS.md` 的 claim 更新
使其超出 u8 封存 digest，`--control-seal` 处于 pending-reviewer（未伪造 reviewer receipt）；
membership 与 materialized `--content` gate 仍绿。最终状态：
`GENERAL_AGENT_E3_EXECUTOR_READY_FOR_REVIEW`。
