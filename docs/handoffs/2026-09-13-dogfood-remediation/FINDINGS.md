# 复核后的问题清单

优先级：P1 阻碍主要日常任务；P2 可绕行但明显误导/摩擦；P3 扩展验证或次要体验。可信度：**源码确认**指当前结构可直接核对；**历史观察**指上一轮合成实测记录；**待复现**不得先认定根因。

## F1 / P1：拒绝不会立即收束当前执行

历史 J5 连续多次拒绝同一 write approval 后又出现相同 preview；J10/J12/J15 拒绝后也出现替代或重复命令。文件/无关进程未执行，是重要的正向边界证据。

源码：`agent/runtime/state.py:2196` 的 `ResolveApproval` 分支，拒绝时写入 `executed=False/rejected=True`，但在 `:2264` 附近继续置为 RUNNABLE，推进 batch 或 MODEL；`agent/cli/app.py:178` 继续运行统一 loop。这解释了为何一次拒绝仍可能触发后续调用，不代表无限执行已被证明。

W2 修复；关键不是仅改“不要重试”的提示，而是让用户拒绝成为 durable、可测试的收束信号。不要把拒绝当成功，也不要清除已完成的效果。

## F2 / P1：工具之后没有交付用户要的结果

历史 J10 要 Skill 三条文字却请求写文件/echo；J12 要委派两点答案却请求 sleep/Python；J15 要 MCP echo 结果却请求本机 echo。无关操作均被审批拦住。失败的是整条用户任务；Skill body 是否真正激活、MCP/child 是否成功仍待 receipt 证明。

共同嫌疑：意图分类、Goal 完成条件、工具结果投影及控制提示。但不能仅凭三条观察断言“都是 prompt 问题”。

源码入口：

- `main.py:96` 开始的 system policy；`agent/runtime/context.py:678` 的 intent gate / tool exposure。
- `agent/runtime/context_control.py:335`：未完成 Goal 不得用 direct_response 结束；`:351`：ANSWERING 可用只读工具，之后 direct_response。
- `agent/runtime/context_control.py:169`：Goal criterion schema；`agent/runtime/state.py` 的 criterion admission。
- `agent/runtime/evidence.py:1163`：已有 generic exact tool receipt 和 process/native sandbox 分支。**不能断言系统只有进程 receipt，更不能用 echo 伪造其它 capability 完成证据。**

J12 提示明确强制“先建 Goal”，本身会把概念题推入较重流程。新复现应分开测普通用户自然请求与显式委派，不能用不合理提示制造同一种失败。W3 先还原每一步 schema、控制与结果，再决定最小修复。

## F3 / P1：Memory 支持的路径没有被真实模型正确理解

J9 启动显示 ready，但自然记忆请求被模型说成无工具；进入 Goal 后返回 `fact_admission_required`；随后用户先提供完整原文，模型仍要求外部佐证。

源码确认：`agent/runtime/loop.py:3910::_fact_admission_for` 要求 memory content **完整等于一条已有 USER_MESSAGE 的 text**，然后绑定 fact、workspace、Goal/revision；不是任意子串，更不是任意模型总结。`agent/runtime/tools.py:346` 却用含糊的 “Runtime-verified source fact” 描述失败，很容易被理解成客观事实必须外部核实。

“来源是用户明确说过”与“事实已被独立证实”不同。W4 修提示与现有两步路径，保留 exact admission；不要把整句“请记住 X”偷偷截成 X 并声称已满足原合同。owner preference 与 workspace Memory 也不要混为一谈。

## F4 / P2：future artifact 批准提示互相矛盾

源码确认：`agent/runtime/tools.py:499` 仍追加 plain yes disabled / approve-artifact 文案；`agent/cli/render.py:288` 和 `agent/cli/app.py:226` 已支持先 y 批准 effect、延后内容确认。J8 实测两阶段流程成功。

W1 仅消除冲突，不能删除内容确认或把“批准生成”算成“当前文件内容已验收”。

## F5 / P2：取消/完成后如何开新任务不清楚

J4 `/cancel` 后新文本仍围绕旧 Goal；J6 verified_done 后新修改需 `/new`。源码 `agent/cli/actions.py:44::new_session_gate`、`agent/runtime/context.py:680` 明确保留终态 Goal，不继承旧工具权限。这是已有设计，不是 checkpoint 坏了。

W5 先做精确的 `/new` / cancel / recovery 指引；自动新建 Goal 或把普通消息默认当新任务是另一个产品决定，不在本包默认修复里。

## F6 / P2：运行中 Ctrl-C 打印栈

历史 J11 两次在 provider 等待中出现 KeyboardInterrupt traceback。源码 `agent/cli/app.py:114` 只保护 input，`:178` 的 run_turn 不在其中。W5 用可注入中断的测试复现并在合适应用边界处理。

干净退出不等于取消远端推理；EXECUTING/unknown outcome 也不能无条件标成未执行或 cancelled。

## F7 / P1（切模型用户）/ P2（固定配置）：默认偏好存储导致误导性的 Memory profile 报错

历史：同一 state root 切 provider 后，即使新 workspace/未启用 workspace Memory 也报 profile 不匹配。

源码链已确认：`main.py:1160` 总是打开固定 `owner-preferences.json` → `agent/composition.py:533` 按存在与否 load/create → `agent/memory/preferences.py:159` 将 provider trust digest 作为 profile → `agent/memory/store.py:184` mismatch fail closed。

这是防止旧偏好无授权流向新模型的保护，不应称为“污染”然后删库。W6 用全新 fixture 复现，给准确 store 类型和不丢数据的恢复指引；迁移、重绑或为每个 provider 偷建旁路 store 均需另行设计。

## F8 / P2：不存在父目录时失败原因不可理解

历史 J3 读取来源后未写入、workspace_search denied/no_match、最后 no_progress。源码 `agent/tools/path_safety.py:679` 打开父目录而不创建，异常统一成 directory traversal denied；`agent/tools/write.py:10` 使用该边界 prepare。

可以确认“write 当前不会创建缺失父目录”，但**不能确认它就是 J3 检索循环的唯一原因**。W6 分别测 direct prepare 和自然任务。最小修复是安全、准确、一次性说明阻塞；不自动增加 mkdir、放开 symlink 或用 shell 绕过。

## F9 / P2：同一小任务多次外发确认

J2 约三次、J6 四次 remote disclosure 是历史观察。类别变化有真实数据边界意义。位置：`agent/runtime/context.py` 的 data_classes 投影和 `tests/provider/test_remote_disclosure.py` 对应实现。

W7 先用现有 transport audit 和事件计数区分“待确认”“HTTP 调用”“重试”。可以修重复/解释不清的显示；不得直接预批准未来所有类别、workspace 内容或其它目的地。需要改授权粒度时提交独立设计。

## F10 / P2：state root 权限拒绝缺少可行动提示

历史普通 mkdir 得到 0755 时 setup 拒绝。`tests/continuity/test_state_root.py:55` 已锁定 owner-only/no-follow。W6 保持拒绝，说明应使用用户专有、workspace 外的状态目录。只对用户明确选定且核验过 owner/path 的目标给恢复建议，不自动 chmod 既有目录。

## F11 / P2：endpoint 组合/GLM 兼容错误缺乏诊断

历史自定义 base URL + 默认 path 发生 404，显式 request-path 可继续；GLM 纯聊天可用但工具两次 incompatible。没有脱敏 wire 样本，**尚不能判定 GLM 是 JSON schema、control 还是 transport 的哪一项失败**。

`main.py:701::_resolve_runtime_provider`、`agent/provider/profile.py`、`tests/provider/test_provider_profile.py:441`（已有防重复 root /v1 测试）为入口。W6 用离线 endpoint fixture，W7 将 GLM 兼容单列未证实；不要全局更换默认 endpoint、吞掉非法字段、加多协议 fallback 或调用未经批准的 GLM key。

## 不应当作为新缺陷重做

- J6 文件 exact preview、批准后 read-back；J7 stale preview 未直接写入且保留外部改动；J8 process + 当前文件二次确认。这些是正向回归项。
- `/new` 后 Memory create→load、资源 close/reopen：已有修复与测试。
- Browser 缺包、sandbox 被宿主拒绝时 unavailable：是诚实 fail-closed，不能改成静默降级。
- 真实 Browser、TUI 完整交互、declared Skill script 尚未测：**证据缺口，不是已证实功能坏了**。列为 P3/后续专项，不自动安装浏览器、启动登录项或扩展能力。
- 英文提示较多、Working 状态下进展不清、stale 文件未及时解释：次要体验项，可在触及相应 renderer 时小范围处理，不启动全产品国际化或新的遥测体系。

## 对原报告必须应用的勘误

1. “无限重弹、只有 Ctrl-C 能退出”应改为“多次重复观察，操作者选择中断；没有穷尽 /cancel、/exit 或无进展阈值”。现有 no-progress 限制存在，不能声称已证明无限。
2. “MCP effect 成功、child 成功”改为“审批和后续 tool-result 阶段被观察到；未保存足以验证执行成功/内容正确的 receipt”。成功与失败各自都能产生 tool result。
3. “单次几十秒、每个 disclosure 都触发完整模型往返”撤回。30 秒是当时的轮询等待间隔，不能作为模型耗时；data-class 变化也不等于 HTTP 计数。
4. “当前 Memory 等价于不可用”限定为“本轮自然路径未完成”，不是所有确定性路径均失败。
5. “先建 Goal 解决全部 capability”错误：answer-only + 只读 grounding 有既存 ANSWERING 路径；effects 才按实际治理合同走 Goal。
6. “缺父目录就是根因”“自动新建 Goal”“合并预授权”分别是待验证解释和设计建议，不是已批准实现。
7. `/new` 那次未复述上一段，只证明该提示没有显露旧内容；不证明 history 工具永远不能在授权后取回旧材料。
8. TUI 仅启动/退出冒烟，输出有截断；不声称真实模型交互、布局或 CLI/TUI 功能全等。
