# S1 Completion Audit — Intermediate Notes (non-authoritative)

> 中间审计产物。本文不是权威文档。重要结论已整理进 `TECH_DEBT.md` / `WORK_LOG.md`，
> 最终结论以审计报告与权威文档为准。日期：2026-06-17。

## 范围

独立 S1 完成度审计（非 goal loop、非继续按 gap 开发）。判断 S1 是否真正达到
`S1_GOAL.md` 的 Baseline Usable Product，核对 P0/P1/P2 完成证据，整理技术债与文档冲突。

## Commits audited: origin/main..HEAD (14)

f5b2709 audit | 24c4237 governance(AGENTS.md) | de57b6e roadmap+goal | dee2cb5 G-15 severity
d7d7f49 backlog reorder | 68e7d76 G-15 untrack config | fe4e398 G-16 README | 85ea264 G-17 acceptance
04a18b9 G-19 reconcile | 0c2f21c G-07b checkpoint | a727e89 G-12 multistep | 422ec5e G-03 real smoke
512c101 G-10 observability | ba1ce08 G-07 L2 umbrella

run↔commit 链一致；G-07b 是唯一生产代码改动（`agent/checkpoint.py +65`）。

## Acceptance criteria 独立核验矩阵

| AC | 要求 | 核验方法 | 结果 |
|---|---|---|---|
| AC-1 | fake 确定性 acceptance | 实跑 golden_e2e/smoke/wiring | ✅ 15 + 6 + 1 passed |
| AC-2 | fake vs real **events.jsonl** 对照同 spine | 读 real smoke 源码 | ⚠️ 运行产物层**未执行**：real smoke 是 provider+tool_executor 直调（源码 L122-124 自述"不是完整 AgentLoop"），不产 events.jsonl。same-spine 仅 G-04 源码层 + G-03 provider 层证据 |
| AC-3 | key-safe real smoke | default-skip 核验 + run16 证据 | ✅ 无 opt-in 时 3 skipped；run16 授权下 3 passed（未在本审计重跑真实调用） |
| AC-4 | 压缩不破坏 tool 配对 | 实跑 pairing+summarize | ✅ 3 passed |
| AC-5 | 最小多步 + checkpoint/resume | 实跑 G-12 + G-07b | ✅ 1 + 3 passed |
| AC-6 | config.yaml 不被跟踪+gitignore；tracked 无真实 key | git ls-files / check-ignore / 掩码扫描 | ✅ 未跟踪、`.gitignore:36` 命中、.env 不存在、tracked 无真实 key |
| AC-7 | README 可用 + 导航有效 | 读 README + docs/current 列表 | ✅ 导航 6 目标均存在；quickstart 引用 config.example.yaml 存在 |

结论：6/7 AC 完整核验通过；AC-2 仅源码层 + provider 层满足，**运行产物层对照未执行**。

## P0/P1/P2 gap 证据强度

全部 satisfied 且有 commit/命令/证据，独立复跑一致。唯一"证据有缝隙"= AC-2（见 TD-007）。
G-15/G-16/G-17/G-19/G-07b/G-12/G-03/G-10/G-07 均强证据。

## 全量健康检查（只读，不扩范围修）

- ruff: 451 errors（既有；S1 只动文档+少量 checkpoint 测试）。
- pytest full: **37 failed, 4745 passed, 12 skipped, 26 xfailed**（acceptance gate 全绿）。

### 37 失败归类（精确）

| 文件 | 数量 | 性质 | 归因 |
|---|---|---|---|
| test_docs_source_of_truth.py | 23 | 旧文档规制 guard（多 FileNotFoundError 找已迁 history 文档） | 22 既有；1（test_root_readme_references_project_status）由 G-16 引入 |
| test_v6_drift_addendum_boundary.py | 5 | 旧 Window/drift 边界 guard | 既有（引用已迁 history 文档） |
| test_architecture_boundaries.py | 3 | 旧 Window2/3 CM-1 inventory guard | 既有（FileNotFoundError docs/06-audit/...） |
| test_evidence_taxonomy_guard.py | 2 | l3 命名需 REAL core loop 断言 | 既有 |
| test_streaming_protocol.py | 1 | 找已迁 streaming doc | 既有 |
| test_provider_diagnostics.py | 1 | isolated flag 文案 | 既有 |
| test_config_secret_safety.py | 1 | **断言 config.yaml 应被跟踪** | **由 G-15 引入：与 untrack 决策相反** |
| test_capability_boundary_contract.py | 1 | 能力边界契约 | 既有 |

**仅 2 个失败由 S1 工作引入**（均为旧 guard 撞上正确的新 S1 交付）：
- test_config_secret_safety.py（G-15 untrack）→ 潜在隐患：失败信息会诱导未来 agent 重新 track config.yaml（工作树含真实 key）→ TD-005。
- test_root_readme_references_project_status（G-16 删 PROJECT_STATUS 引用）→ TD-006 一并覆盖。

35 个既有失败：origin/main 已存在（docs 早已迁 history）；均不在 G-17 acceptance gate 内。

## 文档一致性

- 架构审计 §0/§7/§10.1/§11 已与 G-15 调和（无"提交了真实密钥/需轮换"）✅（G-19 可核实）。
- TECH_DEBT 结尾"不入债"注记将 G-15/16/17/19/07b 以**现在时**列为"仍是 S1 必解项"，但均已 satisfied → 状态过期，需同步（本审计已修）。
- 冻结的 S1_GOAL.md 文本与落定实现有 2 处分歧（**不可改，frozen**，仅记录）：
  - AC-3 写"用 gitignored config/config.local.yaml"；实际 real smoke 经 env bridge 读 gitignored `config/config.yaml`。
  - AC-6 括注"真实 key 仅存于 gitignored .env"；实际 .env 不存在/不创建，真实 key 在 gitignored config.yaml。
  - 这两处的"当前正确口径"已由 G-15 / 架构审计 / GAP 承载，分歧仅残留在冻结目标文本。

## Verdict

S1 = **PASS WITH TRACKED DEBT**。理由见报告 C/D/O。
