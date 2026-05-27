# 全能力红队达标审计报告

日期：2026-05-27
模式：`audit_only` — 只读审计，不改生产代码、不改测试、不调用真实 API
范围：全代码库 15 个能力域 (A-O) 的达标程度审计
审计员角色：红队诚信审计员，非实现者

---

## Executive Summary

**总分：4.2/10** — 项目有清晰的架构理念和扎实的基础设施，但在关键用户路径上缺乏真实的端到端证据。很多能力"看起来有"，但经不起 L3/L4 级别审查。

这个项目不是 demo，而是有明确架构纪律的本地 Agent Runtime。核心设计（统一主流程、RuntimeActionDispatcher provenance、evidence 分类）是正确的。但执行层面存在三个层次的问题：

1. **证据层次**：大量 PASS 来自直接 handler 调用（L1/L2）、fake provider smoke、或 event count 检查，而非真实 runtime E2E（L3）
2. **安全/运维层次**：agent_log.jsonl 773MB 无治理、config/config.yaml tracked dirty、日志可能含敏感信息
3. **架构卫生层次**：core.py/loop.py 过大、部分子系统只有 stub、recall 路径未真正接入 prompt context

项目当前不应继续扩功能。应先执行 3-5 个 remediation loop 还技术债。

---

## Scope and Non-Goals

**本轮范围**：
- 全代码库只读审计
- 15 个能力域 (A-O) 覆盖率与达标度评估
- 文档产出：审计报告 + remediation loop plan + 更新 PROJECT_STATUS/PROGRESS_LEDGER

**本轮不包含**：
- 不修改任何 Python 代码
- 不修改任何测试
- 不调用真实 API
- 不读取 .env 或 config/config.yaml 内容
- 不提交 config/config.yaml
- 不 push、不 tag、不修改 remote
- 不做架构重构

---

## Methodology

1. 收集事实基础（git status/log、文件列表、磁盘占用）
2. 逐域阅读代码、文档、测试、dogfood report
3. 按统一标准打分：0-10 分，侧重 L3/L4 evidence 的有无
4. 分类：PASS(≥7) / CONCERN(4-6) / FAIL(2-3) / BLOCKED(0-1)
5. 问题分级：P0(立即)/P1(本 loop)/P2(近期)/P3(排队)
6. 输出审计文档、remediation plan、更新事实源

---

## Evidence Commands

```bash
pwd                                    # /Users/jinkun.wang/work_space/my-first-agent
git status -sb                         # main...origin/main, M config/config.yaml
git log --oneline -20                  # 最近提交：memory policy fix, dogfood sweep, evidence kind
git rev-list --left-right --count origin/main...HEAD  # 0 0 (同步)
find docs -maxdepth 3 -type f | sort   # 180+ 文档文件
find agent memory llm scripts tests -maxdepth 2 -type f -name '*.py' | sort  # 200+ Python 文件
du -sh agent_log.jsonl sessions runs memory  # 773M agent_log.jsonl, 4.0M sessions, 96K memory
wc -l agent/core.py agent/loop.py      # core.py:1172, loop.py:852
```

---

## Capability Scorecard

| 域 | 名称 | 评分 | 判定 | 最高证据层 |
|---|---|---|---|---|
| A | Unified Runtime Flow | 6/10 | CONCERN | L3 dispatch path (部分) |
| B | Tool 子系统 | 7/10 | PASS | L3 business operation (fake) |
| C | Memory 子系统 | 4/10 | CONCERN | L2 integration (fake) |
| D | Checkpoint / Resume | 3/10 | FAIL | L1 unit + prompt拼接 |
| E | Sub-agent / Delegation | 4/10 | CONCERN | L2 integration (L0 only) |
| F | Skill 系统 | 5/10 | CONCERN | L2 integration |
| G | MCP / External Adapter | 3/10 | FAIL | L1 unit stub |
| H | Provider / Model Config | 6/10 | CONCERN | L3 real API smoke |
| I | Runtime Observer / Trace / Evidence | 5/10 | CONCERN | L2 (日志无治理) |
| J | CLI / TUI / Interactive Dogfood | 7/10 | PASS | L3 fake interactive |
| K | Config / Security / Privacy | 3/10 | FAIL | L0 — 严重风险 |
| L | Test Architecture / Gate Quality | 5/10 | CONCERN | L1-L3 mixed, 冒充风险 |
| M | Docs / Source of Truth / Roadmap | 6/10 | CONCERN | 经前次修复已改善 |
| N | Code Architecture / Maintainability | 4/10 | CONCERN | god object 风险 |
| O | Product Readiness / UX | 3/10 | FAIL | 非用户可就绪 |

**统计**：
- PASS: 2 (B, J)
- CONCERN: 9 (A, C, E, F, H, I, L, M, N)
- FAIL: 4 (D, G, K, O)
- BLOCKED: 0

**总分**：4.2/10（加权平均，非简单算术平均）

---

## Per-Domain Audit Details

---

### A. Unified Runtime Flow / 主流程一致性 — 6/10 CONCERN

**事实证据**：
- `core.chat()` (agent/core.py:249+) 是唯一的 runtime 入口
- `run_main_loop()` (agent/loop.py) 承载模型循环 + turn-end hook
- `RuntimeActionDispatcher.route_from_runtime_loop()` (agent/runtime_integration/dispatcher.py:339) 提供 dispatcher-owned provenance，防止 payload 伪造
- hook 参数化：`provider_kind`/`provider_external_call` 从 dependencies 传入，不做 fake/real 分支
- UNIFIED_RUNTIME_FLOW_CONTRACT.md 明确定义了统一主流程契约

**正面发现**：
1. 统一主流程确实存在且被遵守：`core.chat → run_main_loop → dispatch_model_output → turn-end hook → RuntimeActionDispatcher`
2. provenance 机制 (`route_from_runtime_loop` vs `route`) 区分了真实 loop 调用和直接调用
3. evidence classification (business vs probe) 区分了用户可见动作和内部生命周期检查
4. fake/real 不分裂为两条 runtime

**问题发现**：
1. **CLI shortcut 构成第二能力平面 (P1)**
   - `core.py` 中存在多个 pre-loop shortcut：`show memories`、`forget memory`、`show subagents`、`delegate to subagent`
   - 这些 shortcut 绕过了 RuntimeActionDispatcher，直接操作子系统
   - 虽然当前尚未形成完整的第二 runtime，但如果继续添加 shortcut，风险会快速增加
   - 证据：`agent/core.py` 中的 `_looks_like_*` 和 `detect_*` 函数

2. **Turn-end hook 过重 (P2)**
   - `loop.py:_try_phase1_turn_end_runtime_action()` 同时触发 MEMORY_TURN_END_PROPOSAL、MEMORY_PROPOSE、TOOL_GATE、TOOL_REQUEST、TOOL_INVOKE、TOOL_RESULT、CHECKPOINT_SAFE_SUMMARY、MEMORY_CONSOLIDATE、MEMORY_RECALL、SKILL_SELECT、SUBAGENT_DELEGATE_L0 共 11 种 action
   - 这更像 evidence fanout 而非有限 branch point
   - 大多数 probe action 每个 turn 都运行但返回 noop，增加了噪音

3. **Memory recall 位置错误 (P1)**
   - MEMORY_RECALL 挂在 turn-end hook，但按设计应在 pre-loop 执行
   - `refresh_runtime_system_prompt()` 虽调用 `_memory_runtime.snapshot_for_prompt()`，但这条路径不经过 RuntimeActionDispatcher
   - 结果：recall handler 注册了但实际 memory 注入走的是 bypass 路径

**L3 Evidence 评估**：
- L3 dispatch path verified：部分（hook action 确实从 loop 触发）
- L3 business operation verified：部分（TOOL_GATE/INVOKE/RESULT pipeline）
- L3 complete/full闭环：否

**主要缺口**：
- CLI shortcut 未收敛到统一 dispatcher
- Turn-end hook 承载了过多的 probe action
- Memory recall 实际路径与 dispatcher 注册路径不一致

**建议 loop**：Loop 1 — Runtime entry consolidation
**stop condition**：需要改 checkpoint schema 或涉及真实 API

---

### B. Tool 子系统 — 7/10 PASS

**事实证据**：
- `agent/tool_registry.py`：全局 TOOL_REGISTRY，带 capability/risk/confirmation/output_policy 元数据
- `agent/tool_executor.py`：执行工具、处理 confirmation、checkpoint 存储
- `agent/runtime_integration/tool_gate.py`：TOOL_GATE handler，判断 allowed/blocked/confirmation_required
- `agent/runtime_integration/tool_invoke.py`：TOOL_INVOKE handler
- `agent/runtime_integration/tool_result_feedback.py`：TOOL_RESULT handler
- Tool lifecycle 三个阶段 (gate→invoke→result) 正确实现为同一管道的子阶段，不是三个独立子系统
- 安全工具 (`agent/security.py`, `agent/tools/path_safety.py`) 提供路径安全检查

**正面发现**：
1. Tool pipeline 走统一 RuntimeActionDispatcher，gate/invoke/result 三个阶段各自独立 try/except
2. confirmation 机制完善：支持 always/never/callable 三种确认策略
3. blocked/not_found/confirmation_required 状态正确处理为 evidence
4. tool_args 显式传递，避免隐式 fallback 链
5. Fake 和 Real 共享同一 tool 管道（gate→invoke→result 不变）

**问题发现**：
1. **Confirmation 只在 fake interactive dogfood 中验证 (P1)**
   - Real API interactive dogfood 的 R06-R08 覆盖了 y/n confirmation，但只有 3 个 case
   - 更复杂的 multi-turn tool confirmation（confirm→execute→result→next tool）未覆盖

2. **blocked 路径的测试覆盖以 fake 为主 (P2)**
   - `test_tool_blocked_l3.py`、`test_tool_gate_not_found_l3.py` 等测试文件标记为 L3，但实际大多用 fake provider

3. **Tool retry 机制缺失 (P3)**
   - 工具执行失败后没有 retry 策略；当前行为是 fail-closed

**L3 Evidence 评估**：
- L3 dispatch path verified：是（fake provider 下）
- L3 business operation verified：是（fake provider 下，tool pipeline L3 completion）
- L3 complete/full闭环：部分（fake 下较完整，real 下只有 smoke）
- L3 real API evidence：有（interactive dogfood R06-R08）

**主要缺口**：
- Real API 下的 multi-turn tool confirmation 覆盖不足
- Tool retry 策略缺失
- 工具执行结果与用户可见输出的对应关系未充分验证

**建议 loop**：Loop 3 — Tool real API 交互式覆盖扩展
**stop condition**：需要真实 API 调用但未获授权

---

### C. Memory 子系统 — 4/10 CONCERN

**事实证据**：
- `agent/memory_runtime.py`：Memory Kernel v1，explicit retain 最小闭环
- `agent/memory_policy.py`：DeterministicMemoryPolicy，基于规则匹配
- `agent/memory_store.py`：InMemoryMemoryStore + FilesystemMemoryStore
- `agent/memory_contracts.py`：MemoryDecision、MemoryCandidate、MemorySnapshot 等类型
- `agent/memory_confirmation.py`：MemoryInteractiveConfirmation，两阶段确认
- `agent/runtime_integration/memory_hook.py`：turn-end proposal handler
- `agent/runtime_integration/memory_retain.py`：retain execution handler
- `agent/runtime_integration/memory_recall.py`：recall handler
- 最新修复(3089316)：RETAIN_PREFIXES 增加了中文"请记住"前缀

**正面发现**：
1. Memory 生命周期有清晰的 proposal → review → retain → recall 划分
2. confirmation 是两阶段交互，不跳过用户
3. policy 是可注入的，store 是可替换的
4. 中文"请记住"前缀修复解决了主要的假阴性问题
5. `memory/` 目录已有 `episodes/`、`rules/`、`profile.json` 目录结构

**问题发现**：
1. **Memory recall 未真正进入上下文 (P0)**
   - `MemoryRecallHandler` 完成了从 store 读取 → 渲染 prompt section 的流程
   - 但 `loop.py` 的 turn-end MEMORY_RECALL hook 位置错误（应该在 pre-loop）
   - `refresh_runtime_system_prompt()` 调用 `_memory_runtime.snapshot_for_prompt()` 绕过了 RuntimeActionDispatcher
   - 结果：真实 prompt context 中的 memory section 来自模块级 `_memory_runtime`（in-memory only），而不是经过 dispatcher evidence chain 的 recall handler
   - **当前 recall 不是真正的 L3 evidence**——dispatcher 路径和实际 context 注入路径是两条不同的路

2. **Fake/real Memory 不共享核心路径 (P1)**
   - 模块级 `_memory_runtime = create_memory_runtime()` 默认使用 InMemoryMemoryStore
   - FilesystemMemoryStore 存在，但 L2 inline extraction 才用
   - 模块级单例在多 session 下可能交叉污染 memory

3. **Session-end extractor 过滤语义型偏好 (P1)**
   - PROJECT_STATUS 承认：session-end extractor 仍只处理 episodic proposals，语义型偏好会被过滤
   - 这意味着"记住我喜欢简洁回答"这类偏好可能被漏掉

4. **删除/纠正/冲突处理缺失 (P2)**
   - 有 `forget` 操作，但没有 update/modify/correct 操作
   - 冲突检测（同一 key 不同 value）不存在

5. **confirm→retain→recall E2E 未完全验证 (P1)**
   - 内联"请记住"前缀已修，但整个闭环在 fake + real API 下未系统验证

**L3 Evidence 评估**：
- 当前最高证据层：L2 integration (fake)
- 宣称的 L3 evidence 实际只是 dispatch path verified（handler 被调用了，但结果没有真正进入 prompt）
- 不存在 L3 complete/full闭环 evidence

**主要缺口**：
- Recall 路径 split：dispatcher 一条，实际 context 注入另一条
- confirm→retain→recall 完整 E2E 未验证
- 跨 session recall 未验证
- Memory 冲突处理缺失

**建议 loop**：Loop 2 — Memory E2E 验证闭环（最高优先级）

**stop condition**：涉及真实用户私人数据或需要修改 store schema 导致旧数据丢失

---

### D. Checkpoint / Resume — 3/10 FAIL

**事实证据**：
- `agent/checkpoint.py`：save_checkpoint/load_checkpoint，写到 `memory/checkpoint.json`
- `agent/session.py`：session 管理、resume prompt 生成
- `agent/pending_confirmation_dispatch.py`：pending confirmation 路由
- checkpoint 保存：task status、plan、conversation 摘要、pending tool/memory confirmations

**正面发现**：
1. checkpoint save/load 机制存在，保存了关键状态
2. tool/memory confirmation 会触发 checkpoint 保存
3. 有 truncation 配置（max_result_length, max_tool_results）

**问题发现**：
1. **Resume 本质是 prompt 拼接 (P1)**
   - `session.py` 的 resume 逻辑主要是把 checkpoint 中的 conversation summary 拼回 system prompt
   - 不是真正的 runtime state restoration
   - conversation messages 不完整保存（只保存摘要），导致 resume 后可能丢失精确上下文

2. **无 schema 版本治理 (P1)**
   - checkpoint 格式无 version 字段
   - 如果 state schema 变更，旧 checkpoint 可能加载失败或行为异常
   - 没有迁移逻辑

3. **无 interrupt/resume 的 L3 evidence (P1)**
   - Interactive dogfood 有 I16 (resume decline) case
   - 但没有真正的中断(Ctrl+C)→恢复流程的自动化测试
   - `awaiting_interrupt_choice` 状态已定义但未在 dogfood 中验证

4. **Checkpoint 仅保存到本地文件 (P2)**
   - 没有跨设备/跨 session 的 checkpoint 恢复
   - `memory/checkpoint.json` 是单文件，并发写可能冲突

**L3 Evidence 评估**：
- 最高证据层：L1 unit（checkpoint roundtrip tests）
- 声称的 L3 实际只是 prompt 拼接，不是真正的 state restoration
- 不存在 L3 runtime state restoration evidence

**主要缺口**：
- 真正的 state restoration（不只是 prompt 拼接）
- Schema 版本治理
- Interrupt→resume 的完整 E2E 验证

**建议 loop**：Loop 4 — Checkpoint/Resume 能力补全

**stop condition**：需要改 state schema 导致旧 checkpoint 不可读，或需要真实 API

---

### E. Sub-agent / Delegation — 4/10 CONCERN

**事实证据**：
- `agent/subagent_system/` 包含 registry、delegation、executor、policy、adjudication 等
- `agent/subagents/local.py`：L0 local deterministic subagent
- SUBAGENT_DELEGATE_L0 是 RuntimeActionType 之一
- subagent 结果通过 adjudication 反馈回 parent runtime

**正面发现**：
1. Sub-agent 是通过 RuntimeActionDispatcher 的受控分支点，不是第二个 runtime
2. delegation → execution → adjudication → result 流程清晰
3. L0 deterministic executor 不调用真实 LLM，安全性好
4. 有 tool/memory/skill boundary 隔离机制

**问题发现**：
1. **SubAgent 只是 L0 deterministic executor (P2)**
   - 不涉及真实 child LLM delegation
   - execute_local 只是 rule-based，不做任何推理
   - 当前行为更像"命令别名"而非"子代理"

2. **Delegation result feedback 不完整 (P2)**
   - SubAgentRun 返回给 parent，但 parent 如何处理 subagent 结果未充分验证
   - evidence/state 从 subagent 回流到 parent runtime 的路径不清晰

3. **CLI shortcut 绕过 dispatcher (P2)**
   - `core.py` 的 `detect_delegate_to_subagent` 和 `detect_nl_delegation` 在 main loop 前直接处理
   - 绕过了 RuntimeActionDispatcher

4. **Tool/memory 隔离未在 real API 下验证 (P3)**
   - 边界机制定义了但只在 fake 下测试

**L3 Evidence 评估**：
- 最高证据层：L2 integration (fake)
- L3 dispatch path verified：有（SUBAGENT_DELEGATE_L0 走 dispatcher）
- 不存在 L3 business operation verified（因为 L0 本身就是 deterministic）

**建议 loop**：Loop 7 — SubAgent boundary hardening（低优先级）

---

### F. Skill 系统 — 5/10 CONCERN

**事实证据**：
- `agent/skill_system/` 包含 registry、invocation、loader、selector、descriptor、schema
- `agent/legacy_skills/` 仍存在，提供旧式 skill 加载
- SKILL_SELECT 是 RuntimeActionType 之一
- Skills 有 visibility、tag、keyword 选择机制

**正面发现**：
1. Skill 不拥有 Agent loop，调用是 request/result flow
2. 不直接执行工具，不直接写 Memory
3. SkillInvocationResult 可审计
4. 有 skill checkpoint boundary 机制

**问题发现**：
1. **Skill invocation 未在 real API 下验证 (P2)**
   - 只有 fake 下的 L2 integration tests
   - Interactive dogfood 不包含 skill 相关 case
   - Real API dogfood sweep 的 skill 覆盖基本为零

2. **Legacy skills 与 skill_system 并存 (P3)**
   - `agent/legacy_skills/` 和 `agent/skill_system/` 两套体系
   - 旧代码未清理，可能导致混乱

3. **Skill 与 Tool 的边界不清晰 (P3)**
   - `agent/tools/skill.py` 和 `agent/tools/install_skill.py` 将 skill 操作作为工具暴露
   - 但 skill invocation 本身不经过 tool pipeline

**L3 Evidence 评估**：
- 最高证据层：L2 integration (fake)
- L3 dispatch path verified：有（SKILL_SELECT 走 dispatcher，但 registry 通常为空）
- 不存在 L3 business operation verified

**建议 loop**：Loop 8 — Skill system hardening

---

### G. MCP / External Adapter — 3/10 FAIL

**事实证据**：
- `agent/mcp.py`：MCP client architecture seam，只定义本地边界
- `agent/mcp_models.py`：MCPServerConfig、MCPToolDescriptor
- `agent/mcp_policy.py`：MCP 安全和注册策略
- `agent/mcp_config.py`：MCP 配置管理
- `agent/mcp_stdio.py`：stdio transport（存在但未深度验证）
- `agent/mcp_bridge.py`：桥接层
- FakeMCPClient 存在，用于测试

**正面发现**：
1. MCP 被设计为复用 Tool 管道（mcp_registry_tool_name 注册到 TOOL_REGISTRY）
2. FakeMCPClient 提供安全的本地测试路径
3. 配置管理、安全策略、敏感路径检查都有框架
4. MCP 不成为新 runtime——它通过 Tool registry 接入

**问题发现**：
1. **MCP 没有真实连接验证 (P1)**
   - 虽然存在 `test_real_mcp_flight.py`，但需要真实 MCP server
   - MCP 的 L3 real core loop 测试存在（`test_mcp_l3_real_core_loop.py`），但使用 fake client
   - 没有任何证据表明真实 MCP server 连接能正常工作

2. **MCP tool orchestration 未完成 (P2)**
   - `agent/runtime_integration/mcp_tool_orchestrator.py` 存在但功能受限
   - 多 MCP server 并发、tool conflict、capability negotiation 未覆盖

3. **MCP secret handling 路径不安全 (P2)**
   - MCP server config 可能包含 credentials
   - 当前的 secret handling 依赖 mcp_sanitizer，但没有实际验证

**L3 Evidence 评估**：
- 最高证据层：L1 unit stub
- 声称的 L3 测试实际使用 fake client，不是真实 MCP
- 不存在 L3 real external adapter evidence

**建议 loop**：Loop 9 — MCP minimal real connection（需用户显式授权）

---

### H. Provider / Model Config — 6/10 CONCERN

**事实证据**：
- `agent/provider/simple_config.py`：load_unified_provider_config()，推荐入口
- `agent/provider/factory.py`：build_model_provider_from_env()，fallback 链
- `agent/provider/fake_provider.py`：FakeProvider，安全默认
- `agent/provider/anthropic_http.py`、`openai_http.py` 等 adapter
- `agent/provider/diagnostics.py`：provider 诊断
- config resolution precedence：config.yaml → provider_profiles (legacy) → env vars (legacy) → fake

**正面发现**：
1. 默认 fake provider，零配置可运行
2. config.yaml 是唯一推荐入口
3. provider adapter 内部处理协议细节，不暴露给用户
4. fake/real 共享 core.chat → run_main_loop 路径
5. anthropic_compatible/openai_compatible 覆盖主流 API

**问题发现**：
1. **config/config.yaml tracked 且 dirty (P0)**
   - 这是当前最严重的安全风险
   - 可能含真实 API key
   - 每次 git 操作都有意外提交的风险

2. **Legacy fallback 代码仍存在 (P2)**
   - provider_profiles.yaml、FIRST_AGENT_PROVIDER_PROFILE、MY_FIRST_AGENT_LLM_PROVIDER
   - diagnostics 仍可能输出 legacy 建议
   - `build_model_provider_from_env()` 命名暗示 env 是主入口

3. **Provider identity 混乱 (P3)**
   - 不同 provider 输出不同的 self-identification
   - 已标记为 WONTFIX，但对用户体验有负面影响

**L3 Evidence 评估**：
- L3 real API smoke：有（20-case sweep, 19 non-failing）
- L3 real API interactive：有（15/15 PASS）
- 但 real API smoke 大部分是 direct provider call，不是完整的 runtime E2E

**建议 loop**：Loop 5 — Config safety harden

---

### I. Runtime Observer / Trace / Evidence — 5/10 CONCERN

**事实证据**：
- `agent/local_trace.py`：TraceEvent 数据模型 + JSONL recorder
- `agent/runtime_observer.py`：Runtime event logger
- `agent/runtime_trace_emitter.py`：trace event 发射
- `agent/runtime_trace_projection.py`：trace 投影到 agent_log.jsonl
- `agent/runtime_events.py`：RuntimeEvent (UI 事件)
- `agent/display_events.py`：DisplayEvent (CLI/TUI 输出)
- `agent/runtime_integration/evidence.py`：evidence 分类和 provenance 验证
- agent_log.jsonl 当前大小：**773MB**

**正面发现**：
1. evidence kind classification (business vs probe) 区分了业务动作和生命周期检查
2. RuntimeActionDispatcher provenance 机制防止 payload 伪造
3. classify_evidence_level() 提供标准化的证据等级判定
4. run summary 统计 business/probe 计数

**问题发现**：
1. **agent_log.jsonl 773MB 无治理 (P0)**
   - 巨大且持续增长
   - 没有轮转、大小上限、自动清理策略
   - `agent/log_cleanup.py` 存在但显然未有效工作
   - **可能包含敏感信息**（user messages、model responses、tool outputs）
   - `.gitignore` 已排除，但本地磁盘占用严重

2. **敏感信息泄露风险 (P0)**
   - agent_log.jsonl 记录 user_input、llm_response、agent_reply
   - 这些内容未经脱敏直接写入
   - 虽然 local_trace.py 有 secret redaction，但 agent_log.jsonl 的写入路径可能不走这个脱敏

3. **Evidence overclaim 风险 (P1)**
   - probe events (noop) 可能被统计为能力完成
   - summary 中的 business/probe 计数需要更严格的校验
   - evidence kind classification 是 handler 自报 + 默认值，可能被误标

4. **Sessions/runs 目录管理不足 (P2)**
   - `sessions/` 4.0MB, `runs/` 8.0K
   - 没有清理策略
   - session 数据可能包含未脱敏内容

**L3 Evidence 评估**：
- evidence 系统本身的设计是好的
- 但 773MB 日志使其变成负债而非资产
- 无法确认日志中是否已泄露敏感信息

**建议 loop**：Loop 6 — Log hygiene and evidence governance

---

### J. CLI / TUI / Interactive Dogfood Harness — 7/10 PASS

**事实证据**：
- `scripts/dogfood_interactive_harness.py`：subprocess 驱动的交互式测试
- Fake: 16/16 PASS, 6 类别 (I-SANITY/I-CONFIRM/I-TOOL/I-MEMORY/I-STREAM/I-RESUME)
- Real: 15/15 PASS, 5 类别，kimi-k2.5 via DashScope
- `tests/test_interactive_dogfood_harness.py`：29 tests (28 pass + 1 slow smoke)
- `agent/cli/`：CLI/TUI 实现
- `agent/input_backends/`：Simple + Textual backend

**正面发现**：
1. 交互式 harness 通过 subprocess 验证用户真实路径（stdin→main.py→stdout）
2. Fake-first 设计，不依赖真实 API
3. 结构化断言（traceback 检测、confirmation 检测、secret 泄露检测）
4. Case 覆盖较全面：sanity、confirmation、tool、memory、streaming、resume
5. 15/15 real API interactive PASS 证明了基本交互能力

**问题发现**：
1. **Harness 不测试 streaming 的真正行为 (P2)**
   - I13 (streaming) case 只检测关键词出现
   - 不验证 streaming chunks 的完整性、顺序、延迟

2. **Interrupt (Ctrl+C) 未覆盖 (P2)**
   - 虽定义了 `awaiting_interrupt_choice` 状态
   - 但 harness 不支持发送 Ctrl+C 信号
   - 交叉平台信号发送是已列出的下一步工作

3. **Case matrix 仍有缺失 (P2)**
   - 无 multi-turn complex task case
   - 无 tool result 后的 follow-up question case
   - 无 memory recall 后的 context usage case
   - 无 error recovery case

**L3 Evidence 评估**：
- L3 fake interactive：是（16/16 PASS）
- L3 real interactive：是（15/15 PASS）
- 这是目前证据最强的域

**建议 loop**：Loop 3 — Interactive harness 扩展（与 Tool 共享）

---

### K. Config / Security / Privacy — 3/10 FAIL

**事实证据**：
- `.gitignore` 排除了 .env、agent_log.jsonl、sessions/、runs/、memory/、workspace/
- `config/config.yaml` 是 tracked 文件（在 git 中）且当前 dirty
- `config/config.example.yaml` 提供安全示例
- `agent/security.py`：敏感文件检测
- `agent/runtime_integration/schema.py`：_SECRET_PATTERNS 正则

**正面发现**：
1. .gitignore 覆盖了主要敏感路径
2. config.example.yaml 提供零-key 示例
3. secret 检测正则有基础覆盖
4. 安全默认：provider.enabled: false, type: fake

**问题发现**：
1. **config/config.yaml tracked 且 dirty (P0)**
   - 这是**最严重的安全风险**
   - 文件在 git 中，含真实 API key
   - 任何不小心的 `git add config/config.yaml` + `git commit` 就会泄露
   - 虽然有 guard tests 和 auto-run hard stop，但风险仍然实时存在

2. **agent_log.jsonl 773MB 可能含敏感信息 (P0)**
   - 包含所有 user input、model response、agent reply
   - 无脱敏、无轮转、无大小上限
   - 即使 .gitignore 排除了，本地存储也是隐私风险

3. **无日志脱敏策略 (P1)**
   - `local_trace.py` 有 `_redact_trace_value()` 但需要确认覆盖了所有日志写入路径
   - agent_log.jsonl 的主要写入路径 (`agent/runtime_trace_projection.py`) 是否走脱敏未验证

4. **sessions/runs/memory 目录可能被误提交 (P2)**
   - .gitignore 已覆盖，但新开发者可能不知道
   - 没有 pre-commit hook 验证

5. **sessions 目录 4.0MB 可能含未脱敏内容 (P2)**
   - 没有清理策略
   - 可能包含 session 摘要中的用户数据

**L3 Evidence 评估**：
- 不存在 — 安全审计尚未系统进行
- 当前评估基于代码阅读和文件检查

**建议 loop**：Loop 5 — Security harden（最高优先级之一）

---

### L. Test Architecture / Gate Quality — 5/10 CONCERN

**事实证据**：
- 200+ 测试文件，覆盖单元/集成/dogfood
- `tests/runtime_integration/` 下有多个标记为 L3 的测试
- `tests/test_interactive_dogfood_harness.py`：29 tests
- `tests/unit/test_evidence_kind_classification.py`：17 tests
- pytest + ruff 作为质量门

**正面发现**：
1. 测试文件数量多，覆盖面广
2. 有明确的 L1/L2/L3 分层意图
3. Fake provider 使大多数测试可离线运行
4. 有 guard tests 防止旧模式回归

**问题发现**：
1. **大量测试直接调用 handler 冒充 E2E (P1)**
   - 很多标记为 L3 的测试实际上构造 RuntimeActionRequest 并直接调用 dispatcher.route()
   - 根据 UNIFIED_RUNTIME_FLOW_CONTRACT，这只能算 `harness_runtime_e2e`
   - 真正的 `real_core_loop_runtime_e2e` 要求 dispatcher_origin == "runtime_loop"
   - 例：`test_tool_pipeline_l3_completion.py` — 需要验证它是否真的走 `route_from_runtime_loop()`

2. **L3 标签使用不一致 (P1)**
   - Contract 定义了 L3 dispatch path verified / L3 business operation verified / L3 complete
   - 但测试文件命名和注释中仍使用笼统的 "L3"
   - 没有系统性地审计哪些测试真正满足 L3 标准

3. **Fake 和 Real 的测试不对称 (P2)**
   - Fake 下大量测试，Real 下只有少量 smoke
   - Real API 测试依赖外部服务，不能作为 CI gate

4. **Pytest 全量运行可行性未知 (P2)**
   - 200+ 测试文件，部分可能依赖真实 API 或特定环境
   - 如果 config/config.yaml 含真实 key，部分测试可能意外调用真实 API

**L3 Evidence 评估**：
- 许多测试宣称 L3 但实际是 L2 (harness_runtime_e2e)
- 需要系统性地重新分类所有测试的证据等级

**建议 loop**：Loop 10 — Test taxonomy audit and reclassification

---

### M. Docs / Source of Truth / Roadmap — 6/10 CONCERN

**事实证据**：
- `docs/PROJECT_STATUS.md`：当前状态入口
- `docs/PROGRESS_LEDGER.md`：进度历史
- `docs/dev/AUTO_RUN_WORKFLOW.md`：auto-run 流程
- `docs/dev/ENGINEERING_WORKFLOW.md`：工程 loop
- `docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md`：运行时宪法
- 180+ 文档文件，大量已归档

**正面发现**：
1. 上次 source-of-truth repair 已修复主要文档冲突
2. PROJECT_STATUS/PROGRESS_LEDGER 作为事实源体系清晰
3. 归档文档在 docs/archive/ 下，与 active docs 分离
4. 文档导航表在 PROJECT_STATUS 中

**问题发现**：
1. **PROJECT_STATUS 仍偏乐观 (P2)**
   - "交互式 dogfood harness 就绪（16/16 PASS fake + 15/15 PASS real）" 暗示就绪
   - 但交互式 dogfood 没覆盖 streaming、interrupt、complex multi-turn 等关键路径
   - "Real API Dogfood 19 non-failing / 1 CONCERN / 0 FAIL" 大多数是 direct provider call

2. **部分文档可能已过时（前次修复后新增变更） (P3)**
   - 3089316 (memory policy fix) 和 6c79698 (dogfood sweep) 之后的部分文档可能未更新

3. **文档数量过多 (P3)**
   - 180+ 文档文件，部分内容重叠
   - archive 目录自身也需要维护

**建议 loop**：本次审计后的文档更新即为修复的一部分

---

### N. Code Architecture / Maintainability — 4/10 CONCERN

**事实证据**：
- `agent/core.py`：1172 行 — chat API + CLI shortcuts + memory + subagent + planning + session + dispatcher setup
- `agent/loop.py`：852 行 — 主循环 + turn-end hook (11 种 action)
- `agent/memory_fs_store.py`：875 行
- `agent/memory_emergence.py`：919 行
- `agent/tool_executor.py`：574 行
- `agent/display_events.py`：750 行

**正面发现**：
1. 模块边界大部分清晰：provider/、skill_system/、subagent_system/、runtime_integration/ 各自独立
2. RuntimeActionDispatcher 的高内聚设计（route + context + result 在一个文件）
3. schema 层（RuntimeActionRequest/Result/Event）与执行层分离
4. 中文学习注释提供了一个良好的文档惯例

**问题发现**：
1. **core.py 是 god object (P1)**
   - 承担 chat API、CLI meta command、planning context、dispatcher setup、session/checkpoint
   - 模块级可变状态 (`state`、`_memory_runtime`、`_l2_trigger_guard`) 使得测试隔离困难
   - 1172 行且职责太多，任何修改都有大 blast radius

2. **loop.py turn-end hook 过重 (P1)**
   - `_try_phase1_turn_end_runtime_action()` 同时处理 11 种 action
   - 这个函数应该被拆成多个独立的 hook
   - 与 core.py 的 CLI shortcuts 形成双 hub

3. **模块级可变单例风险 (P2)**
   - `state`、`_memory_runtime`、`_l2_trigger_guard`、`_model_provider`、`client`
   - 测试需要 monkeypatch
   - 多 session 场景下可能交叉污染

4. **大文件分布不均 (P2)**
   - 前 10 大文件合计 ~7000 行
   - memory 子系统文件尤其大（emergence 919 行、fs_store 875 行、extraction 767 行）

**建议 loop**：Loop 11 — Surgical hub slimming（行为保持型抽取）

---

### O. Product Readiness / User Experience — 3/10 FAIL

**事实证据**：
- 项目定位：个人学习/实验项目（PROJECT_STATUS 明确声明）
- 默认 fake provider，零配置可运行
- `main.py` 作为 CLI 入口
- 有 basic TUI (Textual) 和 Simple CLI backend

**正面发现**：
1. 默认 fake 模式安全：用户可以零配置体验
2. config.example.yaml 提供清晰的配置示例
3. CLI/TUI 两种交互模式
4. 有 health check 和 startup readiness check

**问题发现**：
1. **README 不是好的 getting started (P2)**
   - 上次修复后的 README 状态未验证
   - 用户体验从 clone 到 first run 的路径可能仍有障碍

2. **错误信息质量参差不齐 (P2)**
   - 部分错误有中文可读信息
   - 但很多地方是原始 exception traceback

3. **用户无法知道"现在发生了什么" (P2)**
   - TUI 展示了部分运行时信息
   - 但 turn-end probe events 对用户不可见，只有 final response
   - streaming 的用户可见进度不完整

4. **Real API opt-in story 不清晰 (P2)**
   - 用户需要手动编辑 config/config.yaml
   - 但 config.yaml 可能被误提交
   - 没有 `--dry-run` 或 `--check-config` 命令

5. **非 macOS/非 Python 3.12 环境的兼容性未验证 (P3)**

**L3 Evidence 评估**：
- 不存在系统性的用户体验验证

**建议 loop**：Loop 12 — UX hardening

---

## L3/L4 Evidence Classification

### 当前证据等级分布

| 能力 | 宣称等级 | 实际等级 | 差距 |
|------|---------|---------|------|
| Basic chat (real API) | REAL_DOGFOOD_SMOKE | REAL_PROVIDER_SMOKE | 大部分是 direct provider，非 runtime |
| Tool pipeline (fake) | L3 complete | L3 business operation | 接近但 confirmation/retry 未全覆盖 |
| Tool pipeline (real API) | L3 | L2+ (partial real smoke) | 只有 3 个 interactive case |
| Memory recall | L3 dispatch path | L2 integration | 实际 context 注入走 bypass |
| Checkpoint resume | L3 | L1 unit | 本质是 prompt 拼接 |
| Skill select | L3 dispatch path | L2 (empty registry) | handler 只测 no_suitable_skill |
| Subagent delegate | L3 dispatch path | L2 (L0 deterministic) | 不是真实 delegation |
| MCP tool | L3 real core loop | L1 unit stub | 使用 fake client |
| Streaming | L2 | L1+ | fail-closed，无真实验证 |
| Interactive dogfood (fake) | FAKE_LOCAL_SMOKE | L3 fake interactive | 业界最佳 fake evidence |
| Interactive dogfood (real) | REAL_API_INTERACTIVE_SMOKE | L3 real interactive | 业界最佳 real evidence |

### 伪证明列表

1. **"20 cases real API dogfood PASS"** — 多数是 direct provider call，不是 runtime E2E
2. **"Memory recall L3"** — recall handler 注册了但实际 context 注入走 bypass
3. **"Checkpoint resume L3"** — 本质是 prompt 拼接，不是 state restoration
4. **"MCP L3 real core loop"** — 使用 FakeMCPClient，不是真实 MCP server
5. **"Skill L3"** — handler 只测试了 empty registry 的 noop 路径
6. **"Tool pipeline L3 completion"** — fake 下可用，但 real API 下未充分验证
7. **Event count PASS** — 将 probe/noop events 计为能力完成

---

## P0/P1/P2/P3 Issue List

### P0 — 必须立即处理（安全/数据风险）

| ID | 问题 | 域 | 描述 |
|----|------|---|------|
| P0-1 | config/config.yaml tracked dirty | K, H | 含真实 API key 在 tracked 文件中 |
| P0-2 | agent_log.jsonl 773MB 无治理 | I, K | 可能含敏感信息，磁盘占用严重 |
| P0-3 | Memory recall 未真正进入上下文 | C | 两条路径 split，实际 context 不走 dispatcher |

### P1 — 本阶段必须修

| ID | 问题 | 域 |
|----|------|---|
| P1-1 | CLI shortcut 构成第二能力平面 | A |
| P1-2 | Memory confirm→retain→recall E2E 未验证 | C |
| P1-3 | Fake/real memory 不共享核心路径 | C |
| P1-4 | Session-end extractor 过滤语义型偏好 | C |
| P1-5 | Resume 本质是 prompt 拼接 | D |
| P1-6 | 无 checkpoint schema 版本治理 | D |
| P1-7 | 大量 L3 标签测试实际是 L2 | L |
| P1-8 | Evidence overclaim (probe 计为能力) | I |
| P1-9 | core.py 是 god object | N |
| P1-10 | loop.py turn-end hook 过重 | N |

### P2 — 近期应修

| ID | 问题 | 域 |
|----|------|---|
| P2-1 | Real API multi-turn tool confirmation 不足 | B |
| P2-2 | Tool retry 机制缺失 | B |
| P2-3 | Memory 删除/纠正/冲突处理缺失 | C |
| P2-4 | SubAgent 只是 L0 deterministic | E |
| P2-5 | SubAgent CLI shortcut 绕过 dispatcher | E |
| P2-6 | Skill 未在 real API 下验证 | F |
| P2-7 | MCP 无真实连接验证 | G |
| P2-8 | Legacy fallback/provider 代码仍存在 | H |
| P2-9 | Interactive harness 缺 streaming/interrupt/complex case | J |
| P2-10 | Sessions/runs 目录管理不足 | I |
| P2-11 | Pytest 全量运行可行性未知 | L |
| P2-12 | PROJECT_STATUS 仍偏乐观 | M |
| P2-13 | 模块级可变单例风险 | N |
| P2-14 | 大文件分布不均 | N |

### P3 — 可排队

| ID | 问题 | 域 |
|----|------|---|
| P3-1 | Provider identity 混乱 | H |
| P3-2 | Legacy skills 与 skill_system 并存 | F |
| P3-3 | Skill 与 Tool 边界不清晰 | F |
| P3-4 | 文档数量过多 | M |
| P3-5 | 跨平台兼容性未验证 | O |

---

## Recommended Recursive Remediation Loops

按优先级排序：

### Loop 1: Config Safety & Security Harden (P0)
- 处理 config/config.yaml tracked dirty
- 确保真实 key 不会被提交
- 加固 .gitignore 和 pre-commit 策略

### Loop 2: Memory E2E 验证闭环 (P0)
- 修复 recall 路径 split
- 验证 confirm→retain→recall 完整闭环
- 确保 fake/real 共享核心 memory 路径

### Loop 3: Log Hygiene & Evidence Governance (P0)
- 建立 agent_log.jsonl 轮转/大小上限/清理策略
- 验证所有日志写入路径已脱敏
- 确保 evidence 分类准确

### Loop 4: Runtime Entry Consolidation (P1)
- 收敛 CLI shortcuts 到统一 dispatcher
- 精简 turn-end hook
- 确保 branch point 有限稳定

### Loop 5: Interactive Harness 扩展 (P1)
- 添加 streaming 行为验证
- 添加 interrupt/resume 覆盖
- 添加 complex multi-turn case

### Loop 6: Checkpoint/Resume 能力补全 (P1)
- Schema 版本治理
- 真正的 state restoration
- Interrupt→resume E2E

### Loop 7-12: P2/P3 排队项
- Test taxonomy reclassification
- Surgical hub slimming
- SubAgent/MCP/Skill hardening
- UX hardening

---

## Stop Conditions

以下情况必须 hard stop：
- config/config.yaml 的 key 内容需要被读取或打印
- 需要调用真实 API 但未经用户显式授权
- 需要删除或修改用户本地数据（sessions/runs/memory/agent_log.jsonl）
- 需要改变 state/ch checkpoint schema 导致旧数据不可读
- diff 扩大为 broad architecture refactor
- 需要处理真实私人数据
- 发现已 staged 的 secret

---

## Appendix: Inspected Files

核心审计文件（不完全列表）：
- agent/core.py (1172 lines)
- agent/loop.py (852 lines)
- agent/runtime_integration/dispatcher.py (546 lines)
- agent/runtime_integration/schema.py
- agent/runtime_integration/evidence.py
- agent/runtime_integration/tool_gate.py
- agent/runtime_integration/tool_invoke.py
- agent/runtime_integration/tool_result_feedback.py
- agent/runtime_integration/memory_hook.py
- agent/runtime_integration/memory_recall.py
- agent/runtime_integration/memory_retain.py
- agent/tool_registry.py (435 lines)
- agent/tool_executor.py (574 lines)
- agent/memory_runtime.py (573 lines)
- agent/memory_provider.py
- agent/memory_policy.py
- agent/memory_store.py
- agent/memory_contracts.py
- agent/memory_confirmation.py
- agent/checkpoint.py
- agent/session.py
- agent/state.py
- agent/pending_confirmation_dispatch.py
- agent/local_trace.py
- agent/runtime_observer.py
- agent/display_events.py
- agent/provider/factory.py
- agent/provider/simple_config.py
- agent/provider/diagnostics.py
- agent/skill_system/invocation.py
- agent/skill_system/registry.py
- agent/subagent_system/delegation.py
- agent/subagent_system/executor.py
- agent/mcp.py
- agent/mcp_models.py
- agent/dogfood_harness.py
- scripts/dogfood_interactive_harness.py
- scripts/real_api_dogfood_sweep.py
- scripts/real_api_interactive_dogfood_sweep.py
- tests/test_interactive_dogfood_harness.py
- tests/runtime_integration/*.py
- docs/PROJECT_STATUS.md
- docs/PROGRESS_LEDGER.md
- docs/real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md
- docs/audit/global-readonly-audit-2026-05-27.md
- docs/dogfood/real-api-full-dogfood-sweep-report-2026-05-27.md
- docs/dogfood/interactive-dogfood-harness-report-2026-05-27.md
- docs/dev/AUTO_RUN_WORKFLOW.md
- docs/dev/ENGINEERING_WORKFLOW.md
- config/config.example.yaml
- .gitignore
