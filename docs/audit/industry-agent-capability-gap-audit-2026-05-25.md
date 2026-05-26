# Industry Agent Capability Gap Audit

审计目标：基于当前代码实现与 active source-of-truth 文档，诚实判断 First Agent 的真实能力版图、行业差距、可继续自动推进的 Big Loop，以及必须等待 manual human dogfood 的决策点。

审计边界：本轮未读取 `.env` 内容，未调用真实 API，未调用真实 LLM，未执行 dogfood，未读取真实 sessions / runs / memory episodes / 私人资料。`docs/archive/` 只作为历史线索，不作为当前事实依据。

事实依据：`README.md`、`docs/README.zh.md`、`docs/00-overview/CURRENT_CAPABILITY_STATUS.zh.md`、`docs/06-audit/CURRENT_AUDIT_STATUS.zh.md`、active audit / plan / dogfood indexes、当前 `agent/`、`main.py`、`scripts/dogfood*`、以及 provider / tool / memory / subagent / streaming / trace / runtime integration / docs source-of-truth 测试。

## A. Executive Verdict

1. 当前 First Agent 是一个 **manual-dogfood-ready local agent runtime prototype**，不是 broad user usable agent。
2. 不是 broad user usable 的主要原因不是单点 bug，而是产品化链路还缺：安装/启动、provider 配置诊断、真实审批 UX、真实记忆召回价值、trace/debug 可读性、sandbox 等级执行与人工体验证据。
3. 当前最大强项是 **provider-neutral runtime + Tool Pipeline + evidence taxonomy**：`core.chat()`、`loop.py`、`RuntimeActionDispatcher`、provider adapter、ToolRegistry 之间已有可测试的本地闭环。
4. 当前最大短板是 **产品 UX 与真实环境证据不足**：很多能力在 fake/local/synthetic 下可验证，但用户在真实 provider、真实任务、真实确认流程中的体验还没有 manual dogfood 结论。
5. 现在并不是真的“只剩 manual human dogfood”。dogfood 是第一优先级之一，但仍有多条无需人工体验即可推进的工程方向。
6. 不用 human dogfood 也能继续做的大方向包括：packaging/startup readiness、provider config diagnostics、provider tool-call normalization contract、dogfood harness 去状态化、trace/run summary polish、docs source-of-truth enforcement、release checklist。
7. 当前不应继续泛化 AutoRun capability loop；可以继续 **dogfood-prep loop / architecture contract loop / packaging loop / cleanup loop**。
8. 若继续 AutoRun，最合适的是先做 startup/provider/package readiness，而不是 SubAgent L1、Memory consolidation、MCP confirmation 或 sandbox 级执行。
9. 当前没有必须立即修 runtime 的 P0。若目标是“下一个真实用户能跑起来”，P1 是 startup/provider diagnostics、install/release readiness、command shortcut second-plane 风险和 dogfood harness statefulness。
10. 下一步最推荐：先执行 manual human dogfood；若必须开自动 Big Loop，则开 **Packaging / install / startup readiness + provider diagnostics**，它对用户成功启动的影响最大，且不需要真实 API。

## B. Current Capability Inventory

| capability | current implementation evidence | user-visible status | fake/local status | real-provider status | test/dogfood evidence | maturity | depth gap | overclaim risk | next action |
|---|---|---|---|---|---|---|---|---|---|
| Basic chat | `main.py` 调 `core.chat()`；`agent/model_call.py` 统一 provider path；FakeProvider 回显 | 可本地交互，但默认 fake | 可用，确定性 | 取决于 env/provider，可加载但当前 active docs 记录真实配置 401 | `test_chat_provider_injection.py`、local checklist | local usable | 返回值与 streaming event 分工不直观 | 把 fake 回显写成真实智能 | 保持，补启动提示与真实模式诊断 |
| startup/provider mode | `main.py` 显式 `load_legacy_dotenv_config()` 后输出 `render_provider_mode_banner()` | 启动可见 fake/real mode | 清晰显示 local only | 能显示 provider/model，但 auth failure 诊断浅 | `TestProviderModeBanner` | dogfood ready | 缺一键 preflight 和修复建议 | 用户误以为配置可用 | 做 provider diagnostics loop |
| FakeProvider | `agent/provider/fake_provider.py` deterministic `create/stream`，不读 env | 适合安全 demo/test | 可用 | 不适用 | FakeProvider safety tests | local usable | 没有真实推理、工具选择只靠规则 | 写成 broadly user-usable | 继续 freeze intelligence |
| real provider loading | `agent/provider/factory.py` 支持 `anthropic_native/compatible`、`openai_native/compatible` | opt-in 可配置 | 不需要 | adapter 已有，真实可用性受 key/model/base_url 影响 | provider contract tests；real smoke opt-in skipped/gated | demo | 配置错误定位弱，真实 provider dogfood 未完成 | 把 adapter pass 写成 real UX pass | 补 diagnostics，不调用真实 API |
| provider tool-call normalization | Anthropic normalize + OpenAI conversion，统一 `ToolUseBlock` | 用户不可见 | 可测试 | adapter 层有骨架 | `test_provider_anthropic_normalize.py`、`test_provider_openai_*` | demo | 缺跨 provider golden fixtures 和 streaming tool_use contract | provider 支持不等于同等质量 | 建 provider normalization contract |
| tool registry / descriptors | `tool_registry.py` 元数据含 risk/capability/output_policy/confirmation/model-visible | 工具可被模型看到 | 可用 | provider 接收 tools 参数 | registry/tool exposure tests | local usable | descriptor 与产品文案仍偏工程 | 低估安全/UX差距 | 保持，补 UX copy |
| tool-use through provider | `model_call.py` 接收 `ToolUseBlock`；`tool_executor.py` 执行 | demo tool 能走确认 | fake 可触发 demo | 真实 provider 取决于模型是否选 tool | BL3/tool pipeline tests；real provider tool-use script gated | demo | 真实模型工具选择不稳定，无人工证据 | 把 fake tool-use 写成真实 tool-use | 真实 dogfood 后再优化 prompt |
| Tool Pipeline | `TOOL_GATE -> TOOL_REQUEST -> TOOL_INVOKE -> TOOL_RESULT` + ToolExecutor | 本地完整可见 | 可用 | provider-neutral dispatcher 可构建 | runtime integration L3 tests | dogfood ready | confirmation copy、失败恢复、结果复用弱 | 认为 pipeline 等于产品级 tool use | 做 tool approval/debug UX loop |
| tool result display | `DisplayEvent.tool_result_visible`、`RuntimeEvent` sink | 能看到工具结果摘要 | 可用 | provider-neutral | dogfood checklist Step 3 | local usable | 结果结构、长输出、错误解释不足 | 工具结果“可见”不等于“好用” | run summary/debug polish |
| tool approval / confirmation | Tool metadata `confirmation`、pending confirmation、`y/n` path | 能确认/拒绝，但交互朴素 | 可用 | provider-neutral | tool confirmation tests | local usable | 文案、风险解释、编辑/拒绝后的恢复弱 | 写成 real human approval UX | human dogfood 必测 |
| tool risk policy / sandbox | high-risk confirmation、path allowlist、shell blacklist、timeout | 有 guardrail，无 sandbox | 本地可阻挡明显风险 | 不随 provider 改变 | shell/file safety tests | demo | 非容器/非权限隔离，shell 仍可执行 | 写成 sandbox-grade | 当前 defer sandbox-grade |
| memory proposal / confirmation | `memory_runtime.evaluate_user_text()` + pending confirmation | 明确 retain/update/forget 可提示 | 可用 | provider-neutral | memory interaction/user-facing tests | local usable | 普通语义提议有限，UX 需人工验证 | 写成智能长期记忆 | 做 recall UX skeleton，semantic defer |
| memory retain/list/forget | `InMemoryMemoryStore`、optional filesystem store、CLI shortcuts | 可保存/列出/忘记 | 可用 | provider-neutral | memory dogfooding/user-facing tests | local usable | direct forget/list shortcut 绕过主 loop，身份/匹配体验待测 | 把局部操作写成完整 memory product | command boundary + memory UX |
| memory recall user value | snapshot 注入 prompt，`memory.injected` event | 用户价值未证明 | 可注入 | 真实 provider 未验证效果 | `test_memory_recall_injection_baseline.py` 等 | demo | 无 semantic retrieval、无 relevance UX | 写成真实 recall | 做非 LLM UX skeleton，等 dogfood |
| memory consolidation | handler/engine/LLM tests 存在，active docs 标为 frozen | 用户不可用 | 局部/测试骨架 | 需要真实 LLM 才有意义 | consolidation tests，但 active 状态 frozen | stub | 产品价值和安全边界未定 | 写成可用 consolidation | 继续 freeze |
| checkpoint save/resume | `checkpoint.py` 本地 JSON、safe summary、resume header | 可恢复 pending 状态 | 可用 | provider-neutral | checkpoint L3 tests | local usable | 非 durable graph，不保证长任务精确恢复 | 写成 durable execution | 保持小范围，补 UX |
| subagent delegation | `subagent_system` L0 deterministic，Parent-owned | 可列出/委托 demo subagents | 可用 | 无真实 child LLM | subagent user-facing/L3 tests | demo | 不是 real multi-agent，planner/adjudication UX 弱 | 写成真实多 Agent | L0 UX 可 polish，L1 defer |
| natural-language subagent fixture | `core.py` 中文/英文触发 demo-stat | 用户可自然触发 demo | 可用 | provider-neutral，但不是真推理 | dogfood checklist Step 7 | demo | fixture-like trigger，覆盖窄 | 写成 NL planning | human dogfood 后决定 |
| skill system | `skill_system` metadata-first loader、progressive disclosure | safe-local 选择骨架 | 局部可用 | provider-neutral | skill tests/dogfood | demo | runtime 默认 registry 接线与产品 UX 不清 | 写成 marketplace/installed skills | 保持 safe-local，补 boundary docs/tests |
| MCP boundary | disabled by default，dry-run/default allowlist/policy | 默认不可见 | 可注册/测试 | opt-in，真实边界未产品化 | MCP L3 / real smoke opt-in | stub | confirmation pipeline、server lifecycle 不成熟 | 写成完整 MCP support | defer MCP confirmation pipeline |
| streaming/progress | provider-neutral `ProviderStreamEvent`，RuntimeEvent delta，L3 tests | 文本能流式展示 | fake streaming 可测 | Anthropic native supports streaming；OpenAI paths fail closed | streaming protocol/L3 tests | demo | tool_use streaming fallback 可能双 call；progress UX 原始 | 写成成熟 streaming UX | 做 contract/UX polish |
| trace/run summary/debug report | `TraceEvent`、`on_trace_event` sink、`run.summary` event | 有摘要，但偏工程 | 可用 | provider-neutral | local trace L3 tests | demo | 无用户 trace viewer，debug report 仍需打磨 | 写成 observability product | trace/report polish |
| command router / CLI shortcuts | `cli_commands.py` typed intents；`core.py` 5 条 early-return shortcuts | 用户便利，但是第二执行平面 | 可用 | provider-neutral | command boundary tests | local usable | shortcut 绕过 main loop/evidence，扩张风险 | 写成统一 command architecture | 建 migration/freeze plan |
| dogfood scripts/reports | checklist executor、global synthetic/real-api runner、provider preflight | 可收集 fake/local 证据 | 11/11 fake/local active docs 记录 | real-api gated，当前 active docs 记录 401 | dogfood boundary/global tests | dogfood ready | 脚本 bespoke、会写报告、状态残留风险 | 把 agent-driven rehearsal 写成人类 dogfood | 去状态化 harness |
| documentation source-of-truth | reset 后 active/historical indexes + 20 tests | 当前文档入口清晰 | 不适用 | 不适用 | `tests/test_docs_source_of_truth.py` | dogfood ready | 新增 audit 若不纳入策略易漂移；archive 污染仍需防 | 把 archive 当当前事实 | 继续 enforcement |
| redaction/security lint | secret-like redaction in events/trace/checkpoint/provider preflight | 多处防泄漏 | 可用 | provider config 报告脱敏 | redaction/security tests | local usable | 非全局信息流证明，真实 private workflows 禁止 | 写成 privacy-complete | 继续 lint，不接私有数据 |
| hook/lifecycle extension | turn-end RuntimeAction hook + display/trace sinks | 有单点 hook | 本地可测 | provider-neutral | runtime integration tests | demo | 不是完整 lifecycle callback system | 写成 Hook system | defer full hook system |
| packaging/install/release readiness | `requirements.txt`、README quickstart；无 `pyproject.toml`/console script | 手工安装 | 可本地跑 | real provider 配置另行设置 | local trial tests | demo | 无 package、无 release flow、无 install diagnostics | 写成可安装产品 | 优先做 readiness loop |

## C. Industry Comparison Matrix

| industry capability | common expectation | First Agent current status | gap severity | depth gap | complexity to improve | should build now | reason |
|---|---|---|---|---|---|---|---|
| Agent loop / runner | 单入口、可恢复、可观测、工具闭环 | `core.chat()` + `run_main_loop()` 已有统一本地入口 | medium | `core.py/loop.py` 过大，UX 未成熟 | medium | yes | 可通过架构 cleanup 和 debug UX 提升 |
| model provider abstraction | 多 provider adapter，错误诊断清晰 | 四类 provider adapter 已有 | medium | auth/config/preflight 与真实错误解释不足 | low | yes | 不需真实 API 也能做 |
| provider tool-call normalization | 各 provider tool schema 与返回统一 | 有 `ToolUseBlock`，但跨 provider fixture 不够 | high | streaming/tool_use、OpenAI/Anthropic 差异未系统冻结 | medium | yes | 合同测试价值高 |
| tool registry / execution | 明确权限、风险、结果 envelope | registry/executor 成熟度较高 | low | UX 和 failure recovery 不够 | medium | yes | 先 polish，不扩能力 |
| tool approval / policy / sandbox | 人类可理解审批 + 隔离执行 | 有 confirmation，无 sandbox-grade isolation | high | 风险解释和真实审批流程不足 | high | partial | approval UX 可以做，sandbox defer |
| handoffs / subagents | 子任务规划、独立执行、父代理裁决 | L0 deterministic demo | high | 无真实 child model / planner / adjudication 产品面 | high | no | human dogfood 前不应做 L1 |
| memory retain/recall | 可控长期记忆、相关性召回、用户管理 | retain/list/forget 可用；recall 只是 snapshot 注入 | high | 无 semantic recall UX 与真实价值证据 | medium | partial | 做 skeleton，不做 consolidation |
| durable execution | 长任务可中断恢复、幂等、状态迁移 | checkpoint JSON + pending resume | medium | 不是 durable graph orchestration | high | no | 当前不需要大架构 |
| streaming/progress UX | 稳定增量、工具/状态进度、错误恢复 | provider-neutral events 已有 | medium | 产品展示和 streaming tool_use contract 未稳 | medium | yes | 可做 contract polish |
| tracing/observability | trace viewer、debug report、run summary | local trace foundation + run.summary | medium | 无 viewer，报告偏工程 | medium | yes | 不需真实 API |
| hooks/lifecycle | before/after model/tool/memory hooks，可扩展 | 主要是 turn-end hook | medium | lifecycle 覆盖不全 | high | no | 当前会过度工程 |
| MCP/external integration | server lifecycle、approval、tool schema、安全边界 | disabled/default dry-run + policy | high | 未产品化 confirmation pipeline | high | no | 外部集成风险高 |
| evals/dogfood evidence | 自动 eval + 人类 dogfood 分级证据 | synthetic/fake/local 强，人类 dogfood 未完成 | high | 缺 manual human evidence | medium | yes | harness 可去状态化，human 另行执行 |
| CLI/onboarding UX | 安装、启动、模式、错误修复路径明确 | README + banner，有 gaps | high | 无 install package，诊断弱 | low | yes | 最适合下个 AutoRun |
| docs/source-of-truth | 当前文档少且可验证，历史隔离 | reset 完成并有测试 | low | 新增审计纳管和持续防漂移 | low | yes | 低风险高收益 |
| packaging/release | package metadata、console command、release checklist | 只有 requirements/manual | high | 无 package/release readiness | medium | yes | 用户试用前必须补 |
| security/privacy | secret redaction、policy、least privilege | 多处 guardrail，非 sandbox | high | real private workflows 禁止，shell/network 仍需人工确认 | high | partial | redaction lint 可做，sandbox defer |
| extension architecture | 新 provider/tool/memory/subagent 边界清晰 | provider/tool 边界较好，memory/subagent/skill 部分骨架 | medium | extension points 多且可能互相挤压 | medium | yes | 做 contract，不扩 surface |

## D. Capability Depth Gaps

| gap name | current evidence | why depth is insufficient | user impact | architecture risk | minimal next loop | ideal future state | safe-to-auto-run | needs real API | needs human dogfood |
|---|---|---|---|---|---|---|---|---|---|
| memory recall | snapshot 注入、`memory.injected`、MemoryRecall handler | 只能注入已有记录，无 semantic retrieval、无“为什么召回”解释 | 用户不知道记忆是否有帮助 | 可能把 retain/list 误认为 memory intelligence | Memory recall UX skeleton：显示来源、范围、匹配原因 | 可审计、可管理、可解释的长期记忆 | yes | no | yes |
| tool approval wording / policy | `tool.confirmation_requested`、registry risk metadata | 文案偏技术，拒绝/编辑/失败恢复路径弱 | 用户难判断是否该批准 | 高风险工具可能被“确认疲劳”吞掉 | Approval copy + risk packet contract | 人类可理解审批卡片 | yes | no | yes |
| run summary / debug UX | `run.summary` event、local trace sink | 内容偏工程计数，缺用户可行动解释 | 出错时用户不知道下一步 | 运行证据存在但不可消费 | Debug report polish | 一页可读 run report | yes | no | yes |
| streaming/progress UX | ProviderStreamEvent + RuntimeEvent delta + streaming L3 | progress state 与 tool/model/memory 阶段展示粗糙；tool_use streaming contract 需冻结 | 用户感知“卡住”或重复输出 | streaming fallback 可能造成真实 provider 双 call 风险 | Streaming/progress contract audit | 稳定增量 + 阶段进度 + fail-closed | yes | no | yes |
| subagent planning UX | L0 deterministic descriptors、CLI/NL demo trigger | 没有真实规划、无多候选、无父代理裁决可视化 | 用户误解为真正多 agent | L0 demo 被过度扩展到 L1 | SubAgent L0 product copy and boundary | 清晰“local deterministic helper” | yes | no | yes |
| provider tool-call normalization | `ToolUseBlock`、Anthropic/OpenAI adapters | 缺 golden fixture matrix、tool input edge cases、streaming tool_request contract | 真实模型工具调用不稳定时难排查 | adapter 差异漏到 runtime | Provider normalization contract loop | provider-neutral normalized blocks with fixture coverage | yes | no | later yes |
| startup/provider mode clarity | startup banner + env config loader | 无完整 preflight、无 auth/config remediation hints | 用户启动后才撞 401 或 silent fake | provider config source 与 runtime import order 易混 | Startup/provider contract hardening | 启动前清楚 fake/real/auth/model/base_url status | yes | no | yes |
| command shortcut boundary | 5 条 typed shortcut allowlist + early return | 仍是第二执行平面，部分绕过 main loop evidence | 行为不一致，测试难解释 | shortcut 继续增长会侵蚀 architecture | Command shortcut migration plan | CLI commands 统一进入 typed command router or adapter | yes | no | yes |
| dogfood scripts statefulness | scripts 会写 workspace/demo、docs/dogfood report | bespoke 脚本多，状态/报告路径不统一 | 复测结果可能受残留影响 | evidence 被脚本副作用污染 | De-stateful harness loop | tmp-root-first, explicit outputs, no active doc overwrite by default | yes | no | no |
| docs source-of-truth hygiene after reset | active/historical indexes + source tests | 新审计和未来 docs 仍可能绕过分类；archive 搜索易误读 | Agent 可能拿旧文档当事实 | source-of-truth reset 逐步腐化 | Docs enforcement loop | 新 active audit 明确纳管，archive contamination lint | yes | no | no |
| packaging/install/release readiness | README quickstart + `requirements.txt` only | 无 package metadata、console script、release checklist、doctor command | 新用户无法稳定安装运行 | 文档说 ready，产品进不去 | Packaging readiness loop | reproducible install + `first-agent doctor` style diagnostics | yes | no | yes |

## E. Missing Capabilities

| capability | classification | blocker | current status | recommendation |
|---|---|---|---|---|
| sandbox-grade tool execution | must-have for general agent | too complex now / security architecture | confirmation + path guard only | defer；不要把当前 shell/file guard 写成 sandbox |
| real human approval UX | must-have for general agent | blocked by human dogfood | terminal `y/n` path | 先 polish copy，再人工验证 |
| durable graph orchestration | nice-to-have / too complex now | architecture decision | checkpoint JSON only | defer；当前不需要 LangGraph-style rewrite |
| multi-agent orchestration | nice-to-have now, must-have only if product chooses multi-agent | product decision + human dogfood | L0 deterministic | freeze at L0 until dogfood |
| full Hook lifecycle system | nice-to-have | extension architecture risk | turn-end hook only | defer；先收敛 RuntimeAction schema |
| MCP confirmation pipeline | nice-to-have | security/product decision | disabled/dry-run boundary | defer；只保留 opt-in tests |
| provider adapter normalization layer | must-have for reliable real provider | no real API needed for contract | partial per adapter | build now with fixtures |
| install/package/release flow | must-have for broad trial | no blocker | missing package metadata | build now |
| eval suite beyond dogfood scripts | must-have before broad release | dogfood taxonomy decision | synthetic/local scripts | build harness consolidation now，human eval later |
| user-facing trace viewer | nice-to-have | UX decision | trace JSONL/sink only | defer full viewer；build readable report now |
| real long-term memory recall UX | must-have for memory product | blocked by human dogfood / real API for semantic | snapshot injection | build deterministic UX skeleton now |
| workspace/session management | must-have for broad agent | product decision | implicit cwd + local files | defer large design；add release checklist item |

## F. What Can Still Be Done Without Human Dogfood?

| priority | name | why it can be done without human dogfood | why it is valuable | scope | out of scope | expected user impact | architecture risk | complexity | tests/gates | safe-to-auto-run | recommended Big Loop prompt type |
|---:|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Packaging / install / startup readiness | 静态文件、README、import、venv、entry command 都可本地验证 | 用户第一步能否跑起来是 broad usability 前置条件 | package metadata or documented install, startup smoke, doctor/preflight spec | 发布到 PyPI、真实 API 调用 | 降低启动失败率 | low-medium | medium | `ruff`, startup/help tests, docs tests | yes | dogfood-prep / packaging loop |
| 2 | Provider auth/config diagnostics | 可用 synthetic env/monkeypatch 覆盖缺 key/model/base_url/401 message shape | 当前真实 provider 卡在配置/认证状态，诊断比重试 API 更有价值 | redacted preflight packet, banner, error remediation hints | 读取 `.env` 内容、调用 API | 用户知道自己在 fake 还是 real，以及缺什么 | low | low | provider contract tests, no-secret tests | yes | UX / architecture contract loop |
| 3 | Provider tool-call normalization contract | 可用 fixture response 覆盖 Anthropic/OpenAI tool blocks | 真实 tool-use 稳定性的底层合同 | golden fixtures, invalid JSON input, name normalization, streaming tool_request rules | 调真实模型、prompt tuning | 减少 provider-specific bug | medium | medium | provider adapter tests, runtime tool pipeline tests | yes | architecture loop |
| 4 | Startup/provider mode contract hardening | banner/help/import order 都可纯本地测 | 防止用户误处于 fake 或 broken real mode | help text, mode labels, config source rules | real provider reachability | 减少 overclaim 和误操作 | low | low | provider banner tests, help snapshot tests | yes | dogfood-prep loop |
| 5 | Docs source-of-truth enforcement after archive | 可静态测试 active/historical 分类 | 防止 reset 后再次漂移 | source-of-truth lint, archive contamination tests, index policy | 重写 archived docs | 降低 agent-context 污染 | low | low | docs source tests | yes | cleanup loop |
| 6 | Dogfood script consolidation / de-stateful harness | 可改脚本默认 tmp-root、显式 output，不需人工体验 | 证据可信度提升 | consolidate runner options, avoid active report overwrite by default, cleanup workspace/demo | 执行 dogfood、真实 API | 复测更可靠 | medium | medium | dogfood boundary tests, no real IO tests | yes | eval/dogfood loop |
| 7 | Trace/run summary report polish | 基于 RuntimeEvent/TraceEvent fixture 可测试 | 让失败可诊断，减少人工试用成本 | readable report schema, event grouping, safe preview | trace viewer UI | 用户能看懂发生了什么 | low-medium | medium | trace/run summary tests | yes | UX loop |
| 8 | Memory recall UX skeleton without semantic LLM | 可用 deterministic store/snapshot 测来源、匹配、管理文案 | 让 memory 不再只是隐藏 prompt 注入 | list recalled items, source/reason, forget affordance text | embeddings/semantic retrieval/consolidation | 用户理解记忆影响 | medium | medium | memory user-facing tests | yes | UX / capability loop |
| 9 | Command shortcut migration plan / typed command boundary | 可静态分析和 characterization 测试 | 防止第二执行平面继续膨胀 | freeze allowlist, route mapping spec, migration doc/tests | 大改 CLI runtime | 行为更一致 | medium | low-medium | command boundary tests | yes | architecture cleanup loop |
| 10 | Release readiness checklist | 可基于当前 docs/code 静态生成 | 明确从 local prototype 到 release 缺口 | checklist, gates, labels | 发布、tag | 决策更清楚 | low | low | docs tests | yes | cleanup / release-readiness loop |

## G. What Must Wait for Human Dogfood?

| item | why code analysis is insufficient | what human should observe | how to record feedback | likely remediation loop |
|---|---|---|---|---|
| onboarding comprehension | 代码能验证 help 存在，不能验证用户是否理解 fake/real/current stage | 第一次启动是否知道在什么模式、能做什么、不能做什么 | `docs/dogfood/manual-human-dogfood-record-template.md` 逐步记录 | startup/help UX loop |
| approval trust | tests 能证明会弹确认，不能证明用户是否敢批准/知道风险 | 工具确认文案、风险说明、拒绝后恢复 | 记录每次犹豫、误解、误批准 | tool approval UX loop |
| memory value | 代码能保存/注入，不能证明用户觉得“有用而非打扰” | retain/list/forget/recall 是否符合心智模型 | 记录用户期望、误召回、想编辑的内容 | memory UX loop |
| run summary usefulness | tests 能捕获 event，不能证明 summary 能帮助排错 | 用户能否看懂每轮做了什么 | 记录无法解释的 summary 字段 | debug report polish |
| subagent mental model | L0 demo 可运行，但用户是否误以为是真多 agent 未知 | 用户如何理解 delegate/result/adjudication | 记录误解和期望任务类型 | subagent L0 boundary polish or defer L1 |
| real provider conversational quality | 真实 LLM 行为依赖 key/model/base_url/prompt，不可静态推断 | 普通问答、工具选择、错误恢复 | 记录 provider、model、prompt、事件，不记录 secret | provider prompt/tool-use loop |
| tool result visibility | 能显示结果不代表用户能用结果继续任务 | 结果是否足够、是否太长、是否缺下一步 | 记录每个工具结果的可用性 | tool result envelope/report loop |
| error recovery | 静态 tests 覆盖已知错误，真实操作会产生新失败 | 401、工具拒绝、文件权限、超时后的下一步 | 记录错误消息与用户动作 | diagnostics loop |

## H. What Should Stay Frozen / Deferred?

| item | freeze/defer reason |
|---|---|
| FakeProvider intelligence | FakeProvider 的价值是 deterministic、安全、可测；让它“更聪明”会污染证据，制造 fake capability overclaim。 |
| Memory consolidation | active docs 已标记 frozen；没有 manual dogfood 和真实长期记忆需求前，自动 consolidation 容易误写、误删、过度工程。 |
| SubAgent L1 | L0 仍是 deterministic demo；进入 L1 需要真实 planner、上下文打包、人类期望和父代理裁决证据。 |
| Hook full system | 当前 RuntimeAction schema 已经很宽；完整 lifecycle hooks 会增加 extension overload 和调试难度。 |
| MCP confirmation pipeline | MCP 是外部 trust boundary；没有产品化 approval UX 和 sandbox 前，不应扩成真实 pipeline。 |
| sandbox-grade execution | 需要 OS/container/worktree/permission 设计，不是当前 cleanup/dogfood 阶段应临时补的能力。 |
| RAG/embedding/plugin marketplace | 会引入存储、隐私、召回质量、安装安全等新面，当前与 dogfood readiness 不对齐。 |
| broad core/loop rewrite | `core.py/loop.py` 确实大，但广泛重写会破坏现有证据链；应小切片收敛。 |
| real private data workflows | 当前明确禁止读取真实 sessions/runs/memory episodes/private data；没有隐私方案前不能开展。 |

## I. Architecture and Code Quality Risks

| risk | evidence | why it matters | recommendation |
|---|---|---|---|
| `core.py` / `loop.py` / `evidence.py` size | `core.py` 1172 lines, `loop.py` 815 lines, `evidence.py` 1422 lines | 它们是 runtime 关键路径，读者很难判断行为边界 | 不做大 rewrite；按 command boundary、run summary、provider mode 小切片抽离 |
| command shortcut second-plane risk | `core.py` early-return 5 条 CLI shortcut，`cli_commands.py` allowlist 测试 | shortcut 绕过主 loop，容易形成第二套 runtime | 冻结 allowlist，制定迁移计划 |
| provider startup order | `main.py` legacy dotenv load；`core_contexts` lazy provider factory；module-level provider/client 兼容遗留 | 配置来源混用会导致 fake/real 误判或 stale config 疑虑 | 做 startup/provider contract hardening |
| dogfood scripts bespoke/stateful risk | checklist executor 写 `workspace/demo`，global runner 可写 docs/dogfood report | 重跑可能受残留影响，也可能把 synthetic 证据误当人类证据 | tmp-root-first，报告输出显式化，active docs 不自动覆盖 |
| tests taxonomy / E2E evidence honesty | runtime integration 区分 `real_core_loop_runtime_e2e` 和 `harness_runtime_e2e` | 这是强项，但命名和解释仍需持续守护 | 保持 evidence classifier，新增 audit docs 不得 overclaim |
| docs source-of-truth after reset | active/historical tests 已有 20 个 | reset 完成不是永久状态，新文档容易绕过索引 | 增加新 active audit 纳管策略或明确独立审计路径 |
| archived docs contamination risk | 大量历史 docs 仍可被 `rg` 搜到 | Agent 容易把 archive 旧能力当当前事实 | 在 docs lint / prompt 中继续强调 archive 非事实源 |
| runtime action schema growth risk | turn-end hook dispatch memory/tool/checkpoint/skill/subagent/streaming/trace 多类动作 | schema 继续增长会让 loop 成为万能总线 | 收敛 action types，建立 extension admission criteria |
| extension point overload risk | provider/tool/memory/skill/subagent/MCP/trace 都有扩展点 | 每个扩展点都局部合理，但组合复杂度高 | 新能力必须先证明用户价值或 dogfood blocker |

## J. Recommended Next Big Loops

| priority | name | category | why now | expected outcome | scope | out of scope | implementation complexity | risk level | requires human dogfood | requires real API | safe-to-auto-run | required docs/spec/tests | gates | stop conditions |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Packaging / Install / Startup Readiness | packaging | 用户能否启动是所有 dogfood 前置条件 | 清晰可重复的 install/start/help/doctor path | package metadata or install spec, startup smoke, README alignment | PyPI release, real API call | medium | medium | no | no | yes | getting-started docs, local trial tests | help/startup tests pass; docs tests pass | 需要外部发布凭据或真实 API 时停止 |
| 2 | Provider Auth/Config Diagnostics | UX | active docs 记录 real provider 401，下一步不是盲测 API，而是诊断 | redacted preflight + actionable error messages | missing key/model/base_url/auth scheme diagnostics | reading `.env` content, calling provider | low | low | no | no | yes | provider diagnostics spec/tests | no secret output; provider tests pass | 需要真实 key 才能判断 reachability 时停止 |
| 3 | Provider Tool-Call Normalization Contract | architecture | tool-use 是行业 Agent 核心，当前 adapter 深度不足 | cross-provider fixture matrix | normalize Anthropic/OpenAI tool blocks, invalid JSON, short-name matching | prompt tuning, real model behavior | medium | medium | no | no | yes | provider contract tests | fixture matrix pass | 发现需真实 provider behavior 才能判定时停止 |
| 4 | Dogfood Harness De-Stateful Consolidation | eval/dogfood | 当前证据可信但脚本 bespoke/stateful | tmp-root-first runner and report discipline | checklist/global scripts output isolation | executing manual dogfood | medium | medium | no | no | yes | dogfood boundary tests | no real sessions/runs; no active report overwrite by default | 需要人类观察时停止 |
| 5 | Trace / Run Summary Debug Report Polish | UX | 人类 dogfood 前需要可读 debug evidence | readable per-turn report | event grouping, failure reason, safe previews | trace viewer UI | medium | low-medium | no | no | yes | trace/run summary tests | no secret leaks; report stable | 需要视觉/product design 选择时停止 |
| 6 | Memory Recall UX Skeleton | capability | memory 已有 retain/list/forget，但 recall 价值不透明 | deterministic recalled-memory panel/copy | source/reason display, forget affordance | embeddings, consolidation, automatic semantic recall | medium | medium | no for skeleton; yes for value | no | yes | memory user-facing tests | no silent retain; no secret recall | 需要判断“好不好用”时停止 |
| 7 | Command Shortcut Boundary Migration Plan | architecture | shortcut 第二平面是长期架构风险 | frozen allowlist + migration spec/test | typed command boundary, no new shortcuts | runtime rewrite | low-medium | medium | no | no | yes | command boundary tests/docs | allowlist unchanged; no behavior regressions | 触及 broad core rewrite 时停止 |
| 8 | Docs Source-of-Truth Enforcement v2 | cleanup | reset 后必须防复发 | active/historical/audit classification stronger | tests for active docs, archive contamination rules | rewriting archive | low | low | no | no | yes | docs source tests | focused docs suite pass | 需要改变 source-of-truth policy 时停止 |
| 9 | Security/Redaction/Private Artifact Guard Audit | security | 日志/trace/checkpoint体量大，隐私边界重要 | stronger no-secret/no-private-artifact checks | static lint and fixture tests | reading real private files | medium | medium | no | no | yes | security lint tests | no real private reads | 需要实际 private workflow 时停止 |
| 10 | Manual Human Dogfood Round | eval/dogfood | 代码分析不能替代真实体验 | human evidence for UX/product gaps | checklist execution by human | automatic capability expansion | low | medium | yes | optional | no | dogfood record template | feedback recorded; no overclaim | 人类无法执行或 config unsafe 时停止 |

## K. Big Loop Execution Plan

### 1. Can start now without human dogfood

1. Packaging / Install / Startup Readiness
2. Provider Auth/Config Diagnostics
3. Provider Tool-Call Normalization Contract
4. Dogfood Harness De-Stateful Consolidation
5. Trace / Run Summary Debug Report Polish
6. Docs Source-of-Truth Enforcement v2
7. Command Shortcut Boundary Migration Plan
8. Memory Recall UX Skeleton
9. Security/Redaction/Private Artifact Guard Audit
10. Release Readiness Checklist

建议顺序：先做 1 和 2，因为它们直接降低 human dogfood 启动失败率；再做 3 和 4，提高真实 provider/tool 与证据可信度；然后做 5、6、7 这些降低维护风险的 polish；最后再做 8、9、10。

### 2. Should wait for human dogfood

1. Tool approval final wording and approval flow decisions
2. Memory recall product value and semantic recall direction
3. SubAgent L0 是否值得推进到 L1
4. Real provider prompt/tool-use tuning
5. Run summary fields 是否对用户有帮助
6. CLI onboarding final copy and command discoverability

这些项都需要观察真实用户行为。代码分析能指出风险，但不能决定最终 UX。

### 3. Deferred / do not start

1. FakeProvider intelligence
2. Memory consolidation
3. SubAgent L1/L2+
4. Full Hook lifecycle system
5. MCP confirmation pipeline
6. Sandbox-grade execution
7. RAG/embedding/plugin marketplace
8. Broad `core.py` / `loop.py` rewrite
9. Real private data workflows

这些项要么复杂度高，要么依赖真实用户价值判断，要么会扩大安全面。当前阶段启动它们会掩盖 manual dogfood 的核心问题。

## L. Final Recommendation

1. 所有能力没有补齐。当前是本地可测 runtime prototype，不是完整 industry-grade agent。
2. 也不是真的只剩 dogfood。manual human dogfood 很重要，但 packaging、provider diagnostics、normalization contract、dogfood harness、trace/report、docs enforcement 都可以继续自动推进。
3. 可通过代码分析继续推进的主要方向是：安装/启动、provider 配置诊断、provider tool-call normalization、source-of-truth enforcement、dogfood harness 去状态化、debug report、memory recall UX skeleton、command shortcut boundary。
4. 继续推进 SubAgent L1、Memory consolidation、MCP pipeline、sandbox-grade execution、RAG/embedding、full hooks、broad loop rewrite 会导致过度工程。
5. 下一条最好给 Coding Agent 的 prompt 类型是 **dogfood-prep / packaging readiness loop**，而不是 broad capability loop。
6. 建议可以马上开下一个 AutoRun Big Loop，但只限低风险 readiness/architecture contract，不要开新能力扩张。
7. 如果开，最应该开 **Packaging / Install / Startup Readiness + Provider Auth/Config Diagnostics**。它不需要真实 API，不需要 human dogfood，也最能提升下一次人工试用成功率。
8. 如果不开，理由应是先让人类完成 manual dogfood，以免继续自动 polish 掩盖真实体验问题；但这不是因为代码层面已无事可做。
