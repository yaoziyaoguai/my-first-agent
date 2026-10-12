# 按顺序实施的窄切片

以下是建议执行合同，不是根因已全部确定的补丁设计。每个切片先对当前树复现；证据推翻假设时在 RESULTS 中更正，不为了符合资料包而强改代码。文件范围是候选，实际只改必要项。

## W1：去掉相互冲突的 artifact 批准提示（F4，低风险先完成）

**结果**：用户看到“先批准运行，之后另行确认生成文件当前内容”。不需要输入未来 SHA；高级 `/approve-artifact` 仍按原合同工作。

**范围**：`agent/runtime/tools.py` 的 approval preview；必要时 `agent/cli/render.py`、`agent/tui/render.py`，以及对应测试。不重新实现 S2。

**Red**：生产 prepare 产生的 artifact approval 经 CLI/TUI renderer 后，不能同时包含 “plain yes ... disabled” 与 y 批准生成；不只用手工构造的假 preview 测 renderer。

**Green/验收**：

- 普通 UI 的 y 构造 `defer_artifact_confirmation=True`，仅批准精确 effect；生成前无文件 digest 完成证据。
- `confirm_file` 展示当前内容；另一次 exact approval 才接纳其 digest。
- headless 裸 `ResolveApproval(approved=True)` 未显式选择 defer、也无内容确认时，原有拒绝仍有效。不能通过删除 reducer 约束修文案。
- 并发改动、过期 binding 和仅 process receipt 不足以完成 artifact Goal 的测试仍通过。

先跑：`tests/process/test_artifact_approval_contract.py`、`tests/cli/test_render.py`、`tests/tui/test_render.py`。

## W2：一次拒绝后交还用户控制（F1，P1）

**结果**：输入 n 后，不自动重复批准，不自动执行同一 model batch 剩余工具，不换一个命令继续劝批。保留已完成分析/效果，并告诉用户如何调整、恢复或取消。拒绝当前操作不是自动取消整个 Goal。

**范围**：`agent/runtime/state.py`、`agent/runtime/loop.py`、必要的共享视图/renderer、`tests/kernel/test_runtime_approval.py`、CLI/TUI/headless parity。优先复用现有暂停/返回用户的状态路径；如果必须改变 action/checkpoint schema，先提交窄设计，不加隐藏 flag。

**Red 先写这些行为测试**：

1. ScriptedProvider 提供写入，随后排好重复调用。拒绝后，本次 action 新增 provider 调用数=0、新增 effect 数=0，无相同新 approval。
2. 一个 batch 先成功读/写，第二项被拒绝、第三项尚未执行：既有结果保留，第三项不执行，不谎称整个 batch “全部未执行”。
3. operator invocation 与 model invocation 都有拒绝记录；不要把 operator 输出额外注入不应暴露的模型上下文。
4. checkpoint reload/普通 Resume 不得把拒绝当成批准、自动重放或重新弹同一批准。真正的用户新指令/纠正可重新提出操作，但必须形成当前 exact preview/binding 与新的批准。
5. 被拒绝项没有 lease/grant/完成证据；之前合法 lease 不被全局删除，但不能因此执行剩余 batch。
6. stale request/revision/token 的拒绝仍零副作用冲突，不把拒绝绑定到新请求。

**验收**：真实 root 文件写入一次 n 即回到可决策状态，文件不存在；读到的内容不丢。已有对“被拒绝的 required process”进行只读分析的路径，调整为在用户明确继续后可用，不偷偷调用模型继续执行。本切片的暂停策略须在 RESULTS 中说明。

先跑：`tests/kernel/test_runtime_approval.py`、`tests/cli/test_contextual_decisions.py`、`tests/tui/test_approval_journey.py`。再按实际改动扩展到 process authority/recovery/continuity 测试。

## W3：按真实请求选入口，并消化已有工具结果（F2，P1）

**先定位，不预设只改 prompt**。为每个失败 fixture 记录：自然用户输入、首次 advertised control/tool names、模型选择的 control、admitted criteria 的类型、工具结果 success/error/code、下一轮被投影的结果与允许的终止 control。不记录凭据、真实来源正文或原始私有 state。

**范围**：先看 `main.py` system policy、`agent/runtime/context.py`、`context_control.py`、`state.py` criterion admission、`evidence.py`；只有 adapter 结果确实丢失/错误时才改 Skill/MCP/SubAgent adapter。不要在三种能力里各造一套任务终止逻辑。

**两条路径必须分清**：

- 只需文本并可用既有只读工具 grounding：按现有 intent gate → ANSWERING → direct_response，不建立文件/进程 Goal。
- 明确要求 governed effect（包括某些受治理委派/MCP 调用）：按实际注册的 side-effect、approval 与 Goal/receipt 合同完成，不能因为最终输出是文本就把 effect 降为只读。

**Red/回归矩阵**：

1. 正常概念题直接答；需要 source 的只读题先 begin_answer；外部/Skill 内容不能反向创建 Goal authority。
2. 合成 `release-check` Skill 只要求三个 heading、每项一句：证明先激活了 body，再输出；无 write/local_process 请求。不要只检查 startup ready 或模型“说我用了”。
3. 注入一条成功的 benign MCP echo 结果，parent 输出标记；另测 error/timeout 结果，parent诚实解释，没有 echo 作为替代验证。
4. 注入成功 child 的两点答案，parent 汇总；另测 failed/terminated/unknown child，不能编造完成或启动 sleep/Python。
5. 缺少完成条件或 receipt 时走已有诚实的 clarification/blocked 路径，不用任意 tool result、回答文本或任意 exit 0 铸造完成证据。
6. 无关命令换名、套解释器、改变参数也不能满足明确的进程完成条件；复用已有 exact process authority 测试。
7. 明确要求“写文件并运行测试”的任务仍需 Goal、实际 effect 与 read-back/process evidence，不能被纯文本捷径吸走。

如果发现某 capability **没有可接纳的既有完成证据路径**，输出“已定位的合同缺口 + 最小设计 + 受影响测试”，将该产品闭环标为 BLOCKED，而不是新增通用万能 success predicate。让故障解释更诚实可以通过安全测试，但不能把它算作“用户任务已完成”。

先跑：`tests/continuity/test_entry_routing.py`、`test_goal_controls.py`、`test_verified_done.py`，随后只扩展到触及的 `tests/skill/`、`tests/mcp/`、`tests/subagent/`、provider control tests。

## W4：让 Memory 已有的两步路径可用（F3，P1）

**结果**：模型能分清“启动时已注册但当前阶段没暴露”“能力未配置”“有工具但缺合法 source”。准确说明用户来源而非客观真伪。

**范围**：`main.py` 的必要指导、`agent/runtime/context.py`/`context_control.py` 阶段说明、`agent/runtime/tools.py` 错误说明、`agent/memory/tools.py` 工具描述和相关测试。`_fact_admission_for` 规则默认保持。

**Red/验收**：

- 无 Memory 配置时明确不可用，不承诺已保存或发明一个“Memory 设置页面”。
- 有配置时不得因 bootstrap 没暴露 callable 就说未安装；用 operator-trusted 最小能力信息解释阶段，不提前暴露私有 source/可执行权限。尽量复用现有注册信息，不新建 capability registry。
- 用户先单独说 `本项目的测试代号是 SABLE-27`，再要求把上一条原文记入 workspace Memory：工具提议 content 与完整原文一致，批准后保存并产生可核验来源；拒绝则不保存。
- 用户只说“请记住：本项目的测试代号是 SABLE-27”，若希望保存其中子串，应先澄清/请用户单独提供原文；不虚称已经匹配完整 USER_MESSAGE。
- USER_MESSAGE 原文可作为 owner-provided 项目约定，不额外要求改文件或上网证明；assistant/tool/Skill/history 文本不能冒充当前用户来源。
- `/new` 后在同 workspace 正常重新召回合成约定；跨 workspace/过期 Goal/revision/伪造 fact binding 仍被拒绝。owner preferences 与 workspace Memory 各用原有 scope。

先跑：`tests/memory/test_agent_fact_scope.py`、`test_tools.py`、`test_integration.py`、`tests/cli/test_entrypoint.py` 的 Memory `/new` 用例，以及被改 context 的 tests。

## W5：恢复入口和运行中中断（F5、F6，P2）

**结果**：保留 Goal 生命周期，用户知道终态后用 `/new`；Ctrl-C 不把正常中断显示成崩溃，也不掩盖未知 effect。

**范围**：`agent/cli/app.py`、`actions.py`、`render.py`、`main.py` cleanup 边界；TUI 如受影响使用同源 action/view。不加第二套 CLI state machine。

**Red/验收**：

- cancelled/verified_done 后的提示给出准确一步命令；活跃 Goal、pending approval、EXECUTING/unknown 时不能错误宣传 `/new` 已允许。
- input 阶段中断保持现有正常退出；provider 调用期间注入 KeyboardInterrupt 时无 traceback，返回明确非成功中断结果，并关闭当前资源。
- effect 已进入 EXECUTING、结果尚未 durable 时注入中断：保留未知状态，重启走既有恢复，不自动重放、不伪称零副作用。
- 不声称已经取消远端服务端推理；不因进程中断删 checkpoint、历史或 Memory。
- CLI 与 TUI 可采用不同退出键，但 action/recovery 语义一致。

先跑：`tests/cli/test_contextual_decisions.py`、`test_entrypoint.py`、`tests/continuity/test_restart_selection.py`，以及触及的 recovery/process cleanup 测试。

## W6：三类启动/路径错误说清楚（F7、F8、F10、F11 部分，P2）

分别复现、分别修改，禁止一把 catch-all 降级。

**6a 偏好 provider 绑定**：全新 owner state，用 trust-A 建合成偏好，再以 trust-B 启动另一个 synthetic workspace。报错应说明是 owner preferences 的旧 trust 绑定，而非声称用户配置了 workspace Memory。解释可使用独立的新 state root 或恢复原配置；不自动删旧库/重绑/拷贝数据，且新 provider generate 前零旧偏好外发。`tests/memory/test_owner_preferences.py:194` 的防护必须保留。

**6b 路径与目录**：分别测父目录缺失、存在、symlink、workspace 外、敏感名称。缺失父目录可以在不泄露拒读路径详情的前提下给出具体建议；若不能安全区分，使用诚实但有动作指引的拒绝信息。不能把所有 OSError 都解释成 missing parent。真实 J3 无进展原因须另行诊断；不得为“绿灯”自动 mkdir 或调用 shell。

**6c state root 权限/endpoint**：全新 0755 fixture 拒绝并解释 owner-only；不要自动 chmod 真实目录。离线测试 `base=https://api.deepseek.com` + `request_path=/chat/completions`，以及含版本段的自定义 base+明确 path；通过已有 URL 安全策略后显示最终安全目的地供核对。保留完整 explicit group > saved profile，禁止字段混合、探测多个 endpoint 或启动时顺手联网验证。

候选文件：`main.py`、`agent/composition.py`、`agent/provider/profile.py`、路径错误投影；只在确有歧义的那一层改变异常分类/文案，不修改 MemoryStore trust invariant。

先跑：`tests/cli/test_everyday_entrypoint.py`、`test_entrypoint.py`、`tests/provider/test_provider_profile.py`、`tests/memory/test_owner_preferences.py`、`tests/continuity/test_state_root.py`、`tests/tools/test_file_tools.py`。

## W7：证据和成本收尾，不开新优化轮

- 对 F9 用现有 audit ledger/事件计数测新外发类别和实际调用；能离线证明同一 digest 被重复询问才修 bug。仅嫌弹窗多不构成去掉批准的理由。
- 对 F11 GLM，记录“本次没有此 provider 授权/无脱敏失败样本”即可；不要顺手使用 Pi 凭据。取得样本后先明确 wire 失败类别，再决定是否另开兼容修复。
- 补记 stale 文件原因、语言一致性、等待反馈等体验；小修可随对应 renderer 切片验证，广泛改版列为 P3。
- 按 VERIFICATION 做一次最终候选全量/安装/有预算真实回归。真实 Browser、TUI 全 journey、Skill script 与跨平台宿主仍单列未验证。

最终 RESULTS 必须覆盖 FINDINGS 的 F1–F11：每项写 fixed / reproduced-unfixed / not-reproduced / deferred / blocked，附证据；不能用“全部完成”遮掉 deferred。
