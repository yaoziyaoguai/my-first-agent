# Runtime Integration / Runtime Action Harness — Audit Checklist

> 状态：审计清单（不包含实现代码）
> 关联文档：RFC、SDD、TDD、Implementation Loop、E2E Dogfood Plan、CURRENT_AUDIT_STATUS
> 语言：简体中文为主，英文术语括注

---

## 0. 审计范围

本清单覆盖 Runtime Integration / Runtime Action Harness 的设计、实现、测试、验证全流程。每个检查项标注：
- **优先级**：P0（阻塞上线）/ P1（阻塞 release）/ P2（应修复）/ P3（建议）
- **Track**：R/S/A/M/T/C/P/E — 对应 SDD 中的 Track
- **验证方式**：代码审查 / 自动化测试 / E2E dogfood / 文档审查

---

## 1. 设计层面（Design Audit）— 实施前

### 1.1 架构正确性

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| D01 | RuntimeActionDispatcher 是否只是路由层，不做业务逻辑？ | P0 | R | 代码审查：检查 dispatcher 代码中无状态变更、无 IO |
| D02 | RuntimeAction 是否不推进 Runtime state？ | P0 | R | 代码审查：检查 route() 调用前后 RuntimeState 不变 |
| D03 | RuntimeActionDispatcher 是否持有 module-level global mutable state？ | P0 | R | 代码审查：检查无 global 变量 |
| D04 | 子系统内部逻辑是否未被 RuntimeAction 改变？ | P0 | S/A/M/T/C/P | 代码审查 + 现有 subsystem 测试全部通过 |
| D05 | Memory governance（proposal→pending_review）是否未被绕过？ | P0 | M | 代码审查：检查无 silent retain / auto approve 路径 |
| D06 | ToolRegistry 是否仍是 tool 执行的唯一门禁？ | P0 | T | 代码审查：检查所有 tool call 都经过 tool.request RuntimeAction |
| D07 | SubAgent L0 是否无嵌套 delegation？ | P1 | A | 代码审查：检查 delegation context 标记 + 拒绝逻辑 |
| D08 | Skill progressive disclosure 是否保持？ | P1 | S | 代码审查：检查 body 在 metadata 阶段不加载 |

### 1.2 Schema 正确性

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| D09 | RuntimeActionRequest 是否为 frozen？ | P1 | R | 代码审查 + unit test: R-TEST-1 #1 |
| D10 | RuntimeActionResult.status 是否只接受 5 种值？ | P1 | R | 代码审查 + unit test: R-TEST-1 #5 |
| D11 | RuntimeActionEvent 是否不可变？ | P1 | R | 代码审查 + unit test: R-TEST-1 #3 |
| D12 | evidence 字段是否不含 secret？ | P0 | R | unit test: R-TEST-1 #6 + E2E dogfood E09 |
| D13 | CAPABILITY_MODULE_MAPPING 是否覆盖所有 capability？ | P1 | E | unit test: E-TEST-1 #1 |

### 1.3 不变式覆盖

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| D14 | 每项 SDD 不变式是否有对应测试？ | P0 | 全部 | TDD 文档对照：检查每个 Track 的不变式是否有测试 |
| D15 | action event 是否在每次 route() 后产生？ | P0 | R | unit test: R-TEST-2 #7 |
| D16 | "模型文本提到 X" 是否不再作为 pass 条件？ | P0 | E | E2E dogfood plan 检查：所有 pass 条件基于 RuntimeActionEvent |

---

## 2. 实现层面（Implementation Audit）— 实施中/后

### 2.1 代码质量

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| I01 | `agent/runtime_integration/` 下所有文件有中文学习型注释？ | P2 | 全部 | 代码审查 |
| I02 | 无 module-level global singleton？ | P0 | 全部 | 代码审查 + grep `^[A-Z_]+ = ` |
| I03 | 无循环依赖？ | P0 | 全部 | `python -c "import agent.runtime_integration"` 无 ImportError |
| I04 | 每个 handler 文件 ≤ 400 行？ | P2 | 全部 | `wc -l agent/runtime_integration/*.py` |
| I05 | 无 `except: pass` 或 `except Exception: pass`？ | P1 | 全部 | grep + 代码审查 |
| I06 | 所有异常有 error_safe_preview（不含敏感数据）？ | P1 | R | 代码审查 |
| I07 | Dispatcher 不访问 .env / 网络 / 外部系统？ | P0 | R | 代码审查 + negative test: R-TEST-4 #4,5 |

### 2.2 子系统隔离

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| I08 | `agent/runtime_integration/` 不修改 `agent/skill_system/`？ | P1 | S | `git diff --stat` 确认 |
| I09 | `agent/runtime_integration/` 不修改 `agent/subagent_system/`？ | P1 | A | `git diff --stat` 确认 |
| I10 | `agent/runtime_integration/` 不修改 `agent/memory_system/`？ | P1 | M | `git diff --stat` 确认 |
| I11 | `agent/runtime_integration/` 不修改 `agent/tool_registry.py`？ | P1 | T | `git diff --stat` 确认 |
| I12 | `agent/runtime_integration/` 不修改 `agent/checkpoint.py`？ | P1 | C | `git diff --stat` 确认 |
| I13 | `agent/runtime_integration/` 不修改 provider/streaming 内部行为？ | P1 | P | `git diff --stat` 确认 |

### 2.3 core.chat() 集成

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| I14 | `chat()` 的 tool calling 循环结构未被破坏？ | P0 | T | 代码审查：确认 hook 插入位置正确 |
| I15 | `chat()` 的 provider 注入路径未被 RuntimeAction 干扰？ | P1 | R | 现有 test_chat_provider_injection.py 全部通过 |
| I16 | `chat()` 的 plan→confirm→execute 主循环逻辑不变？ | P0 | 全部 | 代码审查 + 现有 chat 测试全部通过 |

---

## 3. 测试层面（Test Audit）

### 3.1 测试覆盖率

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| T01 | `agent/runtime_integration/` 覆盖率 ≥ 80%？ | P1 | 全部 | `pytest --cov=agent.runtime_integration --cov-report=term-missing` |
| T02 | 每个 Track 的必选测试全部通过？ | P0 | 全部 | `python -m pytest tests/runtime_integration/ -v` |
| T03 | characterization test 覆盖 Track E？ | P1 | E | E-TEST-1,2,3 全部通过 |
| T04 | negative test 覆盖每个 Track？ | P1 | 全部 | 每个 Track 至少 3 个 negative test |
| T05 | 全量回归 `python -m pytest tests/ -v` 通过？ | P0 | 全部 | CI-equivalent 命令 |

### 3.2 E2E Dogfood 验证

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| T06 | `actual_runtime_invoked` scenario ≥ 6？ | P0 | 全部 | `python scripts/dogfood_e2e_runtime.py --all` |
| T07 | E08（full combined）pass 条件基于 RuntimeActionEvent？ | P0 | 全部 | 检查 scenario result：action log 中 ≥ 3 种 action_type |
| T08 | 所有 pass scenario 的 invocation_mode == "actual_runtime_invoked"？ | P0 | 全部 | 检查 dogfood report |
| T09 | E09（API key integrity）无 secret 泄露？ | P0 | R | 检查 dogfood report E09 |
| T10 | capability matrix 所有 entry 有明确 evidence 来源？ | P1 | E | 检查 dogfood report capability matrix section |
| T11 | 没有 capability 被错误标记为 runtime_e2e？ | P1 | E | E-TEST-3 #1,2 |

### 3.3 测试方法学

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| T12 | "模型文本提到 X" 不再作为任何 scenario 的 pass 条件？ | P0 | 全部 | 审查 dogfood runner 中所有 scenario 的 pass 条件 |
| T13 | Direct subsystem invocation 场景已降级为 tests/ 下的 integration test？ | P2 | S/A/M/T/C/P | `git diff --stat` 确认新测试文件存在 |
| T14 | Test 文件命名遵循 `test_<module>.py` 约定？ | P3 | 全部 | `ls tests/runtime_integration/` |

---

## 4. 安全层面（Security Audit）

### 4.1 Secret 保护

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| S01 | RuntimeActionEvent.evidence 不含 secret？ | P0 | R | R-TEST-1 #6 + E09 |
| S02 | checkpoint safe_summary 不含 secret？ | P0 | C | C-TEST-2 #1,2,3 |
| S03 | memory proposal body 不含 secret-like 内容？ | P0 | M | M-TEST-3 #1,2 |
| S04 | tool execution result 在 evidence 中 secret 被 redact？ | P0 | T | T-TEST-4 #2 |
| S05 | API key 不被记录在 action log 中？ | P0 | 全部 | E09 pass |
| S06 | error_safe_preview 不含敏感数据？ | P1 | R | 代码审查：所有 error 分支 |

### 4.2 权限控制

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| S07 | hidden/unknown tool 是否被拒绝？ | P0 | T | T-TEST-2 #1,2 |
| S08 | 高风险 tool 是否必须 confirmation？ | P0 | T | T-TEST-2 #4 + T-TEST-3 #1,2,3 |
| S09 | SubAgent 是否不能超过 descriptor 声明的 tools？ | P1 | A | A-TEST-4 #1 |
| S10 | disabled skill 是否不可见？ | P1 | S | S-TEST-2 #4 |
| S11 | Memory 操作是否不绕过 governance？ | P0 | M | M-TEST-4 #1,3 |
| S12 | RuntimeAction 是否不新增 tool 注册方式？ | P1 | T | T-TEST-4 #4 |

---

## 5. 文档层面（Documentation Audit）

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| DOC01 | RFC 与 SDD 是否一致？ | P1 | — | 文档审查：交叉对照 RFC 的 Goals 和 SDD 的 Tracks |
| DOC02 | TDD 是否覆盖所有 Track？ | P1 | — | 文档审查：对照 SDD 的 8 个 Track |
| DOC03 | Implementation Loop 的每个 Phase 有明确 stop condition？ | P1 | — | 文档审查 |
| DOC04 | E2E Dogfood Plan 的 pass 条件基于 RuntimeActionEvent？ | P0 | — | 文档审查 |
| DOC05 | Audit Checklist 覆盖 P0/P1/P2/P3？ | P2 | — | 文档审查（本文件自检） |
| DOC06 | CURRENT_AUDIT_STATUS 已更新？ | P2 | — | 文档审查 |
| DOC07 | README.md 有 runtime-integration 文档入口？ | P3 | — | 文档审查 |
| DOC08 | 所有文档使用简体中文为主、英文术语括注？ | P3 | — | 文档审查 |
| DOC09 | commitment message 格式正确（`docs(runtime): ...`）？ | P3 | — | git log |

---

## 6. 审计结论模板

审计完成后填写：

```
## Runtime Integration 审计结论

日期: YYYY-MM-DD
审计人: [name]
代码版本: [commit hash]

### 通过项

- [ ] D01-D16（设计层面）: __ / 16
- [ ] I01-I16（实现层面）: __ / 16
- [ ] T01-T14（测试层面）: __ / 14
- [ ] S01-S12（安全层面）: __ / 12
- [ ] DOC01-DOC09（文档层面）: __ / 9

### 未通过项

| # | 检查项 | 原因 | 修复计划 |
|---|--------|------|----------|
|   |        |      |          |

### 阻塞项（P0 未通过）

| # | 检查项 | 影响 |
|---|--------|------|
|   |        |      |

### 结论

[ ] 通过 — 所有 P0/P1 项通过，可进入下一阶段
[ ] 有条件通过 — P0 全部通过，P1 部分未通过（附理由）
[ ] 不通过 — P0 有未通过项，阻塞
```

---

## 7. 审计矩阵（按 Track 汇总）

| Track | 设计检查项 | 实现检查项 | 测试检查项 | 安全检查项 | 总计 |
|-------|-----------|-----------|-----------|-----------|------|
| R — Runtime Harness | D01-D03, D09-D12, D15 | I01-I07, I14-I16 | T01-T05, T09 | S01, S05, S06 | 21 |
| S — Skill | D04, D08 | I08 | T01-T05 | S10 | 7 |
| A — SubAgent | D04, D07 | I09 | T01-T05 | S09 | 7 |
| M — Memory | D04, D05 | I10 | T01-T05 | S03, S11 | 8 |
| T — ToolRegistry | D04, D06 | I11 | T01-T05 | S02, S07, S08, S12 | 10 |
| C — Checkpoint | D04 | I12 | T01-T05 | S02 | 6 |
| P — Streaming | D04 | I13 | T01-T05 | — | 5 |
| E — Evidence Matrix | D13, D16 | — | T03, T10-T13 | — | 6 |

---

## 附录 A：不变式快速对照表

以下是 SDD 中每个 Track 定义的不变式，供审计时逐条对照：

### Track R
1. 每个 RuntimeActionRequest 必须产生恰好一个 RuntimeActionResult
2. RuntimeActionResult.status ∈ {"success", "rejected", "confirmation_required", "not_supported", "failed"}
3. evidence 字段不得包含 secret / raw key / raw prompt 内容
4. RuntimeActionDispatcher 不得推进 Runtime state
5. RuntimeActionDispatcher 不得持有 module-level global mutable state

### Track S
1. available_skills 中的每个 skill 必须是 active 状态且有合法 descriptor
2. body 在 metadata 列表阶段不能被加载
3. selected skill 的 allowed_tools 必须 ∩ ToolRegistry visible tools 非空

### Track A
1. SubAgent delegation 必须经过 parent adjudication
2. 被委派的 SubAgent status 必须是 active
3. delegation 的 tool list 必须是 SubAgent descriptor allowed_tools 的子集

### Track M
1. Memory proposal 不得自动 confirmed
2. secret-like 内容不得进入 proposal body
3. Memory governance 不得被 Runtime Hook 绕过
4. Runtime Hook 不得读取真实 sessions/runs/memory episodes

### Track T
1. hidden/unknown tool 必须被拒绝
2. 高风险 tool 必须经过 confirmation
3. tool execution 结果不得包含 secret

### Track C
1. safe_summary 中不得出现 raw key / secret pattern
2. pending_high_risk_tool 不得在 checkpoint 中可重放

### Track P
（无显式不变式，evidence 收集不影响行为）

### Track E
1. capability 不得被标记为 runtime_e2e 除非存在对应的 RuntimeActionEvent
2. subsystem_integration 不得被报告为 runtime_e2e
3. mapping table 是 capability name 的单一事实来源
