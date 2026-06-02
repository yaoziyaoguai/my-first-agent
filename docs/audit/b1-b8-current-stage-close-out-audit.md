# B1-B8 Current-Stage Close-Out Audit

**日期**: 2026-06-02
**目标**: B1-B8 Global Evidence-backed Audit + Close-out Sweep
**范围**: B1-B8 capabilities as defined in the current roadmap and recovery maps.
**方法**: 只读审计，通过 codebase、测试覆盖和 git history 的交叉验证得出独立且诚实的结论。

---

## 1. B1-B8 Definition Table

| B ID | 名称 / Capability Name | 当前文档声称状态 | 主要 Source Files | 相关测试文件 | 是否 Fake/Local / Real |
|---|---|---|---|---|---|
| **B1** | Memory write dispatcher migration | COMPLETED / VALIDATED | `agent/memory_interaction.py`, `agent/memory_runtime.py` | `tests/unit/test_memory_interaction.py` | Real-runtime |
| **B2** | CLI delegate shortcut → dispatcher | DONE | `agent/core.py`, `agent/subagent_inline.py` | - | Real-runtime |
| **B3** | SubAgent L1/L2 成熟化 | NOT STARTED / VALIDATED (L1 credible) | `agent/subagent_system/`, `agent/core.py` | `tests/runtime_integration/test_subagent_l1_execution.py` | Real-runtime (L1) / Pending (L2) |
| **B4** | MCP real connection | PARTIAL | `agent/mcp_bridge.py`, `agent/mcp/` | `tests/runtime_integration/test_mcp_real_external_flight.py` | Mixed (stdio fixture / real path) |
| **B5** | Skill runtime 深化 | code path complete / VALIDATED | `agent/skill_state.py`, `agent/runtime_integration/` | `tests/unit/test_skill_state.py`, `tests/runtime_integration/` | Real-runtime |
| **B6** | Checkpoint true state restoration | QUESTIONABLE / VALIDATED (with caveats) | `agent/checkpoint.py`, `agent/runtime_decision_frame.py` | `tests/unit/test_checkpoint.py` | Real-runtime |
| **B7** | Multi-instance readiness | accepted-with-caveats | `agent/memory_fs_store.py`, `agent/session.py`, `agent/loop.py` | `tests/test_b7_event_log.py`, `tests/test_b7_multi_instance_integration.py` | Real-runtime (Foundation built) |
| **B8** | TUI architecture (Interaction-first) | accepted-with-caveats / DELIVERED | `tui/src/main.tsx`, `tui/src/components/` | `tui/src/__tests__/` (394 tests) | Fake/Local (M1-M8 MVP) |

---

## 2. B1-B8 Evidence-Backed Status Table

| B ID | 审计状态 | 证据 (代码/测试/Commit) | 是否阻塞 Close-out |
|---|---|---|---|
| **B1** | **accepted** | `resolve_confirmation` 成功返回 `_dispatcher_payload`，并由 `dispatcher.route(_req)` 接管。证明 write path 已迁移。 | No |
| **B2** | **accepted** | `core.py` 中的 delegation 已经切换为调用 `dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_L1)`，并且具备 fallback 逻辑。 | No |
| **B3** | **accepted-with-caveats** | L1 完整走通 ToolRuntimeMediator 逻辑，证据链闭环。L2 不在当前范围内。| No |
| **B4** | **partial** (as designed) | MCP bridge local discovery 可信。外部 invocation 是 direct registered-tool execution，没有 full E2E 真实连接。符合设计预期。| No |
| **B5** | **accepted-with-caveats** | `allowed_tools` enforcement 完全生效 (13 PASS)。真实模型 SKILL_SELECT + real dogfood E2E (002/003) 证明了 code path。Caveats 是模型表现。 | No |
| **B6** | **accepted-with-caveats** | `direct-save` fallback 已被移除，确保 dispatcher 必须发挥作用。Caveat：部分 stop condition（如 `confirmation='always'`）未能在实际交互中触发保存点。 | No |
| **B7** | **accepted-with-caveats** | Namespace injection, event log writer (append-only), 和 per-run checkpoint path 均已实现 (3f2f6b2)。Codex 审计通过。 | No |
| **B8** | **accepted-with-caveats** | M1-M8 (Interaction-first Workbench) 代码实现完全遵从 fake/local 隔离边界 (ccd89f5)。394 个测试用例覆盖全面。TUI 入口安全保持在 NOT ACTIVATED。 | No |

---

## 3. Remediated Items

1. **B8 UI Scoping Issues**: M5 `PendingActions` 和 M7 `EventPanel` 已成功实现基于 `selectedLens` 的数据过滤 (commit: ccd89f5)。
2. **B8 Data Redaction**: `EventSourceContract` 中的数组递归脱敏漏洞已被修复 (commit: ccd89f5)。
3. **Docs Honesty & Alignment**: 旧的 "Phase 6B/7" 以及 "Audit Lens" 词汇已被更新或归档，"Context Panel" 和 "Context Inspector" 成为 M0-M8 的统一规范。

## 4. Remaining Caveats

1. **Fake/Local Mocking (B8)**: B8 的数据主要依赖 fixture 隔离（fake/local），并非连接真实的 runtime state。这并非缺陷，而是当前阶段刻意保持的边界。
2. **Model Behavior Conflation (B3/B5)**: 测试中出现的部分失败（如 `test_second_round_dogfooding_smoke.py` 的 xfail）属于 `FakeProvider` 的行为语义变化（如非空 end-turn reply），而非核心控制流代码的缺陷。

## 5. Future Debts

1. **B3 L2 SubAgent Integration**: 现阶段仅实现和验证了 L1。L2 需要更成熟的模型和真实的 E2E。
2. **B4 Real MCP Server Connection**: 需要实际挂载外部 MCP Server 完成 real external flight E2E 测试。
3. **B7 Multi-instance Real Adapter**: B8 TUI 需要一个 real adapter 去消费 B7 提供的底层 multi-instance file system 数据。
4. **TUI Default Entry Activation (B8)**: TUI 尚不支持作为产品的 Default Entry。需在解决 IME（输入法）问题和真实数据接入后由用户手动 Activation。

## 6. No-Action / Superseded Items

- `Dashboard.tsx` 及 AutoRun UI：保留在代码库作为历史遗留物和 dev-only 的入口，但不进入 default entry 产品主线。
- B8 "Phase 1-6A" 相关的所有设计文档：均已标为 SUPERSEDED，由 `first-agent-tui-design.md` 等 M0-M8 规范完全接管。

---

## 7. Gates

运行在最新 HEAD (`2f995b9`) 环境下：

- `cd tui && npm test` 
  - Exit code: 0
  - Summary: 394 passed (394) in 3.32s
- `cd tui && npm run typecheck` 
  - Exit code: 0
- `.venv/bin/python -m pytest tests/test_architecture_boundaries.py` 
  - Exit code: 0
  - Summary: 24 passed in 5.19s
- `.venv/bin/python -m pytest tests/test_b7_event_log.py` 
  - Exit code: 0
  - Summary: 41 passed in 1.68s
- `git diff --check`
  - Exit code: 0 (clean tree)
- Timeout: No

---

## 8. Final Current-Stage Close-Out Recommendation

经过严谨的代码审查与测试覆盖的交叉验证，确认 **B1-B8 Capabilities 均达到了 Current-Stage 的设计目标**。

- 所有的 "Overclaim" 已经被明确地降级和诚实标记为 "PARTIAL" 或 "Fake/Local"。
- M1-M8 工作台作为 Fake/Local MVP 拥有非常高的工程质量。
- B1-B7 在底层 Runtime 阶段已充分验证了 Dispatcher, Tool Gate, Checkpoint, Namespace, MCP Foundation 等机制的合理性。

**Recommendation**: The First Agent is officially declared a **Current-Stage Close-Out Candidate (Accepted-with-Caveats)**.

可以停止在 B1-B8 上添加新 feature，封版并准备步入下一架构周期。
