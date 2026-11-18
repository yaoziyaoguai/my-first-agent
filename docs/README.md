# docs/ 导航索引

项目于 **2026-11-18 完成 v1.0.0 收官，功能开发已结束**。
2026-09-09 的学习冻结及随后解除冻结属于历史阶段。当前范围以能力状态页为准；
旧计划、候选清单和“下一步”不再构成待执行指令。

## 使用与当前状态

| 文件 | 内容 |
| --- | --- |
| [../README.md](../README.md) | 产品入口、架构与执行流程图、快速开始 |
| [guides/daily-use.md](guides/daily-use.md) | 日用操作、确认许可、会话与恢复 |
| [guides/capabilities.md](guides/capabilities.md) | 默认能力、可选范围与已知限制 |
| [guides/advanced-configuration.md](guides/advanced-configuration.md) | Provider、预算、归档与扩展配置 |
| [RELEASE-NOTES.md](RELEASE-NOTES.md) | v1.0.0 范围、身份与验证结果 |
| [architecture/CURRENT_CAPABILITY_STATUS.md](architecture/CURRENT_CAPABILITY_STATUS.md) | 当前能力声明的唯一权威，含收官快照与历史等级 |
| [handoffs/2026-10-25-continuous-improvement/STATE.md](handoffs/2026-10-25-continuous-improvement/STATE.md) | 当前收官记录；此前轮次保留作历史 |

收官记录中的 `previews/...` 是仓库外本机证据，未随 GitHub 仓库发布。
不把原始 provider 日志、checkpoint、私人会话或凭据作为补充文档提交。

## 架构与合同

| 文件 | 内容 |
| --- | --- |
| [architecture/KERNEL_ARCHITECTURE.md](architecture/KERNEL_ARCHITECTURE.md) | 内核模块所有权与状态约束 |
| [architecture/EXTENSION_CONTRACTS.md](architecture/EXTENSION_CONTRACTS.md) | 扩展接入边界 |
| [architecture/capabilities/](architecture/capabilities/) | MCP / Memory / Scheduler / Skill / SubAgent / TUI 的设计 |
| [acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md](acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md) | 历史 E3 reference task 协议 |

[architecture/](architecture/) 下的 `012_*` 至 `018_*_DESIGN.md` 保留各里程碑合同。
[images/](images/) 保存 README 的静态 SVG 架构与执行流程图；文字说明仍以源码和合同为准。

## 历史证据与计划

- [acceptance/](acceptance/)：SEAL / RECEIPT / WHEEL / INDEPENDENT_REVIEW 与
  [records/](acceptance/records/) 中的历史真实验收。
- [implementation/](implementation/)：EXECUTION_LOG、DELIVERY_SEAL、manifest；
  部分路径由 `scripts/verify_*_materialized_tree.py` 硬编码引用。
- [plans/INDEX.md](plans/INDEX.md)：2026 年 7–9 月的 36 份计划，原地保留。
- [superpowers/](superpowers/)：历史 governed-execution 计划；未执行候选仅存档。
- [audits/](audits/)：历史审计与输入包，部分内容绑定原始回执。
- [handoffs/](handoffs/)：各阶段交接、结果与固定证据副本。
- [articles/](articles/)：文章与配套资产。

## 维护约定

- 当前说明与历史时点分开；历史 PASS 只绑定其原始 identity，不自动晋级当前能力。
- 交付证据层保持原路径、原内容，不因清理或去重而移动、改写或删除；重复副本也可能承担独立的摘要与引用约束。
- 新使用文档在此登记；同一事实由原权威来源维护，其它入口负责链接。
