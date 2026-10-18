# First Agent：执行后产品复审（2026-10-17）

状态：Codex 独立源码/离线复审与 Oracle Web 5/5 交叉审计均已完成。
结论是“仍有确定首发阻断”，不是“本轮缺陷已修复”。Oracle 于北京时间 2026-10-17 23:27:55
完成；全新会话的完整答案已保存，exact 临时 Chrome/Profile 清理已确认。

## 1. 结论

它已经是一个有实际执行、持久状态和治理边界的 Agent 内核，不是只有聊天界面的演示。
但当前仍是 **macOS、单用户、CLI 优先的本地候选版本**，不是可以无保留向普通用户公开承诺的稳定产品。
这次没有理由推倒重做；也没有理由因为 3947 个测试通过就宣布日用可靠性已经完全闭合。

- 开发者自用：可以，在隔离项目中、保留人工验收，接受已知限制。
- 对不知情用户宣布“可信自动完成”的邀请 beta：先修本报告 F1/F2/F3，并闭合最小交付证据。
- 面向普通用户公开首发：上述修复之后，还需一个当前安装物上的有限真实用户旅程和一致的支持说明。
- 未做市场/用户访谈，不能从代码审计推断“不会有人用”或“有产品市场匹配”。

本次没有修改产品实现，没有 commit/push/tag、没有改登录项、没有调用产品真实 API。
只新增本目录审计材料和合成离线探针。用户原有 17 个 tracked dirty 文件、旧执行包和未知未跟踪
`result.phase.json` 均保留；后者未读取。HEAD 仍是 `0cc0db1ddbf6d2e9c9526e9588d66e80831b6640`。

## 2. 上轮到底做成了什么

| 项目 | 本次裁决 | 理由 |
| --- | --- | --- |
| W1 明确文件完成下界 | 部分完成，仍有发布阻断 | 原样 D04 反例会被挡住；但删一个中文空格即重新假完成，输入/引用还会被误加为交付物 |
| W2 散文目标的精确授权复用 | 保留，相关本地门通过 | 复用了已有 admitted 文件路径，普通 y 不变成全局授权，范围/次数/期限边界没有被删掉 |
| W3 无催促验收 driver | 主体完成，判定还有缺口 | normal 不注入 correction，不自动“继续”/救场；七键检查已加强。但 staged 仍允许 state revision 冒充 Goal revision |
| 恢复挂起的外发确认 | 正向路径修复，负向与 TUI 不完整 | yes 可以点燃恢复；no 被当作任务纠正，TUI 不显示这类孤儿请求 |
| G 源码门 | 本次独立复跑通过 | 3947 passed、1 skipped，exit 0；不是复制实施者数字 |
| G installed / real | 有较新的实施记录，本次未独立复验 | r3 安装58节点与两个真实样本是上一执行者公开自报；本次未读私有原始日志、未调用 API |
| Git / 发布 | 未交付 | 最新修复还在 main 的未提交工作树中；当前候选不能等同于远端 main / 已发布安装物 |

应保留已有的唯一 Runtime、上下文所有权、精确权限、checkpoint/CAS、
UNKNOWN 不重放、证据 freshness、原文保留、bounded run/transport budgets。
这些不是需要重建的能力。

## 3. 已确认问题

### F1 — P1：正常中文写法仍能“漏做却完成”

位置：
[路径 token](../../../agent/runtime/state.py:260)、
[完成门](../../../agent/runtime/state.py:1928)。

仅把原用户输入中的：

```text
命令行适配器 retry_app/cli.py 必须使用同一个值
```

改成：

```text
命令行适配器retry_app/cli.py 必须使用同一个值
```

其余 provider 脚本、业务要求、工具与审批流程都不变。
provider 只修改 service，给非空泛化 coverage，然后停止：

| 输入 | 产品终态 | CLI 文件 | 独立 CLI 业务检查 |
| --- | --- | --- | --- |
| 有空格 | goal_ready，拒绝假完成 | 未修改 | false |
| 无空格 | VERIFIED_DONE | 未修改 | false |

这不是要求识别“任意自然语言”。两个输入都是直接、明确、同义的文件要求。
`(?<![/\\w.])` 中的 Unicode word 边界把相邻汉字也当成排除条件，导致整个交付文件下界消失。

影响：用户可能信任“已验收”提示而拿到漏做的结果。
当前 README/日用指南关于“原文点名的文件缺一个都不会完成”的无条件表述超过实际能力。

### F2 — P1：识别器会凭空增加义务，阻止正常收尾

位置：
[分句后才消除引文](../../../agent/runtime/state.py:502)、
[路径与参考判定](../../../agent/runtime/state.py:510)。

已确认：

- `Update Python to 3.12` → 把 `3.12` 当成必须交付的文件。
- `Implement SPEC.md requirements` → 把输入规格 `SPEC.md` 当成交付文件。
- `解释“创建 app/example.py；修改 app/other.py”的含义，不要修改任何文件。`
  → 提取出两个示例文件。
- 日志中的“创建 app/old.py”也会成为交付义务。

完整 Runtime 对照：目标 service 已正确，用现有 confirm_file 获得合法当前内容证据，
另附跨分句引文仅供解释；完成门仍点名要求 `app/example.py, app/other.py`，最终停在 goal_ready。
目标文件没有额外改写，也没有绕过审批。问题是无关对象强制准入造成的卡住/误导，不是已证明的越权写入。

修复应是一个有明确范围的“交付对象来源分类”切片，同时解决 F1 与 F2；
不能通过直接删掉完成门、强制让模型重写所有文件、扩大权限来通过测试。

### F3 — P1（CLI）/ P2（可选 TUI）：恢复后拒绝外发被当成新任务

位置：
[CLI 孤儿请求正向解析](../../../agent/cli/app.py:234)、
[拒绝分支仍要求 active run](../../../agent/cli/app.py:540)、
[TUI active=None 分支](../../../agent/tui/render.py:117)。

通过真实 Runtime 的 SubmitMessage → PauseGoal → ResumeGoal 到达：
request 有值、receipt=None、active_run=None、goal=GOAL_READY。

- CLI 提示 `Allow this information to be sent? [y/N]`。
- `y` → AcknowledgeProviderDisclosure，正向恢复修了。
- `n/no/否` → SubmitMessage；真实 Runtime 新增 `control=goal_correction,text=no`，
  又停在 awaiting_disclosure。
- 同状态 TUI 显示“goal resumed/ready”，没有 disclosure form 和 ack_provider 操作。
- Oracle 补充、Codex 实测确认：提示为 `[y/N]`，但空回车在 `app.py:155` 被直接略过。
  合成 REPL 中空回车后再次显示同一个提示（2 次 pending prompt），没有默认拒绝消息；
  这是提示与行为不一致，不是默认放行。

离线 probe 中 provider calls=0；**没有证据表明发生未同意外发**。
确认的缺陷是拒绝失效、污染任务意图，以及同一 durable 决定在不同界面行为不一致。

最小修复应统一同一 pending disclosure 的可见/可答形状，补正反分支与 stale/paused 反例；
不是在 CLI/TUI 中另建状态推进路径。若首发不支持 TUI，需明确降级其支持声明，不能静默留作“已验证”。

### F4 — P2：恢复验收仍可能假阳性

位置：
[consumption 判据](../../../scripts/run_task_trust_d04.py:602)、
[staged 聚合](../../../scripts/run_task_trust_d04.py:619)。

`version_changed` 仍用 `goal_version_changed OR state_version_changed`；
injected_fact_id 与 consumption.fact_id 各自验存在，但不验同一条 correction。

两个合成负对照均被 evaluator 返回 `completed, failures=[]`：

1. Goal revision 没变，仅 state revision 增加。
2. 同上，并把消费的 correction 换成另一条 fact。

这证明验收器不能排除这些伪证据，不证明上一执行者真实 E1-B 一定失败。
真实记录自报“双版本推进”；在查看可靠证据前不能推翻，也不能把不严格判据当作完整恢复证明。
同时保留 Oracle 指出的反证：生产观察器 `_consumed` 本身使用 `self.injected_fact_id`，
所以错绑反例针对最终摘要裁决的防御缺口，不等于真实 Runtime 已消费了另一条 correction。

## 4. 已有能力与真实边界

“有实现”与“当前所有情境已验收”是两回事。下表是代码与合同盘点，不是全能力 promotion。

| 能力 | 当前可以做什么 | 边界/缺口 |
| --- | --- | --- |
| 对话与任务 | 多轮对话、回答/澄清/任务路由、持久 Goal、纠正、暂停/恢复/取消 | 完成识别仍有 F1/F2；不保证任意复杂任务一次做对 |
| 项目文件 | 有界列目录、搜索、读取、写入、编辑、建目录、确认当前文件内容 | 当前 workspace、安全路径规则；写入受审批，不是整盘任意访问 |
| 代码与命令 | local_process；macOS sandbox_exec、shell_exec，可运行有界代码/测试任务 | sandbox network off；当前沙箱只有 macOS，不承诺任意环境/第三方依赖 |
| 上下文与历史 | 预算、压缩、不可变归档、当前工作区历史检索 | 压缩摘要不提升为 authority；不是无限上下文/全设备记忆 |
| 安全与连续性 | 精确授权、限次/限时租约、effect 前后 checkpoint、UNKNOWN 分类、证据 freshness | F3 为交互缺口；不把这些机制宣称为对一切攻击的完全隔离 |
| Provider 与交互 | setup、CLI/headless、HTTP adapters、部分 streaming、TUI extra | 本轮只有源码自动验证；真实支持范围应绑定明确 provider/model/配置 |
| 公开 Web | 可配置 Tavily search/extract、来源回执/引用 | 不是任意网页浏览登录；当前版本未独立重跑真实 Web journey |
| Memory | owner preference；可选受治理 store/search/get/remember/update/forget，词汇召回 | 不是自动无限语义长期记忆，不跨 owner/任意设备共享 |
| Skill | owner-local 目录/资源读取；显式声明 Python entrypoint 可走受控执行 | 需显式可信配置，脚本走审批/隔离；不是远程安装/任意脚本/allowed-tools扩权 |
| MCP | 显式 catalog 的 stdio 工具桥接，经统一审批和恢复 | 非任意 server 即插即用；开放 schema 与 strict-tools 有已知不支持组合 |
| SubAgent | 有界、只读、单 child 调查，复用同一 Runtime 实现 | 非多个并发自治执行者，不让子 Agent 任意写入或授权自己 |
| 专属浏览器 | 隔离 Chromium candidate、受治理网页动作/人工接管边界 | 非个人浏览器、任意登录站点或桌面控制；当前真实验收不完整 |
| 后台调度 | external-caller/control core 与 host adapter 的实现 | 安装命令缺 host composition 时返回 needs_019_config；不能宣传开箱即用后台助手 |

当前并不具备、且不应塞进本次首发必修范围：
跨平台 production host、接管整个 PC、无限自主后台、任意第三方集成、
跨设备无限个人记忆、并行写入型多 Agent、自动修改自己的权限策略。

## 5. 推出首版最紧急的三组工作

### A. 完成门“既不漏判，也不凭空加活”（F1+F2）

- 固定上面两条完整 Runtime 反例，不只测试字符串 helper。
- 有界区分输出文件、输入规格、引文/代码块/日志、版本号、禁止对象；同义直接路径写法不能依赖中英空格。
- 保留 correction/reopen/freshness、已正确文件 confirm-only、原来正常双文件正例。
- 不新增第二模型裁判，不把任意自然语言理解承诺给规则系统，不自动放宽权限。
- 模型该补证时应得到具体的下一步信息；不要只让它重复相同 invalid completion。

### B. 把同一用户决定在恢复前后做完整（F3）

- yes/no、默认拒绝、退出、paused、已确认、stale request，都遵循同一明确语义。
- 拒绝不得被转换为业务纠正，不得触发模型请求或工具效果。
- CLI/TUI 共用已有 typed action/reducer；TUI 支持与否明示。
- 保留未知结果恢复、正确的二次披露和 exact digest 约束。

### C. 用一个真实可交付版本证明日常路径（F4+交付证据）

- 收紧 driver 的 Goal revision 与同一 correction 绑定；负例必须被判 incomplete。
- 源码冻结后再构建一个 clean candidate/wheel，核对 imports 确来自安装物。
- 有限验收，不新建大平台：
  1. 无源码依赖的安装 → setup → 小文件任务 → 结果可用 → /new；
  2. 两文件编码任务正常完成，零业务催促，外部检查独立；
  3. pause/reopen，分别覆盖同意与拒绝，且零副作用重放；
  4. 工作区已经满足要求：只验证/确认即可结束，不能为了准入凑改动或反复 fatal。
- 用现有指标区分文件审批、外发确认、租约选择与“继续催促”；不把所有治理交互归为一种。
- 付费真实调用仍需本轮授权和预算；本次审计没有代替用户授权。
- 同步唯一 RESULTS 当前摘要/README/支持矩阵；保留历史但标清身份与过期结论。
- 用户批准后再有序提交/发布；本次没有 Git 写权限，不把审计当作 commit 授权。

不应把“全量重晋级 015–019”“多 Agent 平台”“再拆一轮巨石文件”作为这三组工作的前置。

## 6. 做重了/做轻了

做得值得保留：唯一循环、effect 事务边界、精确授权、可恢复状态和诚实证据。

做重/承诺过强：用局部词窗规则承担“原文所有文件要求都被覆盖”的可信保证；
不同历史身份的 seals、promotion、验收说明占据日用入口，让接手者难以知道当前到底哪版可用。
解决是收窄合同、统一当前摘要，不是继续叠规则或重写所有历史。

做轻了：用户的“否”、中英文自然书写、输入规格/示例、已满足任务、
同一决定在 CLI/TUI/重启后的表现，以及安装物上不靠提示救场的短旅程。
这些是产品基本功，比再加一个工具更影响日用。

上一执行者自报 normal 11 次普通治理确认 + 1 次范围授权（两者为独立计数），staged
两阶段普通确认合计 15 次。这不能等同“需要催促12/15次”，也不能从未拆分的计数推断
每种确认的次数；但对短任务的操作负担值得单独量化。应优化准确提示与已有精确复用，
不用 allow-all 消除安全边界。

## 7. 证据与限制

本次独立：
- touched-area：285 passed，30.84s；
- 全量：3947 passed、1 skipped，672.22s，exit 0；
- 显式关闭真实 launchd gate 的定点检查：1 skipped，未安装系统项；
- ruff check . / git diff --check：通过；
- F1/F2/F3/F4：合成、离线、生产边界探针；输出见 PROBE-RESULTS.json。

上一执行者公开记录（本次不冒充独立复验）：
- r3 installed 58/58、153 模块 origin、污染负对照；
- E1-A fresh：15 requests、38.7s、11 consents、1 scope authorization、typed done；
- E1-B：16 requests、41.9s、15 consents、typed done；
- r3 首个 normal 在已经完成的 fixture 上反复 claim 失败，用了15次请求。
  该次确实不能充当“从未完成到完成”的正样本；但“已有正确成果能否合理收尾”
  仍是需要单独验证的产品情形，不能用“fixture污染”一笔消掉。

未验证：本次没有新的真实模型、真实外部 Web/MCP、当前安装物端到端、新用户体验或市场需求证据。
不把上述单一编码场景的成功外推成“所有功能正常可用”。

本目录：
- [完整探针](probes.py)
- [探针结果](PROBE-RESULTS.json)
- [本次验证](VERIFICATION.json)
- [输入/源码身份](IDENTITY.json)
- oracle-input：本次独立咨询的最小公开材料，不含 key/真实私有会话。

## 8. Oracle 交叉审计与最终合并判断

[完整原答](ORACLE-ANSWER.md)；[会话/档位/捕获/清理回执](ORACLE-RECEIPT.json)。

Oracle 采用全新会话 `mfa-post-closeout-review-20261017-2318-62c9a1`，附件完成后再次确认
实际 ARIA 为 `Power, item 5 of 5`；形成新 conversation 并捕获完整答案。没有复用旧会话、
手动点击发送、followup 或升级 CLI。记录 PID 96387 已不存在，临时 Profile 已删除。
CLI 中 requested model 的名字不用于冒充 Web 实际模型证明。

双方共同结论：已有 MVP 核心能力，适合知情开发者监督自用；当前快照不宜按“日用收口”
面向普通用户发布。下一步是 **两个产品修复包 + 一个发布证据包**，不是新一轮平台建设。

采纳与核实：
- F1/F2 的因果得到独立静态核验；本地另有完整 Runtime 反例，不依赖 Oracle 运行代码。
- F3 的 no/空回车/TUI 差异得到确认；本地进一步证明 no 写入纠正事实、外发请求增量仍为 0。
- F4 为验收器伪阳性风险，而非已证明的真实 correction 丢失；保留生产观察器正确绑定的反证。
- 已正确工作区是合法产品情形；既有 confirm-only 路径离线可通，真实失败根因仍需最小证据，
  不凭猜测实施“删强制写入”或“提高重试上限”。
- TUI 若不在首发承诺内，可列已知非阻断限制；若随 `[tui]` 日用安装路径宣传，则同一决定必须补齐。
- 不因为约四千个测试就认定测试数量过多；需要减少的是无新证据的重复验收。

证据差异已处理：
- 外审发送时本地 full 仍在运行，Oracle 原答因此不签 full PASS；之后 Codex 得到
  `3947 passed, 1 skipped, exit 0` 完整结束结果，已记于 VERIFICATION.json。
- Oracle 未收到含敏感配置提示的完整 RESULTS，只收到公开脱敏摘要；其对文档矛盾的判断
  是转述核验。Codex 本地实际检查了对应公开记录，但未查私有原始 real 日志。
- 外审将首个工作包标为 P0，是该次发布排序；本报告保持 F1/F2 为严重的 P1 行为缺陷，
  不把它们夸大成已发生的数据泄漏或系统破坏。
- 输入摘要把 normal 的 11 次普通确认简称为治理决定；最终本地报告明确分列
  11 consents + 1 scope authorization，不误报总交互数。

最终停止边界：本次到“审计与建议”结束。未实施产品修复，未授权付费验证，未提交或发布。
