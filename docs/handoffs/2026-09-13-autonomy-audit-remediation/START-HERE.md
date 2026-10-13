# 执行入口：修复自主性交付审计遗留

资料包状态：**READY FOR IMPLEMENTATION**。这表示交接资料就绪，不表示产品问题已修复。
目标：让普通 Coding Agent 不依赖历史聊天，接续现有实现，修掉已确认缺陷并完成缺失验收。

## 直接交给执行者

> 请执行 `docs/handoffs/2026-09-13-autonomy-audit-remediation/START-HERE.md`。
> 先完整读取本包及其明确要求的上游合同，核对当前工作树，再按 FIX-PLAN 的 E0→E5 实施。
> 本次是接续修复，不是从头重建，也不是仅再写一份方案。先复现，最小修复，定向回归；
> 不每改一个点就重跑全部测试或全部付费任务。
> 必须核销 C1–C4、S1–S3、M1、U1–U5，并保留上游 F01–F24、A01–A24、D01–D12、R01–R03。
> 重点证明产品自己推进、检查、收尾，不能由你代做业务后记成产品成功。
> 遵守唯一 Runtime、权限、预算和未知副作用恢复边界。只为真正缺少的用户决定或外部条件
> 暂停受阻项，继续可安全推进的工作；不要把 fixture/grader 未实现说成 API Key 阻塞。
> 在 RESULTS 持续记录事实、失败、未验证与实际命令。整包验收未闭合不得报全部完成。
> 不 commit/push，不增加登录项/daemon，不处理真实私人历史，不在资料包或输出中存放密钥。

## 必读顺序与冲突处理

1. 仓库 [AGENTS.md](../../../AGENTS.md)、[内核架构](../../architecture/KERNEL_ARCHITECTURE.md)、
   [扩展合同](../../architecture/EXTENSION_CONTRACTS.md)、[当前能力状态](../../architecture/CURRENT_CAPABILITY_STATUS.md)。
2. [最新审计](../../audits/2026-09-13-autonomy-result-audit.md)：事实、复现与推断的依据。
3. 本包 [FIX-PLAN](FIX-PLAN.md)、[REPRODUCERS](REPRODUCERS.md)、[ACCEPTANCE](ACCEPTANCE.md)、
   [REAL-API](REAL-API.md)、[RESULTS](RESULTS.md)。
4. 上游 [SPEC](../2026-09-13-coding-autonomy-repair/SPEC.md)、
   [问题总表](../2026-09-13-coding-autonomy-repair/ISSUE-REGISTER.md)、
   [验收合同](../2026-09-13-coding-autonomy-repair/ACCEPTANCE.md)、
   [实施记录](../2026-09-13-coding-autonomy-repair/RESULTS.md)；按需读其 CODEMAP/WORK-PACKAGES。

本包是上游的审计补正，不替换或降低上游验收。当前用户指令及 AGENTS 优先；最新审计用于
纠正旧说明，不可把旧“待实现”文字当作当前代码事实。若实际代码已变，先复验，不机械套补丁。
交接时须携带整个仓库和上游文件；只复制此目录不足以执行。

## 已有实现，不要重复建设

当前已有目录级任务授权、精确 loopback、本任务开发服务、多步只读 child、流协议/续接、
进度取消、会话归档与工作记录等候选实现。它们不等于全部实测合格。
上游 START-HERE 中把其中数项写为“待实现”的段落过时；上游 RESULTS 的“离线完成”概括
也不能盖过最新 C/S 反例。不要重建第二套功能。

基线：`main`，HEAD `838cb2b66fbba674311d4d86fc7c4f4322fd8612` 之上的大量 dirty/untracked。
[BASELINE.sha256](BASELINE.sha256) 只覆盖本包选定的公开输入，不是完整候选身份。
从仓库根运行 `shasum -a 256 -c docs/handoffs/2026-09-13-autonomy-audit-remediation/BASELINE.sha256`。
漂移只触发阅读对应 diff，不授权 reset/stash/覆盖任何内容；实现后保留本基线不重写。

## 范围

- **结果**：修复真实缺陷；补齐可运行业务验收和新候选真实 Dogfood；提供准确可用配置与限制。
- **文件**：预计触及 evidence/state、managed process/resource lifecycle、Runtime/预算、provider、
  对应测试及最小验收夹具/脚本/文档；具体由复现决定，不先扩大核心抽象。
- **不做**：新 scheduler host、跨平台 sandbox、登录项、无限后台、全 PC 控制、新插件市场、
  任意并行写入、按行数拆巨石、自动 promotion。Scheduler 当前安装入口受限须如实说明。
- **证明**：E1–E3 的 Red/Green；全部 A 门禁；D/R 独立结果；最终安装候选身份及审计闭合。
- 不读取 `.env`、未授权凭据或私人数据，不读取根未跟踪 `tui/`；产品 `agent/tui/` 在范围内。
  真实 API 历史授权不得被旧 manifest 的占位值抹掉；具体执行边界见 REAL-API。

## 停止标准

可交付部分结果，但只有本包和上游必需项全部达标，才可写 `IMPLEMENTED AND ACCEPTED`。
缺 Chromium、缺明确预算/可用凭据或未知 ownership，要写具体阻塞与解锁条件；不能虚构通过。
即使全通过，也只证明所列环境/任务，不能声称任意任务、任意平台、任意第三方都可靠。
