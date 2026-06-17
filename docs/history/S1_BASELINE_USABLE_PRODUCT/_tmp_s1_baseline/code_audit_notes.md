# Code audit notes (S1 baseline) — read-only

中间产物。第一手只读审计事实，带 file:line。最终结论以此为证据写入 S1_GOAL_GAP.md。

审计路径（实际已读 / 已核验）：
main.py, agent/core.py, agent/core_contexts.py, agent/loop.py,
agent/provider/{factory,protocol,legacy_adapter,fake_provider,simple_config}.py,
agent/model_call.py, agent/runtime_integration/{dispatcher,phase1_hook,tool_gate,tool_result_feedback}.py,
agent/tool_registry.py, agent/tool_runtime_mediator.py, agent/tool_executor.py, agent/tools/*,
agent/{state,transitions,task_runtime,planner,plan_schema}.py, agent/tools/meta.py,
agent/{memory.py, memory_runtime.py, memory_fs_store.py, context.py, conversation_events.py},
agent/{checkpoint,session}.py, agent/{evidence_recorder,event_log,logger,local_trace,evidence_persistence}.py,
agent/action_scheduler.py, agent/mcp_*.py, agent/subagent_*.py + agent/subagent_system/*,
config.py, config/, README.md, tests/golden_e2e/*, tests/runtime_integration/*。

## L1 Runtime Spine
- 入口单一：main.py:637 main() -> main_loop():335 -> _run_chat_for_backend():195 -> core.chat():763。
- provider 边界薄：protocol.py:77 ModelProvider(create/stream + provider_type/supports_tools/supports_streaming)。
- 单工厂：factory.py:18 build_model_provider()，:36 build_model_provider_from_env()（默认 fake，:90）。
- same-spine 证据：factory.py:44-45 注释；loop.py:249/690「loop 不读 provider_type」；core.py:1158-1159 RT-01「fake/real 共享同一 evidence path」。
- legacy planning client：core.py:171 `_model_provider, client = build_default_model_client()`；client=ProviderBackedClient(legacy_adapter.py:58)，messages.create 转发到同一 provider.create(legacy_adapter.py:29-54)；planning 调用点 core.py:1369。
- 主执行模型调用：model_call.py:66 stream / 83,92 create。
- 旁路（非 fake/real 分叉）：CLI meta-command 提前 return（core.py:852-869，自述非第二 runtime）；agent/local_demo.py:74 独立 demo FakeProvider。

## L2 Context / Memory / State / Checkpoint
- memory：默认 InMemory（core.py:179 create_memory_runtime）；recall core.py:1065（MEMORY_RECALL via dispatcher）；inline retain core.py:961 evaluate_user_text；turn-end 提案/consolidate loop.py:285-435；fs store memory_fs_store.py:59（MEMORY_STORE_ROOT/MEMORY_ROOT，默认不激活）。
- 压缩：active 实现 agent/memory.py:220 compress_history；_find_safe_split_index 保证 tool_use/tool_result 配对，无安全切点则放弃压缩（memory.py:261-263）；core.py:1221 调用，awaiting_tool_confirmation 时不压缩（core.py:1057-1060）。
- 并存风险：agent/context.py:36 另一个 compress_history（recent=messages[-6:]，无配对守卫）；core.py 不 import 它，主路径不走；其他入口可达性 unknown。
- state：TaskState(state.py:192)；KNOWN_TASK_STATUSES(state.py:13)。
- checkpoint：save 关键转移点 core.py:1005/1322/1641/1707；turn-end save 默认关 loop.py:732；写盘 checkpoint.py:403-463；resume session.py:405（main.py:731 无条件）；持久化全量 task state(checkpoint.py:324)。
- 大结果摘要：evidence_persistence.py summarize（>2048B tool_result 变 summary dict，content_persisted=false）；resume 后 API 形态未验证（unknown）。

## L3 Tools / Policy / Evidence
- registry：tool_registry.py:43 TOOL_REGISTRY，:142 register_tool，:205 get_model_visible_tools（max_total=30,max_mcp=5），:399 execute_tool，:424 needs_tool_confirmation。
- 中介执行：tool_runtime_mediator.py:225 mediate -> tool_executor.py:204 execute_single_tool -> tool_registry.execute_tool。
- TOOL_INVOKE dispatcher 只记 evidence、不执行（README 第 11 行 + tool_runtime_mediator P1-2 修复）。
- policy gate：tool_gate.py:32 ToolGateHandler（两 provider 模式一致）；禁用 bash/shell（tool_gate.py）；MCP 工具默认 confirmation=always/high(mcp_policy.py:50-76)。
- tool result -> context：conversation_events.py:116 append_tool_result（role=user, tool_result block, 全量 content），tool_executor.py:546/680 无条件追加；tool_execution_log 留副本。
- evidence：logger.py:150 -> agent_log.jsonl；event_log.py:153 EventLogWriter -> sessions/<id>/events.jsonl；evidence_recorder.py:728 record_evidence（含 provider_type）。仅 safe_summary + result_size，不存模型/工具正文（content_persisted=false）。
- 小缺口：execute_pending_tool 未设 turn_context -> mediator _route_result:1263 对 pending tool 的 events.jsonl tool_output=""。

## L4 Task Orchestration / State Machine / Progress
- legacy Plan 路径 active：planner.py:240 generate_plan / plan_schema.py PlanStep；step 完成 tools/meta.py:45 mark_step_complete（completion_score）；阈值 config.py:208 STEP_COMPLETION_THRESHOLD=80；is_current_step_completed task_runtime.py:48；advance_current_step_if_needed transitions.py:639。
- ActionPlan/Scheduler 路径 seam-only/dormant：planner.py:325 generate_action_plan；scheduler 注入 loop.py:728(None)/1007-1028；main.py 0 引用；test_scheduler_boundary_l2 钉死。
- 进度持久化=checkpoint 快照（current_plan + current_step_index + tool_execution_log）；无独立 durable task ledger；SchedulerState.completed_nodes 仅内存。

## L5 Extension Boundary
- Scheduler：dormant（action_scheduler.py 文件级注释 dormant-by-default；main.py 0 引用）。
- MCP：configurable 默认关（main.py:587-589 MY_FIRST_AGENT_MCP_ENABLE；dry-run 默认开）；bridge mcp_bridge.py:146；policy mcp_policy.py:127。
- SubAgent：V0 configurable 默认关（subagent_routing_flag.py:29），默认走 local_fake stub（subagent_system/executor.py:12/26）；L0 注册(phase1_hook.py:170-173)；L1/L2 frozen 不注册(phase1_hook.py:183-187)；V0 wiring 源码注明未完成；README:14 subagent_action.py + v0_contract.py。
- Skill：skill_system/ + runtime_integration/skill_lifecycle.py；SKILL_SELECT 在 loop.py:467-567；README:46 称 skill system 实验性。

## Cross-cutting
- config/config.yaml 被 git 跟踪且含 api_key/sk- 字段；.gitignore 仅忽略 .env、config/config.local.yaml（未忽略 config.yaml）。README:32/71 自述「含真实 key 不得 commit」「不提交 config/config.yaml」—— 与现实矛盾。（本轮不处理密钥，仅记录。）
- README:5/52-56 文档导航指向 docs/PROJECT_STATUS.md、docs/00-overview/...、docs/README.zh.md、docs/dev/...、docs/06-audit/README.md —— 这些已在本会话移入 docs/history/，导航失效。README:9 自述「developer prototype，不是面向普通用户的产品」。
- 命名：代码含 v0.x / Phase / Loop N / B7 等命名；S 系列需与之显式区隔。

## Tests
- 像 S1 acceptance（驱动完整 core.chat 全链路）：tests/golden_e2e/*（test_golden_simple_conversation.py 用 FakeProvider 跑全链路；test_golden_tool_success / _memory_checkpoint / _policy_evidence / _subagent_delegation / _skill_l3_core_loop）；tests/runtime_integration/test_phase1_real_core_loop.py、test_mcp_l3_real_core_loop.py；tests/smoke/test_first_usable_task_e2e.py。
- 像 real smoke（需 key/网络）：test_provider_real_smoke.py、test_real_mcp_flight.py、runtime_integration/test_mcp_real_external_flight.py。
- 像 seam/harness（不可当主链路证据）：直接 dispatcher.route 的 seam 测试、test_b7_*、test_architecture_boundaries.py（含 scheduler dormancy 守卫）、test_legacy_path_inventory.py。
