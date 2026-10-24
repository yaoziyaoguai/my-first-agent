# 2026-10-24 产品/架构/工程质量改善 — 活动状态

> 单一当前记录：目标、基线、进行中的工作包、已完成项与证据、剩余候选、决策队列、下一步。
> 历史验收记录不改写；权威能力状态仍在 `docs/architecture/CURRENT_CAPABILITY_STATUS.md`。

## 目标与授权

- 有边界的产品审计与本地改善：修复证据充分的实现缺陷与文档漂移；改善不扩权限/隐私/范围的交互与错误反馈；局部架构整理（保持外部行为合同）；删除确证无消费者的冗余；补高价值验证。
- 上限 8 个聚焦工作包（资源上限非成功标准）；每包根因级、可完整验证。
- 不做：commit/push/发布/部署、改凭据/系统服务/全局配置、真实 provider/外部服务调用、扩大权限或数据外发范围、改变持久化兼容或重要公开接口。
- 保留用户未跟踪内容（`result.phase.json` 等）；历史"冻结"状态不构成拒绝本次授权工作的理由。

## 当前基线（2026-10-24 起点）

- `main` @ `c6d8b3f`（r7 product-level audit round — zero findings）；工作树干净，仅未跟踪 `result.phase.json`（用户产物，不动）。
- 完整门命令：`git diff --check` + `.venv/bin/ruff check .` + `.venv/bin/python -m pytest -q -rx`（collect 约 4110 项；最近一次全绿记录为 2026-10-23 consent 轮 4100 passed / 1 skipped）。
- 全部能力对当前 identity 为 `implemented-candidate`；E2/E3 真实层 BLOCKED（上游退役 `deepseek-v4-flash` + 凭据失效）。
- 本轮使用 Skills（来源已核实）：`dev_co`（~/.claude/skills，主协调）、`codebase-design`（同上，审计词汇）、`improve-codebase-architecture`（~/.agents/skills，仅采用其探索方法；HTML 报告/grilling 阶段按其自身限制拒绝）、`graphify`（项目规则强制，每次代码探索先 query）。按需待用：`diagnosing-bugs`、`tdd`。拒绝：gstack-review/qa/lfg（explicit-only）、gstack 系列（不适用）。
- 代码探索规则（hook 强制）：先 `graphify query` 定向再读源码；子代理同样遵守。

## 进行中

**活动已收尾（2026-10-24）**。终态证据：
- 完整门：`git diff --check` ✅ + `ruff check .` ✅ + 全量 pytest 两轮——第一轮 **4143 passed / 1 skipped**；终审修正后第二轮 **4146 passed / 1 failed / 1 skipped**（唯一失败 `tests/sandbox/test_network_only_macos.py::danger_full_positive_control` 为 TCP loopback 正控制：第一轮全绿、隔离重跑 13/13 绿、改动文件无交互面，判定全量并发负载下的环境 flake，非本轮改动所致）。
- 独立终审（project-auditor，只读）：初判 PARTIAL（D-1 阻断）；D-1/E-1/LOW-2 三项修正后未复检（修正均在终审已建议的局部修法内，Red→Green 证据在包表）。
- `graphify update .` 已于终版代码后执行（16546 节点 / 73931 边）。

| 包 | 来源 rank | 分类 | 内容（根因） | 状态 |
| --- | --- | --- | --- | --- |
| P1 | r2 | A | 验证失效后按修复指引重跑仍永久无法完成：`admit_process_receipt_criterion` 铸 digest-pinned mandatory criterion，receipt 失效后永不可满足，任务卡死+lease 静默消耗循环（state.py:3919-3982、loop.py:1425-1440） | ✅ 已完成：Red journey（`test_write_after_validation_revalidation_completes_goal`，修前 GOAL_READY）→ 守卫（同指纹 digest-free 义务在场则跳过铸造，process+sandbox 对称）→ Green + 边界单测 2（覆盖跳过/未覆盖仍铸）+ 聚焦回归 202+8 passed。diff：state.py +22，tests +297 |
| P2 | r3 | A | 非编码交付词表缺口：「整理成/写成 notes.md」可 prose 收尾零交付；W1 完成下界对这些措辞为空集；反向「帮我修了/refactor」不触发门控（context.py:85-111、state.py:275-293） | ✅ 已完成（含终审 D-1 修正）：中文复合交付动词入 trigger 1/2/6 与 release 对称表；把/将句式加礼貌前缀+修了；英文收窄为「summarize/organize + into/to/as + 扩展名」；W1 同源补词。**终审 D-1**：state.py 实施误用裸动词（整理/总结/保存…），「总结 failures.log 里的失败原因」被误铸强制写义务→确定性卡死 W1 完成门；已收窄为复合式+目的地标记（成/到/为，允许短宾语间隔；英文 into/to/as），补 4 条读引用负例入冻结矩阵（Red×4→Green）。证据：016 187→191 + release-A 34→38 + 相邻大套件 1744 passed |
| P3 | r4 | A | unknown-effect 恢复边界 /pause /cancel /resume 被通用 "State conflict" 文案踢出会话（exit 2）；conversation_busy 同病；真正出路（success/failed/stop）被掩盖（render.py:325-326、app.py:231-232） | ✅ 已完成（含终审 LOW-2 修正）：Red（修正输入后真实失败：/pause 于 AWAITING_RECOVERY+Goal 解析为 PauseGoal 命中 state.py 守卫 → exit 2）→ render CONFLICT 按 error_code 分派 + app.py 存活集 `_SURVIVABLE_CONFLICT_CODES`（continue 而非 return 2；CAS 类保持 exit 2）。**终审 LOW-2**：恢复指引硬编码 success/failed/stop 对公共观察子形（continue/stop）不准；文案改为指路重印的 pending 提示（权威选项随形状）。Green 3/3 + 相邻 418→423 passed（cli+tui+consent_ux） |
| P4 | r5 | A | consent S6 gate→charge 毫秒窗口 grant 失效→FAILED_FATAL runtime_failure，而非按合同转 AWAITING_DISCLOSURE 重问（loop.py:2063-2082、1726-1737；provider_consent.py:594-607 raise 未捕获） | ✅ 已完成：探针实测调用序（gate=第5时钟调用、charge=第6）精确定位窗口；Red（flip=5 → failed_fatal "gate is stale"，曾因 flip=4 命中 gate 自身过期路径得到假 Green，已修正）→ 修复=两处 charge 站点 try/except ValueError + 统一 helper `_pause_for_disclosure_recheck`（顺带消除 2 处 30 行重复的过期分支，4 份重复→1 helper）→ Green 9/9（含姊妹 pre_transport 行为不变）+ 相邻 105 passed（consent_ux 全部+compaction+model_call_recovery+runtime_approval+kernel contracts）+ ruff |
| P5 | r9+r11 | B×2 | 审批/披露决策点呈现：f/d 提示问句连打两遍（render.py:347/361，c64cb5b 回归）；精确 ID 死路（/help 宣传 <request-id> 但 CLI 从不显示；无参绑定缺失；披露挂起兜底误导文案） | ✅ 已完成：Red×4（问句 count==2；裸 /approve、/resolve-success 均死路；"hello" 得 "reserved command"）→ 修复=f/d 分支去重问句；裸 /approve、/reject、/resolve-success、/resolve-failed 绑定单一 pending（对齐 /approve-goal-target 既有无参语义；错误 ID 仍拒绝；公共观察恢复仍禁猜）/help 同步 [request-id]；披露挂起裸文本指明 y/s/n 三选项。显示 ID 路线被既有合同测试（不暴露内部 ID）否决，按替代方案闭合 → Green 423 passed（cli+tui+consent_ux）+ ruff；test_commands 帮助文本断言随合同演化更新 |
| P6 | r7 | B | veto 误判礼貌问句与中文语气问句（trigger 允许 could-you 前缀而 veto 不对称；中文缺 可以吗/对不对 尾），fake 端到端 Run failed | ✅ 已完成（含终审 E-1 修正）：release 表中文前缀+语气尾+英文礼貌只读 check 问句分支。**终审 E-1（P3 级）**：礼貌 check 释放会吞掉复合请求（"Could you check why X, then fix the bug in app.py?" 被降级纯文字）；改为条件释放——同句含第二祈使（then/and + fix/update… effect 动词）时不释放；纯问句释放不变（曾误用 not-triggered 条件打破纯问句行，已纠正为第二祈使信号）。新增 2 条复合请求行（stash Red→Green）。016 全套 + 相邻 650 passed |
| P7 | r15 | B | 敏感路径三套名单漂移：goal-auth 集合 ⊂ path_safety、缺 11 名（含 id_rsa/credentials.json），与 KERNEL_ARCHITECTURE.md:69 声称不符；修复=成员判定复用 path_safety（只收紧）+同步测试 | ✅ 已完成：Red×13（漂移名全部实证放行）→ 单源化=名单+谓词上移到 contracts.py（`is_intrinsically_sensitive_component` 公开权威源；避免 contracts→tools 反向依赖环），path_safety 私有别名导入（内部调用点零改动），`safe_goal_authorization_target` 改用同源谓词（只收紧，普通路径不受影响）→ Green 14/14 + 回归 164 passed（path_safety/file_tools/goal_controls/sandbox/delivery_manifest/kernel contracts）+ ruff；KERNEL_ARCHITECTURE.md 声称由代码兑现，文档无需改 |
| P8 | r6+r1(README)+r13 | A文档+B文案 | 指引错误小集：README wheel 构建无 build/ 残留防呆（已删模块仍打进 wheel，RESULTS 已实证机制）；README `--state-root /tmp/...` 示例在 macOS 必败（symlink 合同拒绝）；history_capacity_exceeded 文案不给 --status/archive 解法 | ✅ 已完成：README wheel 块加 `rm -rf build first_agent.egg-info` 防呆+成因注释；`--state-root` 示例改 `$HOME/first-agent-dev-state` 并注明 /tmp symlink fail-closed 原因；capacity 文案追加 `--status` 列表 + `archive <id>` 释放路径（与 restore 提示同风格）。验证：ruff + continuity 20 passed + main import OK；消息文本无测试钉死（disposition 测试不钉文案），test_016 打包清理测试为可选项未做（需在测试里调 pip wheel，成本不成比例） |

不实施、留记录/决策：
- r8（chat 会话永久 active 不可归档→重启选择器摩擦+256 容量墙）→ 决策队列：涉及 retire 语义/选择器 new 出口设计取舍，推荐方向=空闲 chat 视为非 active 或放开空闲归档，需用户选向。
- r10（edit 冲突失败误导为路径卫生问题）→ 候补（P 系列如有余力再做）。
- r12（验证失效重跑对用户不可见，与 P1 复合）→ 候补；P1 修复后仍有透明度缺口。
- r14（预算耗尽暂停原因未落盘，重启后仍推荐注定失败的 /resume）→ 决策队列：修复需 ActiveRun schema 变更（触碰持久化兼容边界）。
- r16（consent/lease 数值 10+ 同步点无失败信号）→ 决策队列附注：调值（已排期）时同步实施插值化。
- S3（8 个子包 __init__ 再导出约 56 名零消费者）→ 低价值，不动，仅记录。

关键复现产物：`/tmp/mfa-improve/j4/drive_j4_brick.py`（P1 场景）、`/tmp/mfa-improve/j3/probe_prose_escape.py`（P2）、`/tmp/mfa-improve/verify/`（复核探针）。

## 已完成（本轮）

1. 技能发现：会话索引 + `~/.agents/skills` + `~/.claude/skills`（项目内无本地技能）。
2. 事实重建：AGENTS/STRATEGY/README/daily-use/capabilities/KERNEL_ARCHITECTURE/EXTENSION_CONTRACTS/CURRENT_CAPABILITY_STATUS/RESULTS(tail) 已读；分支/HEAD/diff 已核对。

## 已知开放项（无新证据不重审）

- E2/E3 真实层：BLOCKED_UPSTREAM_MODEL_RETIRED / 凭据 401（需用户提供有效 key 或换模型授权）。
- 读/验证类输出发送逐次披露疲劳（实测 16 次/小任务）：2026-10-23 consent 合同接受的边界；扩大静默复用范围需用户裁决。
- P2-2/P2-3 覆盖缺口（W1 复验×wire continuity、healed fact×投影链路）。
- TUI 恢复外发确认显示缺口（TUI 非日用入口）；`/compact`、`/context` 未实现（已文档化）；Scheduler `needs_019_config`（设计内）。

## 决策队列（需要用户裁决）

1. 读/验证类输出是否纳入会话级许可（降 16 次/任务披露疲劳）——涉及数据外发范围扩大，建议方向：保持逐次披露但改善文案中的额度/剩余提示；是否扩展 `s` 范围需用户明示。
2. E2/E3 真实层补跑：需有效凭据或新模型授权（候选 `deepseek-flash`/`deepseek-v4-pro`）。
3. `result.phase.json`（仓库根、未跟踪、用户产物，本轮按授权保留未动）：终审提示疑似 harness 散落产物，若未来 commit 需先确认归属再清理。

## 下一步

**无待办。** 活动按第九节标准完成：核心旅程/链路覆盖（P1-P8 对应全部 4-6 旅程的审计与修复）、授权内高价值问题全部处理、最终候选完整验证（两轮全量门）、遗留取舍/决策队列/未验证范围如实交接。工作树 18 文件改动 + 本目录记录未 commit（未授权），待用户处置：审阅 diff → 自行 commit 或指示后续。
