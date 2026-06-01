# B8 Interaction-first Workbench — TDD Plan

**创建日期**: 2026-06-02
**状态**: DRAFT
**依赖文档**:
- `docs/proposals/b8-interaction-first-workbench-proposal.md`
- `docs/milestones/b8-interaction-first-workbench-milestones.md`
- `docs/design/b8-interaction-first-workbench-sdd.md`

---

## 1. 测试策略总览

### 1.1 测试金字塔

```
         ┌──────┐
         │ E2E  │  M8 smoke: npm start → 三区域渲染 → q 退出
         ├──────┤
         │ 集成  │  M3: InputBar → FakeRuntimeGateway → InteractionView
         │      │  M4: selectedLens → AuditLens 刷新
         │      │  M7: EventStreamReader → AuditLens Event 子面板
         ├──────┤
         │ 单元  │  所有 data 层纯函数、组件渲染、状态管理
         └──────┘
```

### 1.2 测试环境

- 框架: Vitest
- TUI 组件: Ink 的 `render()` 测试（非浏览器 DOM）
- Data 层: 纯函数测试，不依赖 React/Ink
- Gateway: 契约测试，FakeRuntimeGateway 不访问 .env/real API

### 1.3 回归基线

- 现有 287/287 TUI tests 保持 PASS
- 每个 milestone 完成后全量回归
- 不允许为让新测试通过而改旧测试的断言语义

---

## 2. M1 Tests — Interaction-first Layout

### 2.1 布局结构测试 (6)

| ID | 测试 | 类别 |
|----|------|------|
| M1-L1 | WorkbenchLayout 渲染三区域: AgentLensPanel / InteractionView / AuditLensPanel | 单元 |
| M1-L2 | 三区域宽度比例: AgentLens 25% / InteractionView 50% / AuditLens 25% | 单元 |
| M1-L3 | InputBar 在底部渲染 | 单元 |
| M1-L4 | StatusBar 在底部渲染 | 单元 |
| M1-L5 | 默认焦点在 InputBar | 单元 |
| M1-L6 | InputBar 接受文本输入并显示 | 单元 |

### 2.2 焦点管理测试 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M1-F1 | Tab 从 InputBar → AgentLensPanel | 单元 |
| M1-F2 | Tab 从 AgentLensPanel → AuditLensPanel | 单元 |
| M1-F3 | Tab 从 AuditLensPanel → InputBar（循环） | 单元 |
| M1-F4 | Shift+Tab 反向切换焦点 | 单元 |

### 2.3 现有资产保留测试 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M1-A1 | Auxiliary panels 可通过 keybinding 访问（不占用默认布局） | 集成 |
| M1-A2 | 287 existing tests PASS（regression） | 回归 |

### 2.4 M1 禁止项测试 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M1-N1 | Default entry NOT ACTIVATED | 守护 |
| M1-N2 | 不读取 .env | 守护 |

**M1 合计: 14 tests (12 new + 2 guard)**

---

## 3. M2 Tests — Agent Lens / Selected Context

### 3.1 Agent Lens 树渲染 (5)

| ID | 测试 | 类别 |
|----|------|------|
| M2-T1 | AgentLens 渲染 ≥3 agent nodes | 单元 |
| M2-T2 | 每个 agent 有 ≥1 session，每个 session 有 ≥1 run | 单元 |
| M2-T3 | 状态标记正确渲染（active/paused/completed/failed/historical/superseded） | 单元 |
| M2-T4 | 树节点展开/折叠 | 单元 |
| M2-T5 | 空树状态：无 agent/session/run 时展示 empty state | 单元 |

### 3.2 Lens 导航与选择 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M2-N1 | ↑↓ 在树节点间移动高亮 | 单元 |
| M2-N2 | Enter 选中节点 → selectedLens 更新 | 单元 |
| M2-N3 | 选中 agent 节点 → selectedLens.agentId 设置，sessionId/runId 清空 | 单元 |
| M2-N4 | 选中 run 节点 → selectedLens 完整设置 | 单元 |

### 3.3 Lens 切换副作用 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M2-S1 | selectedLens 变化 → InteractionView 清空对话历史 | 集成 |
| M2-S2 | selectedLens 变化 → InteractionView 显示新 context（"Agent: X / Session: Y / Run: Z"） | 集成 |
| M2-S3 | selectedLens 变化 → AuditLens 数据重载 | 集成 |
| M2-S4 | 同一 lens 重复选中不触发重载（幂等） | 单元 |

### 3.5 M2 禁止项测试 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M2-N1 | 不连接真实 runtime 获取 agent 列表 | 守护 |
| M2-N2 | Default entry NOT ACTIVATED | 守护 |

**M2 合计: 15 tests**

---

## 4. M3 Tests — Interaction MVP

### 4.1 InputBar 交互 (5)

| ID | 测试 | 类别 |
|----|------|------|
| M3-I1 | Enter 发送消息 → RuntimeGateway.send() 被调用 | 单元 |
| M3-I2 | Shift+Enter 换行，不发送 | 单元 |
| M3-I3 | 空输入不发送 | 单元 |
| M3-I4 | ↑↓ 在输入历史中导航 | 单元 |
| M3-I5 | 发送后 InputBar 清空 | 单元 |

### 4.2 InteractionView 展示 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M3-V1 | InteractionView 展示用户消息 | 单元 |
| M3-V2 | InteractionView 展示 agent 响应 | 单元 |
| M3-V3 | 对话历史保留多条消息（发送 3 条后显示 6 条：3 user + 3 agent） | 集成 |
| M3-V4 | 新消息自动滚动到底部 | 单元 |

### 4.3 FakeRuntimeGateway (5)

| ID | 测试 | 类别 |
|----|------|------|
| M3-G1 | FakeRuntimeGateway.send() 返回 InteractionResponse | 单元 |
| M3-G2 | 响应包含 agent message | 单元 |
| M3-G3 | 响应包含模拟 tool call | 单元 |
| M3-G4 | 响应包含模拟 memory proposal | 单元 |
| M3-G5 | FakeRuntimeGateway 不访问 .env / 真实文件系统 / 网络 | 守护 |

### 4.4 Tool Call / Memory Proposal 展示 (3)

| ID | 测试 | 类别 |
|----|------|------|
| M3-T1 | Tool call 在 InteractionView 中展示（toolName + parameters + result） | 单元 |
| M3-T2 | Memory proposal 在 InteractionView 中展示（type + key + status） | 单元 |
| M3-T3 | Tool call gate status 颜色标记（allowed=green, blocked=red, requires_confirmation=yellow） | 单元 |

### 4.5 RuntimeGateway 接口契约 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M3-C1 | RuntimeGateway 接口定义 send/approve/reject 方法签名 | 契约 |
| M3-C2 | 不绕过 RuntimeGateway 直接操作（InputBar 不调用 tool/memory） | 守护 |

### 4.6 M3 禁止项 (1)

| ID | 测试 | 类别 |
|----|------|------|
| M3-N1 | Default entry NOT ACTIVATED | 守护 |

**M3 合计: 20 tests**

---

## 5. M4 Tests — Dynamic Audit Lens MVP

### 5.1 Audit Lens 刷新 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M4-R1 | AuditLens 随 selectedLens 切换刷新 | 集成 |
| M4-R2 | Interaction 后 AuditLens 可手动 refresh | 集成 |
| M4-R3 | 空 selectedLens → empty state | 单元 |
| M4-R4 | 同一 selectedLens 不重复加载（去重） | 单元 |

### 5.2 子面板 (5)

| ID | 测试 | 类别 |
|----|------|------|
| M4-P1 | Evidence 子面板展示 ≥1 条 evidence | 单元 |
| M4-P2 | Gate 子面板展示 gate 统计数据 | 单元 |
| M4-P3 | Audit 子面板展示命令执行记录 | 单元 |
| M4-P4 | Memory 子面板展示 memory summary | 单元 |
| M4-P5 | Tab 在子面板间切换 | 单元 |

### 5.3 xfail/caveat 展示 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M4-X1 | xfail 状态展示为 xfail（不是 pass） | 单元 |
| M4-X2 | caveat 文本完整展示 | 单元 |
| M4-X3 | accepted-with-caveats 状态标注正确 | 单元 |
| M4-X4 | xfail 不计入 pass 统计 | 单元 |

### 5.4 数据筛选 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M4-D1 | Evidence 数据按 selectedLens sessionId 筛选 | 单元 |
| M4-D2 | global evidence（不属于特定 session）始终展示 | 单元 |

**M4 合计: 15 tests**

---

## 6. M5 Tests — Controlled Action / Pending Confirmation

### 6.1 Pending Action 展示 (4)

| ID | 测试 | 类别 |
|----|------|------|
| M5-P1 | PendingAction 在 StatusBar 中显示数量和类型 | 单元 |
| M5-P2 | PendingActionPanel 展示待确认操作列表 | 单元 |
| M5-P3 | 多个 pending action 同时展示 | 单元 |
| M5-P4 | 空 pending action → StatusBar 不显示 | 单元 |

### 6.2 Approve/Reject (5)

| ID | 测试 | 类别 |
|----|------|------|
| M5-A1 | approve 操作 → RuntimeGateway.approve() 被调用 | 单元 |
| M5-A2 | reject 操作 → RuntimeGateway.reject() 被调用 | 单元 |
| M5-A3 | approve 后 StatusBar 更新（pending count 减少） | 集成 |
| M5-A4 | reject 后 StatusBar 更新 | 集成 |
| M5-A5 | FakeRuntimeGateway.approve() 返回 simulated result | 单元 |

### 6.3 安全守护 (3)

| ID | 测试 | 类别 |
|----|------|------|
| M5-S1 | RuntimeGateway 不直接调用 tool | 守护 |
| M5-S2 | RuntimeGateway 不直接写 memory | 守护 |
| M5-S3 | 不绕过 ToolRuntimeMediator | 守护 |

**M5 合计: 12 tests**

---

## 7. M6 Tests — Multi-instance History Foundation

### 7.1 Evidence Namespace Contract (3)

| ID | 测试 | 类别 |
|----|------|------|
| M6-E1 | EvidenceNamespace 数据结构定义合法 | 契约 |
| M6-E2 | namespace 支持 agent/session/run/instance 层级 | 契约 |
| M6-E3 | 冲突检测规则定义 | 契约 |

### 7.2 Multi-Run Storage Contract (3)

| ID | 测试 | 类别 |
|----|------|------|
| M6-S1 | MultiRunStorageContract 定义文件命名规则 | 契约 |
| M6-S2 | TTL 策略定义 | 契约 |
| M6-S3 | cleanup 策略定义 | 契约 |

### 7.3 文件扫描 (3)

| ID | 测试 | 类别 |
|----|------|------|
| M6-F1 | AgentLens 从文件系统扫描构建 agent/session/run 树 | 单元 |
| M6-F2 | 扫描空目录 → empty state | 单元 |
| M6-F3 | 历史 run 的 evidence/gate 摘要正确展示 | 单元 |

### 7.4 只读守护 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M6-G1 | 文件扫描不写入 runtime state | 守护 |
| M6-G2 | 不要求真实 concurrency runtime | 守护 |

**M6 合计: 11 tests**

---

## 8. M7 Tests — Runtime Event Stream / Audit Lens

### 8.1 EventStreamReader (5)

| ID | 测试 | 类别 |
|----|------|------|
| M7-R1 | 解析合法 JSONL（每行一个 JSON object） | 单元 |
| M7-R2 | 处理 malformed line（不 crash，记录 warning） | 单元 |
| M7-R3 | 处理空文件（返回空数组） | 单元 |
| M7-R4 | 处理 partial write（最后一行不完整，跳过或记录） | 单元 |
| M7-R5 | 不写入 event log（只读） | 守护 |

### 8.2 Filter (3)

| ID | 测试 | 类别 |
|----|------|------|
| M7-F1 | Event type filter 正确 | 单元 |
| M7-F2 | Session/run/instance filter 正确 | 单元 |
| M7-F3 | 多 filter 组合（type + sessionId） | 单元 |

### 8.3 Redaction (2)

| ID | 测试 | 类别 |
|----|------|------|
| M7-D1 | Redaction indicator `[redacted]` 展示 | 单元 |
| M7-D2 | 非敏感字段不标记 redacted | 单元 |

### 8.4 Event Source Contract (2)

| ID | 测试 | 类别 |
|----|------|------|
| M7-C1 | EventSourceContract 定义 event schema | 契约 |
| M7-C2 | Backpressure/truncation 策略定义 | 契约 |

**M7 合计: 12 tests**

---

## 9. M8 Tests — Default Entry Readiness

### 9.1 退出与 fallback (2)

| ID | 测试 | 类别 |
|----|------|------|
| M8-Q1 | q 键退出 TUI | E2E |
| M8-Q2 | CLI 独立可用（不依赖 TUI） | 集成 |

### 9.2 安全扫描 (3)

| ID | 测试 | 类别 |
|----|------|------|
| M8-S1 | No .env access from TUI | 守护 |
| M8-S2 | No secret in TUI output（redaction 生效） | 守护 |
| M8-S3 | 所有操作经过 RuntimeGateway（无 bypass） | 守护 |

### 9.3 IME/Paste 基础 (2)

| ID | 测试 | 类别 |
|----|------|------|
| M8-I1 | Paste 文本到 InputBar 不崩溃 | 集成 |
| M8-I2 | IME 基础输入（如 Ink 支持） | 集成 |

### 9.4 Default Entry (1)

| ID | 测试 | 类别 |
|----|------|------|
| M8-D1 | 用户未批准时 default entry NOT ACTIVATED | 守护 |

**M8 合计: 8 tests**

---

## 10. 跨 Milestone 回归测试

| ID | 测试 | 类别 |
|----|------|------|
| REG-1 | 所有 tests PASS（每个 milestone 完成后） | 回归 |
| REG-2 | tsc --noEmit 零错误 | 回归 |
| REG-3 | npm start 成功渲染 | 回归 |
| REG-4 | git diff --check 无 whitespace 错误 | 回归 |

---

## 11. 测试数量汇总

| Milestone | New Tests | Guard Tests | 合计 |
|-----------|-----------|-------------|------|
| M1 Layout | 12 | 2 | 14 |
| M2 Agent Lens | 13 | 2 | 15 |
| M3 Interaction MVP | 18 | 2 | 20 |
| M4 Dynamic Audit | 15 | 0 | 15 |
| M5 Pending Action | 9 | 3 | 12 |
| M6 Multi-instance | 9 | 2 | 11 |
| M7 Event Stream | 10 | 2 | 12 |
| M8 Default Entry | 4 | 4 | 8 |
| **Total** | **90** | **17** | **107** |

加上现有 287 tests，全部通过时约 394 tests。

---

## 12. RED → GREEN 执行顺序

每个 milestone 内部:

1. 写契约/接口类型定义
2. 写守护测试（RED — 必须 fail 才能证明守护有效）
3. 写功能单元测试（RED）
4. 实现 data 层（GREEN）
5. 写组件测试（RED）
6. 实现组件（GREEN）
7. 写集成测试（RED）
8. 实现集成（GREEN）
9. 全量回归 + tsc

Milestone 间: M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8（严格依赖链）

---

## 13. 版本历史

| 日期 | 变更 |
|------|------|
| 2026-06-02 | 初始版本 — 覆盖 M0-M8 测试策略，107 new tests |
