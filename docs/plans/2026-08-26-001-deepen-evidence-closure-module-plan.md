# 2026-08-26-001 evidence closure 模块深化（bounded architecture loop）

## Scope

单一架构候选：把散落在 `AgentRuntime` 私有方法里的 evidence-closure 纯知识
（`_pending_goal_obligation_tools`、`_repairable_evidence_tools`、
`_evidence_repair_instruction`）收进 `agent/runtime/evidence.py`，使
closure/repair 知识高内聚、测试面收敛到模块接口。

非目标：blocked-claim grounding 重构、process lifecycle、tool governance、
provider codec、checkpoint schema、产品特性、机械拆文件。

## Protected seam

- **Owner**：`ClosedEvidenceRegistry`（`agent/runtime/evidence.py`）现在拥有完整
  子簇——`derive`（证明）、`pending_obligation_tools`（缺失义务）、
  `assess_gap`（缺口 → 可修工具 + 有界修复指引，单一 `_GAP_REPAIRS` 表分发）。
  reason 字符串由本模块 raise，修复分发与 raise 同文件演进。
- **Consumer**：`AgentRuntime` 仍是唯一 production model/tool loop 与状态变更
  入口；它在 blocked/completion 修复路径消费 `EvidenceGapAssessment`，仍持有
  provider/tool 调用、CAS/checkpoint、control 处理与状态迁移。无任何 Runtime
  所有权移动。
- **Test surface**：缺口/义务知识经由 registry 接口测试
  （`tests/kernel/test_evidence_registry.py`）；经由 `run_turn` 的集成测试不变。

## Key decisions

1. `_repairable_evidence_tools` 与 `_evidence_repair_instruction` 合并为一张
   精确键表 `_GAP_REPAIRS`：条目同时携带候选工具与专属指引，消除 Runtime 侧
   两个平行字符串分发器的漂移面。`repair_instruction` 与工具可用性无关，
   `repairable_tools` 才是可用工具投影，故无工具上下文的调用方可省略
   `available_tools`。
2. 保留旧 asymmetry：旧 instruction 分发器对 `required source kind must
   contain extracted web content` 家族使用子串匹配，而 tools 侧始终精确匹配。
   `assess_gap` 在精确键 miss 时对该家族保留单一 substring 指引分支（常量
   `_WEB_CONTENT_KIND_*` 单点定义，复用表条目的 instruction）：带额外上下文的
   reason 取得与 exact reason 相同的专属指引，但不凭 substring 取得修复工具；
   其余 reason 一律精确键，miss 落入通用兜底。
3. `pending_obligation_tools` 逻辑逐字迁移（含 process entrypoint 相关性判定），
   依赖 `agent.runtime.state` 的两个纯函数；state 不反向依赖 evidence，无环。

## Review fix（2026-08-26，Codex Spec 审计）

审计发现初版实现把上述家族统一为精确键，带上下文的 reason 退化为含
`blocked_claim` 的通用兜底，违反本轮 failure semantics 不变。修复：回归测试
`test_gap_assessment_extended_web_kind_reason_keeps_substring_instruction`
（Red 确认后）+ `assess_gap` miss 分支的单点 substring 指引保留（见 Key
decisions 2）；不泛化模糊匹配，不触及其他 reason 家族与任何 Runtime 路径。

## Verification

- 基线：focused 99 passed（test_runtime_errors / test_verified_done /
  test_evidence_registry / test_research_evidence）。
- Red→Green：9 个新接口测试先 AttributeError Red，实现后 focused 108 passed；
  review fix 追加回归测试后再 Red→Green，focused 109 passed。
- 行为保真：从 git HEAD 提取旧两分发器，与新接口逐一对比输出——review fix
  后 21 reasons（15 表键 + 动态 f-string + 未知 + substring 家族的严格前缀 /
  扩展后缀 / 近邻家族对照）× 6 工具集**全部全等，无例外**。
- 首轮全量：`.venv/bin/python -m pytest -q -rx` 一次通过（1472 passed，
  review fix 前）；review fix 后 focused 109 passed，最终由外部审计对稳定代码树
  运行全仓 Ruff、`git diff --check` 与一次全量 pytest：1473 passed。
