# First Agent：真实使用问题修复资料包

日期：2026-09-13。用途：让一个能读代码、改 Python、运行测试的普通 coding agent 接手；不需要 Oracle Web、Pi、Claude Code 或原对话。

## 结论

先修“拒绝后收束、已有工具结果能否交付、Memory 入口可理解性”，再修恢复和提示。不要继续增加能力或重构整个内核。

没有证据支持 P0（已发生的严重越权/数据损坏）。有多项影响日常使用的 P1；已有文件批准、read-back 和并发漂移保护应保留。上一份 dogfood 报告中“无限循环”“MCP/child 已成功”“单次几十秒”等说法有证据越界，已在本包逐项纠正。

本包是**诊断与执行合同，不是已完成的修复**。本次只新增资料包，没有改产品代码、调用真实模型、访问私有状态或提交 Git。

## 交接方法

1. 将**当前仓库及其已有工作树改动**交给执行者；仅 clone GitHub 的 main 不一定得到被测版本。
2. 让执行者读取 [START-HERE.md](START-HERE.md)，其中有可直接粘贴的任务提示。
3. 按 [WORK-PACKAGES.md](WORK-PACKAGES.md) 顺序推进，每个切片先复现，再最小修复、定向测试。不要每改一处就跑全量。
4. 用 [VERIFICATION.md](VERIFICATION.md) 收尾，填 [RESULTS.md](RESULTS.md)。存在阻塞时明确交付部分结果，不拿离线 Green 代替真实任务成功。

文件导航：

- [FINDINGS.md](FINDINGS.md)：问题、优先级、证据强弱、原报告勘误与暂缓事项。
- [WORK-PACKAGES.md](WORK-PACKAGES.md)：修改范围、设计边界、Red test、验收合同。
- [VERIFICATION.md](VERIFICATION.md)：定向测试、真实模型任务、预算与证据标准。
- [BASELINE.md](BASELINE.md)：版本和已有改动，防止修错基线。
- [BASELINE.sha256](BASELINE.sha256)：当前相关源码、测试及历史材料的内容指纹，不是可安装快照。
- [RESULTS.md](RESULTS.md)：接手者的执行记录模板。

## 最小日用交付线

- 拒绝一次后不会马上再次劝批或换命令绕着问；已经完成的结果不丢失。
- 只要求文本/指定工具结果的任务，不凭空创建文件、执行 echo/sleep/Python 来“证明完成”。
- 已配置 Memory 时不再误报未安装；明确支持的“用户原文 → 批准 → 保存 → 召回”闭环有证据。
- 新任务入口、文件二次确认和运行中中断可理解，且不破坏未知副作用的恢复语义。
- 未支持/未验证的能力诚实报告；不提升 capability claim，不重绑历史 acceptance/promotion。

新 receipt 类型、自动新建 Goal、迁移偏好、扩大外发预授权、自动 mkdir 都不是本包默认授权的“顺手修复”。如果确定必须做，先提交窄设计和依据，再由用户决定。
