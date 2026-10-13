# First Agent：有界可靠性修复执行包

日期：2026-10-02。状态：**资料包待执行；不代表修复已经完成。**

## 1. 任务与唯一范围

修复本次只读审计确认的四类问题，使“完成判断、浏览器正常退出后的收尾、验收评分、长期会话归档”可信。
用户要求资料包详细，但明确要求**不要扩大范围**。本包不是重启过去所有优化轮次的许可。

| ID | 本轮必须交付 | 不包含 |
|---|---|---|
| F1 | 成功执行但改写验证输入的 process 不得保留旧完成证据；可信同输入的多项验证仍可完成 | 全盘快照、任意外部文件一致性、第二套验证运行时 |
| F2 | 浏览器正常 shutdown 已确认清理后，重启能通过原受治理路径补记关闭并继续收尾 | 任意 crash 自动恢复、接管个人 Chrome、后台清理 daemon |
| F3 | Dogfood 只据 typed 状态、真实执行 receipt、独立行为检查判定；未测项明确不通过 | D07–D12 新场景、通用评测平台、付费场景大规模重跑 |
| F4 | 归档锁文件不再让有空余容量的工作区随使用次数增长而不可用，且不破坏互斥/恢复 | 全新历史系统、清理用户真实历史、破坏性迁移 |
| L1 | 准确保留调度入口、安装态、平台与真实 Dogfood 的未完成声明 | 接通 scheduler host、注册登录项、跨平台移植、自动晋级 |

本包通过，只能宣布上述修复与约定的本地验证完成；不能宣布“所有功能 production-ready”“全部真实 Dogfood 完成”。

## 2. 给执行者的直接指令

1. 先完整读取仓库 `AGENTS.md`、本文件、[FIX-PLAN.md](FIX-PLAN.md)、[ACCEPTANCE.md](ACCEPTANCE.md)。
2. [RESULTS.md](RESULTS.md) 是本次任务唯一进度与结果记录；修改该记录，不另建平行 CURRENT/新轮次计划。
   `docs/architecture/CURRENT_CAPABILITY_STATUS.md` 仍是项目总体能力声明入口，本包不能自行提升其等级。
3. 核对工作树和 [BASELINE.sha256](BASELINE.sha256)。不匹配时定位具体差异，不恢复旧代码、不重置用户工作。
4. 每项先写失败反例，再做最小修复和 focused 回归。旧测试通过不代表新反例不存在。
5. 建议顺序 F1 → F2 → F3 → F4 → L1/最终验证。阶段结束更新 RESULTS，不每改一行就全量测试。
6. 不因一项局部 Green 停工；完成本包可安全推进的全部事项。遇到必须扩大产品/权限边界的选择，记录真实阻塞并停止受影响部分，不擅自扩展。
7. 最后做一次集成 focused、一次完整项目 gate、限定的真实本地浏览器验证与安装态 smoke；标准见 ACCEPTANCE。
8. 交付结果摘要、实际 diff 范围、测试证据和未验证边界。**不要 commit/push/tag、不要发 PR。**

普通 Coding Agent 可以手动遵循这些步骤；不依赖 Oracle、Pi、Claude Code 或某一特定模型。
如宿主有 `dev_co`，可用其开发交接流程；实现阶段可用 `tdd`。技能不存在不阻止按本文执行，也不授权安装工具。
本任务不要求调用 `oracle-web`、`review`、`qa` 等完整外部工作流。

## 3. 基线与输入

- 工作目录：`/Users/jinkun.wang/work_space/my-first-agent`。默认在当前 `main`，遵守项目级规则。
- 审计 HEAD：`838cb2b66fbba674311d4d86fc7c4f4322fd8612`。
- 编包前：134 个 tracked 文件已修改，11,333 行增加、900 行删除；26 个 untracked 顶层状态条目（含目录）。
- `main` 相对本地缓存 `origin/main` ahead 7；没有 fetch，不代表实时远端状态。
- 以上 dirty/untracked 是既有工作。尤其本包依赖的 `resource_lifecycle.py`、验收脚本和测试本身可能尚未 tracked，不能忽略、删除或自动提交。
- BASELINE 是 29 个明确公开相关文件的 SHA-256，不是整个仓库身份或秘密扫描，不包含私有数据。

```bash
pwd
git status --short --branch
git rev-parse HEAD
shasum -a 256 -c docs/handoffs/2026-10-02-bounded-reliability-repair/BASELINE.sha256
```

基线不匹配本身不是错误：仓库可能被其他人推进。核对适用性、保留新工作，再在 RESULTS 记实际起点。
首次不要无条件重跑全量；先复现本包反例。

## 4. 不可改变的架构与安全边界

- `AgentRuntime.run_turn` 是唯一 production model/tool loop 和状态变更入口。
- `ContextManager` 独占上下文选择；`ToolRuntime` 独占工具 callable 调用。
- CLI、验收 driver、scheduler 只能作为 adapter/caller，不得另写 agent loop、绕过审批或直接把 Goal 改成完成。
- 所有 effect 保留 policy/approval、EXECUTING checkpoint、result checkpoint。
- 不增加 service locator、宽松 fallback、隐藏开关，不做按行数驱动的大文件拆分。
- 不读取 `.env`、密钥文件、真实日志/会话、私有 Memory/MCP/Skill/SubAgent 数据或未跟踪根目录 `tui/`。
- 测试仅使用新建临时 workspace/state/profile 与假数据。明确新建的测试 state 可以为验收而读，不能借此读取用户现有 state。
- 不调用真实 provider/MCP/外部站点，不读取或搬运历史聊天中的 API key，不更换模型/额度配置。
- 本地 loopback 服务、测试进程和专属测试 Chromium 仅用于本包验证；必须有界并清理本次自己创建的资源。
- 不新增或删除 macOS 登录项/launchd，不操作系统全局设置，不删除不属于本任务的进程、目录或锁。

## 5. 旧材料的地位

以下只作定位与历史证据，**其未完成大清单不是本包的额外任务**：

- [架构总览](../../architecture/KERNEL_ARCHITECTURE.md)、[扩展合同](../../architecture/EXTENSION_CONTRACTS.md)。
- [当前能力状态](../../architecture/CURRENT_CAPABILITY_STATUS.md)。
- [旧修复执行记录](../2026-09-13-autonomy-audit-remediation/RESULTS.md)，尤其第 88 行以后的追加记录。
- [既有场景 manifest](../2026-09-13-coding-autonomy-repair/TASK-MANIFEST.json)：本轮仅修复已物化场景的验收真实性，不补全全部 D/R 清单。

## 6. 变更预算与停止规则

- 所有改动必须能映射到 F1–F4 或 L1 的具体验收行。文件 allowlist 是导航而非必须全改。
- 可以补充本项必需的私有 helper、receipt 字段/严谨序列化和测试；涉及旧格式时必须准确拒绝不兼容记录，不能静默信任旧证据。
- 禁止以“修复不够优雅”为由替换整套运行时、浏览器、存储、评测或打包系统。
- 新发现的问题若不影响本包合同，写入 RESULTS 的“范围外发现”并继续原目标；不能自动另开一轮。
- 外部依赖缺失、权限拒绝或 paid API 未授权时，记录具体命令/原因/影响，不装全局依赖、不绕过限制。
- 完成本包后停止，不自动扩展 scheduler、跨平台、MCP/Skill/SubAgent 或真实 Dogfood 场景。
