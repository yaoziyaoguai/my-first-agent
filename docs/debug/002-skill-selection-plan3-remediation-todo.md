# 002 Skill Selection Plan 3 Debug / Remediation Todo

**创建日期**: 2026-05-31
**审计来源**: 002 Skill Selection Plan 3 独立架构审计报告 (Sections A-J)
**当前状态**: NOT CREDIBLE — Plan 3 核心差异化能力未接入 runtime

---

## 1. 当前审计结论

### 1.1 状态

- **002 当前**: NOT CREDIBLE
- **002 正确标记**: partial-credible / code-path credible with real-model evidence (Plan 2 model-owned tool_use + Plan 3 lifecycle)
- **核心缺口**: Plan 3 的 turn-start structured selection phase 未真正接入 runtime 生产路径
- **真实实现**: Plan 2 模型自主 tool_use (SKILL_SELECT tool) + Plan 3 lifecycle 管理 + turn-end keyword fallback

### 1.2 问题本质

Phase 2 (SkillCandidateRetriever) 和 Phase 3 (build_skill_selection_section) 的模块代码存在、质量良好、测试通过，但从未被 `agent/core.py` 的 `chat()` 或 `refresh_runtime_system_prompt()` 调用。

具体缺失:
- `SkillCandidateRetriever.retrieve()` — 仅在 retriever.py 模块定义和测试文件中被调用，生产路径 0 次调用
- `build_skill_selection_section()` — 仅在 prompt_section.py 模块定义和测试文件中被调用，生产路径 0 次调用
- `skill.selection.entered` evidence — 从未在 runtime 路径中产生 (dogfood D01 证实)
- `skill.candidates.built` evidence — 从未在 runtime 路径中产生 (dogfood D02 证实)

### 1.3 Dogfood 状态

9 PASS / 3 CONCERN / 0 FAIL:
- D01 CONCERN: No `selection.entered` evidence → 证实 retriever 未接入
- D02 CONCERN: No `candidates.built` evidence → 证实 selection section 未注入
- D06 CONCERN: 模型对 "1+1等于几？" 触发 `skill.select` → turn-end hook 过度触发

---

## 2. P0 Blocking Issues

### P0-1: SkillCandidateRetriever.retrieve() 未接入 runtime

- **证据**: `grep -rn "SkillCandidateRetriever\|\.retrieve\(" agent/ --include="*.py"` 在 `agent/` 非 tests 目录中返回 0 次实际调用
- **影响**: candidate retrieval 不存在于真实 `core.chat` runtime path；模型选择 skill 时只有 Level 1 基本信息 (name/description/tags)，没有 routing 信息
- **修复目标**: 在 `refresh_runtime_system_prompt()` 中调用 `SkillCandidateRetriever.retrieve(user_input, skill_registry)`
- **完成标准**: 真实 runtime 路径产生 `skill.candidates.built` evidence；`grep` 确认生产路径有调用

### P0-2: build_skill_selection_section() 未接入 runtime prompt path

- **证据**: `build_skill_selection_section()` 只在 `prompt_section.py:45` 定义、测试文件中调用，`build_system_prompt()` 无 `selection_section` 参数
- **影响**: 模型在 system prompt 中看不到候选 skill routing 信息 (when_to_use/triggers/match_reason)
- **修复目标**: `build_system_prompt()` 新增 `selection_section` 参数；`refresh_runtime_system_prompt()` 调用 `build_skill_selection_section(candidates)` 并传入
- **完成标准**: 真实 runtime prompt 中包含 candidate skill selection section

### P0-3: skill.selection.entered / skill.candidates.built evidence 不产生

- **证据**: dogfood D01/D02 CONCERN — selection.entered 和 candidates.built 在 action_log 中不存在
- **影响**: Plan 3 evidence chain 不完整，无法证明 selection phase 在运行
- **修复目标**: turn-start selection path 通过 dispatcher 记录 evidence
- **完成标准**: dogfood D01/D02 从 CONCERN 变 PASS；action_log 中存在对应 event

---

## 3. P1 Issues

### P1-1: turn-end hook 仍是事实主 selection path

- **修复目标**: turn-start selection (通过 prompt injection) 成为 primary skill routing path；turn-end hook 仅处理 keyword fallback（当模型未自主选择且 turn-start selection 未产生结果时）
- **判断标准**: turn-start 路径有 evidence (selection.entered → candidates.built → section.injected) → model 在 candidate context 下选择 → lifecycle activated
- **如果 P0 修复后 turn-end hook 的 keyword fallback 仍被触发**: 必须判定是模型行为 (MODEL_BEHAVIOR_CONCERN) 还是代码设计问题

### P1-2: _active_skill dict 标记 deprecated 但仍多处直接写入

- **修复目标**: 本轮不清理（涉及 B7 namespace 隔离，超出 scope）；在 remediation todo 中登记为 B7 前置清理任务
- **处置**: 记录 caveat，不伪装关闭

### P1-3: SDD 声称 response 前 selection，但代码实际不是

- **修复目标**: P0 修复后代码和 SDD 一致 — selection section 在 model response 前注入 prompt
- **判断标准**: `refresh_runtime_system_prompt()` 在 `_call_model()` 之前调用 → selection section 在 model response 前存在于 system prompt

### P1-4: deactivate 无自动触发逻辑

- **修复目标**: 本轮明确: task complete / no_skill 不强制 deactivate（模型可能后续 turn 仍需同一 skill）；只在 explicit_clear / switch 时 deactivate
- **处置**: 登记为已知 caveat (P2-4)，不伪装关闭。B7 阶段处理完整 lifecycle management

### P1-5: PROGRESS_LEDGER.md overclaim

- **证据**: "Plan 3 pipeline fully implemented and verified" — 但 retriever + selection section 未接入 runtime
- **修复目标**: 改为准确描述 "Plan 3 Phase 4-7 complete: ActiveSkillLifecycle + allowed_tools integration + B7 extension points. Phase 2-3 modules exist but not yet integrated into production runtime path."
- **等待**: P0 修复后再更新，确保 wording 与证据一致

---

## 4. P2/P3 Issues

### P2-1: 中文关键词匹配弱
- **处置**: 已知限制，已在 002 hardening 中确认。本轮不修。登记 caveat。

### P2-2: chat() 内部构建 SkillRegistry，外部无法注入多 skill E2E
- **处置**: 架构限制，需 chat() 接口变更。本轮不修。登记为 B7 前置任务。

### P2-3: build_skill_selection_section 格式缺少 when_to_use/when_not_to_use
- **处置**: 候选信息中 score/reason/matched_terms 已提供路由信号；when_to_use 字段在 manifest 中存在但未传入 retriever 的 candidate。可选增强 (P3-3)，本轮不阻塞 credible。
- **行动**: 在 `build_skill_selection_section()` 中添加 `when_to_use` 字段(如果 manifest 有此数据)。检查 `SkillCandidate` dataclass 是否需要扩展。

### P3-1: dogfood 结果文件未随代码变更自动更新
- **处置**: 每次修复后同步更新 dogfood 结果文件。

### P3-2: tests/unit/test_skill_retriever.py 有未提交修改
- **处置**: 读取 diff，判断是否为 import reorder 或实质性变更；如仅为 formatting，单独 commit 或归类。

---

## 5. 修复顺序

```
Loop 1 (P0): Runtime integration
  ├── TDD RED: 写 failing tests 验证 retriever + selection_section 未接入 runtime
  ├── Implementation:
  │   ├── prompt_builder.py: add selection_section parameter to build_system_prompt()
  │   ├── core.py: refresh_runtime_system_prompt() accept user_input, call retriever + build_skill_selection_section()
  │   └── core.py: dispatch selection.entered + candidates.built evidence via dispatcher
  ├── TDD GREEN: tests pass
  └── Gate: focused tests + ruff + git diff --check

Loop 2 (P0 evidence): Dogfood re-run
  ├── Update/rerun dogfood script
  ├── Verify D01/D02 change from CONCERN → PASS
  └── Document any remaining CONCERN

Loop 3 (P1): Fallback downgrade verification
  ├── Verify turn-end hook only triggers when turn-start didn't produce result
  ├── Verify _skill_selected_by_model flag correctly prevents keyword override
  └── Update loop.py comments to reflect safety-fallback-only status

Loop 4 (P1+P2): Docs overclaim correction
  ├── PROJECT_STATUS.md: accurate wording
  ├── PROGRESS_LEDGER.md: remove "fully implemented and verified"
  └── Update remediation todo status

Loop 5 (P3): test_skill_retriever.py uncommitted fix
```

---

## 6. 完成定义

002 从 NOT CREDIBLE 升级到 credible-with-caveats 的条件:

### 必须满足 (P0):
- [x] ~~retriever 在 core.chat runtime path 被调用~~ → P0-1
- [x] ~~selection section 在模型响应前注入 prompt~~ → P0-2
- [x] ~~skill.selection.entered evidence 存在~~ → P0-3
- [x] ~~skill.candidates.built evidence 存在~~ → P0-3
- [x] ~~model 在 candidate skill context 下选择 select_skill / no_skill~~ → 已有 SKILL_SELECT 工具
- [x] ~~active_skill 由 lifecycle 管理~~ → Phase 4 已完成 ✅
- [x] ~~allowed_tools 由 ToolRuntimeMediator enforcement~~ → Phase 5 已完成 ✅
- [x] ~~keyword / turn-end fallback 不再是事实主路径~~ → P1-1

### 可以保留 caveat (P1/P2):
- [ ] turn-end keyword fallback 作为 safety net 仍存在 (安全性正向)
- [ ] 中文关键词匹配弱 (已知限制)
- [ ] chat() 无法注入多 skill registry (架构限制 → B7)
- [ ] deactivate 无自动触发 (B7 lifecycle management)
- [ ] _active_skill dict deprecated 待清理 (B7)

### 必须修正:
- [x] ~~文档不 overclaim~~ → P1-5
- [x] ~~dogfood CONCERN 关闭或有明确非阻塞解释~~ → P0-3

### 不会声称:
- 002 fully credible (仍有 caveats)
- Plan 3 pipeline fully implemented (直到 B7/B8 完成)
- product-ready

---

## 7. 实现计划

### 7.1 受影响文件

| 文件 | 变更类型 | 变更量估计 |
|------|---------|-----------|
| `agent/prompt_builder.py` | MODIFY | +3 行 (selection_section 参数) |
| `agent/core.py` | MODIFY | +20 行 (retriever 调用 + selection section + evidence dispatch) |
| `tests/unit/test_prompt_builder.py` | MODIFY/ADD | +15 行 (selection_section 注入验证) |
| `tests/runtime_integration/test_skill_turn_start_selection.py` | MODIFY | +30 行 (runtime path 验证) |
| `scripts/real_evidence_002_plan3_dogfood.py` | MODIFY | 更新以验证新 evidence |
| `docs/dogfood/real-evidence-002-plan3-results.json` | UPDATE | 重新运行后更新 |

### 7.2 架构边界

- **不创建第二 runtime**: retriever 调用在现有 `refresh_runtime_system_prompt()` 中，属于 main runtime path
- **不绕过 ToolRuntimeMediator**: SKILL_SELECT tool_use 仍走标准 pipeline
- **不破坏 ReAct loop**: selection section 只是 prompt 增强，不影响 loop 结构
- **keyword fallback 保留但不作为 main path**: turn-end hook 仅在模型未自主选择时作为 safety net

### 7.3 关键设计决策

1. **注入点选择**: `refresh_runtime_system_prompt()` 而非 `chat()` 直接调用。
   理由: 这是 system prompt 构建的集中点，已有 `skill_registry` 参数；新增 `user_input` 参数最小化接口变更。

2. **evidence dispatch**: 复用现有 dispatcher 管道（`refresh_runtime_system_prompt` 已有 `dispatcher` 参数）。
   `skill.selection.entered` 和 `skill.candidates.built` 作为新 RuntimeActionType dispatch。

3. **selection_section 位置**: 在 system prompt 中放在 Level 1 skill 列表之后、active_skill body 之前。
   理由: 模型先看到可用 skill 概览 → 再看候选匹配 → 再看已激活 skill body。
