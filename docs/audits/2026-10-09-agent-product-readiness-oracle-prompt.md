# my-first-agent 产品可用性与必要能力审计（2026-10-09）

你是独立审计者，不是执行者。用户明确要求 Oracle Web 最高档（5/5），希望你与本地 Codex 一起核对另一个 coding agent 最近完成的修复，判断还缺哪些“成为一个能好用、能交互的个人 Agent 产品”所必需的能力。请用中文回答。

## 目标与非目标

目标用户第一层：拥有自己的模型 API、懂基本终端操作的个人用户，完成日常文件/资料处理、代码修复与小功能、受治理浏览器任务。第二层：不了解内部实现、希望打开后能自然交互的普通用户。请分开评价，不要混为企业平台或全能桌面 Agent。

“先能用，不扩大范围，不漂移”。本轮只审计，不实施，不发版，不更改权限。不以更多 MCP/向量库/并行 Agent/后台 daemon/全平台/GUI 功能堆砌作为产品成立的前提。不要按文件行数拆分、不要建议重写运行时。允许你内部从正确性、产品体验、边界安全三个视角交叉分析；本地执行建议请 optional_subagents: []。

## 源码身份与信任边界

工作树：main，HEAD 838cb2b66fbba674311d4d86fc7c4f4322fd8612，缓存 origin/main ahead 7，有大量未提交改动。这些附件是当前公开产品源码和合成测试/开发记录，不是已发布版，不包含密钥、私有用户会话或真实用户日志。
唯一 model/tool loop 是 AgentRuntime.run_turn；ContextManager 独占上下文，ToolRuntime 独占工具执行。CLI/TUI/headless 只做 action/event adapter，副作用必须经过审批与 durable checkpoints。保留这些边界。
docs/architecture/CURRENT_CAPABILITY_STATUS.md 的 candidate/seal 标记是当前证据政策，不应把旧 milestone accepted 等同当前版本全功能可用，也不要仅因没重新 seal 就把现有功能判为不存在。

## 最近修复：要核对，而不是照抄自评

docs/handoffs/2026-10-02-bounded-reliability-repair/RESULTS.md 含旧历史与最新 follow-up/真实 Dogfood（存在陈旧段落互相覆盖），按明确日期判断：
- F1/R1：进程造成输入变更时失效旧验证；多项只读验证通过原生沙箱准入闭合；再次批准同命令铸造新 lease。
- F2/R3：浏览器 owner shutdown 留闭合凭据，新 owner 可补记，不对未知清理签成功；dead worker 不重等。
- F3/R2：验收 driver 必须读 typed 终态与真 durable evidence，不再用成功文案或自造 tests 作为完成；runner 与 validator 离线贯通。
- F4：archive/restore 锁残留与容量分离、inode 重验。
- 执行者报告 2026-10-04 全量 3673 passed / 1 skipped；2026-10-04/05 的真实 DeepSeek D01/D02/D06 分别用 12/12/23 请求 completed。
这些是执行者报告，不是本次 Codex 重跑，也不是所有功能、所有平台、所有网站保证。当前审计不读取私有日志、不调用真实产品模型 API。

## 本地初读观察（待独立验证，不要求迎合）

1. CLI 确有 /new、y/n 审批、目标/目录级授权、pause/resume/cancel、sources、资源收尾与验证摘要。不是“毫无交互”。
2. CLI run_turn 同步：运行中不能继续输入 /pause；KeyboardInterrupt 返回130并提示重启检查，与 TUI 活跃 cancel token 不同。需判断普通用户实际后果、最小必要修复。
3. Renderer 显示 Working、模型等待心跳和文本增量，但忽略 TOOL_REQUESTED/TOOL_RESULT 和其它进度阶段。用户能否知道当前在做什么、卡在哪里？
4. Textual compose 主要是几个 Static + 单行 Input + Footer；状态刷新覆盖主显示，并不见会话 transcript。请核对历史/最终交付内容是否可回看、长输出是否可读、恢复后的任务是否有足够上下文；不要先假设必须 Web UI。
5. setup 只保存 provider metadata，需要用户手输模型名/base URL/环境变量，然后手动 export key；能力 readiness 有打印但可操作性与默认路径需评估。
6. scripts/f2_f3_local_browser_journeys.py 的 _run_bounded 使用 daemon threading.Thread + join(timeout)，超时返回后没有终止线程，main 的 ExitStack 仍清理 base。“bounded stop, cleanup proceeds”可能夸大截止与清理保证。这是测试驱动证据问题，不能无依据扩大为生产 Runtime 一定泄漏。
7. scheduler 命令 core=None fail closed、扩展默认 opt-in；这些不应自动上升为最紧急产品缺能力。请明确已经足够和应该继续冻结的部分。

附件不是全仓库。对于没有提供内部实现的能力，标注“本次无法独立核验”，不要把文件缺失当功能缺失。需要新增事实时只用官方/开源 primary sources 调研，给直接链接并区分事实与建议；无须为了流程机械调研。

## 请交付

A. 直接结论：它是否已是“Agent”，作为上述两层用户的产品各处于什么状态？优势是什么，最影响日常使用的瓶颈是什么？不要辱骂或虚假夸奖。
B. 已完成/仍缺证据矩阵：针对最近 R1/R2/R3/F4，区分实现、自动测试、真实模型报告、你自己的可见证据；避免重开已解决问题。
C. 按必要性排序最多 5 项：每项标注 P1/P2/P3、类型（真实缺陷/缺交互产品化/验证缺口/文档误导）、具体用户旅程/失败方式、附件文件+函数或行号、最小改动范围、可观察验收条件。确凿缺陷和审美建议分开。
D. 7 个用户旅程短表：首次安装配置、提交普通多步任务、了解进度并中止、审批与权限、失败/重启恢复、查阅结果并开始下一任务、日常连续使用。给 available / limited / unverified 与理由。
E. 明确哪些做重了、哪些做轻了；哪些已有能力够用。提议未来不超过 3 个顺序小切片，使“打开→做事→看懂→必要时停→拿走可信结果”闭环，而不重构整个架构。
F. 不做清单：至少列出应暂缓的诱人但非必要能力；不要把市场所有 Agent 特性都当必需。
G. 用下面 YAML 结束，建议不是执行授权：
codex_execution_advice:
  implementation_plan:
    - <最小有序建议>
  non_goals:
    - <明确排除>
  optional_subagents: []
  verification:
    - <验收与真实证据边界>

