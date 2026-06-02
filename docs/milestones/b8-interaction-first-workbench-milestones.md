# B8 Interaction-first Workbench — Milestones

**创建日期**: 2026-06-02
**状态**: COMPLETED-WITH-CAVEATS — M1-M8 delivered as fake/local foundation, current-stage close-out candidate
**依赖文档**: `docs/proposals/b8-interaction-first-workbench-proposal.md`

---

## Actual Status Override (2026-06-02)

本文最初是 M0-M8 规划文档。当前事实以代码、测试和 `docs/audit/b1-b8-current-stage-close-out-audit.md` 为准：

- M1-M8 已作为 **fake/local foundation** 交付；412/412 TUI tests PASS，tsc clean。
- M6/M7 是 foundation/contract/fixture viewer，不是真实 multi-instance runtime 或真实 runtime event stream。
- TUI default entry **NOT ACTIVATED**；M8 是 readiness checklist，不是默认入口启用。
- 旧 Dashboard / AutoRun / Project Operations / Audit 面板保留为 legacy/auxiliary，不在当前 WorkbenchLayout 默认主线。

下方仍保留部分规划期 exit criteria；如与本节冲突，以本节和 close-out audit 为准。

---

## 核心原则

**Milestone 按"主入口成熟度"定义，不按"面板数量"定义。**

每个 milestone 回答一个问题：用户离"把 TUI 当 First Agent 主入口"还有多远？

---

## M0 — Existing TUI Inventory / Direction Correction

### Goal
确认当前 B8 资产，纠正产品方向，为后续 interaction-first 开发建立清晰基线。

### Scope
- 完成 B8 Phase 1-6A 能力清单
- AutoRun 降级为 dev-only（已完成 — cdad13f）
- Product direction 从"信息展示中心"改为"interaction-first workbench"
- Existing audit panels 重新定位为 auxiliary（保留，但不占主界面）
- Proposal + Milestones + SDD + TDD Plan 文档就绪

### Non-goals
- 不修改任何 TUI 代码
- 不新增 UI
- 不改变 default entry 状态

### Required Docs
- `docs/proposals/b8-interaction-first-workbench-proposal.md`
- `docs/milestones/b8-interaction-first-workbench-milestones.md`（本文件）
- `docs/design/b8-interaction-first-workbench-sdd.md`
- `docs/plans/b8-interaction-first-workbench-tdd-plan.md`

### Required Tests
- 规划时既有 287/287 TUI tests 必须继续 PASS；当前 close-out gate 为 412/412
- tsc --noEmit clean

### Exit Criteria
- [ ] Proposal 清楚回答 why/what/boundary
- [ ] Milestones M0-M8 定义完成
- [ ] SDD 定义布局、数据模型、安全边界
- [ ] TDD Plan 覆盖所有 milestone 的测试策略
- [ ] Roadmap/debt/status 与上述文档一致
- [ ] 当前全量 TUI tests PASS, tsc clean（close-out gate: 412/412）

### Stop Conditions
- 文档自审未通过 → 继续修文档，不进入 M1
- 现有 tests regression → 先修 regression

### What Must Not Be Claimed
- 不得声称 "B8 产品方向已最终确定"（需用户确认 proposal）
- 不得声称 "TUI 已具备交互能力"
- 不得声称 "default entry ready"

---

## M1 — Interaction-first Layout

### Goal
TUI 默认布局从"7 视图工作台"改为"Agent Lens / Interaction View / Context Panel"三区域布局。默认焦点在 Interaction View。现有 auxiliary panels 不再抢占主界面。

### Scope
- 实现 `WorkbenchLayout` 组件：左侧 AgentLens (25%) / 中间 InteractionView (50%) / 右侧 ContextPanel (25%)
- 实现 `InputBar` 组件（底部输入区域，初期只接受文本，不发送）
- 实现 `StatusBar` 组件（底部状态栏）
- 实现 `AgentLensPanel` 组件（agent/session/run/instance 树，初期 fake/local fixture 数据）
- 实现 `InteractionPanel` 组件（对话展示区域，初期只显示 placeholder）
- 实现 `ContextPanel` 组件（通用 Context/Inspector placeholder，不复用 project-specific evidence/gate/audit 面板）
- 旧 7 视图导航不进入默认主线；如未来需要，只能作为重新设计后的 auxiliary/dev-only 能力
- 键盘焦点管理：默认焦点在 InputBar，Tab 切换到 AgentLens/ContextPanel

### Non-goals
- 不连接真实 runtime gateway
- 不发送真实 input 到 agent
- 不读取 .env
- 不调用真实 API
- 不激活 default entry

### Required Docs
- SDD §3 Layout Architecture 更新为已实现状态
- M1 completion report

### Required Tests
- Layout 结构测试：AgentLens/InteractionView/ContextPanel 三区域存在
- 焦点管理测试：默认焦点在 InteractionView
- InputBar 接受文本输入
- AgentLens 展示 fake fixture 数据
- 键盘导航测试（Tab 切换区域）
- 现有 287 tests 回归

### Exit Criteria
- [ ] `npm start` 渲染三区域布局
- [ ] InputBar 可输入文本
- [ ] AgentLens 展示 fixture agent/session/run 树
- [ ] Tab 可在三区域间切换焦点
- [ ] 旧 auxiliary panels 不占用默认布局；当前 WorkbenchLayout 不提供整页 Dashboard 切换
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- 布局实现导致现有 tests regression → 先修回归
- 需要读取 .env / secrets → HARD_STOP
- 布局方案需要用户重新确认 → 停止并询问

### What Must Not Be Claimed
- 不得声称 "交互能力已就绪"
- 不得声称 "default entry ready"
- 不得声称 "真实 agent 连接已验证"

---

## M2 — Agent Lens / Selected Context

### Goal
Agent Lens 可以展示和切换 agent/session/run/instance，切换后 Interaction View 和 Context Panel 同步变化。

### Scope
- `AgentLens` 数据模型：AgentLensNode（id/type/label/status/children）
- `SelectedLens` 状态管理：当前选中的 agent/session/run/instance
- `AgentLensPanel` 增强：树形展开/折叠、↑↓ 导航、Enter 选中
- `InteractionView` 响应 lens 切换：清空对话历史，显示新 context
- `ContextPanel` 响应 lens 切换：重新加载对应 evidence/gate/audit 数据
- 状态标记：active/paused/completed/failed/historical/superseded
- 初期数据：self-contained fake/local fixture；不读取 `PROJECT_STATUS` / `PROGRESS_LEDGER` 作为主 UI 数据源

### Non-goals
- 不连接真实 runtime 获取 agent/session/run 列表
- 不实现真实多实例并发
- 不写 runtime state
- 不激活 default entry

### Required Docs
- SDD §4 Data Model 更新 AgentLens/SelectedLens 实现状态
- M2 completion report

### Required Tests
- AgentLens 树渲染：≥3 agent nodes, 每个 ≥1 session, 每个 session ≥1 run
- ↑↓ 导航在树节点间移动
- Enter 选中节点 → selectedLens 更新
- selectedLens 变化 → InteractionView 清空
- selectedLens 变化 → ContextPanel 数据重载
- 状态标记正确渲染（active/paused/completed/failed）
- 空树状态：无 agent/session/run 时展示 empty state
- 现有 tests 回归

### Exit Criteria
- [ ] AgentLens 展示 ≥3 agent 的模拟树
- [ ] ↑↓/Enter 可切换 selected lens
- [ ] 切换后 Interaction View 显示 "Agent: X / Session: Y / Run: Z"
- [ ] 切换后 Context Panel 数据刷新
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- Lens 数据模型需要真实 runtime identity → 停止，不伪造
- 需要访问 .env / real API → HARD_STOP

### What Must Not Be Claimed
- 不得声称 "真实多实例支持"
- 不得声称 "runtime identity 集成完成"
- 不得声称 "default entry ready"

---

## M3 — Interaction MVP

### Goal
用户可以在 InputBar 输入文本，通过 fake/local runtime gateway 获得响应，Interaction View 展示对话历史。

### Scope
- `RuntimeGateway` 抽象接口：`send(input: string, lens: SelectedLens) → InteractionResponse`
- `FakeRuntimeGateway` 实现：返回 deterministic fake 响应（模拟 agent 对话）
- `InteractionView` 增强：展示对话历史（用户消息 + agent 响应），自动滚动
- `InputBar` 增强：Enter 发送，Shift+Enter 换行，历史导航（↑↓）
- 对话历史数据模型：`InteractionMessage { role, content, timestamp, toolCalls?, memoryProposals? }`
- fake gateway 返回简单回复 + 模拟 tool call + 模拟 memory proposal

### Non-goals
- 不连接真实 core.chat()
- 不执行真实 tool
- 不写 memory/checkpoint
- 不调用真实 API
- 不读取 .env
- 不激活 default entry

### Required Docs
- SDD §5 Runtime Gateway Boundary 更新
- M3 completion report

### Required Tests
- InputBar Enter 发送消息
- InteractionView 展示用户消息
- FakeRuntimeGateway 返回 agent 响应
- InteractionView 展示 agent 响应
- 对话历史保留多条消息
- 模拟 tool call 在 InteractionView 中展示
- 模拟 memory proposal 在 InteractionView 中展示
- Shift+Enter 换行（不发送）
- 空输入不发送
- RuntimeGateway 接口契约测试
- FakeRuntimeGateway 不访问 .env/real API
- 现有 tests 回归

### Exit Criteria
- [ ] 用户输入 "hello" → InteractionView 展示 fake agent 响应
- [ ] 对话历史可滚动（↑↓ 在 input 历史中导航）
- [ ] FakeRuntimeGateway 不访问任何真实资源
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- FakeRuntimeGateway 需要模拟过多 runtime 行为 → 停止，重新设计接口
- InputBar 实现涉及 IME 复杂性 → 记录 IME debt，不阻塞 M3

### What Must Not Be Claimed
- 不得声称 "真实 agent 交互已验证"
- 不得声称 "core.chat 集成完成"
- 不得声称 "default entry ready"

---

## M4 — Context Inspector MVP

### Goal
Context Panel 随 selected lens 和 interaction 动态刷新。当前实现展示通用 selection / message count / pending / history / event foundation，不渲染 project-specific audit dashboard。不把 xfail 当 pass。

### Scope
- `InspectorSnapshot` 数据模型：通用 context/selection/interaction summary；history/event foundation 使用 fake/local projection
- `ContextInspectorState` 管理：selected lens → context data 映射
- `ContextPanel` 增强：通用 Context/Inspector；history/event viewer 只读 fake/local projection，非 audit dashboard
- Interaction 后自动 refresh context data（从 fake/local fixture 重新加载）
- xfail/caveat/accepted-with-caveats 状态展示正确
- 数据源：self-contained fake/local fixture；不复用 `PROJECT_STATUS` / `PROGRESS_LEDGER` / dogfood / debt 作为默认产品数据源

### Non-goals
- 不做实时 event tail（那是 M7）
- 不连接真实 runtime event source
- 不写 runtime state
- 不激活 default entry

### Required Docs
- SDD §6 Context Refresh 更新
- M4 completion report

### Required Tests
- ContextPanel 随 selected lens 切换刷新
- Evidence 子面板展示正确
- Gate 子面板展示正确
- Interaction 后 ContextPanel 可手动/自动 refresh
- xfail 状态展示为 xfail（不是 pass）
- caveat 文本展示
- accepted-with-caveats 状态展示
- 空 selected lens（无 agent/session/run）→ empty state
- 现有 tests 回归

### Exit Criteria
- [ ] ContextPanel 展示 generic Context/Inspector；不叫 Audit Lens，不渲染 audit dashboard
- [ ] 切换 selected lens → ContextPanel 数据变化
- [ ] Interaction 后 refresh → 数据更新
- [ ] xfail 正确标注
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- 动态刷新需要访问真实 runtime → 停止，使用 fixture
- Audit 数据量过大导致 TUI 性能问题 → 记录 performance debt

### What Must Not Be Claimed
- 不得声称 "实时审计"
- 不得声称 "真实 runtime event 展示"
- 不得声称 "default entry ready"

---

## M5 — Controlled Action / Pending Confirmation

### Goal
Interaction 中产生的 pending action（tool confirmation、memory proposal）在 UI 中展示，approve/reject 只通过 controlled operation gateway。

### Scope
- `PendingAction` 数据模型：actionType/actionId/toolName/parameters/timestamp/status
- `PendingActionPanel` 组件：展示待确认操作列表
- `StatusBar` 增强：显示 pending action 数量和类型
- approve/reject 操作只通过 `RuntimeGateway` 抽象——fake gateway 返回 simulated result
- 不绕过 ToolRuntimeMediator
- 不直接执行 tool
- 不直接写 memory/checkpoint

### Non-goals
- 不连接真实 ToolRuntimeMediator
- 不执行真实 tool
- 不写真实 memory
- 不激活 default entry

### Required Docs
- SDD §7 Pending Action / Confirmation 更新
- M5 completion report

### Required Tests
- PendingAction 渲染
- approve 操作 → RuntimeGateway.approve() 被调用
- reject 操作 → RuntimeGateway.reject() 被调用
- 多个 pending action 同时展示
- approve/reject 后 StatusBar 更新
- RuntimeGateway 不直接调用 tool
- RuntimeGateway 不直接写 memory
- FakeRuntimeGateway approve 返回 simulated result
- 现有 tests 回归

### Exit Criteria
- [ ] Pending action 在 StatusBar 中显示
- [ ] approve/reject 通过 RuntimeGateway 抽象
- [ ] 无直接 tool/memory/checkpoint 写入
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- approve/reject 实现需要绕过 ToolRuntimeMediator → HARD_STOP
- 需要真实 tool execution → 停止，使用 fake

### What Must Not Be Claimed
- 不得声称 "真实 tool execution 已验证"
- 不得声称 "ToolRuntimeMediator 集成完成"
- 不得声称 "default entry ready"

---

## M6 — Multi-instance History Foundation

### Goal
定义 evidence namespace + multi-run storage contract。Agent Lens 支持多 agent/session/run/instance 历史浏览（只读 projection）。

### Scope
- `EvidenceNamespace` 数据模型定义（不实现，仅定义契约）
- `MultiRunStorageContract` 定义（文件命名、TTL、cleanup 策略）
- Agent Lens 数据源扩展：支持从文件系统扫描构建 agent/session/run 树
- 历史浏览：按时间线展示 past runs 的 evidence/gate 摘要
- 只读 projection：不写 runtime state
- 不要求真实并发 runtime
- 不要求真实 provider

### Non-goals
- 不实现 B7 multi-instance orchestrator
- 不做真实多实例并发
- 不修改 Python runtime
- 不激活 default entry

### Required Docs
- SDD §8 Multi-instance History 更新
- `docs/design/b8-evidence-namespace-contract.md`（evidence namespace 契约定义）
- `docs/design/b8-multi-run-storage-contract.md`（storage contract 定义）
- M6 completion report

### Required Tests
- EvidenceNamespace 契约测试
- MultiRunStorageContract 契约测试
- AgentLens 从文件系统扫描构建树
- 历史 run evidence/gate 摘要展示
- 空历史 → empty state
- 不写入 runtime state 的 guard test
- 现有 tests 回归

### Exit Criteria
- [ ] Evidence namespace contract 定义完成
- [ ] Multi-run storage contract 定义完成
- [ ] AgentLens 展示历史 runs
- [ ] 只读 projection 不写 runtime state
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- 历史浏览需要真实 runtime identity → 使用 fixture
- 文件扫描涉及 .env / secrets → HARD_STOP

### What Must Not Be Claimed
- 不得声称 "B7 multi-instance 就绪"
- 不得声称 "真实多实例并发支持"
- 不得声称 "default entry ready"

---

## M7 — Runtime Event Stream / EventPanel

### Goal
定义 event source contract。Context Panel 支持 events.jsonl reader（只读，不 tail real process）。

### Scope
- `EventSourceContract` 定义：event schema、namespace、backpressure、redaction、truncation 策略
- `EventStreamReader` 实现：解析 events.jsonl，支持 malformed/missing/partial write
- Context Panel Event 子面板：展示 parsed events，支持 type/session/run/instance filter
- Redaction indicator：脱敏字段标注 `[redacted]`
- 只读：不 tail real process，不写 runtime
- 数据源：初期使用 fake/local fixture events.jsonl

### Non-goals
- 不做实时 tail（不 tail real agent_log.jsonl）
- 不创建第二 runtime event 写入路径
- 不修改 Python runtime event log 格式
- 不激活 default entry

### Required Docs
- SDD §9 Runtime Event Stream 更新
- `docs/design/b8-event-source-contract.md`（event source contract 定义）
- M7 completion report

### Required Tests
- EventStreamReader 解析合法 JSONL
- EventStreamReader 处理 malformed line（不 crash）
- EventStreamReader 处理空文件
- EventStreamReader 处理 partial write（最后一行不完整）
- Event type filter 正确
- Session/run/instance filter 正确
- Redaction indicator 展示
- 不写入 event log 的 guard test
- 现有 tests 回归

### Exit Criteria
- [ ] Event source contract 定义完成
- [ ] EventStreamReader 正确解析 fixture events.jsonl
- [ ] Context Panel Event 子面板展示 events
- [ ] Malformed/partial write 安全处理
- [ ] 所有 tests PASS, tsc clean
- [ ] Default entry NOT ACTIVATED

### Stop Conditions
- EventStreamReader 需要 tail real process → 停止，使用 fixture
- 需要创建新 event 写入路径 → HARD_STOP

### What Must Not Be Claimed
- 不得声称 "实时 event stream"
- 不得声称 "真实 runtime event 集成"
- 不得声称 "default entry ready"

---

## M8 — Default Entry Readiness

### Goal
评估 TUI 是否可以作为 First Agent 默认入口候选。用户显式选择后激活。不自动激活。

### Scope
- Interaction view 可用（M3 已验证）
- Input/paste/IME 基础检查（不要求完美，记录已知限制）
- Exit/fallback CLI 可用（q 退出，CLI 保留）
- No secret leak（redaction + safety scan）
- No runtime bypass（所有操作经过 RuntimeGateway）
- Default entry checklist 更新（反映 M0-M7 完成状态）
- 用户显式确认后才激活

### Non-goals
- 不自动激活
- 不声称 product-ready
- 不删除 CLI
- 不做全面 IME 测试

### Required Docs
- Default entry readiness report
- Known limitations 文档
- M8 completion report

### Required Tests
- q 退出 TUI
- CLI 独立可用
- No .env access from TUI
- No secret in TUI output
- All operations through RuntimeGateway (guard test)
- IME/paste 基础测试（如 Ink 支持）
- 现有 tests 回归

### Exit Criteria
- [ ] Interaction view 可正常使用
- [ ] q 退出，CLI fallback 正常
- [ ] 安全扫描通过（no secret leak）
- [ ] Runtime bypass guard tests PASS
- [ ] 用户未批准时保持 default entry NOT ACTIVATED；readiness checklist 完成不等于激活
- [ ] 所有 tests PASS, tsc clean

### Stop Conditions
- 安全扫描发现 secret leak → HARD_STOP
- Runtime bypass 被发现 → HARD_STOP
- 用户未批准 → 不激活，保持 NOT ACTIVATED

### What Must Not Be Claimed
- 不得声称 "product-ready"
- 不得声称 "所有 IME 场景已验证"
- 不得在用户未批准时激活 default entry

---

## Milestone 依赖链

```
M0 (Direction Correction)
  │
  ▼
M1 (Layout) ──────► M2 (Agent Lens) ──────► M3 (Interaction MVP)
                      │                         │
                      ▼                         ▼
                    M4 (Context Inspector) ◄────────┘
                      │
                      ▼
                    M5 (Controlled Action)
                      │
                      ▼
                    M6 (Multi-instance History)
                      │
                      ▼
                    M7 (Event Stream)
                      │
                      ▼
                    M8 (Default Entry Readiness)
```

M1-M3 是交互核心链，M4-M5 是 context/controlled 链，M6-M7 是历史/流链。

---

## 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — M0-M8 定义，按主入口成熟度而非面板数量 |
| 2026-06-02 | B8 remediation — Audit Lens → Context Panel/Inspector, Dynamic Audit → Context Inspector, M1-M8 fake/local foundation 状态对齐 |
| 2026-06-02 | B1-B8 close-out sweep — 标注规划期条目与实际实现边界；M6/M7 fake/local caveats、default entry NOT ACTIVATED、legacy panels 非主线 |
