# docs/ 导航索引

维护状态：仓库已于 2026-09-09 冻结为学习里程碑（tag `study-freeze-2026-09-09-candidate`）。
当前能力状态的唯一权威是 [architecture/CURRENT_CAPABILITY_STATUS.md](architecture/CURRENT_CAPABILITY_STATUS.md)；
本索引只做导航，不改变任何文件的权威性。

## 当前权威（读这里）

| 文件 | 内容 |
|---|---|
| [architecture/CURRENT_CAPABILITY_STATUS.md](architecture/CURRENT_CAPABILITY_STATUS.md) | 当前能力状态矩阵（含 r18 closure record 与冻结声明） |
| [architecture/KERNEL_ARCHITECTURE.md](architecture/KERNEL_ARCHITECTURE.md) | 内核架构权威 |
| [architecture/EXTENSION_CONTRACTS.md](architecture/EXTENSION_CONTRACTS.md) | 扩展合同权威 |
| [architecture/capabilities/](architecture/capabilities/) | 六项 v1 capability 设计（MCP/Memory/Scheduler/Skill/SubAgent/TUI） |
| [acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md](acceptance/CAPABILITY_REFERENCE_TASK_PROTOCOL.md) | E3 reference task 验收协议 |

## 里程碑设计（012–019 冻结合同）

- [architecture/](architecture/) 下的 `012_*` 至 `018_*_DESIGN.md`：各交付里程碑的设计合同。

## 交付证据层（keep-locked，不得修改）

- [acceptance/](acceptance/)：各里程碑的 SEAL / RECEIPT / WHEEL / INDEPENDENT_REVIEW 与
  2026-07-25 七项 capability E3 记录（[records/](acceptance/records/)）。
- [implementation/](implementation/)：EXECUTION_LOG、DELIVERY_SEAL、009_DELIVERY_MANIFEST.json
  （被 `scripts/verify_*_materialized_tree.py` 硬编码引用）。
- 这些文件由 fail-closed 交付机制锚定；移动或修改任何一份都会使对应 verifier 链失效。

## 历史计划层（原地保留，见索引）

- [plans/INDEX.md](plans/INDEX.md)：36 份计划文档的执行状态索引（done/active）。
- [superpowers/](superpowers/)：governed-execution program 计划集；020a/020b/021/022 为冻结后
  尚未执行的候选计划，仅存档。
- [audits/](audits/)：历史审计（其中两份被 README 引用为证据链组成部分）。
- [articles/](articles/)：对外博客资产。

## 约定

- 新文档先在本索引登记再提交。
- 交付证据层不接受任何"清理""归档"或"同步"类修改。
