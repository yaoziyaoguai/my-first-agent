# 008 Coding Agent Handoff

下面的 prompt 面向 Claude Code + GLM 5.2。它授权连续完成本地实现与自动验证，但不授权 commit、push、真实外部调用、读取 secrets/private roots 或替用户做 E3 acceptance。

## Copyable prompt

```text
你正在 /Users/jinkun.wang/work_space/my-first-agent 中执行一次连续的 stabilization loop。

目标：完整实施 docs/plans/2026-07-19-008-stabilize-capability-reintroduction-plan.md 的 U0-U9，把当前六项 capability candidate 收口为有精确 automated claim 与 E3 eligibility verdict 的 candidates。自动门通过的能力可标 locally-verified；SubAgent 即使安全拒绝路径全部 Green，也必须在缺少合格 provider-native hard-deadline receipt 时标 E3-blocked。不要增加新能力，不要做 E3 reference task，不要把任何能力标成 accepted。

开始前按顺序完整阅读：
1. AGENTS.md
2. docs/architecture/KERNEL_ARCHITECTURE.md
3. docs/architecture/EXTENSION_CONTRACTS.md
4. docs/audits/2026-07-19-capability-reintroduction-audit.md
5. docs/architecture/CURRENT_CAPABILITY_STATUS.md
6. docs/plans/2026-07-19-008-stabilize-capability-reintroduction-plan.md
7. docs/acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md
8. docs/implementation/008_STABILIZATION_EXECUTION_LOG.md
9. docs/implementation/008_INTENDED_TREE_MANIFEST.json
10. docs/architecture/capabilities/TUI_DESIGN.md

执行原则：
- 这是一个长循环，不要每做一小步就停下来询问。按 U0→U9 串行推进，直到 Definition of Done 全部有可复现证据，或遇到真正需要用户决定的 blocker。
- 每个 unit 都先写一个会因目标缺口而失败的行为测试并运行得到 Red；确认失败原因准确后做最小 Green；再运行 touched-area tests。禁止先改实现再补迎合实现的测试。
- U1 的 shared Kernel regressions 必须先 Green，之后才能继续 effectful capability；MCP 的 U2-U3 未 Green 前不得运行真实 MCP。
- 保持 AgentRuntime.run_turn 是唯一 production loop/state owner，ContextManager 是唯一上下文选择者，ToolRuntime 是唯一 callable owner。不得添加第二套 loop、service locator、compatibility fallback、dormant feature flag、dynamic plugin discovery 或不可终止 helper thread。
- 工作树很脏，已有大量旧文件删除和新 Kernel/capability 文件。它们是本轮上下文，不要 reset、checkout、恢复旧实现或清理用户未跟踪内容。只改计划明确列出的文件和必要的直接依赖。
- U0 只冻结 intended-tree manifest 的 immutable baseline/control schema 与初始 exact membership；每个普通 entry 使用 ordered `owner_units`，同一路径被后续 unit 修改时追加 owner，U9 才写 final add/modify SHA-256。禁止用 repository-wide `git add -A` 或 glob 吞入后来出现的用户文件。manifest 自身不自我哈希；execution log 与 CURRENT_CAPABILITY_STATUS 不进入内容 `entries`，只在 U9 content gate 之后由 manifest 的 `control_files` 单向封存最终 SHA-256；verifier 必须证明它们不是执行、构建或 test-discovery 输入。
- 不读取 .env、credential、真实 Memory/Skill/MCP/SubAgent/Coding Agent 私有目录或真实日志。所有安全测试使用临时目录、sentinel 和 repo-owned fixture；不得进行真实 provider、真实外部 MCP 或网络调用。
- 不执行 commit、push、tag、remote 修改。不要为了让门通过而 skip、xfail、缩小 discovery、放宽断言或隐藏路径。
- Graphify 当前 graph 陈旧。只有能证明 refresh 不摄入 ignored/private 输入时才刷新；否则继续用源码和测试并在 log 记录跳过原因。

持续执行协议：
1. 在 docs/implementation/008_STABILIZATION_EXECUTION_LOG.md 更新当前 unit、Red command/关键失败、Green 改动、验证 command/exit code。只记录 bounded 摘要，不记录秘密或绝对 private path。
2. 完成一个 unit 后检查 git diff，确认每一行都可追溯到该 unit；修掉自己引入的 dead import/format 问题，不顺手重构。
3. 如果测试失败，诊断并继续修复；timeout、输出截断、缺 exit code、ignored source 或只测 test double 都不是 pass。
4. 发生 context compaction 或中断时，重新读取本 prompt、008 plan 和 execution log，从第一个未验证 unit 继续，不重做已被确切证据证明完成的工作。
5. 只有下列情况才停止执行并向用户提问：需要破坏性操作；需要真实 secret/private data/外部调用；计划出现无法从架构文档解决的产品选择；同一 blocker 已经通过三种安全方法验证仍无法推进。提问时给出证据、已尝试方法和最小决策，不要只说“需要更多信息”。

最低验证合同：
- 每个 A1-A19 finding 都有命名的 targeted regression test；severity 只决定优先级。
- 显式运行 Memory lint，不能依赖默认 Ruff ignore。
- 运行 plan 中的 focused fault/closure suites、architecture owner tests 和 U9 clean Git materialized-tree harness。
- 最终依次运行并取得未截断 exit 0：
  git diff --check
  .venv/bin/ruff check .
  .venv/bin/ruff check agent/memory tests/memory
  .venv/bin/python -m pytest -q -rx
- 从 clean Git materialized tree 再安装、collect、lint、test，证明新机器收到的内容与本地一致。
- materialized-tree gate 使用两阶段协议：先运行 `.venv/bin/python scripts/verify_materialized_tree.py --content`；把已知 exit/result 写入 execution log 后，将 log SHA-256 写入 manifest；最后运行 `.venv/bin/python scripts/verify_materialized_tree.py --control-seal`。content gate 必须从 materialized tree non-editable 安装到临时 venv/prefix，从 neutral cwd 且清除 import injection 后运行，并断言所有 product module/entrypoint origins 都在临时安装内，绝不能借原 dirty tree/editable import 假绿。脚本只能操作临时 Git index，禁止 stage 或改写真实 index；control seal 后不得再修改仓库文件。

完成时：
- U9 content gate 前保持 CURRENT_CAPABILITY_STATUS 的 pre-promotion claims；content gate exit 0 后，才按每项自动结果更新 status。全部仍不得标 accepted，SubAgent 另标 current HTTP providers unsupported / E3-blocked。
- 在 content gate 后只更新 CURRENT_CAPABILITY_STATUS 和 execution log，逐项列出 Red/Green 证据、最终命令、exit code、test count、未验证的 E3 和残余风险；随后在 manifest 中封存两个 digest 并运行 control seal。control seal 后只输出终端最终报告，不再写仓库文件。
- 给用户一个自包含最终报告：outcome、files changed、verification、known caveats、E3 下一步。
- 不 commit、不 push。

现在开始，从 U0 的 Git/Ruff delivery integrity 和完整 Red baseline 做起；连续推进，不要先复述计划后停下。
```

## Human-owned tail

Coding loop 完成只代表 automated/local readiness。用户随后只对被标为 eligible 的能力按 `docs/acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md` 逐项授权 E3；没有 record 的 capability 继续保持 candidate。SubAgent 在出现合格 provider-native hard-deadline/termination receipt 前保持 E3-blocked，不能用当前 HTTP adapters 做 reference task。
