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
- r16（consent/lease 数值 10+ 同步点无失败信号）→ 裁决 B 维持延后：调值（已排期）时同步实施插值化。
- S3（8 个子包 __init__ 再导出约 56 名零消费者）→ 低价值，不动，仅记录。

第一轮复现产物：`/tmp/mfa-improve/j4/drive_j4_brick.py`（P1 场景）、`/tmp/mfa-improve/j3/probe_prose_escape.py`（P2）、`/tmp/mfa-improve/verify/`（复核探针）。

## 第二轮（合并后双裁决修复轮，2026-10-24）

- 第一轮 18 文件改动经 PR #6（7 commits）merge 到 `main` @ **`f084c9c`**。
- 双裁决（oracle_web 位置 4/5，9m33s + 本地独立收敛）对第一轮全部开放决策逐项裁决，收敛结果：披露疲劳 → **C+keep-open**（改善额度提示，会话级许可扩展仍需用户明示）；r8 空闲 chat 归档 / r14 预算暂停出路 / r10 edit 冲突误导 / r12 重跑不可见 → **全部 A 修复**（r14 取渲染层路线，无 schema 变更）；r16 插值化 → **B 延后**；E2/E3 真实层 → **维持 BLOCKED**；追加 S1（STATE.md 记录 merge SHA）与 S2（P2-2/P2-3 跨层测试）。
- 修复队列（Q1→Q7）全部完成：

| 项 | 裁决 | 内容（根因） | 状态 |
| --- | --- | --- | --- |
| Q1 r8 | A | 无 Goal 的空闲 chat 会话永久 active 不可归档（`_require_user_archive_eligible` 要求 goal 非 None 且终态）→ 256 容量墙+选择器摩擦。修复=无 Goal 也视为已结束（归档可逆；有 Goal 仍须终态）；`SessionArchivePreview.goal_status/user_outcome` 放开为 `None`；CLI 预览显示 "chat conversation" | ✅ Red（空闲 chat 归档被拒）→Green；continuity+cli 套件绿 |
| Q2 r14 | A | 预算耗尽暂停在 `--status` 仍推荐注定失败的 /resume。渲染层读取已持久化的 `last_safe_result.error_code == "model_attempt_budget_exhausted"` 分派出路（同 ledger 提高 `--max-model-attempts` 重启）；无 schema 变更、不触持久化兼容边界 | ✅ cli 套件绿 |
| Q3 r10 | A | edit old_text 失配被归类为路径卫生拒绝（workspace_file_denied），恢复指引误导（换路径而非重读文件）。修复=新 `EditContentConflictError`（继承 WorkspaceSecurityError）经 safe_binding 单独归类 `edit_content_conflict`，dispatch 文案改为「文件已变化：重读后基于当前内容重编辑；勿重试同一 old_text」 | ✅ Red（冲突文案含 "absolute"/路径卫生误导）→Green；tools 64 passed |
| Q4 r12 | A | 验证失效后自动重跑对用户不可见（与 P1 复合的透明度缺口）。修复=render 层 `_invalidation_rerun_note`：状态流中存在 "invalidated by later workspace activity" 的 completion_not_verified POLICY_RESULT 时，VERIFIED_DONE 渲染一次性补注「先前验证被后续工作区变更失效并已重跑」（按 goal_id+revision 去重） | ✅ Red→Green ×2（有/无失效无错注）；cli 套件绿 |
| Q5 item1C | C | 活跃 routine 许可剩余额度在披露文案中不可见。修复=grant 可用（未过期）时披露消息显示 "N of M model sends left, expires …"；含 this-pending-content-only 源时追加不受覆盖提示；耗尽显示 "all M model sends used"。会话级许可范围扩展仍 keep-open | ✅ consent_ux 套件绿（17 次 with_use 链真实铸造） |
| Q6 S2 | — | P2-2：W1 文件交付 × 自动压缩恢复旅程——6 轮长 chat（触发真实 TOKEN_PRESSURE 压缩+CONTEXT_SUMMARY 事实）后提交文件任务，恢复后 prose 假完成在控制门被拒（artifact criterion must be admitted），notes.md 未落盘，义务存活；批准后真实写入+读回+claim → VERIFIED_DONE。关键机制事实：全部读回必须晚于最后一次写入（晚写使早读失效）。P2-3：healed fact × 磁盘重开 × wire 投影——孤儿严格拒绝 prefix 落盘重开后真实投影 fail closed（invalid_tool_message_continuity），accept_action 自愈经真实 CAS 持久化、新 store 实例重开后 wire 精确成对（闭合 in-memory 版未覆盖的重启路径） | ✅ acceptance 17 passed；continuity_control 146 passed |
| Q7 S1 | — | 本节：记录 merge SHA `f084c9c` 与第二轮全量证据 | ✅ 本文件 |

关键复现产物：`/tmp/mfa-improve/s2/`（S2 旅程探针集，~15 个：run 终止矩阵、压缩触发、pinned 成本测量、证据失效序）。

## 已完成（本轮）

1. 技能发现：会话索引 + `~/.agents/skills` + `~/.claude/skills`（项目内无本地技能）。
2. 事实重建：AGENTS/STRATEGY/README/daily-use/capabilities/KERNEL_ARCHITECTURE/EXTENSION_CONTRACTS/CURRENT_CAPABILITY_STATUS/RESULTS(tail) 已读；分支/HEAD/diff 已核对。

## 已知开放项（无新证据不重审）

- E2/E3 真实层：凭据已解决（2026-10-24 key）；E1/E2 PASS、E3 缺陷已修复待复跑确认——以复跑结果为准更新 CURRENT_CAPABILITY_STATUS。
- 读/验证类输出发送逐次披露疲劳：真实层量化=23 次/E3 旅程；会话级许可实现（item 1）为下一包，设计已定（有界 grant+逐次非阻断通知+分类收窄+硬边界）。
- TUI 恢复外发确认显示缺口（TUI 非日用入口）；`/compact`、`/context` 未实现（已文档化）；Scheduler `needs_019_config`（设计内）。

## 决策队列（需要用户裁决）

1. ~~读/验证类输出是否纳入会话级许可~~ 已裁决（2026-10-24 下午）：按建议方向实现（有界 grant+逐次非阻断通知+分类收窄+硬边界）；实现为下一包。
2. ~~E2/E3 真实层补跑~~ 已授权并执行（2026-10-24 下午）：新 key + deepseek-flash；E1/E2 PASS、E3 缺陷已修复（复跑见第四轮表）。
3. `result.phase.json`（仓库根、未跟踪、用户产物，本轮按授权保留未动）：终审提示疑似 harness 散落产物，若未来 commit 需先确认归属再清理。

## 下一步

第四轮完整门：`git diff --check` ✅ + `ruff check .` ✅ + 全量 pytest **4159 passed / 1 skipped / 0 failed / 1 error**（error=`test_packaged_policy_real[read_package_file-allowed]` TimeoutError，全量负载下超时；隔离重跑 12/12 绿；改动无 sandbox 交互面，判定环境 flake）。真实层请求合计 110（修复前 56 + 修复后 54）。按既定模式交付后，会话级许可（item 1）为下一个工作包。

## 第二轮交付记录（历史）

PR #7（5 commits）merge 到 `main` @ **`e035450`**；完整门 4157 passed / 1 skipped / 0 失败；merge gate 审计 PASS（无 P0/P1）。

**第三轮（merge-gate follow-up）已交付**：审计 P2-1——r12 渲染层标记与 evidence 层错误文案各持字面量（漂移会让重跑提示静默消失）。修复=`INVALIDATED_BY_LATER_WORKSPACE_ACTIVITY` 常量单源（evidence 定义、render 导入、值钉测试；生产者侧由 P1 旅程对真实 POLICY_RESULT 断言钉住）。顺带 LOW-1（quota 行 `expires_at` 过 `terminal_text`）与 LOW-2（旅程 docstring 回合数 5→6）。完整门 **4158 passed / 1 skipped / 0 失败**。审计 LOW-3（r8 测试命名略过度声明）与 LOW-4（r14 代理字段取舍，已文档化）不动。

## 第四轮（用户裁决三项 + E3 真实层缺陷修复，2026-10-24 下午）

用户裁决与授权：①会话级许可按我的建议方向（先测量后实现）；②E2/E3 真实层提供新 key + 模型 `deepseek_v4.1_flash`（API 实测该名不存在，支持列表为 `deepseek-flash`/`deepseek-v4-pro`，flash 档意图明确取 `deepseek-flash`；key 已存记忆不落仓库）；③r16 先补清单测试、插值化本体等调值轮。

| 项 | 内容 | 状态 |
| --- | --- | --- |
| manifest 重绑 | `TASK-MANIFEST.json` model_id `deepseek-v4-flash`→`deepseek-flash`（退役模型导致准入 pin fail-closed 拒绝派发；上轮同型重绑先例） | ✅ 已改（随本轮 PR 交付） |
| E1 normal | 新预览（main@3ea6af1 wheel 非可编辑安装，origin=site-packages）+ deepseek-flash。修复前 10 请求/20s PASS；**修复后复跑 19 请求/37s 再 PASS**（守卫无回归） | ✅ **PASS** ×2，typed VERIFIED_DONE，业务+补充全 true |
| E2 staged | 同上。修复前 26 请求/52s PASS（correction 注入/durable/消费/新 PID resume 全链证据成立，**E2 历史上首次真实层全过**）；**修复后复跑 22 请求/51s 再 PASS** | ✅ **PASS** ×2 |
| E3 already-correct | 修复前两跑（cap 20/40）均 INCOMPLETE_CLOSURE：零写合同保持、业务全对，但 goal 卡 `goal_ready`，stop=`limit_pause_requires_user`。**修复后复跑**：13 请求即达 typed VERIFIED_DONE（修复有效性直接证明），但 deepseek-flash 改写了 `tests/test_retry_service.py`（1 次 effect）→ 判定 FAIL_ALREADY_CORRECT_WRITE——零写门正确拦截；该失败为**模型语义层**（v4-flash 2026-10-18 曾零写过 E3），非产品缺陷 | ✅ 产品缺陷已修复验证；E3 真实层终判=FAIL(模型语义)，如实记录 |
| E3 缺陷（真实层钉死） | 根因：goal 已有 digest-free process 义务（#1，请求命令指纹）时，模型自发第二条不同指纹验证命令的**批准路径 per-call fallback**（state.py:3708）再铸 #2——F1 保守失效下任意第二次进程执行失效其前全部 receipt，两条不同指纹强制 process 判据**构造上永不可同时满足**（任一时刻只有最后执行进程的 receipt 存活）。真实层表现：24 次连续 `completion_not_verified`(invalidated) 直到预算耗尽，模型重跑请求命令也救不活（救活 #1 的同时杀死 #2）。修复=per-call fallback 在已有 process 义务时不再铸造（rebind 替换失败义务与 runtime-owned 绑定不受限）；兼容钩子 `admit_process_receipt_criterion` 同理加防御。Red→Green 合成旅程 `test_aux_process_must_not_mint_second_unsatisfiable_criterion`（撤修复复现卡死）。**合同演进**：两个钉住「不同指纹照铸」旧合同的测试随 E3 证据更新（`test_015_compat_mint_skips_when_any_process_obligation_exists`、`test_unrelated_approved_command_does_not_rebind` 的 per-call 期望；rebind 保护断言原样保留） | ✅ 修复+旅程 Green；kernel 421/acceptance 18/process 47 passed；真实层复跑见上 |
| r16 清单测试 | `test_consent_ux_r16_numeric_copy_tracks_the_constants`：常量→文案一致性（铸造侧 max_uses/TTL + offer/exhausted 文案数字）；只改常量不改文案立刻红。插值化本体（文案 f-string 推导）等调值轮 | ✅ consent_ux 58 passed |
| 会话级许可（item 1） | 方向已定（有界例行许可+逐次非阻断通知）；真实层测量数据点：单次 E3 旅程 23 次披露决定；源构成分类与 grant 类别实现为下一包 | ⏳ 设计已定，实现待做 |

真实层证据目录：`~/.local/share/first-agent/previews/quality-20261024/real-validation-2026-10-24{,b}/`（b=修复后复跑）。复现探针：`/Users/jinkun.wang/.cache/mfa-e3r/`。未授权不做的事不变：无真实 provider 调用、无凭据变更、无发布部署。E2/E3 与会话级许可扩展仍等待用户输入。

## 第五轮（PR #9 merge + 审计 P2-1 复核 + F-C 修复，2026-10-24 晚）

**PR #9 交付**：merge-gate 审计 PASS（无 P0/P1；1×P2 follow-up + 2×LOW）→ merge `2cc22ca`（分支已删）。

**P2-1 复核（探针实测，结论与审计不符）**：审计称 correction 路径仍可铸出第二条不同指纹强制 process 判据重现死亡螺旋。实测（`probe_p21.py` 端到端）：correction 的 `retained_ids` 过滤会**先**把 approval-path 已入场义务 #1（id 只存在于 admitted）从 admitted 移除（替换语义——「再跑一遍」要求新证据），再铸 pending 提案 #2；批准不同指纹命令后最终**只有一条** process 义务（可满足）。死亡螺旋形状在 correction 路径构造上不可达（#1 幸存 retained_ids 过滤 ⟺ #1 ∈ proposed ⟹ 去重命中 ⟹ 不铸 #2）。已用两个测试锁定该不变量（中间形状 + 端到端），防未来回归。

**F-C（复核中发现的真实缺陷，已修复）**：correction required 去重沿 `_is_runtime_owned_obligation` 在 TOOL_RECEIPT 下同时匹配 `required-local-process` 与 `required-governed-tool` 两个前缀——pending governed-tool 义务在场时，用户明示的 process correction **静默不铸**（`probe_fc.py` 证实），验证要求失去强制（与 E3 过铸死亡螺旋相反方向的欠铸失败模式）。governed-tool receipt 不受 F1 进程失效约束，两类判据本可同时满足，无需互斥去重。修复=新增 `_REQUIRED_RUNTIME_OBLIGATION_PREFIXES`（按 effect 类取同类前缀，TOOL_RECEIPT 下只认 local-process）。

**LOW-1（已修）**：主 manifest 与 locked 镜像的 `model` 同步此前无测试钉住（漂移只会在真实派发准入 pin 处 fail-closed）；freeze 测试补 `locked["model"] == manifest["model"]` 断言。

| 项 | 内容 | 状态 |
| --- | --- | --- |
| P2-1 复核 | 探针实测推翻审计机制（retained_ids 先 drop #1，终态单义务）；测试锁定 correction 路径的 E3 不变量（`test_correction_replaces_admitted_process_obligation_without_minting_a_second` + `test_correction_replaced_obligation_admits_single_process_criterion`） | ✅ 复核+锁定 |
| F-C 修复 | `_REQUIRED_RUNTIME_OBLIGATION_PREFIXES` 同类前缀去重；governed-tool 不再挡铸 process 义务 | ✅ Red→Green（`test_process_correction_mints_obligation_even_with_pending_governed_tool`） |
| LOW-1 | freeze 测试钉主/locked manifest model 同步 | ✅ |
| item 1 测量 | 真实层旅程工具构成：读/验证类调用占 68-77%（E1 13/19、E2 19/28、E3 10/13，read_file 8/14/7 为主）；`workspace_excerpt`（file-proof、reusable=True、goal+workspace+digest 绑定）为最强分类；list/search 输出落 generic `tool_results` 类（reusable=False）。read-scope grant 定为只覆盖 proof-backed 的 `workspace_excerpt`（Option A），list/search 留后续 | ✅ 测量完成，设计定稿 |

## 第六轮（item 1 实现：r 读域会话许可，2026-10-24 晚）

**PR #10 交付**：merge-gate 审计 PASS（0×P0/P1/P2，2×LOW：双 pending 绑定次序为既有语义记 backlog；STATE.md 测量数字引用仓库外证据目录）→ merge `8a5fa0f`（分支已删）。

**r 许可设计（用户裁决采纳的建议逐条落地）**：
- **Option A 分类收窄**：grant 类别集 = `ROUTINE_DATA_CLASSES + ("workspace_excerpt",)`——只并入 proof-backed 的 excerpt 类（Runtime 持久化 file-source proof 绑定 goal/revision/workspace/内容 digest、reusable=True）；`tool_results` 等通用类与 summary 不随之扩，仍逐次披露。
- **显式 opt-in**：独立键位 `r`（`GrantProviderWorkspaceReadConsent`），与 `s` 分开——routine 可授予的请求上 r 明确报错「already covered by the routine scope」，不静默升级；非常规部分超出 excerpt（含不可复用来源）时报「beyond verified workspace file excerpts」。
- **硬上界与 s 完全一致**：同 `CONSENT_MAX_USES=32`/`CONSENT_TTL_SECONDS=3600`（validator 钉死 profile→类别集恰等 + max_uses 固定）；撤销/失效/身份漂移/扣次重算全部复用既有 grant 机制（`/revoke-provider-consent` 直接适用）。
- **逐次非阻断通知**：`grant_workspace_read` 放行的每次派发在扣账后附带一行 warning（`workspace_read_dispatch_notice`：本次 N 份工作区摘录重发 + 剩余额度），不打断、不要求决策。
- **B3 同款硬化**：r 许可放行时在场未消费的单次 y 一并烧掉（`mark_receipt_consumed`），防 grant 失效后 exact_receipt 额外放行一次。
- **门语义**：`workspace_read_classes_covered`（非常规部分恰为 workspace_excerpt 且全 reusable）+ `_grant_covers_structure`；routine scope 仍走 `grant_routine`；新出现 excerpt 源在许可内被覆盖（这正是疲劳来源——会话级语义本体）。

**覆盖**：10 个新测试（gate 准入/拒绝、charge+通知文案、B3 烧票据、CLI parse、reducer 铸造+RUNNABLE 恢复、CLI 两类拒绝、offer 行可见性、数字钉、validator 钉、checkpoint 编解码往返）。**已知缝隙（记入调值轮）**：loop 层通知接线（6 行 reason 分支）无 journey 级测试——域内既有覆盖模式为 gate/reducer/CLI 层（journey 仅 routine 形状），r16 插值化轮补齐 journey 级 consent 测试时一并覆盖。
