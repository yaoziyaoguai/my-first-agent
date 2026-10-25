# 2026-10-25 持续产品/架构/工程质量改善 — 活动状态

> 单一当前记录：目标、基线、工作包、证据、剩余候选、决策队列。历史验收不改写；
> 能力状态权威在 `docs/architecture/CURRENT_CAPABILITY_STATUS.md`。

## 目标与授权

- 有边界的产品审计与本地改善（同 2026-10-24 活动框架）：修复证据充分的实现缺陷与文档漂移、
  改善不扩权限/隐私/范围的交互与错误反馈、局部架构整理、删除确证冗余、补高价值验证。
- 上限 8 个聚焦工作包；用户追加指令：遇到问题直接修复、持续「审计→修复」循环、
  以提升 agent 实用能力与用户体验为目标。
- 不做：commit/push/发布/部署、真实 provider/外部服务调用、扩大数据外发范围、
  改持久化兼容或重要公开接口。保留用户未提交内容。

## 基线（2026-10-25 起点）

- `main` @ `f0df92e`（PR #12 调值轮 merge；完整门 4178/0F，由调值轮会话执行并记录）。
- 本轮开始时工作树上的调值轮未提交改动已由**并发会话**（my-first-agent-d1）自行收尾并 merge，
  该会话现 idle；本会话此后独占工作树。
- 本轮 Skills：`dev_co`（~/.claude/skills，协调）、`codebase-design`（同上，deep module/seam 词汇）、
  `graphify`（项目 hook 强制）。拒绝：gstack-*、contract-first、oracle-web（外部会话未授权）、
  lfg/review/qa（explicit-only）、improve-codebase-architecture（无新证据不重跑）。

## 旅程基线（审计仪器，仓库外）

- 安装级验证：`~/.local` wheel 快照（git archive HEAD → pip wheel → 独立 venv），
  harness 在 `~/.cache/mfa-c1025/harness/`（PTY driver、loopback server、wheel 内进程旅程
  `journey_common.py`：patch `main._build_provider/_provider_descriptor` 注入 scripted
  provider + remote 描述符，走真实 CLI/审批/checkpoint 路径，零网络）。
- 旅程结论（J1 安装/编码、J2 问答、J3 读任务、J5 纠正/暂停、J6 二任务、c1 探针）：
  - 安装/setup/审批/写盘/纠正/暂停语义正常；完成门读回强制正确拒假完成（actionable 指引）。
  - **C1 缺陷**（已修，见 P1）：s 授权后同 turn 下一次发送因结构钉死必再问且无解释。
  - 疲劳事实：读/列目录任务 4 次披露/旅程（tool_results 类逐次）；r 许可只覆盖
    workspace_excerpt——扩到 list/search 属外发范围扩大，**在决策队列**。
  - 待证（C）：进程内快速重开 paused 会话出现 checkpoint_TimeoutError（2/2）；疑似 harness
    同进程连跑伪影（产品 continuity 套件覆盖真实跨进程恢复），未定性。
  - 小观察：裸文本 "y" 在 needs_authority 时被记为 goal_correction（语义可议，未定性）。

## 工作包

| 包 | 分类 | 内容（根因） | 状态 |
| --- | --- | --- | --- |
| P1 | A（交互诚实性） | C1：routine grant 钉死铸造时 control_schema_digest/tool_bindings；goal 准入改变两者 → 同 turn 下次发送必再披露，提示却显示"Active routine permission: N of 32"无解释，自相矛盾。修复=渲染层在"活动许可在场仍需决策"时按 request vs grant 实际结构差异追加解释行（grant_eligible 时附 s 续期指引）；gate 结构钉死语义保持（安全属性）。Red（`test_consent_ux_active_grant_structure_drift_explains_re_prompt`，含 gate 不放行前置钉死 + 结构未漂移反例）→ Green；consent_ux 41 passed、cli 261 passed、ruff 绿；**安装物端到端复验**：c1 场景两类提示均出现解释行（grant_eligible 带 renew 指引 / 带新源时不带） | ✅ 完成 |
| P2 | C→调查 | TimeoutError 一律归类 checkpoint_TimeoutError（main.py `_bounded_state_failure_detail`） | ✅ 调查后 declined：该 helper 只被 checkpoint open/close 的 `(CheckpointError, OSError)` 捕获方调用（LOG-01 有界诊断，刻意设计）；非 checkpoint 超时到达该前缀的路径需要 OSError 子类的 TimeoutError 且同时绕过上层处理，真实可达性极窄。不改，避免为不可达路径加分支 |
| P3 | B（结构） | codebase-design 视角的结构审计 | ✅ 关闭：具体产出已随 P1 执行（`grant_structure_drifted` 谓词单源化，render 与 gate 同一规则）。两个候选 declined：①main.py credential 双点（1377 主门=ExitStack 前 pre-flight UX 快败，`_build_provider:1072`=构造点强制；两层目的不同，具体重复仅默认 env 名一个 `or` 表达式，漂移启动即暴露，合并收益不抵改动）②app.py `_parse_action` 与 render 无真实规则复制（answerable 判定已在 views 单源，双方共同引用）。文件行数本身不构成拆分理由 |
| P4 | C（审计线索） | 旅程 state 出现 needs_authority + render_pending 静默，疑似"沉默卡死" | ✅ 证伪：复核全部旅程 state——每个 needs_authority 态都带 answerable pending disclosure（会渲染问句）；"静默"样本实为 receipt 已消费的正常形状（探针未查 receipt 的误报）。goal PAUSED 静默是 B（2026-10-18）刻意设计（先 /resume）。附带核实：needs_authority 下裸 "y" 记为 goal_correction 由 `acknowledge_noop_goal_delta`（state.py:1323）优雅消费，非缺陷 |
| P5 | A→B（外发疲劳，用户委托裁决） | 决策队列 1 落地：读/列/搜输出 proof 化并入 r 会话许可。根因=读类工具输出走 `_generic_tool_sources`（reusable=False）→ 每个新读源逐次披露（E3 真实层 16-23 次/旅程主驱动）。修复=新增 `ResultSourceKind.WORKSPACE_READ`；read_file/list_files/search_paths/search_text/read_file_chunk/confirm_file 铸造 `ProviderFileSourceProofV1`（`read_source_identity` 提供路径身份，digest 公式与 inspect_mutation 一致）；tools.py 铸造点提取 `_file_source_proof` 共用（source governance 分支同样铸造）；context.py 投影对"自带 receipts 的读结果"保留 citation 链（仅无 receipts 的写读回整体替换为 excerpt 投影——修复中发现的回归：无条件替换会断 workspace 引用，3 个 reference 测试拦下）；r 提示文案更新为 "verified workspace reads — file excerpts, directory listings, and search results"。**命令 stdout 明确不铸 proof**（非 workspace 派生，维持逐次披露）。Red×5（工具 3+投影 2）→Green；全量 4186/0F；**安装物端到端**：goal-bound 读旅程答一次 r 后 0 再问，b.py/c.py 两个新文件内容均经会话许可到达模型，逐次非阻断余额通知（1/2/3 workspace file excerpt(s) re-sent...）与 Sources/citation 链完整 | ✅ 完成 |

## 已完成（非包）

- 旅程仪器建设（见上）；技能发现与事实重建；与并发调值轮会话的冲突避免与释放确认。

## 决策队列（需要用户裁决）

1. ~~读/验证类输出会话级许可扩展~~ → **已裁决并落地（P5）**：2026-10-25 用户委托
   本会话决定。list/search/read 输出 proof 化并入 r（同一 workspace 派生信任边界，
   类级会话覆盖含新文件）；命令 stdout 不纳入（真扩大）。剩余子项：goal-less
   对话（BeginAnswer 路径）的读仍逐次（proof 绑定 goal 是刻意语义，未视为缺陷）。
2. ~~E2/E3 真实层复跑~~ → **已授权并执行（2026-10-25）**：结果见下节
   「E2/E3 真实层复跑轮」。E1/E2 PASS、E3 零写契约首次成立（闭合失败属模型
   语义层）、P5 真实层 r 旅程 PASS（答 r 一次后读类零再问）。

## E2/E3 真实层复跑轮（2026-10-25，用户「授权」后执行）

- **候选/安装身份链**：`~/.local/share/first-agent/previews/quality-20261025/`
  （candidate=工作树快照（main@f0df92e+P5 未提交改动，driver/manifest/fixture
  与工作树逐字节一致过门）；wheel 装入独立 venv，install guard 强制产品模块
  origin=site-packages；编排解释器 pyenv 3.12.2（第三方闭包 httpx 从其 site
  解析——首轮用 verification-venv 解释器即败于此，0 请求即停未耗预算））。
  模型 deepseek-flash、`TASK-MANIFEST.json` 既有授权（40/1800s 窗口）。
- **冻结 d04 三样本**（`real-validation-2026-10-25/`，driver 对披露一律答 y）：

  | 样本 | 结果 | 请求 | 墙钟 | 关键事实 |
  | --- | --- | --- | --- | --- |
  | E1 normal | **PASS** | 15/40 | 28.6s | typed VERIFIED_DONE、业务双 true、七补充全 true；披露 15 次（r 选项出现 7 次）；对比 2026-10-24b 基线 19 请求 |
  | E2 staged | **PASS** | 29/40 | 45.2s | 注入(approval)→durable 消费→pause→**新 PID resume**→VERIFIED_DONE 全链闭合；披露 30 次（r 出现 4 次）；基线 22 请求，批内方差 |
  | E3 already-correct | **INCOMPLETE_CLOSURE** | 16/20 | 31.0s | **零写契约首次成立**（files_unchanged、effects=0、effect_tools={}）、业务双 true、pytest 七补充全 true；闭合败于 `invalid_model_control`（模型反复提交语境不可用 control kind，repair 额度耗尽 fail-loud；loop.py:2448 已知模型语义类，016 E3 同型观测；E1/E2 同构建收敛 → 非产品回归、非 P5 回归） |

- **P5 真实层 r 旅程**（`real-read-journey-2026-10-25-goal/`，自写 reactive driver，
  ≤12 请求预算）：goal-bound 读任务 → 披露序列 routine→s（无 r）、结构漂移→y、
  带 workspace_excerpt→**答 r 一次**；**此后 0 再披露**，仅非阻断余额通知
  （"4 workspace file excerpt(s) re-sent…31→28 of 32 model sends left"）；后续
  发送（含 b.py/c.py 新读源）全部被 r 会话许可覆盖，内容到达模型，goal 经
  3/3 evidence 判据闭合（"Goal completion verified by closed evidence oracles"）。
  6/12 请求。判据全 PASS。
  附 goal-less 对照（`…-goalless/`）：同任务不诱导 goal 时模型走 BeginAnswer，
  读类无 proof → 无 r 选项、逐次披露（4 请求 4 披露）——**P5 已知刻意语义的
  真实层实证**（proof 绑定 goal），非缺陷。
- **预算与凭据**：本轮累计物理请求 **71**（预检 1 + E1 15 + E2 29 + E3 16 +
  goalless 4 + goal 6）；key 仅经环境变量注入、产物防御性抹除、全部产物 `sk-`
  扫描**零命中**；历史累计 324+71=**395**。未 commit/push。
- 记录同步：本轮证据目录在 previews（仓库外）；CURRENT_CAPABILITY_STATUS 加
  2026-10-25 日期增补（指针至本节）。

## 下一步

- **P5 对抗验证轮已收尾**（5 视角攻击 + 独立复核，9 agent，0 误报）：
  - **medium×2 已修**：①r 选项句诚实性——r 许可捆绑全 routine 类别（r⊃s，
    2026-10-24 item 1 既有语义），选项句改为 "Also allow routine conversation
    data and verified workspace reads…"，r 场景同显 Routine scope 解释行，
    "read-scope" 标签改 "read+routine"（quota/status/确认行三处）；②大读结果
    （>max_tool_result_chars 8k）proof 铸于全文、投影文本已截断 → 校验失配 →
    静默退回逐次披露（恰是疲劳主体）——`_valid_file_proof` 对被裁剪 fact 改用
    `_clip_tool_results` 保留的全文 sha256 校验。
  - **low×2**：③receipts+proof 生产主路径无测试 → 补（citation 链存活 + 恰一个
    reusable source）；④binding 形状变化使升级前在途 confirm_file 审批 fail-closed
    失效（approval_mismatch，需重新批准一次）——判定为正确行为不改码，**升级
    注意事项记录于此**。
  - 端到端复验（安装物）：r 选项新文案 + 大文件 b.py（12.5k，截断投影）仍被
    r 覆盖（0 再问）、内容到达模型。
- 最终完整门（2026-10-25，P5+对抗修复后）：`git diff --check` 通过；
  `.venv/bin/ruff check .` 通过；`.venv/bin/python -m pytest -q -rx`
  **4188 passed, 1 skipped, 0 failed**（P5 累计新增 7 测试：tools 3 + kernel 4）。
- E2/E3 真实层复跑轮收尾（见上节）：E1/E2 PASS、E3 零写成立+闭合败于模型语义、
  P5 真实层 r 旅程判据全 PASS。决策队列清空。
- **主体已 merge**：用户授权 commit+push 后，4 commit 经 PR #13 merge 到 main
  （`8d8c697`）；merge gate 审计 PASS（无 P0/P1/P2；P3-1 在途 confirm_file 审批
  升级后 fail-closed 需重批一次=正确行为，已附 PR 描述为升级注意事项）。

## 审计 follow-up 轮（2026-10-25，用户「把审计出来的问题都修复」）

- **LOW-1（修）**：`grant_structure_drifted` 与 `_grant_covers_structure` 的
  平行结构判定提取为单源 `_grant_structure_pinned`（provider_consent.py），
  gate 放行与渲染解释共用同一核心；gate 语义逐字等价（绑定覆盖→digest→类别）。
- **LOW-2（修）**：render.py C1 注释措辞精确化——结构漂移是"唯一需要专门解释行
  的剩余原因"（新源由 sources 段解释、类级差异由选项句自述），不再断言"只有"。
- **LOW-3（修）**：tripwire 测试 `test_local_process_stdout_never_mints_a_file_source_proof`
  （kernel/process_draft_bounds）——注册级断言 `result_source_kind is None` +
  runtime 级 goal 绑定在场断言 `result_source_proof is None`；未来给进程工具加
  kind 属扩权，必然显式变红。
- **P3-1（不改码）**：fail-closed 是刻意安全属性，已文档化为升级注意事项。
- 验证：ruff 绿；聚焦 108 passed（tripwire+consent_ux+file tools）；kernel+cli
  689 passed；完整门见下。
- 完整门（follow-up 轮）：`git diff --check` 通过；`.venv/bin/ruff check .` 通过；
  `.venv/bin/python -m pytest -q -rx` **4189 passed, 1 skipped, 0 failed**
  （+1 = LOW-3 tripwire）。
- follow-up 已落地：PR #14（单源结构判定 + 注释精确化 + 进程 proof tripwire）。

## 双审计交叉验证轮（2026-10-25，用户「自审计 + oracle_web 审计 → 交叉验证后修复」）

- **审计来源**：① 自审计（本会话：/help 收录、空输入语义、fatal 退出路径、
  终态摘要、恢复文案、preflight、命令拒绝文案逐项核码）；② Oracle Web
  （skill oracle-web，档位 4/5 extra-high 已验证，slug
  `mfa-usability-audit-20261025`，4m13s，4 文件 ~20k tokens：daily-use/
  capabilities/CAPABILITY_STATUS/本 STATE）。
- **交叉验证结论**（Oracle 7 项 + 自审计 1 项 → 确认 3、证伪/已实现 4）：

  | 项 | 裁决 | 依据 |
  | --- | --- | --- |
  | 致命失败无恢复指引（自审计 × Oracle#4/#5） | **确认→F1** | FAILED_FATAL 基础分支只打错误码即 `return 1`（app.py:251），用户不知 state 已保存可重启续作；对比 LIMIT_RECOVERY 有指引 |
  | 文档漂移（Oracle#1/#7） | **确认→F2** | capabilities.md:26 仍断言"读/验证类……仍单独披露（16 次）"（P5 前旧事实）；daily-use 试用入口=机器特定 2026-10-18 路径、Provider 配置=`deepseek-v4-flash`（10-24 实测 API 列表已无此名） |
  | 无 r 选项时无解释（Oracle#3 有界部分） | **确认→F3** | goal-less 读逐次披露时 r 从不出现且不说原因；s-unavailable 有同式先例；Oracle 建议的"显示许可余额"部分已实现（quota 行+/status）decline |
  | VERIFIED_DONE 语义透明（Oracle#2） | **证伪/已实现** | `delivery_summary_message`（views.py:78）已含 Required evidence N/M + "User acceptance: not established"；verification scope 句实测在 r 旅程输出中 |
  | 启动 preflight（Oracle#1 功能部分） | **decline（已部分存在）** | main.py 主门 ExitStack 前已有 credential pre-flight 快败；模型有效性探测需真实调用（非默认授权）；可行动切片=F2 文档 |
  | 模型侧修复引导再加码（Oracle#4 模型侧） | **decline（无新证据）** | 2026-10-18 发现 1 轮已给 gap-repair 分型+completion_claim 指引；再加码属猜测性提示词工程 |
  | 状态特定恢复指引全面重构（Oracle#5 全量） | **decline（超出有界切片）** | Ctrl-C 分支/未知效果 pending/恢复边界 CONFLICT 均已有状态特定文案与出路；缺口即 F1 |
  | 上下文命令建议（Oracle#6） | **decline（大部已实现）** | pending 决策自带选项渲染自述；/help 全量；new_session_gate 拒绝文案状态特定（actions.py:55）；再加每状态建议属噪音换收益 |

- **修复（分支 fix/2026-10-25-dual-audit-usability）**：
  - **F1** render.py FAILED_FATAL 基础分支追加恢复句（"Saved state was kept —
    …run first-agent again…or /cancel after restarting"）；Red→Green
    `test_fatal_result_carries_recovery_guidance`（含 auth 分支不重复追加反例）；
    既有摘要界断言 400→600（含恢复句，截断证明仍有效）。
  - **F3** render.py 无 r 选项且发送含未覆盖来源时追加 "r unavailable — …
    verified workspace reads under an active task" 解释行（s-unavailable 同式）；
    Red→Green `test_consent_ux_r_unavailable_explains_why_when_sources_not_covered`
    （含覆盖成立提供 r 选项正例）。
  - **F2** 文档：capabilities.md 外发许可行改写为 P5 现状（r 覆盖 proof-backed
    读含新文件；命令输出与无任务读仍逐次；旧 16 次断言标注被取代）；daily-use.md
    试用入口标注历史记录并指向自行安装、Provider 配置改 `deepseek-flash`（附
    10-24 实测支持列表说明）、支持矩阵行更正模型名。
- 验证：cli+consent_ux 338 passed；完整门见下。
- 完整门（双审计轮）：`git diff --check` 通过；`.venv/bin/ruff check .` 通过；
  `.venv/bin/python -m pytest -q -rx` **4191 passed, 1 skipped, 0 failed**
  （+2 = F1/F3 Red→Green）。
- 双审计轮已 merge：PR #15（`d1d63f5`）；merge gate 审计 PASS（F1 恢复句对全部
  27 个可达 fatal error_code 逐一核验无误导；F3 elif 触发条件与 reusable 铸造
  点语义精确对应；文档与 contracts/代码一致）。跟进 LOW×3（审计建议下一轮随手
  并入）：①message-form 恢复句补一行显式断言；②goal-less fatal 时 "/cancel"
  措辞不普适（无害）；③capabilities.md 可恢复"写文件结果稳定来源静默复用"注记。
- 活动关闭（主体+follow-up+双审计轮均已落地，main @ d1d63f5）。

## LOW 跟进轮（2026-10-25，用户「把剩余的问题都改完」）

- 范围：上述 LOW×3 + PR #14 审计遗留 LOW（tripwire 注释"唯一开关"表述对进程
  路径略强）+ 2026-10-24 调值轮 backlog 的 managed_web 就绪窗口 flake，共五项。
- **①（修）**：`test_fatal_result_carries_bounded_exception_summary` 补两条
  显式断言——message-form（含摘要）与长消息截断形态的输出都带恢复句
  （此前只有裸错误码形态被断言）。
- **②（修）**：render.py FAILED_FATAL 恢复句按 goal 状态分支——非终态 goal
  （GOAL_READY/EXECUTING/NEEDS_AUTHORITY/PAUSED/BLOCKED）保留 "/cancel it after
  restarting" 出路；goal-less（纯对话）与终态 goal（VERIFIED_DONE/CANCELLED，
  `cancel_goal` 明确拒绝）改为 "continue this conversation"，不再给落空的
  /cancel 指引。测试重写为三态钉住（goal-less 无 /cancel、active goal 有
  /cancel、VERIFIED_DONE 无 /cancel）+ auth 反例。
- **③（修）**：capabilities.md 外发许可边界列恢复注记"写/编辑文件结果的
  稳定来源在许可内静默复用"——核实 write_file/edit 注册
  `result_source_kind=WORKSPACE_FILE_EFFECT`（file_ops.py:282/306），与
  WORKSPACE_READ 走同一 `_file_source_proof` 铸造（tools.py:900 docstring
  明示 W1/P5 共用），注记与代码事实一致。
- **④（修）**：process tripwire 测试 docstring 精确化——两闸结构：进程 draft
  走 `_process_outcome` 结构性早退（tools.py:761）到不了铸造点；即便重构直落
  通用路径，两个铸造点也都要求注册携带 kind（source-governance 分支只接受
  WORKSPACE_READ）。不再断言"唯一开关"。
- **⑤（修，根因比记录更深）**：tests/process/test_managed_web.py 满负载
  flake 家族三处一次修齐。首次整门实录 `reaps_descendants` 在 getpgid 处
  ProcessLookupError（1/12 轮空载也复现）——真根因：监督者在 direct child
  退出的下一次 poll（≤0.1s）即回收整组（managed_web_child.py supervise 循环），
  测试要在 pid 文件出现后的亚 0.1s 窗口完成观察，本质竞态。修法=launcher
  发布 pid 后等 release 文件才退出，把「观察后代在组内存活」与「子退出触发
  回收」解开（被测属性不变）；lifetime 回 30s 只作逃逸上界。同族两处顺带：
  两处 fixture 就绪窗口 5s/1.5s→30s；三处 finally killpg 加
  suppress(ProcessLookupError)（poll→killpg TOCTOU 会用清理异常掩盖首发
  失败）；两处 proc.wait(5)→30（满负载退出延迟）。压力验证：空载 12 连跑
  + 满负载 4×yes 3 轮，0 失败（修复前空载 1/5、1/9 复现）。
- 验证：聚焦 52 passed（cli render + kernel process draft + managed web）；
  完整门见下。
- **对抗验证轮**（ultracode workflow，6 agent：每修复一个反驳者 + 完整性
  critic）：五项全部未被推翻；critic 确认无遗漏、无意外文件。三项可执行
  追加修复：
  - **⑥ lifetime 起算点**（反驳者实证）：test 2 `enforces_lifetime` 的
    lifetime 从 spawn 起算——满负载启动 >2.0s 时 server 在 bind 前被杀，
    30s 就绪窗无效（实际容错仅 lifetime）。lifetime 2.0→8.0，被测属性不变。
  - **⑦ 终态集合单源**：render 内联 {VERIFIED_DONE, CANCELLED} 是第三份
    拷贝（actions.py 与 continuity/sessions.py 各有一份模块私有同名集合）。
    单源化为 contracts.py `TERMINAL_GOAL_STATUSES`（GoalStatus 旁，公开
    常量），三处消费点统一导入。
  - **⑧ 注释时间指代**：test 2 就绪窗注释"本轮 flake 记录"改为明确
    指向 2026-10-24 轮。
  - 记录不修：FAILED_FATAL 恢复句在 unknown-effect 落盘失败窗口（loop.py
    `_finish_unknown_effect_persistence_failure`，极窄可达）显示 /cancel 但
    暂被拒——先答恢复提示即解除、REPL 存活，非死路（反驳者定性 + 模拟实证）；
    render.py:152 既有 .value 级内联（非本轮引入，不顺手扩权改写）。
- 验证（追加修复后）：managed_web 文件空载多连跑 + 满负载 3 轮 0 失败；
  完整门见下。
- 未纳入：goal-less 对话读类会话级覆盖（权限边界扩大，仍需用户裁决）；
  E3 闭合失败（模型语义层，非产品缺陷）。
- 落地：单 commit `210264f` 经 **PR #17 merge 到 main（`8300399`）**；
  merge gate 审计 **PASS（0 P0/P1/P2）**——六项声明逐一核真（补集精确性、
  frozenset 等价、new_session_gate 行为不变、契约测试 21 passed 无清单
  冲突、四条失败路径全有界、无断言弱化）；聚焦 264 passed。审计 LOW×3
  不阻断：render.py:152 既有 `.value` 级终态内联（第四份拷贝，下次触碰
  该文件时顺手统一）；unknown-effect 落盘失败窗口 /cancel 暂落空（已
  自记录，非死路）；test 2 极端负载下可能以"未就绪"有界失败（务实折中）。
- 门过程备注：一次中间门 3F+1E（TimeoutExpired 型）经定性为环境争抢
  （graphify 全量重建 + 疑似并发会话共用 .pytest_cache；隔离复跑受疑
  探针 12/12 绿、lastfailed 中测试名在本树不存在）；无负载复跑
  **4191 passed / 0 failed**（662s）为权威结果。教训：完整门期间不并行
  跑 graphify update / CPU 重任务。
