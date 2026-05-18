# v0.9.x Stabilization Audit Checklist

Status: Audit checklist for v0.9.x stabilization / P3 refactor track.

本文供独立审计使用。审计目标是判断 v0.9.x Stabilization 是否保持行为中性、治理边界不变、dogfood 可信、benchmark 可复现，并且没有把 P3 重构扩张成新功能主线。

## 1. 审计输入

审计前应读取：

- `docs/refactor/V0_9_X_STABILIZATION_RFC.zh.md`
- `docs/refactor/V0_9_X_STABILIZATION_SDD.zh.md`
- `docs/refactor/V0_9_X_STABILIZATION_TDD.zh.md`
- `docs/refactor/V0_9_X_IMPLEMENTATION_LOOP.zh.md`
- `docs/refactor/V0_9_X_DOGFOOD_AND_BENCHMARK_PLAN.zh.md`
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- 相关 implementation diff。
- selected tests / full pytest / dogfood / benchmark evidence。

## 2. 总体审计问题

- 是否仍是 behavior-neutral refactor first？
- 是否有 characterization tests first？
- 是否保持 high cohesion / low coupling？
- 是否避免机械拆文件、贫血抽象、新巨石？
- 是否用证据定位问题，而不是表面打补丁？
- 是否在关键生产代码和测试中加入中文学习型注释/docstring？
- 是否没有修改 Memory governance、ToolRegistry authority、Checkpoint schema？
- 是否没有让 Skill/SubAgent 拥有主 Agent loop？

## 3. Observability 审计边界

v0.9.x 只允许 minimal debug/audit support。

允许：

- 定位 Runtime / Provider / Memory / Skill / SubAgent / ToolRegistry 问题的最小事件和记录。
- 支持 dogfood 结果证明的 evidence。
- 支持 audit evidence。
- 支持 checkpoint / confirmation / boundary debugging。

禁止：

- 引入 OpenTelemetry。
- dashboard。
- trace viewer。
- metrics system。
- span hierarchy 大设计。
- 复杂 event pipeline。
- 为 observability 扩大 runtime 复杂度。
- 让 observability 变成新的主架构线。

如果 trace / runtime events / streaming events 被包装成独立产品能力或新主架构线，应至少判为 P2；如果它改变 runtime 行为或隐藏 regression，应升级为 P1/P0。

## 4. P0: Release-blocking / safety-critical

P0 examples：

- Memory governance 被绕过。
- ToolRegistry 被绕过。
- Checkpoint schema 非预期破坏。
- secret 泄露。
- runtime data tracked。
- behavior regression hidden by tests。
- Skill/SubAgent 获得主 Agent loop ownership。
- Real LLM / `.env` 在未授权路径被调用或读取。
- dogfood report 泄露 API key / token / private runtime data。

P0 处理：

- 立即停止。
- 不继续 refactor。
- 不 push。
- 不 tag。
- 写 root cause evidence。
- 修复后重新跑相关 selected tests、full pytest、dogfood 和 audit。

## 5. P1: Major behavior or governance regression

P1 examples：

- core loop 行为变化。
- dogfood runner 变成 scripted pass。
- provider factory 被绕过。
- Memory `pending_review` 语义变化。
- test split 丢覆盖。
- synthetic checks 冒充 real execution。
- provider config 回退 legacy `config.py` 或 shell env fallback。
- confirmation 边界被 CLI/TUI、Skill 或 SubAgent 应用层绕过。
- Observability 事件改变 runtime state transition 或 checkpoint/confirmation 时机。

P1 处理：

- 停止当前 phase。
- 还原或修复导致 regression 的 scoped change。
- 补 characterization tests。
- 重新跑 selected tests 和 full pytest。

## 6. P2: Design debt / audit integrity issue

P2 examples：

- 新巨石文件。
- 低内聚抽象。
- docs 与代码不一致。
- config 仍有误导。
- benchmark 不可复现。
- governance matrix uncovered 被标记 pass。
- report 缺少 evidence source。
- helper 命名隐藏真实职责。
- Trace/runtime events 被设计成复杂 event pipeline，但尚未改变核心行为。
- 为 observability 增加不必要依赖或跨层 coupling。

P2 处理：

- 不应进入 release/tag 决策。
- 可以在同一 stabilization loop 中修复。
- 修复必须有 docs/test/audit evidence。

## 7. P3: Non-blocking polish / backlog

P3 examples：

- 命名 polish。
- 文档例子不足。
- 非阻塞大文件 backlog。
- 部分 helper 仍可进一步拆分。
- benchmark 样本数量可增加。
- dogfood report 可读性可提升。
- Observability future track 需要单独 RFC，但当前没有进入实现 scope。

P3 处理：

- 可记录为 backlog。
- 不阻塞当前 phase 完成，前提是 P0/P1/P2 为 0。

## 8. Track-specific checklist

### Track C: `core.py` slimming

- Runtime orchestration 仍由 Parent Runtime 拥有。
- 抽出的 helper 不执行工具、不写 Memory、不保存 checkpoint。
- checkpoint / confirmation / memory / tool result 行为不变。
- runtime events 只作为 debugging and audit evidence。
- 没有 Observability platform 化。

### Track M: Memory module refactor

- no silent retain。
- no auto approve。
- `pending_review` 语义不变。
- inline confirmation 不变。
- filesystem-first 不变。
- Skill/SubAgent 不直接写 Memory。

### Track D: Dogfood runner refactor

- synthetic checks 不冒充 real execution。
- real-api 仍 gated。
- provider factory 未被绕过。
- project dotenv scoped loader 安全。
- no shell env fallback。
- report 不泄露 secret。

### Track G: Config unification

- `config.py` legacy 职责清楚。
- `agent/provider/config.py` 仍是 provider/API config authority。
- `agent/local_config.py` 不展开 env secret。
- 无 import-time `load_dotenv()`。
- docs 与代码一致。

### Track T: Large tests split

- characterization coverage preserved。
- pytest discover 稳定。
- 没有删除历史覆盖。
- 没有弱化断言。
- 没有用 skip / xfail 掩盖失败。

### Track B: Benchmark baseline

- golden traces 可复现。
- fixed synthetic inputs hash 稳定。
- expected / actual boundary 可比较。
- uncovered 不等于 pass。
- benchmark 不依赖真实 LLM / `.env`。

## 9. Go / No-Go

Go 条件：

- P0/P1/P2 为 0。
- P3 明确记录且不阻塞。
- selected tests 通过。
- full pytest with temp HOME 通过。
- synthetic dogfood 通过。
- benchmark baseline 可复现。
- docs/audit status 同步。

No-Go 条件：

- 任意 P0。
- 未解决 P1。
- P2 影响审计可信度或 release 判断。
- full pytest 失败。
- dogfood regression。
- benchmark 不可复现。
- 需要真实 LLM / `.env` 才能证明默认 refactor 正确。
