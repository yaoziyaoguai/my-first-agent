# User-Usable Agent Runtime Issue Sweep

Date: 2026-05-25
Status: active
Based on: Post User-Usable Agent Runtime MVP Independent Audit (score 5/10)

## A. Current Baseline

以下事实基于仓库代码和独立审计证据：

| 事实 | 证据 |
|------|------|
| unified runtime flow 成立 | `core.chat()` → `loop.py` → Tool Pipeline 是唯一主流程 |
| fake/real 未分裂 | FakeProvider/RealProvider 共享同一 `chat()` 路径，仅 provider adapter 不同 |
| Tool pipeline 可用 | TOOL_GATE→TOOL_REQUEST→TOOL_INVOKE→TOOL_RESULT 四阶段 L3 verified |
| FakeProvider deterministic tool decision 可用 | 基于关键词匹配的 `_decide_tool_calls()` |
| Memory forget CLI 可用 + forget by ID | `detect_forget_memory()` → `remove_record()` by ID or content match |
| SubAgent delegate CLI + NL delegation | `detect_delegate_to_subagent()` + `detect_nl_delegation()` → `delegate_once()` |
| Streaming 是 fake/demo deterministic chunking | `FakeProvider` chunk_size=12（debug/fake only） |
| Trace run summary 含详情 | tool_names, memory_actions, subagent_names, error_reasons |
| MEMORY_RECALL AD complete — implementation deferred | `docs/design/MEMORY_RECALL_DUAL_PATH_AD.md` |
| Real provider opt-in docs 已存在 | README.md Real Provider Opt-in 章节 |
| CLI command router 已提取 | `agent/cli_commands.py` 独立模块 |
| Progress/event UX | subagent.delegating/delegated, memory.forgotten 事件 |
| 当前评分 ~6+/10 | post-issue-sweep 评估 |

当前目标：developer-usable / manual-dogfood-ready / local-user-usable agent。
不追求 broadly product-ready。

## B. Issue Backlog

### P2（用户可感知的能力缺口）

**Issue 1: core.py CLI meta-command 膨胀**

- 现状：`show memories` / `forget memory` / `show subagents` / `delegate to` 解析和渲染逻辑散落在 `chat()` 入口（~150 行），与 runtime orchestrator 混在一起
- user outcome：`core.chat` 职责清晰，命令解析独立可测试，后续新增命令不污染 core
- scope：提取 CLI meta-command 检测/渲染到独立模块；`core.chat` 保持唯一统一入口
- out of scope：不做 plugin framework、不做 command registry 抽象层、不做 CLI framework 迁移
- affected files：`agent/core.py`（提取）、新增 `agent/cli_commands.py`（command router/presenter）
- tests：现有 `test_subagent_user_facing.py`、`test_memory_interaction.py` 全部通过；新增 `tests/test_cli_commands.py` 验证提取后行为不变、无 direct runtime bypass
- safety：router 不执行 Tool Pipeline/Memory retain/SubAgent runtime 核心副作用；只能调用已有 runtime-facing service
- gates：ruff、focused tests、full gate
- expected demo：`python main.py` 交互模式下所有 CLI 命令行为不变
- commit：`refactor(core): extract CLI command router from core.chat`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

**Issue 2: SubAgent delegation 仅限 CLI meta-command**

- 现状：只有 `delegate to demo-stat: task` 格式触发，用户不能自然语言委托
- user outcome：用户说"帮我统计 demo workspace"就能触发 demo-stat
- scope：在 `chat()` 的 memory evaluation 之前增加 1-2 个 safe deterministic NL delegation fixture；仍走 `delegate_once()` + `SubAgentRegistry`
- out of scope：不让 FakeProvider 成为复杂 planner；不引入第二条 runtime；不做真实 LLM NL delegation
- affected files：`agent/core.py`（新增 `_looks_like_nl_delegation()` 检测函数）
- tests：`tests/test_subagent_user_facing.py` 新增 NL trigger/policy_blocked/not_found 测试
- safety：NL fixture 必须是 deterministic 关键词匹配，不调 LLM
- gates：ruff、focused tests
- expected demo：用户输入"帮我统计 demo workspace"→ demo-stat 返回 ok + summary
- commit：`feat(subagent): add safe NL delegation intent fixtures`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

**Issue 3: Streaming / progress overclaim**

- 现状：FakeProvider `stream=True` 时按 chunk_size=3 做 deterministic chunking，不是真实 provider streaming UX
- user outcome：用户看到的是 progress/event UX（工具调用中/完成/失败），不是 fake token chunking
- scope：(a) 调整 fake chunk_size 为可读值或标记 debug-only；(b) 确保 progress/event 是用户主体验；(c) 文档诚实标注
- out of scope：不实现真实 provider streaming
- affected files：`agent/provider/fake_provider.py`、`README.md`
- tests：`tests/test_streaming.py` 更新 chunk_size 断言
- safety：不改 streaming 架构
- gates：ruff、focused tests
- expected demo：fake streaming 输出可读；progress event 优先于 token chunk
- commit：`fix(streaming): make fake chunking readable, document as debug/demo`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

### P3（用户可用性 polish）

**Issue 4: Memory management IDs + forget by ID**

- 现状：`forget` CLI 只能按 content 精确匹配；`show memories` 不展示 ID/source/time
- user outcome：`show memories` 展示每条记忆的 ID、来源、时间；`forget <id>` 精确删除
- scope：(a) `memory_list_event` 和 CLI 输出增加 ID/source/created 字段；(b) `_looks_like_forget_memory` 支持按 ID forget（"forget id:xxx" / "忘记 id:xxx"）；(c) 保持 content match 兼容
- out of scope：不读取真实 memory episodes；不改变 Memory store 底层
- affected files：`agent/core.py`（forget CLI）、`agent/display_events.py`（memory_list_event）、`agent/memory_store.py`/`agent/memory_runtime.py`（如需要）
- tests：`tests/test_memory_interaction.py` 新增 ID forget/list fields 测试
- safety：只用 local/fake store；不读真实 episodes
- gates：ruff、focused tests
- expected demo：`show memories` → 看到 ID/来源/时间；`forget id:xxx` → 精确删除
- commit：`feat(memory): add stable IDs and forget-by-ID to memory CLI`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

**Issue 5: Run summary enrichment**

- 现状：run summary 主要是计数（N tools, M memories）
- user outcome：summary 显示具体 tool names、memory actions、subagent names、error reasons
- scope：(a) 在 run summary event 的 metadata 中增加 tool_names、memory_actions、subagent_names、error_reasons；(b) 脱敏
- out of scope：不泄漏 secret/private data；不改变 Trace 架构
- affected files：`agent/loop.py`（run summary event 构造）、`agent/display_events.py`
- tests：`tests/test_trace*.py` 验证 summary 字段
- safety：脱敏检查
- gates：ruff、focused tests
- expected demo：run summary 展示 `工具: echo_task_summary, write_demo_note | 子代理: demo-stat | 记忆: stored 1`
- commit：`feat(trace): enrich run summary with tool/memory/subagent details`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

**Issue 6: Progress/event UX for tool/memory/subagent actions**

- 现状：用户看不到"正在调用工具"/"正在委托子任务"等进度提示
- user outcome：用户能看到 tool started/completed、subagent delegated/completed、memory retained
- scope：复用现有 `RuntimeEvent`/`tool_requested`/`subagent_list_event` 机制，确保 chat() 路径中这些 event 被正确 emit 到 on_runtime_event
- out of scope：不实现真实 token streaming；不创建第二条 event runtime
- affected files：`agent/core.py`（确保 subagent delegation emit progress event）、`agent/loop.py`（确保 tool invoke emit progress event）
- tests：验证 user-visible progress event 在 chat() 输出中出现
- safety：不改 event 架构
- gates：ruff、focused tests
- expected demo：用户委托子代理时看到进度提示
- commit：`feat(ux): emit progress events for tool/subagent/memory actions`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

**Issue 7: SubAgent demo-stat fixture 太少**

- 现状：只有 demo-stat 一个 demo subagent
- user outcome：有 2 个 safe local demo subagent
- scope：新增一个 demo-notes 或扩展 demo-stat 能力；仍走统一 SubAgent delegation path
- out of scope：不做 multi-agent framework
- affected files：`tests/fixtures/subagents/`（新增 SUBAGENT.md）、`agent/subagent_system/executor.py`（如需扩展 deterministic outcomes）
- tests：新增 descriptor 加载和 delegation 测试
- safety：所有 fixture 都是 deterministic local-only
- gates：ruff、focused tests
- expected demo：`show subagents` 展示 ≥2 个 subagent
- commit：`feat(subagent): add second safe demo subagent fixture`
- safe-to-auto-run：yes；如果 Issue 2/6 已提供足够用户价值，可 skip
- stop conditions：只有 hard stop；可 skip

**Issue 8: Overclaim sweep**

- 现状：文档中可能有 "MVP complete" 等容易被误解的表述
- user outcome：所有文档诚实标注能力边界
- scope：扫描 README/roadmap/plan 中的 overclaim 表述，修正为 local/fake/manual-dogfood-ready 等标签
- out of scope：不改代码行为
- affected files：`README.md`、`docs/plans/*.md`、`docs/ROADMAP.md`
- tests：无需新增测试
- safety：N/A
- gates：git diff --check
- expected demo：文档标签诚实
- commit：`docs: sweep overclaim language, use honest capability labels`
- safe-to-auto-run：yes；可在最后做一次性 sweep
- stop conditions：只有 hard stop

**Issue 9: Manual dogfood checklist**

- 现状：没有 local manual dogfood checklist
- user outcome：新用户可以按 checklist 连续使用 10-20 分钟
- scope：创建 `docs/dogfood/local-manual-dogfood-checklist.md`
- out of scope：不做真实 API dogfood
- affected files：新增 `docs/dogfood/local-manual-dogfood-checklist.md`
- tests：N/A
- safety：只描述 fake/local/no-secret 路径
- gates：git diff --check
- expected demo：按 checklist 操作全部通过
- commit：`docs(dogfood): add local manual dogfood checklist`
- safe-to-auto-run：yes
- stop conditions：只有 hard stop

### Deferred / Blocked

| Item | Reason |
|------|--------|
| Real provider dogfood | 需要用户显式授权和 API key |
| Pre-loop MEMORY_RECALL implementation | AD complete — implementation deferred |
| Full Hook system | deferred；可在 roadmap 记录 |
| MCP confirmation="always" full pipeline | product decision required |
| Plugin marketplace / RAG / embedding | out of current scope |

## C. Execution Order

基于用户价值和技术依赖排序：

1. **Issue 1: Command Router extraction** — 结构债，先清理再扩展
2. **Issue 4: Memory management IDs + forget by ID** — 用户可直接使用的改进
3. **Issue 6: Progress/event UX** — 改善交互反馈
4. **Issue 5: Run summary enrichment** — 与 Issue 6 互补
5. **Issue 2: Natural-language SubAgent delegation fixture** — 降低使用门槛
6. **Issue 3: Streaming wording/chunking polish** — 消除 overclaim
7. **Issue 8: Overclaim sweep** — 文档诚实
8. **Issue 9: Manual dogfood checklist** — 最终验证
9. **Issue 7: Additional SubAgent fixture** — 如果仍有价值（可在 Issue 2 后评估 skip）

## D. Big Loop Stop Rules

只因 hard stop 停。以下不是 stop reason：
- 一个 issue 完成
- 文档完成
- focused test 完成
- 需要实现/测试/修 stale test
- commit/push 完成
- queue empty

## E. Per-Issue Gates

每个 issue：
- `git diff --check`
- `.venv/bin/ruff check agent tests scripts`
- 相关 focused tests
- 每 2-3 个 issue 或最终停止前：`HOME=/private/tmp .venv/bin/python -m pytest tests/ -x -q`

## F. Context Policy

- context <15%：不开始大型新 issue
- context <10%：完成当前 issue、minimal gate、commit/push、写 handoff
- context <5%：立即写 handoff、commit/push、HARD_STOP_CONTEXT_LOW_HANDOFF_WRITTEN
