# Runtime Integration / Runtime Action Harness Implementation Notes

> 本文件记录 implementation-loop 过程中的假设、取舍、偏差和风险。它不是 scope
> creep 的理由；后续独立实现审计应把这里当作审计输入。

## Phase 0 - 只读对齐

### 初始状态

- 仓库路径：`/Users/jinkun.wang/work_space/my-first-agent`
- 分支：`main`
- 起始 HEAD：`6559efe docs(runtime): close runtime integration E2E spec audit`
- 工作区：clean
- tag：`HEAD` 无 tag
- push 状态：`origin/main...HEAD = 0 9`，本地 ahead 9，未 push

### 已读 committed docs

- `README.md`
- `docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`
- `docs/dogfood/E2E_RUNTIME_DOGFOOD_REPORT.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_RFC.zh.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_SDD.zh.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_TDD.zh.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_E2E_DOGFOOD_PLAN.zh.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_IMPLEMENTATION_LOOP.zh.md`
- `docs/runtime-integration/RUNTIME_INTEGRATION_AUDIT_CHECKLIST.zh.md`

### 现有模块边界

- `agent/core.py`：仍是 public `chat()` 入口和主 runtime hub，实际 loop 编排已经下沉到 `agent.loop.run_main_loop`。
- `agent/response_handlers.py`：解析 model stop reason，拥有 tool_use/end_turn/max_tokens 的 state mutation 和 checkpoint 调用。
- `agent/tool_executor.py` / `agent/tool_registry.py`：ToolRegistry 仍是工具 authority；confirmation 与真实工具执行路径已存在。
- `agent/skill_system/registry.py` / `loader.py`：已有 metadata discovery 与 progressive body load，可复用，不需要改 Skill 内部。
- `agent/subagent_system/delegation.py` / `executor.py` / `adjudication.py`：已有 L0 deterministic delegate_once + parent adjudication，可复用，不做 L1/L2。
- `agent/memory_runtime.py` / `memory_policy.py`：已有 deterministic explicit memory policy 与 pending confirmation；实现 turn-end proposal hook 时不得 silent retain 或 auto approve。
- `agent/checkpoint.py`：checkpoint schema 稳定，不能改 schema；safe summary 只能作为 RuntimeAction evidence / payload，不能写新字段。
- `agent/model_call.py` / `agent/provider/streaming.py`：streaming provider abstraction 已存在；unsupported provider 必须 fail closed。
- `scripts/dogfood_e2e_runtime.py`：当前仍大量 direct subsystem invocation，并且 synthetic 模式也会进入 provider preflight；本轮只可在不读取 `.env` 的前提下更新诚实分类和 runtime action evidence 引用。

### 初始假设

- `RuntimeActionDispatcher` 是实例化对象，不作为 module-level global singleton。
- `target_module_proof` 由 dispatcher/context 持有的独立 observer 生成；handler 只能请求 observer 包裹目标模块调用，不能自行 mint proof。
- `RuntimeActionRequest.payload` 代表 model action decision 或 runtime policy input；handler 不从自然语言文本推断缺失的 selection metadata。
- 本轮不调用真实 LLM，不运行 real-api dogfood，不读取 `.env`；真实 `core.chat()` + provider dogfood 只能留给独立授权后的审计/验证。

### 关键取舍

- 为避免把 `action_id` 塞进 model-visible payload，handler 将通过 dispatcher 注入的 execution context 获取 action_id 和 observer。这是对 SDD 伪代码 `handle(request)` 的小偏差，但能更好地保证 proof 不是 handler self-asserted。
- RuntimeActionEvent 只记录 route receipt；`runtime_e2e` 分类统一由 evidence contract helper 判定，防止 event-only 或 `module_invoked=true` 自欺。
- Tool fake overlay 只作为 `ToolGateHandler` 构造参数存在，不写入 production `TOOL_REGISTRY`，不出现在 production capability matrix。

### 初始最小变更面

- 新增 `agent/runtime_integration/`：schema、dispatcher、evidence observer、各子系统 action handler。
- 新增 `tests/runtime_integration/`：按 committed TDD 覆盖 schema、negative evidence、handler paths、capability matrix。
- 最小修改 `agent/core.py` / `agent/tool_executor.py` / `agent/model_call.py`：只在可控 hook point 接入 dispatcher 或 evidence sink；若现有主循环无法安全接入，则保留为 partial 并记录。
- 更新 `scripts/dogfood_e2e_runtime.py` 的 capability matrix / synthetic preflight 行为，避免 synthetic 模式读取 `.env`，并诚实保留未完成 scenario 为 partial/subsystem_integration。

### Stop-condition near misses

- E2E dogfood 文档要求 `core.chat()` + real LLM，但本轮全局禁止真实 LLM 和 `.env` 读取。因此真实 provider dogfood 不在本轮执行；需要通过 runtime action unit/integration evidence 先建立本地可信证据链，最终 real-api E2E 留给授权后的独立 implementation audit。
- `checkpoint.safe_summary` 不能改变 checkpoint schema；如果后续发现必须写入 checkpoint 新字段才能证明 boundary，将停止而不是改 schema。

## Phase 1-5 - 实现过程记录

### Action evidence design decisions

- `RuntimeActionRequest` / `RuntimeActionResult` / `RuntimeActionEvent` 放在
  `agent/runtime_integration/schema.py`，只表达 action 边界，不推进业务 state。
- `RuntimeActionDispatcher` 每次 route 创建 `action_id` 与 `RuntimeActionContext`；
  context 持有 `RuntimeActionModuleObserver`。handler 不能自行生成
  `target_module_proof`，只能通过 `context.observe_module_call()` 包裹目标模块调用。
- `RuntimeActionEvent` 只复制最终 evidence 作为 receipt；`runtime_e2e` 判定集中在
  `agent/runtime_integration/evidence.py`，必须看到 dispatcher routed、handler invoked、
  target module invoked、independent proof、linked action/module、result returned to parent runtime。
- `subagent.delegate_l0` 额外要求 `parent_adjudicated=true`，否则即使有 module proof 也不算
  runtime_e2e。

### 子系统路径映射

- `skill.select` -> `SkillRuntimeActionHandler` -> `SkillLoader.load_body`
- `tool.request` / `tool.gate` / `tool.invoke` -> `ToolGateHandler`
  -> `ToolRegistry.lookup_and_risk_check` 或 `DogfoodFakeToolOverlay.block`
- `memory.turn_end_proposal` / `memory.propose` -> `MemoryTurnEndProposalHandler`
  -> `DeterministicMemoryPolicy.decide`
- `checkpoint.safe_summary` -> `CheckpointSafeSummaryHandler`
  -> `CheckpointSafeSummary.redact`
- `streaming.provider_call` / `streaming.event` -> `StreamingProviderCallHandler`
  -> `collect_stream_response`
- `subagent.delegate_l0` -> `SubAgentDelegateL0Handler` -> `delegate_once`

### Runtime E2E 判定争议

- fake high-risk ToolRegistry overlay 的 target module 是 `DogfoodFakeToolOverlay`，不是
  production `ToolRegistry`。它可以证明 dogfood-local blocked path，但 capability matrix
  不得把 `fake.*` 当作 production real capability。
- Checkpoint 场景本轮证明的是 turn-end / before-save safe summary boundary，不证明旧
  `save_checkpoint/load_checkpoint` direct subsystem path。旧 direct path 保留为历史函数，但
  默认 runner 改走 RuntimeAction boundary。
- Streaming unsupported provider 只产生 `not_supported` / fail-closed evidence，不算
  runtime_e2e；同一 E07 场景另跑 supported branch，只有 supported branch 可升级。
- E01 仍依赖 provider/chat path；在本轮无真实 LLM 授权下保持 partial，不伪造成 runtime_e2e。
- E08 虽覆盖六个 RuntimeAction target，但 Provider/core.chat 未执行，因此场景整体保持 partial；
  capability matrix 可以把各子 capability 标为 runtime_e2e，但不能把 Provider capability 升级。
- `Memory recall/injection` 不是本轮 turn-end proposal hook；matrix 显式保持 not covered，避免被
  `MemoryPolicy` proof 误升级。

### 已升级为 runtime_action 路径的 scenarios

- E02 Skill selection：默认 runner 使用 `RuntimeActionDispatcher→SkillRuntimeActionHandler→SkillLoader`。
- E03 SubAgent L0：默认 runner 使用 `RuntimeActionDispatcher→SubAgentDelegateL0Handler→delegate_once`。
- E04 Memory proposal：默认 runner 使用 turn-end `MemoryTurnEndProposalHandler`，不读真实 episodes，不写 confirmed memory。
- E05 ToolRegistry gate：默认 runner 使用 dogfood-local fake overlay blocked path，不污染 production registry。
- E06 Checkpoint：默认 runner 使用 no-tool turn-end `CheckpointSafeSummaryHandler`，不改 checkpoint schema。
- E07 Streaming：默认 runner 同时覆盖 unsupported fail-closed 与 supported delta/final path。
- E08 Full combined：默认 runner 组合 Skill / SubAgent / Memory / Tool / Checkpoint / Streaming 六个 RuntimeAction。
- E09 Adversarial：默认 runner 通过 fake shell blocked 与 secret-like memory rejected 验证 fail-closed。

### 仍保持 partial / subsystem_integration 的范围

- E01 Runtime planning / Provider call：无真实 provider 授权时只做 deterministic registry baseline；
  capability matrix 中 Runtime planning / Provider call 不能标 runtime_e2e。
- Memory recall/injection：当前 committed docs 主要要求 turn-end proposal hook，本轮未扩展 recall/injection
  runtime action，因此 matrix 保持 not covered 或 partial。

### Deviations and tradeoffs

- `scripts/dogfood_e2e_runtime.py` 保留旧 direct subsystem scenario 函数，但
  `SCENARIO_RUNNERS` 已切到 RuntimeAction 版本。这样避免一次性删除大量历史 dogfood 代码造成审计噪声。
- synthetic dogfood mode 不再调用 `_run_preflight()`，避免读取 `.env`。real-api mode 仍保留原 preflight
  行为，但本轮不运行。
- `contains_secret_like()` 允许 `api_key=[REDACTED]` 等脱敏占位符，否则 checkpoint-safe summary 会因为
  已脱敏标签被误判为泄露。

### Deferred risks

- RuntimeAction 目前是本地 harness 与 dogfood runner 的明确 action path；尚未把真实 `core.chat()` 主循环中
  所有 tool/model/turn-end 边界强制改成 dispatcher path。该整合需要真实 provider dogfood 或更大 runtime loop
  改造，本轮在无 LLM 授权下不扩大。
- Capability matrix 已引用 action evidence，但生产 capability matrix 与 dogfood-local fake overlay 的分离仍需独立审计确认。

## Phase 6 - 验证记录

- `tests/runtime_integration` focused suite：`26 passed`。
- synthetic dogfood 函数级验证：E02/E03/E04/E05/E06/E07/E09 为 runtime_action pass；E08 为 runtime_action partial
  （Provider 未覆盖）；E01 为 direct subsystem partial；`Memory recall/injection` 保持 `not_covered`。
- `git diff --check`：通过。
- `.venv/bin/ruff check agent tests scripts`：通过。
- 默认 HOME 下完整 pytest 失败 3 个既有 memory backend 测试，原因是 sandbox 拒绝写
  `/Users/jinkun.wang/.my-first-agent/memory/_meta/.index.json.lock`。该路径属于真实 home 配置/状态边界，
  本轮未申请提升权限，也未写入真实 home。
- 使用临时 HOME 重跑完整 pytest：
  `HOME=/private/tmp/my-first-agent-pytest-home .venv/bin/python -m pytest -q`
  结果：`2799 passed, 14 skipped`。
