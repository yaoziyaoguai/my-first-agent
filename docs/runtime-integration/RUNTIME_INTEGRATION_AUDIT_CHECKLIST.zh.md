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
| D07 | SubAgent L0 是否无嵌套 delegation？是否遵守 L0 allowed/prohibited 列表（禁止：L1/L2、嵌套委派、自主规划、多智能体、并行委派、workspace automation、memory handoff、shell/external process、绕过 parent adjudication）？ | P1 | A | 代码审查：检查 delegation context 标记 + 拒绝逻辑 + allowed/prohibited 全部条款 |
| D08 | Skill progressive disclosure 是否保持？ | P1 | S | 代码审查：检查 body 在 metadata 阶段不加载 |

### 1.2 Schema 正确性

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| D09 | RuntimeActionRequest 是否为 frozen？ | P1 | R | 代码审查 + unit test: R-TEST-1 #1 |
| D10 | RuntimeActionResult.status 是否只接受 5 种值？ | P1 | R | 代码审查 + unit test: R-TEST-1 #5 |
| D11 | RuntimeActionEvent 是否不可变？ | P1 | R | 代码审查 + unit test: R-TEST-1 #3 |
| D12 | evidence 字段是否不含 secret？ | P0 | R | unit test: R-TEST-1 #6 + E2E dogfood E09 |
| D13 | CAPABILITY_MODULE_MAPPING 是否覆盖所有 capability？ | P1 | E | unit test: E-TEST-1 #1 |
| D14 | Skill action payload 是否包含 selected_skill_id, selection_reason, selection_confidence, body_load_decision, allowed_tools_after_selection, available_skill_metadata，且 selection metadata 来源链接到 RuntimeActionRequest.payload.model_decision_metadata？ | P1 | S | 代码审查 + unit test: S-TEST-1 |
| D15 | SubAgent action payload 是否包含 subagent_name, delegate_once_called, subagent_request_built, parent_adjudicated, no_nested_delegation, no_shell_or_external_process？ | P1 | A | 代码审查 + unit test: A-TEST-1 |
| D16 | selected_skill_id / selection_reason / selection_confidence 和 subagent_name 是否来自 RuntimeActionRequest.payload（skill 使用 model_decision_metadata），handler 只做验证不做选择？ | P1 | S/A | 代码审查：handler 从 request.payload 提取并验证，不自行决定、后验补、二次调用 LLM 或从文本推断 |
| D17 | RuntimeActionResult 是否包含 action_id 字段？ | P1 | R | 代码审查 + unit test: R-TEST-1 #9 |
| D18 | RuntimeActionResult.evidence 是否包含 action_id, dispatcher_routed, target_handler_invoked, handler_name, target_module, module_invoked, structured invocation_proof（含 call_id/function_called/call_signature/observed_at/observation_method）, target_module_proof（含 proof_id/observation_source/observer_identity/observation_independent/linked_action_id/linked_target_module——独立观测源，handler 不得自我填充）, result_returned_to_parent_runtime, evidence_level？ | P0 | R | 代码审查 + unit test: R-TEST-3 |
| D19 | Tool evidence 是否拆分 registry_handler_invoked / target_module_invoked / dangerous_tool_function_invoked？ | P1 | T | 代码审查：三个字段语义不重叠 |

### 1.3 不变式覆盖

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| D19 | 每项 SDD 不变式是否有对应测试？ | P0 | 全部 | TDD 文档对照：检查每个 Track 的不变式是否有测试 |
| D20 | action event 是否在每次 route() 后产生？ | P0 | R | unit test: R-TEST-2 #7 |
| D21 | "模型文本提到 X" 是否不再作为 pass 条件？ | P0 | E | E2E dogfood plan 检查 |
| D22 | dispatcher_routed=false、target_handler_invoked=false、module_invoked=false、target_module_proof 缺失、proof_id 缺失、linked_action_id 不匹配、linked_target_module 不匹配或 result_returned_to_parent_runtime=false 时 capability 是否不得标 runtime_e2e？ | P0 | R/E | unit test: R-TEST-3 #7,#14-19, E-TEST-2 #2,#2a |
| D27 | target_module_proof 是否来自独立观测源（spy/return_marker/call_id/dogfood_trace），且 proof_id 非空、linked_action_id 匹配 action_id、linked_target_module 匹配 target_module，handler 不得自我填充 invocation_proof？ | P0 | R | 代码审查 + negative test：fake handler 自填 module_invoked=true 但无独立观测 → fail |
| D23 | E2E dogfood plan 中是否不存在 bash/shell/run_shell 作为 allowed tool？ | P1 | 全部 | 文档审查：grep bash/shell/run_shell in dogfood plan |
| D24 | Memory hook 是否为 turn-end hook（而非仅 tool 后触发）？ | P1 | M | 代码审查 + unit test: M-TEST-1 #2 |
| D25 | Streaming 是否处理了 unsupported provider 的 fail-closed 分支？ | P1 | P | 代码审查 + unit test: P-TEST-3 #4-7 |
| D26 | Tool Alias Policy 是否在文档中定义且 E2E plan 遵循？ | P1 | T/E | 文档审查：检查 fake. 前缀使用 + ToolRegistry 真实 tool name

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
| T07 | E08（full combined）pass 条件是否基于 R.6 Runtime E2E 11 项证据链，而非仅 RuntimeActionEvent？ | P0 | 全部 | 检查 scenario result：action log 中 ≥ 3 种 action_type，且每个 runtime_e2e event 有 target_module_proof.proof_id、observation_independent=true、linked_action_id、linked_target_module |
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
| T15 | tool alias mismatch 检测测试是否存在？ | P1 | T | T-TEST-2 #7, #9 |
| T16 | streaming unsupported provider 的 negative tests 是否存在？ | P1 | P | P-TEST-3 #4-7 |
| T17 | E08 scenario 是否验证 module invocation proof（非仅 event）？ | P0 | E | E-TEST-4 #1, #4 |

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
| S13 | E2E plan / allowed_tools 中是否无真实 bash/shell/run_shell？ | P1 | 全部 | 文档审查 + grep：违反为 P1 |
| S14 | fake tool（fake. 前缀）是否不会真实执行、不污染真实 ToolRegistry，且 fake high-risk blocked path 固定 evidence.decision=blocked？ | P1 | T | unit test: T-TEST-2 #8, #11, #13-20 |
| S16 | 真实 ToolRegistry 中是否不存在 fake. 前缀 tool？ | P1 | T | 代码审查 + grep |
| S15 | 禁止的 tool name（bash, shell, run_shell）是否在 gate 层被拒绝？ | P1 | T | unit test: T-TEST-2 #9 |

---

## 5. 文档层面（Documentation Audit）

| # | 检查项 | 优先级 | Track | 验证方式 |
|---|--------|--------|-------|----------|
| DOC01 | RFC 与 SDD 是否一致？ | P1 | — | 文档审查：交叉对照 RFC 的 Goals 和 SDD 的 Tracks |
| DOC02 | TDD 是否覆盖所有 Track？ | P1 | — | 文档审查：对照 SDD 的 8 个 Track |
| DOC03 | Implementation Loop 的每个 Phase 有明确 stop condition？ | P1 | — | 文档审查 |
| DOC04 | E2E Dogfood Plan 的 pass 条件是否基于 R.6 Runtime E2E 11 项证据链？ | P0 | — | 文档审查：不得出现 current-valid RuntimeActionEvent-only / module_invoked-only pass |
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
6. 每个 RuntimeActionResult 必须有唯一的 action_id（审计 P1-2 新增）
7. runtime_e2e 必须同时满足 SDD R.6 Runtime E2E 11 项证据链：RuntimeActionEvent emitted、RuntimeActionDispatcher routed、target handler invoked、module_invoked=true、target_module_proof exists、proof_id present、observation_independent=true、linked_action_id 匹配 action_id、linked_target_module 匹配 target_module、result returned to Parent Runtime、parent_adjudicated where applicable。
8. module_invoked=false → 不得标 runtime_e2e（审计 P1-2 新增）

### Track S
1. available_skill_metadata 中的每个 skill 必须是 active 状态且有合法 descriptor
2. body 在 metadata 列表阶段不能被加载
3. selected skill 的 allowed_tools 必须 ∩ ToolRegistry visible tools 非空
4. selected_skill_id 必须来自 RuntimeActionRequest.payload.model_decision_metadata，handler 只做验证不做选择（审计第二轮修复）
5. selection_reason / selection_confidence 必须来自 RuntimeActionRequest.payload.model_decision_metadata；handler 不得后验补、二次调用 LLM 或从自然语言推断；缺失任一字段、字段未链接到 metadata、handler-invented 或 report-invented 均不得 runtime_e2e pass
6. test harness / dogfood report 不得后验补 selection_reason / selection_confidence；E2E/Audit 必须能抓住 missing/source violation

### Track A
1. SubAgent delegation 必须经过 parent adjudication
2. 被委派的 SubAgent status 必须是 active
3. delegation 的 tool list 必须是 SubAgent descriptor allowed_tools 的子集
4. subagent_name 必须来自 model tool-call arguments（RuntimeActionRequest.payload），handler 只做验证不做选择（审计第二轮修复）

### Track M
1. Memory proposal 不得自动 confirmed
2. secret-like 内容不得进入 proposal body
3. Memory governance 不得被 Runtime Hook 绕过
4. Runtime Hook 不得读取真实 sessions/runs/memory episodes
5. Turn-end hook 在 tool-executed 和 no-tool turns 中都必须触发（审计 P1-4 新增）

### Track T
1. hidden/unknown tool 必须被拒绝
2. 高风险 tool 必须经过 confirmation
3. tool execution 结果不得包含 secret
4. registry_handler_invoked 为 true 不代表 target_module_invoked 为 true（gate 检查 ≠ tool 执行）（审计第二轮新增）
5. dangerous_tool_function_invoked 对 fake. 前缀 tool 必须为 false（审计第二轮新增）
6. fake. 前缀 tool 不得存在于真实 ToolRegistry 中（审计第二轮新增）
7. gate_disposition 是 ToolGate handler-level immediate output，合法值仅 allowed / rejected / confirmation_required；evidence.decision 是 final evidence-level classification，合法值 allowed / rejected / confirmation_required / not_found / blocked；not_found / blocked 不得作为真实工具 gate_disposition。
8. fake high-risk blocked path 必须包含 requested_tool_name、requested_capability、production_registry_found=false、dogfood_overlay_found=true、overlay_tool_name、resolved_test_tool_name、registry_handler_invoked=true、target_module_invoked=true、dangerous_tool_function_invoked=false、evidence.decision=blocked。
9. fake high-risk blocked path 不得用 confirmation_required 代替 blocked；production_registry_found=true、dogfood_overlay_found=false、dangerous_tool_function_invoked=true、fake.* persisted into production ToolRegistry、fake.* exposed to normal runtime、fake.* appears in production capability matrix as real capability 均为 fail。

### Track C
1. safe_summary 中不得出现 raw key / secret pattern
2. pending_high_risk_tool 不得在 checkpoint 中可重放
3. checkpoint boundary is turn-end / before save_checkpoint（审计 P2 tool-event residue 新增）
4. checkpoint boundary does not depend on Track T tool events；tool execution 是可选前置步骤，非必要触发条件（审计 P2 tool-event residue 新增）
5. no-tool user turn 必须能到达 checkpoint safe summary / save_checkpoint boundary（审计 P2 tool-event residue 新增）
6. tool-after-only checkpoint trigger → P2 / fail before commit（审计 P2 tool-event residue 新增）
7. no-tool checkpoint boundary missing → P2 / fail before commit（审计 P2 tool-event residue 新增）
8. checkpoint path without target_module_proof → not runtime_e2e（审计 P2 tool-event residue 新增）
9. direct checkpoint subsystem invocation → subsystem_integration / partial only（审计 P2 tool-event residue 新增）

### Track P
1. provider.supports_streaming=false 时：status="not_supported"，不得生成 fake final event（审计 P2-1 新增）
2. unsupported provider streaming 不得标 runtime_e2e（审计 P2-1 新增）

### Track E
1. capability 不得被标记为 runtime_e2e 除非满足 SDD R.6 Runtime E2E 11 项证据链；RuntimeActionEvent、RuntimeActionEvent + module_invoked=true、handler_name + target_module + module_invoked=true 都不是充分条件。
2. subsystem_integration 不得被报告为 runtime_e2e
3. mapping table 是 capability name 的单一事实来源
4. RuntimeActionEvent 存在但 module_invoked=false → 最高只能 subsystem_integration（审计 P1-2 新增）
5. module_invoked=true 但 target_module_proof 缺失、proof_id 缺失、observation_independent=false、linked_action_id 不匹配或 linked_target_module 不匹配 → 最高只能 subsystem_integration（审计第三轮新增）
6. handler 自我填充 invocation_proof 或 target_module_proof → 不构成 runtime_e2e（审计第三轮新增）
7. 模型文本提到能力 → 不算任何级别的 evidence（审计 P1-2 新增）
