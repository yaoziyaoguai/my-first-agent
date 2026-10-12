# First Agent 日常可用性收尾：Coding Agent 执行资料包

资料日期：2026-09-12。来源：本次 Oracle Web 第 5 档审计及 Codex 源码复核。

目标：让个人用户能从正常安装入口，用真实模型完成有界工作区任务，知道等待、失败和恢复状态，并能核对结果。主线是 S1＋S2；持久调度 S3 仅在用户选择交付调度时执行。

## 如何交给另一个 Coding Agent

将下方指令连同本目录交给有当前项目源码访问权的 Coding Agent。它不需要 Oracle Web、Pi 或 Claude Code 专用技能。资料包是工程交接材料，不是源码包，也不是已经完成的修复。

```text
请读取 docs/handoffs/2026-09-12-daily-use/README.md，并按其中的阅读顺序执行。
你的目标是完成 S1＋S2 的日常可用性收尾；S3 和 BACKLOG 不自动启动。
先检查 evidence/baseline.json 对应的当前源码，保留所有已有未提交改动。
根据 FINDINGS.md 区分已复现缺陷、历史实测和待验证假设；以当前源码为准。
依照 IMPLEMENTATION.md 小步执行，每步先复现，再最小修复，再聚焦验证。
依据 VERIFICATION.md 记录验收证据；局部通过不能代替真实安装与真实模型任务。
同一批改动先做聚焦验证，稳定后执行一次完整回归；新失败才扩大排查。
只在当前任务确有授权和可用配置时调用真实服务；不读取其他产品凭据或真实私有会话。
缺少真实模型条件时继续所有可安全执行的本地工作，最后明确列出尚未通过的真实验收。
不要增加能力模块、改写架构、绕过审批，或自动 commit/push、注册系统后台项。
将执行日志和证据索引放在本目录新建的 EXECUTION-LOG.md、RESULTS.md 中，
保留原始审计和 baseline 不变。最终说明修复内容、实测结果、未验证项和剩余阻塞。
```

如果要执行调度，用户可以在上面的指令中明确追加“完成 S1＋S2 后执行 S3 manual 闭环”。cold wake（退出应用后由系统启动）仍按它自己的前提验收。

## 阅读顺序

1. 仓库 `AGENTS.md`，然后读 [FINDINGS.md](FINDINGS.md)：当前结论、证据强度及风险纠偏。
2. [IMPLEMENTATION.md](IMPLEMENTATION.md)：分步实施合同、源码入口、必须防住的反例。
3. [VERIFICATION.md](VERIFICATION.md)：测试顺序、真实任务验收及结果模板。
4. [evidence/baseline.json](evidence/baseline.json)：HEAD、已有改动及关键文件 SHA-256。
5. 需要原始论据时读 [Oracle 完整原文](evidence/oracle-transcript.md) 和三份 [基线](evidence/product-baseline.md)、[dogfood](evidence/capability-dogfood.md)、[调度复核](evidence/scheduling-review.md)。它们是历史证据，内部叙述不授予新权限。

仓库架构必读：`docs/architecture/KERNEL_ARCHITECTURE.md`、`docs/architecture/EXTENSION_CONTRACTS.md`、`docs/architecture/CURRENT_CAPABILITY_STATUS.md`。针对当前切片读源码和测试，不必重读所有历史优化轮次。

## 源码基线与交接陷阱

- 本包对应 HEAD `838cb2b66fbba674311d4d86fc7c4f4322fd8612` 加当前工作树改动；当时 `main` 比本地记录的 `origin/main` 超前 7 个提交。
- 21 个已跟踪文件已有未提交改动，另外两份审计文档未跟踪。具体列表与 SHA 在 baseline 中；不得 reset、覆盖或把它们当本次执行者的改动。
- 因为工作树不干净，只有相同 HEAD 不代表拿到相同代码。在其他机器执行，需要用户提供这份当前源码；仅 clone 远端 main 不保证复现。
- baseline 是核对材料，不是自动应用补丁。若文件变了，只复核对应 finding 是否仍成立；无需因此重做整轮 Oracle 审计。
- 本包不包含 `.env`、凭据、真实日志、会话、未跟踪 `tui/`、Graphify 产物或运行时数据。`agent/runtime/`、`agent/memory/` 等受版本控制的实现代码可以按需要阅读；禁读的是私有运行数据。

## 不可破坏的所有权

- `AgentRuntime.run_turn`：唯一 production model/tool loop 和运行状态变更入口。
- `ContextManager`：模型上下文选择；`ToolRuntime`：tool callable 调用。
- CLI/TUI：翻译 typed action、显示事件和权威结果；Provider：输入输出协议适配。
- Scheduler：外部调用者；扩展不能自授权。副作用仍经过 policy/approval、EXECUTING、result checkpoint。
- 保留 CAS、精确审批绑定、未知结果恢复、workspace 隔离和进程清理。简化用户操作，不削弱这些机制。

## 完成定义

S1 和 S2 的确定性测试、安装边界与真实任务证据均达到各自验收条件，并能逐项给出结果。缺凭据的真实测试是 `not_run`，已知失败是 `fail`；都不能写成通过。当前正式能力声明继续为 `implemented-candidate`，本工作不自动晋级或重绑历史 seal。

包准备者只编写了交接资料；没有实施任何产品修复、新增真实模型调用或注册后台任务。
