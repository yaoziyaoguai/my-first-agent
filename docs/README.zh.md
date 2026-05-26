# First Agent 文档入口

这篇文档解决什么问题：给新开发者、架构审计者和 Coding Agent 一个稳定阅读入口，说明哪些文档是入口、哪些是 canonical spec、哪些只是历史记录。

不解决什么问题：不替代 Memory / Skill / SubAgent 的 RFC，也不记录每个历史版本的细节。

推荐读者：新开发者、维护者、Coding Agent、准备做审计的人。

## 读者路径

### 10 分钟理解项目

1. [根 README](../README.md)
2. [Current Capability Status](00-overview/CURRENT_CAPABILITY_STATUS.zh.md)
3. [First Agent Overview](00-overview/FIRST_AGENT_OVERVIEW.zh.md)
4. [Architecture Map](00-overview/ARCHITECTURE_MAP.zh.md)
5. [Capability Matrix](00-overview/CAPABILITY_MATRIX.zh.md)

### 准备本地运行

1. [Getting Started](01-getting-started/GETTING_STARTED.zh.md)
2. [Test Matrix](05-testing-dogfood/TEST_MATRIX.zh.md)
3. [Current Audit Status](06-audit/CURRENT_AUDIT_STATUS.zh.md)

### 了解当前阶段和下一步行动

1. [Current Capability Status](00-overview/CURRENT_CAPABILITY_STATUS.zh.md) — 当前能力、边界和下一步
2. [Capability Gap Audit](audit/capability-gap-audit-low-complexity-2026-05-25.md) — 本轮 low-complexity remediation 选择依据
3. [全局 Red-Team 审计](audit/global-red-team-product-architecture-audit-2026-05-25.md) — 架构/代码/UX/安全基础审计
4. [审计文档索引](audit/README.md) — active vs historical 审计分类
5. [计划文档索引](plans/README.md) — active vs historical 计划分类
6. [Dogfood 报告索引](dogfood/README.md) — active vs historical dogfood 分类

### 做架构或实现审计

- Memory canonical spec: [docs/rfc/MEMORY_CANONICAL_RFC.md](rfc/MEMORY_CANONICAL_RFC.md)
- Skill canonical spec: [docs/rfc/SKILL_CANONICAL_RFC.md](rfc/SKILL_CANONICAL_RFC.md)
- SubAgent canonical spec: [docs/rfc/SUBAGENT_CANONICAL_RFC.md](rfc/SUBAGENT_CANONICAL_RFC.md)
- Skill SDD/TDD/Loop/Audit: `docs/design/`, `docs/archive/testing/`, `docs/archive/roadmap/`, `docs/audit/`
- SubAgent SDD/TDD/Loop/Audit: `docs/design/`, `docs/archive/testing/`, `docs/archive/roadmap/`, `docs/audit/`

## 文档状态规则

- `docs/00-overview/`：当前中文入口，面向人类和 Coding Agent。
- `docs/01-getting-started/`：本地运行、测试、dogfood。
- `docs/05-testing-dogfood/`：测试矩阵和 dogfood 命令。
- `docs/06-audit/`：当前审计状态和发布前证据。
- `docs/rfc/`：canonical spec（MEMORY/SKILL/SUBAGENT），不能随意归档。
- `docs/design/`、`docs/dogfood/`、`docs/audit/`：系统级设计和实现循环证据，保留为实现依据。
- `docs/archive/`：历史 design/testing/roadmap/runtime-integration/specs/implementation-notes 等已归档。
- 根层 `docs/V0_*`、旧 release、旧 roadmap、旧 smoke 记录：历史证据，不作为当前入口。

## 术语约定

| 中文 | English | 含义 |
|---|---|---|
| 主代理运行时 | Parent Agent Runtime | 拥有主 loop、状态、模型调用和分派 |
| 工具注册中心 | ToolRegistry | 工具 authority，决定工具定义、风险、confirmation |
| 工具执行器 | ToolExecutor | 执行单次工具调用并处理 tool_result / checkpoint |
| 记忆治理 | Memory Governance | 决定 memory candidate 是否进入 store |
| 技能系统 | Skill System | filesystem-first 指令/资源包系统 |
| 子代理系统 | SubAgent System | parent-controlled bounded delegation |
| 检查点 | Checkpoint | 安全恢复边界 |
| 人工确认 | Confirmation / Ask User | 高风险动作和不确定决策的人类控制边界 |

## Provider 与配置边界

Claude Code / Claude / Anthropic 可以出现在历史文档、业界参考和 provider adapter
说明里，但不是项目主运行时依赖。生产代码中的 SDK lazy import 只能位于
`agent/provider/` adapter 内；`core.py`、Memory、Skill、SubAgent 和 dogfood runner
必须通过 provider interface / factory。

配置入口分三层：

- `config.py`：legacy runtime/CLI 兼容常量，不作为 provider dogfood 权威配置。
- `agent/provider/config.py`：provider/API 配置权威。
- `agent/local_config.py`：本地 agent customization metadata，默认不读真实 home、
  不读 `.env`、不展开 env secret。
