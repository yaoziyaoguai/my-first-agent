# 018 Execution Log

- Spec: `docs/superpowers/specs/2026-08-28-governed-browser-tasks-design.md`
- Design: `docs/architecture/018_GOVERNED_BROWSER_TASKS_DESIGN.md`
- Acceptance: `docs/acceptance/018_GOVERNED_BROWSER_TASKS_E3.md`
- Executor preference: Claude Code GLM 5.3 `[1m]`, `effort=max`
- Rules: no commit/push; preserve existing dirty worktree; do not read `.env`, secret,
  credential, private/runtime data, or untracked `tui/` content.

## 2026-08-28 — Research and design freeze preparation

- 用户确认 design summary：First Agent 专属隔离 Playwright profile、唯一 Runtime/
  ToolRuntime 治理、精确 action approval、user takeover、SSRF/prompt-injection guard、
  download isolation，不增加第二套 Agent loop。
- Primary-source review 完成：Playwright isolation/persistent profile/auth state/locator/ARIA/
  pages/downloads；CDP surface；OWASP SSRF；Anthropic browser prompt injection；WebArena/
  BrowserGym；browser-use 对照。
- 旧 018 plan 的 Docker/`SandboxEnvironment`/ChangeBundle/quarantine 依赖与 delivered 017
  native Seatbelt 不一致，标记为待重写，不允许直接执行。
- 书面 spec/design/E3 已创建；用户于 2026-08-28 review 并批准，status 已更新为
  `frozen-user-approved-2026-08-28`。下一步用 writing-plans 重写 implementation plan；
  尚未开始产品代码实现。
- Plan 编写前 owner self-review：将 browser preflight 明确拆为纯
  `BrowserActionPolicy.prepare(observation, action)` 与仅在既有 `EXECUTING` checkpoint 后
  运行的 `BrowserEnvironment.execute(...)`。这只澄清已批准的唯一 ToolRuntime/effect-order
  invariant，不改变用户产品边界；避免 approval preparation 在 checkpoint 外访问 browser。

## 2026-08-28 — Task 1: typed contracts, URL policy, observation projection

- 新增 `agent/browser/__init__.py`、`agent/browser/contracts.py`、
  `agent/browser/ports.py`、`agent/browser/url_policy.py`、
  `agent/browser/observation.py` 与 `tests/browser/test_contracts.py`、
  `tests/browser/test_url_policy.py`、`tests/browser/test_observation.py`。
  未修改其他产品文件。
- 严格执行 Red→Green：三个测试文件均先以 collection error Red
  （`ModuleNotFoundError: agent.browser` / `agent.browser.url_policy` /
  `agent.browser.observation`），再最小实现 Green。
- 合同要点：closed enums（BrowserMode/BrowserActionKind/BrowserConsequence/
  BrowserActionOutcome/BrowserCleanupOutcome，未知字符串 ValueError）；
  `BrowserSessionSpecV1.site_bound` 强制 opaque profile_ref + 非空 exact origin
  allowlist，positive limit 显式拒绝 bool；identity 全部经 runtime
  `canonical_json_digest`；executed receipt 必须携带 pre/post observation
  identity 与 outcome class。唯一 `KnownNotExecuted` 复用
  `agent.runtime.contracts`（ports re-export，测试断言同一对象），无重复定义。
- URL policy 要点：resolver 仅构造注入（测试用 deterministic FakeResolver，
  不触 host resolver）；HTTPS-only、拒 userinfo/IP literal/localhost/trailing
  dot/非默认端口；全部 A/AAAA answer 逐个 `ipaddress` 判定（v4-mapped 按内嵌
  v4），空 answer fail closed；SITE_BOUND 要求 canonical origin 在 exact
  allowlist（子域不匹配）。审查修复：`URLPolicyRejection` 更名
  `URLPolicyError`，并删除测试中无占位符的 f-string 前缀。
- Observation 要点：`project_aria_snapshot` 纯投影，确定性截断
  （400 nodes/64 KiB/depth 15，截断必置 `truncated=True`）；
  password/secret/hidden value 与是否为空都不投影；普通 input 仅投影
  `value_empty` 与公开 label/form_action；`BrowserObservationV1`/
  `BrowserElementRefV1` 字段集合 closed，无 HTML/cookie/header/body/screenshot
  安放处。审查修复：测试 import 块 I001 重排。
- Focused gate（Task 1 Step 6 命令）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/browser/test_contracts.py tests/browser/test_url_policy.py tests/browser/test_observation.py -rx`
  → **58 passed** in 0.12s（contracts 14 + url_policy 34 + observation 10）。
- Touched Ruff：`ruff check agent/browser/ tests/browser/test_contracts.py
  tests/browser/test_url_policy.py tests/browser/test_observation.py`
  → All checks passed。`git diff --check` → clean。
- 边界声明：未运行 full suite、未 materialize、未运行 E3/U1/U2/U3（按计划
  分别留给 Task 9/10）；未安装 Playwright/Chromium；未触碰 `.env`/secret/
  private/runtime/未跟踪 `tui/`；无 commit/push/branch。

## 2026-08-28 — Task 2: owner-only profile store 与 opaque session ledger

- 新增 `agent/browser/profile_store.py`、`agent/browser/session_store.py` 与
  `tests/browser/test_profile_store.py`、`tests/browser/test_profile_locking.py`、
  `tests/browser/test_session_store.py`。未修改其他产品文件。
- Profile store 要点（含三轮独立审计修复）：
  - dirfd 锚定（`dir_fd`+`O_NOFOLLOW`，root→profile→metadata 无 parent-swap
    窗口；owned root 绝对路径之上的父链归 composition 层边界，非本模块声明）；
    root/目录 0700、metadata/lock/guard 0600，过宽自动收紧。
  - closed decode：exact keys、bounded read（metadata 64 KiB/lock 1 KiB）、
    `O_NONBLOCK`+`S_ISREG`（目录/FIFO 不阻塞）、digest hex64、pid/revision
    正 int 拒 bool；CAS second-open 对实际持有 fd 做同一 validation。
  - 单 writer：tri-state `ProcessIdentityProbe`（`os.kill` ESRCH 是唯一 dead
    判定；固定 `/bin/ps` 取 start identity），unknown 一律 `ProfileLockUnknownError`
    且发生在 unlink 前；root-anchored `guard-<profile_id>`+flock 消除
    takeover TOCTOU 与 clear 期间的 guard inode 再生（确定性多进程 race
    测试：双 contender barrier 编排，旧实现 Red 双 writer，新实现恰一位）。
  - mutation API 全部要求完整 trusted ref（forged digest/status → Integrity，
    stale revision → Conflict）；clear 先 revoke/关闭 writer 再删 canonical
    root（already-revoked 直接删），partial/identity 不确定 CLEANUP_UNKNOWN +
    quarantine（`_quarantine` 自身 symlink 校验，绝不 rename 出 owned root）；
    revoke 后 clear 返回 CLEANED。
- Session ledger 要点（含两轮审计修复）：
  - 冻结迁移集 + 跨字段 phase-shape 校验（OPENING 无数据、ACTIVE 无 action、
    PREPARED/EXECUTING 绑 action+observation 无 outcome、RESULT_OBSERVED
    绑 action+outcome、CLOSED 只接受两个合法来源形态的 union）；profile
    binding 必须同 null 或同完整（canonical ref+positive revision）。
  - 公开 compare_and_swap 限定机械迁移（OPENING→ACTIVE、
    ACTION_PREPARED→EXECUTING），进入 ACTION_PREPARED/记录 result/close 由
    专用 API 独占 binding/outcome/revision 检查。
  - 所有公开 mutation（CAS/observation/begin_action/record_result/close）
    显式 `expected_profile_revision` 并在 flock CAS 内重验——effect 前
    （ACTION_PREPARED→EXECUTING）重验封住 prepare 后 drift 的 TOCTOU（spec
    §4.2 session-wide authority 失效语义）。
  - action-observation binding；EXECUTING 无 result 为 recoverable unknown
    （`pending_recovery`，load 只读、绝不静默转 not-executed）；ledger 只存
    opaque IDs/digests（bytes 无 goal/URL/account 原文）；begin 构造的
    payload 先通过与 load 相同的 closed decode（单一 truth，无规则漂移）。
- Task 2 合并门（真实 exit 0，无 pipe 截断）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/browser/test_profile_store.py tests/browser/test_profile_locking.py tests/browser/test_session_store.py -rx`
  → **93 passed** in 6.17s（profile_store 17 + profile_locking 31 + session 45）。
  Touched Ruff → All checks passed；`git diff --check` → clean。
- 边界声明：仅 Task 2 focused/合并门；未运行 full suite（Task 9）、未
  materialize/未运行 E3（Task 10）；未安装 Playwright/Chromium；未触碰
  `.env`/secret/private/runtime/未跟踪 `tui/`；无 commit/push/branch。

## 2026-08-28 — Task 3: Chromium public-read adapter 与 egress guard

- 新增 `agent/browser/playwright_adapter.py`、`tests/browser/fakes.py`、
  `tests/browser/test_public_read.py`、`tests/browser/test_egress_guard.py`、
  `tests/browser/test_browser_cleanup.py`；`pyproject.toml` 增加
  `browser = ["playwright==1.62.0"]` extra（base dependencies 仍无
  playwright，adapter 顶层 lazy import）。
- 主审 8 项 hard blocker 全部按 Red→Green 闭合：
  1. 只使用真实 Playwright 1.62 API——固定 `evaluate` 脚本收集 element
     refs（value 原文与 secret 空/非空在浏览器内判定、不回传）、
     `get_by_role(...).click()`、`mouse.wheel` 滚动；静态断言源码无
     fake-only API（collect_observation_state/resolve_element/click_ref），
     fake 只实现同一真实接口（evaluate 按 marker 只接受 adapter 固定脚本）。
  2. eguard 接入真实 context 路由：`context.route("**/*")` +
     `context.on("page")` popup gate；document/redirect（redirected_from）/
     frame（subframe）/subresource/websocket（wss 归一 https；ws:// 拒）/
     popup 每个事件在实际 continue/close 前经同一 `BrowserEgressGuard`
     （session 绑定 mode/allowed_origins，非 execute 硬编码），拒绝即
     abort/close 且 send 计数为 0。
  3. worker 异常不再杀线程：dispatch 异常作为 error response 回传，线程
     存活；caller `_roundtrip` 持串行锁 + bounded put（5s）+ response
     timeout；非合同异常（URLPolicyError/RefusedError 之外）与超时 poison
     该 handle；close 的任何不确定/join 失败返回 CLEANUP_UNKNOWN。
  4. 单次收尾：page→context→browser 各恰好一次，Playwright stop 由
     worker with 退出恰好一次且永远最后；worker finally 只清理异常退出
     残留（closed/is_closed 判定，不 double-close）。
  5. `_origin_of` 用 netloc（保留显式 port）；navigate 后 session 记住
     admit 的 canonical url/origin，observe 优先使用。
  6. worker session 保存 spec 的真实 mode/allowed_origins，供全部 request
     事件与 navigate 共用。
  7. 测试覆盖：one browser/fresh non-persistent context/headless/
     accept_downloads=False/无 storage-state/无 extension/bounded timeouts、
     route/ws/popup/frame/subresource guard 计数、evaluate marker、
     worker 异常 response + poison、roundtrip timeout poison、close join
     失败 UNKNOWN、launch 失败 fail closed 恰一次（无 fallback）。
- 诚实边界：本任务全部经注入 fake factory/resolver 验证合同；未安装
  Playwright、未下载/启动 Chromium、未联网（真实 resolver 对 fake host
  返回空答案 fail closed 亦被测试证明）。真实 Chromium engine、真实
  evaluate/ locator/ route 行为属于 U2 materialized E3（Task 10）。
- Focused gates（直接运行、pytest 自身 exit code、无 pipe 截断）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/browser/`
  → **181 passed** in 8.19s，exit 0（Task 1 58 + Task 2 93 + Task 3 30）。
  `.venv/bin/ruff check agent/browser/ tests/browser/` → All checks
  passed，exit 0；`git diff --check` → exit 0。
- 边界声明：未运行 full suite（Task 9）、未 materialize/未运行 E3
  （Task 10）；唯一 AgentRuntime/model/tool loop 未动（adapter 无
  Provider/Runtime import、不推进 state、不自授权）；未触碰 `.env`/
  secret/private/runtime/未跟踪 `tui/`；无 commit/push/branch。

## 2026-08-28 — Task 3 第二轮审计修复（Playwright 官方 API/egress 记账）

- 独立审计对照官方 Playwright Python 文档发现三处真实 API 偏差与记账
  缺口，全部按 Red→Green 闭合：
  1. `Request.redirected_from` 是 property 不是方法：`_classify_request`
     改属性访问；FakeRequest 同步 property 化；新增回归测试断言
     `isinstance(FakeRequest.redirected_from, property)` 且 adapter 源码
     无 `.redirected_from()` 调用。
  2. `context.on("page")` 对每个新 Page 触发（含 `new_page()` 主 page），
     且晚于 popup 初始响应——不能作为 first-request gate。重构为：
     `context.route("**/*")` 是唯一 first-request gate（含 popup 初始请求
     与 goto 产生的导航）；`on("page")` 降级为 post-creation containment
     （主 page 跳过、about:blank 未导航跳过、`is_admissible` 纯查询不
     计数、非 allowlist popup 只 close 不计 send）。FakeContext.new_page
     现实地同步触发 page 事件。
  3. `new_context(service_workers="block")`：官方推荐——route 不拦截
     Service Worker 控制的请求，必须显式 block，测试断言 kwargs。
  4. egress 记账单一 seam 重构：`admit_request` 纯 admission（attempt+1、
     policy 判定、rebinding 检查，不动 send）；`record_send` 只在
     `route.continue_()` 实际发生后调用（continue 异常 → abort 不计）；
     `is_admissible` 纯查询（navigate 预检/popup containment，不计数）。
     execute NAVIGATE 改用纯查询预检——拒绝仍在 goto 前 fail closed，实际
     导航请求由 route 唯一 admit+send，消除 preflight 双计数；fake
     `page.goto` 现实地经过 context route（请求流测试证明 navigate 恰好
     attempt=1、send=1）。
  5. click 歧义 fail closed：`get_by_role(..., exact=True)` 后用真实
     `locator.count()`，匹配数 ≠1 → `KnownNotExecuted("browser_target_
     ambiguous")` 零点击（duplicate role/name Red 证明）。
- 保留不变：worker confinement、bounded queue、poison/cleanup 语义、
  显式 port 保留、DNS-rebinding fail closed、fake-only API 静态禁令。
- Focused gates（直接运行、pytest 自身 exit code）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/browser/`
  → **187 passed** in 8.44s，exit 0（Task 1 58 + Task 2 93 + Task 3 36；
  中途一次 `test_clear_serializes_against_late_guard_recreation` 时序
  偶发失败，单独复跑与全套复跑均 Green——该测试为多进程确定性编排，
  单次 flake 如实记录）。`.venv/bin/ruff check agent/browser/
  tests/browser/` → All checks passed，exit 0；`git diff --check` → exit 0。
- 边界不变：未安装 Playwright/未启动 Chromium/未联网；未 full/未
  materialize/未 E3；未触禁区；无 commit/push。

## 2026-08-28 — Task 4: pure consequence policy 与 site-bound interactive actions

- 新增 `agent/browser/action_policy.py`、`tests/browser/test_action_policy.py`、
  `tests/browser/test_interactive_actions.py`；扩展
  `agent/browser/playwright_adapter.py`（binding revalidation、interactive
  actions、mode-select launch）与 `tests/browser/fakes.py`（locator
  fill/select_option、BrowserType 级 launch_persistent_context）。
- 主审 mid-turn 更正均已落实：
  - persistent context 用真实 BrowserType API
    （`playwright_handle.chromium.launch_persistent_context`，owner profile
    root 下 canonical profile 目录），不是 browser 实例方法——fake 的
    `FakeBrowser.launch_persistent_context` 恢复为断言防护，静态回归测试
    证明 adapter 源无 `browser.launch_persistent_context`、有
    `chromium.launch_persistent_context`；cleanup 反映 persistent 语义
    （page→context；无独立 browser 对象；public-read 才关共享 browser；
    Playwright stop 仍由 with 退出恰一次最后执行）。
  - `BrowserActionBindingV1` 严格保持 observation+action 的
    consequence/identity/preview 最小集（无 Goal/lease 字段——Task 5 的
    Candidate/Lease 才承载 approval authority）；"approval use" mutation 以
    adapter 的 single-use binding 消费记账满足（`_consumed_bindings`，
    不构成第二套 approval 系统）。
- 纯 policy（只 import contracts）：closed consequence 矩阵（back/reload/
  scroll/close-session/same-origin 无 query 导航/observed link=OBSERVE；
  query/跨 origin 导航、fill/select=DISCLOSE；upload=UPLOAD；download=
  DOWNLOAD；submit 按钮/form 绑定/未知元素语义=COMMIT；模型 risk=low 无
  效）；preview 只用 typed metadata（value 原文只出现 sha256 摘要）；
  binding_digest 冻结 observation/page/frame/origin/target 元数据。
- adapter execute（keyword `binding=`）：mode-select closed action set
  （public-read 拒绝 fill/select；upload/download 的 staging/quarantine 属
  Task 7，本任务 policy 分类、adapter 拒绝执行不降级）；binding
  revalidation（action digest/observation/page/frame 篡改或 single-use
  已消费 → 冻结 `browser_binding_changed`）；effect 前立即 re-resolve
  （同一固定 evaluate 脚本）并比对完整冻结元数据与 origin（漂移 → 冻结
  `stale_browser_target`），零 action/network effect；fill/select/click 只
  用 role/label locator（`get_by_role(..., exact=True)` + `locator.count()`
  歧义 fail closed）。site-bound exact-origin confinement 由 session
  allowed_origins + route guard 保证；launch 失败 fail closed 恰一次尝试
  （延迟 launch 语义下 worker 线程存活、无 fallback 引擎）。
- Focused gates（直接运行、pytest 自身 exit code）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx tests/browser/`
  → **218 passed** in 7.99s，exit 0（Task 1 58 + Task 2 93 + Task 3 36 +
  Task 4 31：action_policy 18 + interactive 13）。`.venv/bin/ruff check
  agent/browser/ tests/browser/` → All checks passed，exit 0；
  `git diff --check` → exit 0。
- 边界声明：全部经注入 fake 验证；未安装 Playwright/未启动 Chromium/
  未联网；未运行 full suite（Task 9）、未 materialize/未 E3（Task 10）；
  唯一 AgentRuntime/model/tool loop 未动；未触禁区；无 commit/push。

## 2026-08-28 — Task 4 审计闭合记录（主审通过前最后一次修复）

- 五项 P0（session authority 绑定、ReceiptError poison、canonical 确认
  时机、url/frame-tree preflight、binding digest closed invariant）与
  类型一致性 blocker（observation profile_revision 改 positive int |
  None，与 durable profile revision 同型，closed contract/projection
  双侧校验）全部按 Red→Green 闭合。
- 最终 focused gates（独立未 pipe、pytest 自身 exit）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/browser/ -rx`
  → **255 passed** in 8.03s，exit 0；`.venv/bin/ruff check agent/browser
  tests/browser` → All checks passed，exit 0；`git diff --check` → exit 0。
- Task 4 覆盖：纯 consequence policy 与 closed binding（digest 唯一
  validate seam）、site-bound persistent context（BrowserType API、owner
  profile root、exact origins）、完整 effect 前 re-observe（逐字段含
  url/frame_tree/form_method）、single-use binding 于首个 effect 前消费、
  零/全 fill、profile path escape 防护、budget/expiry（injected clock）
  在 effect owner 闭合。

## 2026-08-28 — Task 5: Runtime-owned browser authority 与 takeover state

- 新增 `tests/continuity/test_browser_authority.py`（8 测试）、
  `tests/continuity/test_browser_takeover.py`（7 测试）、
  `tests/continuity/test_browser_recovery.py`（5 测试）；修改
  `agent/runtime/contracts.py`、`state.py`、`checkpoint.py`、`context.py`、
  `views.py`、`tests/kernel/test_contracts.py`（closed enum 集合同步）。
- 合同要点：
  - `ExecutionAuthorityClass.BROWSER_SESSION`（closed enum 扩展，015/017
    测试集合同步）。
  - `BrowserActionCandidateV1`（digest 覆盖全部绑定字段——Goal/revision/
    session/browser identity/profile binding/origins/mode/page/frame/
    observation/action/consequence/preview/issued/expires/max_uses=1；
    replace 篡改 digest 构造层拒；mode/consequence 为 closed 字符串值，
    runtime 不 import browser 包——依赖方向保持 browser → runtime）。
  - `BrowserAuthorityLeaseV1`（exact `authorizes`：全部 identity exact
    equal、public-read lease 拒非 observe consequence、RFC3339 now 过期
    判定、`with_use_consumed` 超 max_uses 构造层拒）。
  - `BrowserTakeoverRequestV1` + typed `CompleteBrowserTakeover`/
    `CancelBrowserTakeover`（RuntimeAction 子类）。
  - `ApprovalRequest.browser_action_candidate`（单字段=结构上限"至多一个
    strict browser candidate"；checkpoint codec 演进 browser_keys 集合）。
  - `ConversationState.browser_leases/browser_takeover_pending`。
- state 层（复用现有 reducer 模式，无第二 runner/policy owner）：
  - `_mint_browser_authority_lease`：ResolveApproval(approved) 对 browser
    candidate 铸 lease；expiry 锚定 candidate 的 RFC3339 expires_at。
  - `begin_browser_takeover`：pending 在暴露前持久化（revision CAS+1）；
    已有 pending fail closed；期间零 provider/tool 活动（facts/active_run
    原样）。
  - `complete_browser_takeover`：exact request/session/profile 校验 → 清
    pending、期望 profile revision+1、强制 fresh observe
    （BrowserTakeoverCompletion），不铸任何 commit approval
    （browser_leases 原样不动）；`cancel_browser_takeover` 清 pending。
  - goal terminal（cancel_goal）使 browser_leases 失效。
- checkpoint：state codec 序列化 browser_leases/pending takeover（旧
    checkpoint 缺字段按空迁移）；pending request codec 增加
    browser_action_candidate（known_key_sets 演进）；round-trip 后 pending
    精确保留；序列化无 monotonic 字段（durable 时间全 RFC3339 字符串）。
- views/context：`project_browser_takeover_status`（重开投影
    "browser takeover waiting" + /browser-done + /cancel，无 "resuming"；
    丢失/漂移 session → needs-human）；`advertised_browser_controls`
    （pending 期间只 advertise complete/cancel）。
- security：序列化 checkpoint 扫描 password/cookie/storage_state/
    form_value/credential/hunter2 sentinel 全部缺失。
- Focused gates（直接运行、pytest 自身 exit）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/continuity/test_browser_authority.py tests/continuity/test_browser_takeover.py tests/continuity/test_browser_recovery.py tests/kernel/test_runtime_approval.py tests/kernel/test_effect_ordering.py tests/kernel/test_context_manager.py tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_contracts.py tests/kernel/test_state_transitions.py -rx`
  → **61 passed** in 0.21s，exit 0。Touched Ruff → All checks passed，
  exit 0；`git diff --check` → exit 0。
- 边界：未跑 full；唯一 AgentRuntime loop 未动（takeover controls 走
    typed RuntimeAction/state reducer，无 browser runner）；未触禁区；
  无 commit/push。

## 2026-08-28 — Task 5 二轮审计修复：真实 Runtime 路径

- 审计 8 项全部按 Red→Green 闭合（12 个新 Red 初始失败 → 全 Green）：
  1. `CompleteBrowserTakeover`/`CancelBrowserTakeover` 进入 `Action` 联合
     与 `canonical_action_digest`；`AgentRuntime.run_turn` 实际处理两者
     （state legal/apply 分支 + loop `_finish` COMPLETED 分支）。
  2. `ResolveApproval(approved=True)` 经 reducer 实际铸造 browser lease
     （`_mint_browser_authority_lease` 接入 apply 链）；混合
     process/sandbox/browser candidate 在 `ApprovalRequest.__post_init__`
     fail closed。
  3. browser ToolResult 的 typed `browser_takeover_request` 字段：唯一
     AgentRuntime 在 tool result 处理链先 `begin_browser_takeover` 持久化
     pending 再继续（`_interpret_browser_takeover_tool_result` 为同一真实
     路径的显式方法）；pending 期间 `_run_locked` 入口 gate 使
     provider/tool/observe/recording 为零（非 typed controls 一律
     CONFLICT/browser_takeover_pending）。
  4. `KernelContextManager.build` 实际投影：pending 时 system 只含
     takeover waiting + /browser-done + /cancel 文本；无 pending 不含。
  5. goal correction（CORRECT control）与 cancel 均清空 browser_leases。
  6. RFC3339 比较改为解析后的 zoned datetime（`_parse_browser_datetime`），
     不再依赖字符串序（`10:00-07:00` = 17:00 UTC 正确判过期）。
  7. codec unknown/partial fail closed：browser takeover/candidate/lease
     的 `_expect_keys` strict 拒绝（CheckpointVersionError）。
  8. restart 后 `LocalCheckpointStore.load()` + Runtime typed action
     完成/取消走通（run_turn COMPLETED、pending 清除）。
- 途中修复：helper 误占 `_tool_result_fact` 的 `@staticmethod` 导致
  runtime_turn 回归（已恢复并回归 Green）。
- Focused gates（直接运行、pytest 自身 exit）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/continuity/test_browser_authority.py tests/continuity/test_browser_takeover.py tests/continuity/test_browser_recovery.py tests/kernel/test_runtime_approval.py tests/kernel/test_effect_ordering.py tests/kernel/test_context_manager.py tests/kernel/test_checkpoint.py tests/kernel/test_checkpoint_recovery.py tests/kernel/test_contracts.py tests/kernel/test_state_transitions.py tests/kernel/test_runtime_turn.py -rx`
  → **76 passed** in 0.24s，exit 0（新增 15：authority +5、takeover +7、
  recovery +3）。Touched Ruff → All checks passed，exit 0；
  `git diff --check` → exit 0。
- 边界：未跑 full；唯一 AgentRuntime loop 保持（takeover 经 typed action
  reducer，无第二 runner/policy owner）；未触禁区；无 commit/push。

next_task=6

## 2026-08-28 — Task 6: governed browser tools 与 exact effect authority

- 新增唯一五项 browser registrations：`browser_open`、`browser_observe`、
  `browser_act`、`browser_close`、`browser_begin_takeover`；schemas 为 closed
  surface，不暴露 raw JS/CSS/XPath/CDP/launch args/host path，callables 不捕获
  Provider/ContextManager/checkpoint/AgentRuntime。
- `KernelToolRuntime` 仍是唯一 admission/approval/invoke owner：non-OBSERVE
  `browser_act` 生成 exact `BrowserActionCandidateV1`，只接受 current Goal/
  session/profile/browser/origin/page/frame/observation/action/consequence 的 durable
  single-use lease；`EXECUTING` checkpoint 在 adapter effect 前消费 use。
- `BrowserGovernance` 只归一化 exact BROWSER_SESSION result kinds；browser callable
  不能自授权、不能伪造 source receipt。真实 `AgentRuntime` 集成测试证明：open
  approval 前 adapter open=0；DISCLOSE approval 前 execute=0；批准后恰好执行一次，
  result checkpoint 后 lease `uses_consumed=1`，并经同一 ToolRuntime close。
- Focused gates（pytest 自身 exit 0）：browser tools/authority、takeover flow、runtime
  approval/effect ordering/governance 共 **63 passed**；touched Ruff 与
  `git diff --check` 均 Green。未跑 full/materialized/E3；无真实 browser/network I/O；
  未触禁区；无 commit/push。

next_task=7

## 2026-08-28 — Task 5 三轮审计：移除私有-helper 假阳性并闭合真实 takeover

- 上一轮记录中的 `_interpret_browser_takeover_tool_result` 测试只直接调用私有
  helper，没有经过 `run_turn → ToolRuntime.invoke → ToolResult → checkpoint`；该
  证据已判无效，helper 与对应测试均已删除。
- 新的真实 Red 证明 browser callable 返回 `ToolResult` 会被唯一 ToolRuntime 的
  防伪门改写为 `source_contract_mismatch`，因此 pending 从未持久化。最小 Green
  改为：governed `browser_begin_takeover` callable 只返回无 authority 的 typed
  `BrowserTakeoverRequestV1`；ToolRuntime 仅在 exact BROWSER_SESSION/tool name/Goal
  identity 全匹配时归一化为 `ToolResult.browser_takeover_request`，其他形状 fail
  closed。
- 唯一 AgentRuntime 在 durable ToolResult 后同一 CAS 写入 pending、使旧 browser
  action leases 失效、释放当前 invocation ownership，并立即返回
  `browser takeover waiting for user`；不再调用下一轮 provider/tool。pending 期间
  普通 `SubmitMessage` 入口 gate 保持 provider/tool 为零；typed complete/cancel
  清 pending 后重新 claim 原 active run 并恢复同一 `_drive`，没有第二套 loop。
- `begin_browser_takeover` 现在要求 request 的 Goal ID/revision 与当前 durable Goal
  exact 匹配；错误 Goal 在 state mutation 前拒绝。
- Focused gates（pytest 自身 exit 0）：Task 5 三个原 continuity 文件 + 真实 flow、
  approval/effect-order/context/checkpoint v2/v4 共 **77 passed**；touched Ruff 与
  `git diff --check` 均 Green。未跑 full/materialized/E3；无外部 browser I/O；
  未触禁区；无 commit/push。

next_task=6

## 2026-08-28 — Task 7: upload staging 与 download quarantine

- 新增 browser-owned `BrowserQuarantine` 与 bounded download receipt：upload 只接受
  workspace-relative regular file、25 MiB cap、exact SHA-256；approval 与 invoke
  前都重验 device/inode/size/mtime/digest，同内容换 inode 也零 upload。批准后才复制到
  one-shot staging，adapter 只接收 staging path，调用结束清理。
- download 只写入 0700 quarantine，100 MiB cap，opaque exclusive filename、bounded
  MIME/size/SHA/origin/action identity receipt；durable metadata 不含 host path。未批准
  download 由 Playwright event handler 取消；批准后 click/save 已发生而 quarantine
  finalization 失败时异常上抛、session poison，绝不降格为 known-not-executed。
- descriptor/no-follow 边界按 Red→Green 收紧：quarantine root 逐级 no-follow 创建，
  source parent symlink 拒绝，session cleanup 使用 anchored dirfd 且先完整验证后删除，
  被替换成 symlink 时不触碰外部文件；opaque ID 碰撞使用 exclusive link，绝不覆盖旧
  download。`KernelToolRuntime.invoke` 将 revalidation binding 异常统一归一为
  `IntentConflictError`，证明 callable 尚未调用。
- Focused gates（pytest 自身 exit 0）：`tests/browser/` 加 browser authority/recovery/
  takeover continuity 共 **320 passed** in 9.83s；另 tool-runtime/workspace revalidation
  **18 passed**。Touched Ruff 与 `git diff --check` 均 Green。
- 边界：未跑 full（Task 9）、未 materialize/真实 Chromium E3（Task 10）；未安装或
  下载 Chromium；未触禁区；无 commit/push。

## 2026-08-28 — Task 8: optional composition, CLI UX, evidence oracle（candidate）

- 垂直切片全部 Red→Green：
  1. `BrowserResources(registrations, closeables, readiness, reason_code)` 与
     `build_browser_resources(workspace, state_root, *, enabled, resolver=None,
     playwright_factory=None, binary_probe=None, egress_ready=None)`
     （agent/composition.py）。disabled → 零 registration/NOT_ENABLED；无
     playwright → TEMPORARILY_UNAVAILABLE + 唯一 closed reason
     `browser_package_missing`；profile root 权限破坏 →
     `browser_profile_permissions`；binary probe False →
     `browser_binary_missing`；egress probe False →
     `browser_egress_unavailable`；注入 fake factory → READY + 五个唯一
     registration（browser_open/observe/act/close/begin_takeover）+
     reverse-close closeables。签名无 allow_private/disable_guard；无
     Chrome/Safari/CDP fallback；冻结精确四字段接口（无 environment
     seam——ownership 经 governed registration 路径的真实关闭行为证明）。
  2. CLI：`_browser_status_lines`（恰好一条 readiness 行 + 一条 next
     action，无 traceback/path/cookie/account）；`--browser` flag 经唯一
     composition root 接入（registrations/closeables/startup 行）；
     user-only `browser_profile_user_command`（list/revoke/clear，opaque id
     only）与 `handle_browser_user_command`（/browser-done、/browser-cancel
     铸造 typed Complete/CancelBrowserTakeover；/browser-profiles* 走
     profile 命令）；takeover pending 的 restart 投影
     （RestartProjection.browser_takeover_pending → "browser takeover
     waiting" + /browser-done + /cancel，绝不 "resuming"）。
  3. closed browser readback evidence oracle：`EvidenceOracleKind.
     BROWSER_READBACK` + `_browser_readback`（predicate exact closed：
     receipt_kind=browser_readback_v1 + receipt_digest + session_ref +
     readback_observation_digest + profile_revision（public-read 为 None）+
     browser_identity_digest）。证据 = 两条 durable facts：identity 全等、
     executed、非 error、非 fake、outcome=effect_applied 的
     browser_action_v1 receipt，加上同 session/profile/browser identity
     且 digest 精确匹配的后续 browser_observe；identity 不用顺序替代；
     纯推导不调用 browser/tools。
  4. 审计闭合（load-bearing）：production `agent/browser/tools.py` 的
     action receipt metadata 补齐 session_ref/profile_revision/
     browser_identity_digest（observe 原已具备）；端到端测试证明真实
     `_BrowserTools.act`+`observe` 输出直接满足 evidence oracle
     （非手工 fixture）。
  5. 唯一 owner 保持：静态断言 composition 只有一个 AgentRuntime 构造点、
     无 BrowserRuntime；browser 只经 build_browser_resources 进入。
- 文档保守更新：README/STRATEGY/CURRENT_CAPABILITY_STATUS 均标注 018 为
  implemented candidate（非 delivered；materialized E3 与独立 review 属
  Task 9-10）。
- **二轮审计闭合（同日）**：先前 BLOCKED 的四项全部 Red→Green：
  1. `_browser_qualification_reasons` 增加 bundled Chromium binary 与
     egress readiness 两个 closed qualification：production 只读探测
     （`_default_browser_binary_available` 只检查已安装 playwright 能否
     定位 executable path，不启动/下载；`_default_browser_egress_ready`
     只验证 resolver 构造成功），测试经 `binary_probe`/`egress_ready`
     constructor seam 注入 False，分别得到
     `browser_binary_missing`/`browser_egress_unavailable` + 零
     registration。qualification 优先级 package→permissions→binary→egress。
  2. CLI `/cancel` 在 takeover pending 时映射为 CancelBrowserTakeover
     （真实 pending state 测试）；无 pending 返回 None 交还原路径。
  3. `render_browser_approval_preview`：exact/bounded（consequence/kind/
     origin/字段名/value digest），≤512 字符，无 secret/path/cookie/account。
  4. `BrowserProfileStore.list_profile_ids()` 公开接口（dirfd 锚定、
     canonical opaque ID only）；`browser_profile_user_command` 的 list
     改用公开接口，不再触碰私有 `_root`。
- **三轮审计（冻结接口纠正 + shutdown fail-closed，awaiting fresh
  audit）**：`BrowserResources` 必须严格只有 registrations/closeables/
  readiness/reason_code 四个冻结字段——先前的 `environment` 只读 seam
  已删除（字段、docstring、返回赋值全部移除）。shutdown ownership 测试
  改为经 `resources.registrations` 的真实 governed 路径：
  `KernelToolRuntime` + `browser_open` approval（ApprovalGrant）+
  `browser_observe` 打开 composition 拥有的 session（journal 观察
  launch==1），随后执行 `resources.closeables` 并经 injected
  factory/journal 断言 Playwright stop 恰一次。新增
  `test_browser_resources_has_exact_frozen_four_fields`
  （`dataclasses.fields` 精确四字段断言防回归）。
  `PlaywrightBrowserEnvironment.shutdown` 收紧为 fail closed：任何 session
  的 cleanup 为 CLEANUP_UNKNOWN、或收尾后 worker 仍存活时抛出
  `BrowserCleanupUnknownError`（session 已标记 unusable，无 fallback）；
  新增真实 closeable-path 失败回归
  （`test_shutdown_fails_closed_when_session_cleanup_unknown`：经 governed
  open 后注入 page.close 失败 → shutdown 必须抛错，绝不从成功-only
  journal 断言宣称清理闭合）。
- Focused gates（无 pipe/tail，pytest 自身 exit code）：
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/browser/
  tests/continuity/test_browser_verified_done.py tests/continuity/
  test_browser_authority.py tests/continuity/test_browser_takeover.py
  tests/continuity/test_browser_recovery.py tests/continuity/
  test_browser_takeover_flow.py tests/cli/test_018_browser_experience.py
  tests/kernel/test_evidence_registry.py -rx --tb=short`
  → **371 passed** in 10.48s，pytest exit 0（中途一次
  `test_clear_serializes_against_late_guard_recreation` 多进程时序偶发
  失败，单独复跑与全套复跑均 Green——与 Task 4 记录的同一已知 flake）。
  Touched Ruff → All checks passed，exit 0；`git diff --check` → exit 0。
- 边界：未跑 full（Task 9）、未 materialize/真实 Chromium（Task 10）；
  未触禁区；无 commit/push。

- **四轮审计（冻结签名/真实渲染/Goal 绑定，awaiting fresh audit）**：
  1. `build_browser_resources` 公开签名冻结为 `(workspace, state_root, *,
     enabled, resolver=None, playwright_factory=None)`——公开的
     binary_probe/egress_ready 测试旋钮已移除；binary/egress qualification
     改为模块级私有 seam（`_browser_binary_available_for_factory`/
     `_BROWSER_EGRESS_SEAM`，测试 monkeypatch，production 仍为真实只读
     探测）。新增 `test_public_signature_is_exactly_frozen`
     （`inspect.signature` 精确参数列表/kind/default 断言）。
  2. production-dead `main.render_browser_approval_preview` 已删除；测试
     改为真实 governed **browser_act** 审批 UX（五轮审计精化）：
     site-bound `browser_open`（ApprovalGrant 批准并 invoke）→
     `browser_observe` → DISCLOSE `fill_form` 经实际 BrowserActionPolicy/
     `KernelToolRuntime.prepare` 得到 `ApprovalRequired.request.preview`
     与 browser_action_candidate；只将该真实 approval 数据投影为
     `APPROVAL_REQUESTED` RuntimeEvent 交真实 `TerminalRenderer` 渲染。
     断言 preview 含 fill_form/canonical origin/disclose/字段名（Email）、
     ≤512 字符，且原值（secret）、password、cookie、/Users/、account、
     tmp_path 全部缺失——无平行 preview/event 构造，不只断言工具名。
  3. browser completion evidence 绑定当前 Goal：production
     `agent/browser/tools.py` 的 action receipt 与 observe metadata 均补
     trusted `goal_id`/`goal_revision`（来自 `BrowserSessionSpecV1`，
     spec identity digest 已覆盖）；`_browser_readback` 要求 receipt 与
     readback observe 的 Goal 绑定与当前 `derive(goal_id, goal_revision)`
     全等。新增两个 Red：internally-consistent 但 old goal_id / old
     goal_revision 的 action+readback 均不得满足当前 completion。
     predicate 形状不变，无第二 evidence 路径。
- **Codex fresh audit PASS（2026-08-28）**：独立复跑 51 passed；冻结 public
  signature、BrowserResources 四字段、唯一 provider.generate/ToolRuntime
  invoke owner、touched Ruff、git diff --check 全 Green。Task 8 complete。

next_task=9

## 2026-08-28 — Task 8 fresh ordinary-UX audit + Task 9 intentional Red

- 修复三条此前未被 focused gate 覆盖的真实用户路径：site-bound persistent
  context 显式 `headless=False`；composition 将同一 `BrowserQuarantine` 同时
  注入 adapter 与 governed tools；takeover/profile 命令现经真实 `run_repl`
  入口解析，不再依赖 production-dead helper。
- 新用户 profile 路径闭合：`/browser-profiles create <canonical HTTPS origin>
  <account label>` 是 user-only control，只回显 opaque profile ID；profile
  create 与 composition 共用同一 browser identity derivation，site-policy
  digest 与后续 site-bound exact origin set 不一致时在 ToolRuntime prepare
  阶段 fail closed，零 browser I/O。模型工具面仍只有冻结的五个 browser tools。
- Focused browser/CLI gate：**322 passed** in 9.87s；touched Ruff 与
  `git diff --check` Green。
- Task 9 harness 已收紧为 strict 3-attempt identity/counter/subcheck schema，
  并增加“journey verdict 不得 literal True”的 AST oracle。当前该 oracle
  故意为 Red（runner 中 33 个占位 verdict），所以尚未跑 source full、未 seal、
  未 materialize、未生成真实 E3 receipt；旧/占位结果不得用于 promotion。

next_task=9-real-observations

## 2026-08-28 — Task 9 real observations、recovery closure 与 verifier

- 用真实 Playwright 1.62 + bundled Chromium revision 1234 + deterministic hostile TLS
  fixture 替换全部占位 verdict；13 条 journey 的每个 subcheck 都来自实际
  browser/tool/store/evidence 观察，无 literal `True`。单次串行诊断最终 J1–J13
  全部 Green，exit 0，stderr 无 traceback、pending Task 或 TargetClosedError。
- 真实 egress 闭合：HTTP(S) route 使用 `fetch(max_redirects=0)`，每个 redirect
  target 在发送前重新 admission；WebSocket 使用 `route_web_socket` pre-connect；
  denied popup/frame/subresource/WebSocket/redirect 对 adversary server 均为零请求。
  test-only TLS route proxy 只做固定 public host→loopback fixture 映射，不进入产品
  URL policy 或 production composition。
- 真实 takeover 闭合：worker idle 时只泵 Playwright driver events，不 observe、不记录、
  不触发 Runtime/provider/tool；login response 确认后才完成 takeover，profile revision
  精确 +1，旧 session binding 失效但仍可 cleanup。
- unknown recovery 闭合：effect 后 adapter crash 保持 durable `EXECUTING` unknown，禁止
  replay；poisoned handle 禁止 observe/execute，但显式 browser_close 仍到达 worker 并
  清理 page/context/browser。close 不擦除 unknown recovery evidence。
- Chromium qualification 生命周期噪声根因是 Playwright 仅查询 executable path 时在主
  进程启停 driver；已改为 bounded child-process probe，捕获 child stderr，产品进程
  J1 readiness 复跑干净。base install 仍不依赖 Playwright，不自动下载、不 fallback。
- receipt schema/reducer 已从 test harness 收到 `scripts/run_018_e3.py` 单一实现；harness、
  verifier 共用同一 exact 3-attempt/13-journey/counter reducer。新增 018 overlay verifier：
  runner/fixture/journey scripts 进入 sealed materialized root，seal/log/verifier/receipt/
  review/wheel artifact 为 detached controls；untracked `tui/` 与 `build/` 明确不 admission。
- Focused gate：browser + browser continuity/CLI + 018 reference/harness/verifier 共
  **499 passed** in 21.59s，exit 0。一次旧 `route.continue` 断言因 single-hop
  redirect-safe 实现而失败，改为断言 `fetch(max_redirects=0)`、fulfill 与 exactly-one
  send 后同一完整 focused gate Green。
- 尚未宣称 Task 9/018 complete：下一步先跑 touched Ruff/diff-check，再做唯一一次 source
  full；source freeze 后写 018 seal，随后才执行 clean materialized/full 与真实 3×13 E3。

next_task=9-source-full

## 2026-08-28 — Task 9 source-full closure

- 第一次完整 source gate 暴露 **30 个真实失败**（`2128 passed, 30 failed`）：
  4 个 architecture oracle 尚未纳入 018 browser package/authority owner，另 26 个由
  checkpoint v7 encoder 漏写 `browser_action_candidate` 引起。修复后原 30 项全部 Green，
  checkpoint/architecture 聚焦组 **60 passed**。
- 第二次完整 source gate 收敛为 **1 failed, 2159 passed**：旧 v5 migration fixture 在把
  current v7 payload 降级时没有删除 018 browser key；fixture 改为真实 v5 shape，相关组
  **48 passed**。
- 第三次完整 source gate 仍为 **1 failed, 2159 passed**，定位到
  `BrowserProfileStore.clear()` 的真实 TOCTOU：root guard 在最后 `rmdir` 前释放，晚到 writer
  可重建 lock 并把 cleanup 变成 `CLEANUP_UNKNOWN`。实现现持有同一 guard 覆盖 revoke、
  descriptor-safe tree removal 与最终 canonical `rmdir`；精确 race 连续 5 次 Green，完整
  profile/session 组 **93 passed**。
- 最终 source freeze gate（修复集稳定后只重跑一次）：
  - `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx` →
    **2160 passed in 233.84s**，exit 0，输出完整未截断；
  - `.venv/bin/ruff check .` → All checks passed，exit 0；
  - `git diff --check` → exit 0。
- 未读取/纳入 `.env`、secret、credential、private/runtime、未跟踪 `tui/` 或 browser
  profile/cache；无 commit/push。下一步只创建 detached 018 seal control，验证 exact
  membership/control 后进入 clean materialized gate 与正式真实 Chromium 3×13 E3。

next_task=9-seal

## 2026-08-28 — Task 9 first seal invalidation and closed-oracle repair

- 首个 018 delivery candidate 在 source/materialized/full/真实 Chromium 3×13 Green 后，fresh
  Spec reviewer 仍用真实 Chromium mutation 证明两项 U2 oracle 可空过，因此该 identity 未晋级：
  J2 只看到静态 `Storage seeded` 文本、没有证明 cookie 与 localStorage 真的先存在；J4 用总
  attempt 数证明五类拒绝，删除 popup trigger 后仍可能 Green。
- J2 现先在独立 probe 中同时读回 cookie 与 localStorage 已存在，clean close 后由 fresh
  session 证明两者均 absent；no-seed、only-cookie、only-localStorage 与任一 fresh reuse 都
  fail closed。
- J4 现由 egress guard 记录 closed `RequestKind -> integer` attempt/rejection/send counters；
  receipt 不含 URL、页面正文或请求内容。redirect、popup、frame、subresource、WebSocket
  分别要求自身 attempt/rejection 增加且 send 保持零，移除任一 trigger 都使整旅程失败。
- 以上修复属于 ordinary source，首个 seal/materialized/receipt 均按合同作废；没有复用旧
  identity，也没有把旧 Green 当作 promotion evidence。

next_task=9-final-freeze

## 2026-08-28 — Task 9 final freeze, materialized E3 and U3 closure

- Final source gate：
  - `git diff --check` → exit 0；
  - `.venv/bin/ruff check .` → All checks passed；
  - `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx` →
    **2203 passed in 284.31s**，exit 0，输出完整。
- Final ordinary delivery identity：
  - entry count：`309`；
  - overlay root：`a32e575cbe248618d3c1468cbcb64e38b4d0dde0e026c15406ae966a4a052363`；
  - seal SHA-256：`5d187b2794c282c5ec8f3ac71aff337a441088c1123799b86e76c2aec67ed421`；
  - base manifest：`4da6fe1f158bf0c57ef6c2160ce9076a90b1125404e32f5ee2d81fd86460e74f`；
  - 017 parent seal：`527f47ce26a9eb2f8311fa4a78684dd6854f0e9dfe81dac91a31bc89817989d1`；
  - verifier：`5b10ae6d053ee09d4775bc8886fc84d15841b17e2825a377fe396569b01d0a21`。
- Clean materialized gate 从 sealed tree 构建 wheel，并在 clean venv 安装 browser extra：
  **2201 passed, 2 skipped in 250.07s**，exit 0；materialized root
  `5d8490689aec430c625d7086c5bb53d7a92130ac4a3aba4d3abb1d8715152d41`，wheel
  `07bab579db23314fc29f5befa2ddf6ecbbe0ee14e9cbfe8abf90e0dcc5ee146b`。
- 正式 U2 使用 Playwright `1.62.0`、Chromium revision `1234` 驱动真实 hostile TLS
  fixture；三次 attempt 各 **13/13 journeys true**、claim gate **63/63**。receipt SHA-256
  为 `c731b59dc7941decdf680a622278c97df135c8d24268137322c6313bdba1d1ba`；membership、
  control-seal、attestation 均 exit 0。
- Fresh U3 两轴均独立 PASS：Spec/Product reviewer 亲跑 544 个 018 focused tests，并对
  J2 三种 seed 缺失、J4 五种 trigger 缺失、J6 no-headed 做真实 Chromium mutation；
  Standards/architecture reviewer 亲跑 229 个 focused tests，确认 telemetry 仅含 closed
  counters、CLI 仍为 typed action adapter、`AgentRuntime.run_turn`/`ContextManager`/
  `ToolRuntime` ownership、takeover ordering 与 cleanup fail-closed 均未漂移。
- Detached independent review 已绑定以上 exact identity；该 detached 记录不改变 ordinary
  root。018 v1 只晋级 frozen dedicated-Chromium/bounded-sites-and-actions scope，不扩张为
  personal browser、desktop control、任意站点兼容、后台 autonomy 或 production-ready 声明。
- 未读取/纳入 `.env`、secret、credential、private/runtime、未跟踪 `tui/`；无 commit/push。

next_task=019-research
