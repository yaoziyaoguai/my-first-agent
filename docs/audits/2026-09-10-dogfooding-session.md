# Dogfooding 会话报告:r19 第一轮之后的真实使用检验

日期:2026-09-10 · 执行:Claude Code 代替 owner 跑多样化任务(headless/main 级双驱动,
真实 `glm-5.2` @ bigmodel,`thinking disabled`)· 材料/timeline/ISSUES 留档
`~/work_space/fa-dogfood/`(仓库外)。

## 任务结果

| # | 任务 | 终态 | 产物质量 | 耗时 | 审批 |
|---|---|---|---|---|---|
| 1 | 多文件代码(median+测试) | completed | 产物对(t1v2 独立核验 4 passed) | 33-38s | 2-3(全 edit) |
| 2 | 2000 行 CSV 聚合 | **failed_fatal** | **100% 精确**(月度+Top3 全对) | 165s | 3(write+2×process) |
| 3 | 目录整理 | **failed_fatal** | 完全正确(texts/docs/data) | 138s | 5(mkdir/mv 绕行) |
| 7 | 250+ 行长文档 | completed | 312 行一次成形 | 91s | 1 |
| 8 | 两难测试(诚实性) | completed | 两全解+独立核验通过 | 40s | 1 |
| 4/5 | Memory+/new(main 级) | startup failed | 未走到(见缺陷) | — | — |
| 6 | Web 检索 | blocked | 无 Tavily key | — | — |

**总评**:模型工作质量高(6/6 跑通任务产物全部正确或精确);产品层问题集中在
**终态可靠性与交互死锁**,不在能力面。

## 发现(按修复优先级)

### P0-1 显式验证指令不强制 process criterion(t1/t1v2/t8 三连复现)

TASK 明确"运行 pytest 确认全部通过",模型三次零 `local_process` 调用即
`verified_done`(goal criteria 仅 FILESYSTEM_DIGEST)。t1 第一次产物实际是错的
(预置测试期望错)仍 VERIFIED_DONE——"验证过的完成"可被整体绕过。
**修复方向**:用户消息含 run/test/validate/build 语义时(precise 词表),
Runtime 在 goal_proposal 接纳时强制铸造 process criterion(policy 引导升级为
系统强制;与 evidence gate 语义一致)。

### P0-2 渐进披露的提案死锁(t5 系列,实证)

`goal_bootstrap` 阶段 `ContextPack.tools` 为空(spy 实证 main 路径 provider 首收
`tools=[]`,registrations 17 个齐全)。"请在 Memory 记住 X" → 模型看不到 memory
工具 → 按 policy answer-only("我没有持久 Memory 工具")→ 永远到不了工具披露。
**修复方向**:system policy 明示"Goal 建立后可用的工具类别";或 bootstrap 阶段
披露工具名目录(只读元信息,不开放调用)。

### P1-1 多轮工具后 completion 阶段 malformed_tool_call 死循环(t2×8、t3×9)

任务实质完成后模型连续 8-9 次坏 tool call,修复引导无效,修复上限耗尽 → 整个
会话 `failed_fatal`(产物在,用户看到"失败")。期间流出 230 个 text delta(边
解释边反复发坏调用)。单工具写任务(t1/t7)不复现 → 与多轮工具上下文的 completion
有关。**修复方向**:①normalize 给 malformed_tool_call 附有界 shape detail(现在
诊断盲区);②修复上限将耗尽时降级为 PAUSED + 保产物状态而非 FAILED_FATAL;
③抓包定论模型到底发了什么(脱敏 dump)。

### P1-2 /new 重装配 × --memory-create 冲突(t5)

第二轮装配 create 遇已存在 store → startup failed,进程退出,/new 后用户被踢出。
**修复方向**:重装配时 create 退化为 open(同一 store 复用)。

### P1-3 文件工具缺 move/rename/delete(t3)

模型被迫走 `local_process mv`(任意进程批准替代受治理 move,语义变宽);批量为
preview 核对负担重。**修复方向**:受治理 `move_file`(exact approval/EXECUTING/
receipt,同 write 通道)。

### P2(UX/诊断)

- malformed_tool_call 修复引导无 shape detail(仅 malformed_control 有)。
- 流式 delta 走 `partial(print)` 绕过注入的 write_fn(harness 采集盲区)。
- disclosure ack 为首轮必需输入;`Resume` 等类型化合同对集成者有学习成本
  (建议 actions 层统一 builder)。
- disclosure 每轮 ack 的交互成本未测(真实用户体感)。
- Web(Tavily)未配置即 blocked——常用能力的获取/引导成本待检视。

## 亮点(保持)

- 模型任务质量:6/6 产物正确;大 CSV 用"写脚本+local_process"策略 100% 精确
  (对比基线 task1 心算——policy 场景差异值得复盘)。
- 诚实性:两难任务给出两全解,无虚报。
- 治理链全程 fail-closed 正确(memory 越界拒绝/symlink state root 拒绝)。

## 复现

`~/work_space/fa-dogfood/`:drive.py(headless)/drive_main.py(main 级)、
tN-*(材料)、out-t*.json(timeline)、ISSUES.md(逐条记录)。
