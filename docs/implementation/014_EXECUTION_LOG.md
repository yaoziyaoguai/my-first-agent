---
title: 014 Grounded Workspace Knowledge Agent - Execution Log
type: implementation-log
date: 2026-08-04
authority: 014-execution-evidence
status: in-progress
---

# 014 Grounded Workspace Knowledge Agent — Execution Log

## 0. 记录规则

本文件只记录可复现事实，不拥有产品要求。每个 executor/Codex handoff 必须追加：owner、active U-ID、准确
Red/Green、命令、exit code、输出是否完整、changed files、decision/deviation、remaining gate。不得覆盖失败、预填
测试数、把 timeout/截断/fake/model self-report 写成 pass。

权威顺序见 `docs/implementation/014_LOOP_HANDOFF.md`。

## 1. Planning freeze（2026-08-04）

- Owner：Codex（planning only）
- Branch：`main`
- HEAD at planning start：`1e89417` (`feat: deliver everyday workspace agent`)
- Remote baseline：`origin/main` 同一 commit（planning start observation）
- Pre-existing user content：未跟踪根目录 `tui/`，只记录类别；未读取、删除、覆盖或纳入。
- Secrets/private/runtime：未读取。
- Commit/push：未执行。

### Materials created

- `docs/plans/2026-08-04-001-feat-grounded-personal-knowledge-agent-plan.md`
- `docs/architecture/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_DESIGN.md`
- `docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_E3.md`
- `docs/implementation/014_LOOP_HANDOFF.md`
- 本 execution log

### Planning evidence used

- 013 verified baseline、Kernel/Extension contracts、capability evidence closure lessons。
- Repo-grounded review of ContextManager/Memory scope、session horizon、WorkspaceBoundary、ToolRuntime/evidence seams。
- Agent-native flow review of history/action/context parity、Web authority、source receipts、citation and outcome limits。
- Tavily official Search/Extract API docs and OWASP SSRF guidance。

### Settled implementation direction

- current exact workspace history only；legacy unbound goal-less checkpoint 不召回。
- History JIT tools，不自动 ContextSource。
- descriptor-relative workspace search，不 shell-out。
- domain read 与 network egress 正交；Web per-call exact approval。
- fixed Tavily Search/Extract；不从本机 direct fetch source host。
- Kernel-validated SourceReceipt；ContextManager 投影 data class/untrusted。
- citation oracle 证明 provenance linkage，不声称 semantic truth。
- outcome projection 只读，不晋级 Memory/Skill，不自主优化。

## 2. Baseline gates

Status：**source baseline Green；U0 architecture Red 已准确命中**。

2026-08-04，owner=Codex，planning docs 落盘后完整运行：

- `git diff --check` → exit 0，完整输出。
- `.venv/bin/ruff check .` → exit 0，`All checks passed!`。
- `.venv/bin/python -m pytest -q -rx` → exit 0，`730 passed in 197.80s`，输出完整。

U0 implementation 起点补充（2026-08-04，owner=Codex）：

- `git status --short --branch` → `main...origin/main`；仅本轮五份 014 docs、`STRATEGY.md` 与用户未跟踪
  根目录 `tui/`；后者未读取/触碰。
- architecture search → production `.generate(`、`.invoke(`、`.compare_and_swap(` 仍只在
  `agent/runtime/loop.py`；CLI、TUI、Scheduler 和 SubAgent 只调用同一 `AgentRuntime.run_turn`。
- `.venv/bin/python -m pytest tests/architecture/test_cutover_absence.py
  tests/architecture/test_dependency_dag.py tests/reference/test_013_everyday_workspace.py -q -rx`
  → exit 0，`11 passed in 4.30s`，输出完整。
- 013 的三个 materialized 命令当前均 exit 1：`expected 104, actual 109` 与 overlay digest drift。原因是五份
  新 014 文档尚未进入新的 014 seal；这是 U8 要闭合的预期 materialization Red，不是被隐藏的 013 pass。
- 新增 `tests/architecture/test_014_grounded_workspace_layer.py`；首次 focused run exit 1，`2 failed in
  0.06s`，准确缺失 `EgressClass` 与 `RecoverUnknownObservation`，未同时写 production Green。

上述 730 是当前 source baseline，不是 014 implementation pass；review 后文档变化仍需重新跑 `git diff --check`。

## 3. Unit ledger

| Unit | Owner | Red | Green | Exit | Notes |
|---|---|---|---|---|---|
| U0 Baseline/contract | Codex | 2 accurate failures | existing invariants 11 passed | closed | 013 seal drift 转交 U8；014 contract Red 转交 U2 |
| U1 Context/source | Codex | production entrypoint scope mismatch | 544 relevant passed | closed | exact identity/context scope split + source validation |
| U2 Grounding contracts | Codex | 6 accurate failures + 1 contract Red | 520 relevant passed | closed | egress/output/receipt/recovery/context/UI |
| U3 History | Codex | 4 binding Reds + integration conflicts | 536 relevant passed | closed | v3 binding + bounded catalog/tools/outcome |
| U4 Workspace search | Codex | 7 accurate failures | 456 relevant passed | closed | descriptor-relative budgets + source E2 |
| U5 Tavily Web | Codex | 4 accurate collection errors | 547 relevant passed | closed | fixed destination + approval E2 |
| U6 Research evidence | Codex | 1 collection Red | 16 focused passed | closed | Runtime citation oracle + production completion path |
| U7 Product journeys | Codex | 3 UX/composition Reds | 290 relevant passed | closed | source surfaces + integrated restart journey |
| U8 Materialized docs | Codex | 3 delivery Reds + known tree-manifest Red | 842 materialized passed | closed | v3 seal/E2M |
| U9 Real E3 | Codex | 7 harness Reds + live diagnostics | 3 consecutive live runs, 19/19 each | closed | secret-free receipt set |
| U10 Full review | Codex | held-out + post-held-out review | full gates 925 + fresh review no P0/P1/P2 | closed | frozen E3 三连 + mandatory held-out + full gates；见 §9.3 |

### U1 evidence（2026-08-04）

- Red：新增真实 `main → build_composition → MemoryContextSource → ContextPack` 测试；首次 exit 1。Memory store
  使用稳定路径 scope，而旧 composition 用 exact filesystem identity 查询 source，故 `ORCHID-014` 不在 model
  context。Goal bootstrap 的 exact `workspace:v1:*` identity 同时受测试保护，不能用修复 Memory 为由降级。
- Green：`KernelContextManager` 与 `build_composition` 分离 `workspace_identity_digest` / `context_scope_digest`；
  `main` 传入 session exact identity 与 Memory path scope，workspace Memory source 排在 owner preference 前。
- Hardening：Kernel 校验 source/snapshot/candidate name、scope、content digest、snapshot digest、item/token/provenance
  cap；截断 excerpt 使用独立 digest，并保存 original digest/truncation provenance。Memory source 按请求 item/token
  budget 构造 deterministic snapshot。
- Focused：U1 初始相关套件 `106 passed in 3.50s`；补齐 mutation/cap/clip tests 后 `36 passed in 2.43s`。
- Broad touched-area：kernel/memory/provider/continuity/cli/reference/subagent/scheduler 共 `544 passed in 18.41s`，
  exit 0，输出完整。
- `git diff --check` 与 touched-file Ruff 均 exit 0。未调用真实 provider，未读取 secret/private/runtime，未触碰
  根目录 `tui/`。

### U2 evidence（2026-08-04）

- Red：新增 source/egress/recovery tests，首次 focused run exit 1，`6 failed, 7 passed`；准确命中 callable-owned
  result/data-class、PUBLIC_NETWORK approval、Context receipt mapping 与 fixture recovery identity。另加 stable
  source ID test 首次 exit 1，证明旧实现错误地把内容 digest 纳入 source identity。
- Contracts：closed `EgressClass` / `SourceKind`、`ToolExecutionOutput`、`SourceReceiptDraft/V1`、
  `SourceAuthorityBinding`、`RecoverUnknownObservation`；Kernel 而非 callable 铸造 receipt/data class/source ref。
- Egress/recovery：PUBLIC_NETWORK 固定 READ_ONLY + ALWAYS approval；`approval_basis_revision` 跨 approval bookkeeping
  保持稳定；send 后异常不展平成 `executed=false`，而是 durable unknown observation。Typed recovery exact bind
  tool/intent，恰好一次追加无 receipt/evidence 的结果，replay 不重发；WRITE generic recovery 回归保持 Green。
- Authority/context：Runtime 只从同 conversation、passed canonical `web_search_snippet` fact 解析 opaque ref；
  ContextManager 重验 receipt 后映射 `first_agent_history/workspace_excerpt/public_web_content` 并标记 untrusted；
  history/Web source 不能借文本相等获得 Memory admission。新增 data class 会强制新的 provider disclosure。
- UX/restart：CLI/TUI/headless view 对 PUBLIC_NETWORK unknown 不再要求用户猜成功/失败，只允许记录
  `observation_unknown` 后继续或停止，并明确不会自动重试；generic WRITE recovery UX 不变。
- Focused source/recovery/checkpoint/provider suite：`24 passed in 0.25s`；CLI/TUI focused：`68 passed in 4.41s`。
- Broad relevant：kernel/continuity/provider/cli/tui/reference `520 passed in 12.45s`，exit 0，输出完整；
  `.venv/bin/ruff check .` 与 `git diff --check` 均 exit 0。
- 未调用网络/provider，未读取 secret/private/runtime，未触碰用户未跟踪根目录 `tui/`。

### U3 evidence（2026-08-04）

- Binding/compatibility：新 checkpoint 初始化即写 immutable `ConversationWorkspaceBindingV1` / schema v3；decoder
  继续严格接受 v2。Goal-bound v2 只有 exact identity 匹配时才由首次 `AgentRuntime.run_turn` lease 内 CAS 迁移；
  goal-less v2 保持只读并计入 `legacy_unbound`。Focused binding/continuity 首轮准确 Red 后 `53 passed in 4.72s`。
- Startup capacity：加载上限固定 `WORKSPACE_HISTORY_CAPACITY=256`，active display cap 固定 16；terminal history
  不占 active cap。达到容量仍可恢复已有会话，只有创建新 conversation 返回 typed
  `history_capacity_exceeded`，不删除历史；unknown entry/corrupt/unsafe checkpoint 继续 fail closed。
- Catalog/tools：新增只读 `HistoryCatalog`、`history_search` / `history_get` governed registrations，并由 normal
  `main → build_tool_registrations → KernelToolRuntime` 静态组合。只召回 exact scope + identity 可证明的 checkpoint；
  production 排除 current conversation，legacy unbound、identity mismatch、cross-workspace 与 tool argument inventory
  均无召回。没有 HistoryAgent、index、cursor、Memory copy 或第二 loop。
- Ref decision：完整 catalog digest 进入 search receipt；get ref 绑定同 catalog 进程签发的 immutable record snapshot。
  这是实现期明确修正：若绑定整个目录 revision，Runtime 保存 search ToolResult 的正常 checkpoint 会让 ref 立即
  stale；当前形状允许 search→get，并在被引用记录修改/删除时准确 stale。
- Ranking/outcome：lexical/field-weighted、canonical revision/conversation/fact position 排序；10 个标注 case
  `recall@5 >= 0.80`，修正记录按 position 优先且冲突显式标记，no-match closed。Outcome 从 checkpoint 只读投影
  `user_confirmed_acceptance/verified_delivery/blocked/cancelled/failed/acceptance_unknown`；delivery 不冒充满意。
- E2：同一 `AgentRuntime` 完成 model → `history_search` → Kernel source receipt → untrusted
  `first_agent_history` context → model final；无 helper/fake path 替代 Runtime。History focused `7 passed`。
- Broad relevant：history/continuity/kernel/provider/cli/tui/scheduler/013 reference `536 passed in 18.02s`，exit 0，
  输出完整；touched Ruff 与 `git diff --check` exit 0。
- 未调用网络/provider，未读取 secret/private/runtime，未触碰用户未跟踪根目录 `tui/`。

### U4 evidence（2026-08-04）

- Red：新增 `tests/tools/test_workspace_search.py`；首次 focused run `7 failed`，准确命中三个 primitive 未注册、
  workspace read/list 尚无 source receipt，以及 walker 没有独立 traversal budgets。
- Boundary：在既有 `WorkspaceBoundary` 内实现 descriptor-relative `search_paths`、`search_text`、
  `read_file_chunk`；敏感名称在 stat/open 前拒绝，目录与文件均 `O_NOFOLLOW`，子目录 open 后重验 inode，拒绝
  symlink、多硬链接和 protected inode。没有 subprocess、index、watcher 或第二套读取路径。
- Budgets/output：scan entries、matches、opened files、total/single-file bytes、depth、snippet、deadline 分别计数；
  locator 排序 deterministic，invalid UTF-8 显式 replacement，binary closed，所有截断都带 bounded reason 与
  snapshot/content digest。
- Source contract：`read_file`、`list_files` 与三个新 primitive 都返回 `ToolExecutionOutput`；receipt 由 Kernel
  铸造为 `workspace_path` / `workspace_excerpt`，write/edit 保持普通 effect output。Runtime E2 已验证下一次模型调用
  只看到带 receipt 的 untrusted `workspace_excerpt`。
- Focused workspace/path/file suite：`23 passed in 0.24s`；补齐 depth/deadline 独立 cap、private zero-open、
  ancestor swap、invalid UTF-8/binary、hardlink/symlink 和 deterministic ordering 证据。
- Broad relevant：tools/kernel/provider/cli/tui/012+013 reference `456 passed in 7.23s`，exit 0，输出完整；
  touched Ruff 与 `git diff --check` exit 0。
- 未调用网络/provider，未读取 secret/private/runtime，未触碰用户未跟踪根目录 `tui/`。

### U5 evidence（2026-08-04）

- Official contract check：只读 Tavily 官方 API reference，确认固定 base URL 仍为 `https://api.tavily.com`，
  Bearer authentication、`POST /search`、`POST /extract`、`basic` depth、Search exclusion flags 与 Extract
  `format=text`/timeout 均与 frozen design 一致；未发送真实请求。
- Red：新增 `tests/web/` 后首次 focused run exit 2，`4 errors during collection`，准确命中 `agent.web` 整个
  production capability 尚不存在。
- Profile/safety：`WebProfileV1` 只保存 strict non-secret fixed fields 与 digest，owner-only atomic file；未配置不
  注册，已配置但 exact env 缺失在 session/runtime 创建前失败。URL admission 只接受 bounded public HTTPS，拒绝
  userinfo、fragment、异常端口、private/metadata literal 与 credential-like query。
- Client：只连接固定 Tavily Search/Extract destination；owned `httpx.Client` 使用 `trust_env=False`、
  `follow_redirects=False`、有限时、无 retry。Search 明确关闭 answer/raw content/images/auto；Extract 固定
  basic/text/single approved URL。Content-Type、解压后 streaming bytes、strict JSON/depth/count/field/URL equality
  全部 fail closed；auth/rate/protocol/timeout 分类不包含 key 或 response body。
- Authority/receipts：`web_search` 与 `web_fetch` 都是 `READ_ONLY + PUBLIC_NETWORK + ALWAYS approval`；fetch 只接
  Runtime-issued opaque `source_ref`。Receipt locator 移除 query，完整 URL 从 digest-bound durable search result
  恢复；content/profile/source-ref mutation 使 authority/approval 失效且 network count 0。Kernel 通过显式
  `prepare_authority_binding` seam 把 exact canonical URL 放进持久化 approval，不在 Kernel 内硬编码 Tavily policy。
- E2：同一 `AgentRuntime` 完成 model → exact approval（发送前 count 0）→ injected Tavily transport → Kernel source
  receipt → untrusted `public_web_content` → next model context；请求实际只到 `api.tavily.com`。
- Focused Web suite：`34 passed in 0.57s`。Broad relevant：web/kernel/provider/cli/continuity/tui/012+013 reference
  `547 passed in 27.76s`；`.venv/bin/ruff check .`、`git diff --check` 均 exit 0，输出完整。
- 未读取或回显 credential value，未调用真实 Tavily/model，未触碰用户未跟踪根目录 `tui/`。

### U6 evidence（2026-08-04）

- Red：新增 `tests/continuity/test_research_evidence.py` 后首次 focused collection exit 2，准确命中
  `agent.research` / `CitationManifestV1` / closed oracle 均不存在；未用模型自报或 fixture flag 冒充 pass。
- Contract/admission：新增 canonical digest-bound `CitationManifestV1` 与纯 read-only
  `build_citation_manifest` primitive。只有 exact citation sidecar write approval 才由 Runtime 铸造额外 mandatory
  `RESEARCH_PROVENANCE` criterion；sidecar target 缺少该 admission 时不能完成。
- Oracle：从当前 conversation + current Goal/revision 的 durable `SourceReceiptV1`、artifact/sidecar exact
  `read_file` facts 重算 linkages。拒绝 fake/mock/synthetic、old/swapped/truncated receipt、search snippet 冒充
  extracted content、insufficient kinds/classes/count、freshness failure、虚构 URL、重复/缺失 marker、artifact mutation
  与 assistant self-report。
- Semantics：trusted Goal context 明确投影 `verified_delivery`，声明只证明 artifact digest、citation/source linkage 与
  freshness，不证明 semantic truth 或 user acceptance；现有只读 outcome projection 继续只在 exact
  `USER_CONFIRMATION` evidence 后称为 acceptance。
- E2：同一 `AgentRuntime.run_turn` 接受真实 `CompletionClaim` control，经 Runtime-owned oracle 从 raw facts 重算、
  持久化 evidence 并到达 `VERIFIED_DONE`；timestamp 由 injectable Runtime clock 生成，不再使用非时间占位字符串。
- Focused research suite：`16 passed in 0.07s`；continuity/kernel-registration/history/skill 回归 `109 passed`，
  research/context/verified/outcome 回归 `35 passed`；均 exit 0，输出完整。
- Full gate：`git diff --check`、`.venv/bin/ruff check .` exit 0；全套 `828 passed, 1 failed in 57.56s`。唯一失败
  `tests/architecture/test_cutover_absence.py::test_product_tree_contains_only_kernel_packages` 是 U0 已登记并转交 U8
  的 materialized product-tree manifest drift（尚未纳入 U3-U6 新包），不是 U6 行为失败；不得把 full gate 记为 pass。
- 未调用网络/provider，未读取 secret/private/runtime，未触碰用户未跟踪根目录 `tui/`。

### U7 evidence（2026-08-04）

- Red：reference collection 首先准确命中缺失 `project_source_views`；`setup-web` 首次解析为 unknown subcommand；
  everyday policy 首次缺少 just-in-time/untrusted/Web/citation 行为约束。三个缺口分别 Red 后最小 Green。
- Source UX：新增共享只读 `SourceView`，CLI/TUI/headless 同源展示 kind、可读 title/locator、observed state、
  complete/truncated/search-only/extracted/no-match/failed；默认不显示 opaque ref/digest，显式 `/sources --advanced`
  才显示 source ref。普通无来源回答不增加 source noise。
- Web UX/config：新增 non-secret `first-agent setup-web`，用户无需手写 JSON；保存 fixed Tavily destination、env name、
  timeout/result caps，不读取或保存 key。Search/Extract exact approval preview 均完整显示冻结 third-party notice，明确不
  承诺 zero retention、training exclusion 或 deletion；profile/approval binding 继续绑定 notice digest。
- Policy/composition：默认 policy 要求 history/workspace just-in-time、Web Search→Extract 分别批准、所有来源视为
  untrusted data、search snippet 不冒充 extracted page、citation sidecar 使用 canonical builder 并回读；无 mode 或
  合成 continue。默认 `main` 静态组合 history/workspace/research，Web 仅在 strict profile 存在时注册。
- Reference E2：一条 goal-free journey 在同一 `AgentRuntime` 完成 provider disclosure → history → expanded
  disclosure → workspace → expanded disclosure → Tavily Search approval → public-Web disclosure → Tavily Extract
  approval → grounded answer；request host 仅 `api.tavily.com`，两次 approval 前 count 分别为 0/1。
- Artifact/restart E2：另一条 production journey 先 durable Goal，再取得 current-Goal history/workspace/extracted-Web
  receipts；在 artifact write pending approval 处重建整个 composition，exact pending request 保持，Web observations
  不重放；随后实际 write artifact/sidecar、read-back、Runtime citation evidence 并 `VERIFIED_DONE`。审批序列精确为
  `web_search, web_fetch, write_file, write_file`，无 mode/continue。
- Injection：真实 `read_file` source 含写文件/声明完成指令，下一模型调用即使尝试服从，Runtime 仍在 prepare 前以
  `effectful_tool_requires_goal` 拒绝；目标文件、Goal authorization 与 evidence 均未产生，context 标记 untrusted。
- Focused 014+013 reference `13 passed`；reference/CLI/TUI/history/tools/Web/continuity broad `290 passed in 10.51s`；
  `.venv/bin/ruff check .` 与 `git diff --check` exit 0，输出完整。
- Web 网络只用了 injected `httpx.MockTransport`；未调用真实 provider/Tavily，未读取 secret/private/runtime，未触碰
  用户未跟踪根目录 `tui/`。

### U8 evidence（2026-08-04）

- Red：完整 source suite 在 U6 已准确留下
  `test_product_tree_contains_only_kernel_packages` 失败；新建 014 delivery contract 后首次 collection exit 2，准确
  缺失 `scripts/verify_014_materialized_tree.py`。加入只读 verifier 后 focused run 为 `3 failed, 2 passed`：缺
  014 seal、README operator Web/Sources 文档，以及 temp fixture 对 `.gitignore` admission 的旧预期；逐项修正，未
  读取真实根目录 `tui/` 内容。
- Product tree/docs：静态产品树显式纳入 `agent.history`、`agent.research`、`agent.web` 与 workspace search；README
  说明 current-workspace history、bounded workspace search、可选 `setup-web`、Search/Extract 双批准、`/sources`
  和 provenance 不等于语义真理/用户接受。base dependency 仍只有 `httpx`，没有 Tavily/browser SDK；Web 未配置
  时 `build_web_resources` 注册零工具，013 普通旅程保持 Green。
- Delivery：新增 strict `delivery-overlay-seal/v3`；base 绑定 frozen 009 manifest，parent 绑定 013 seal，verifier
  与 143 个 ordinary entries 的 path/operation/mode/content root 均精确绑定。012/013/014 controls 不进入 ordinary
  root；ignored、denied/private/runtime、`.codex-tmp-*` 和根目录 `tui/` 在读取/hash 前排除；verifier 无 generate
  模式。
- E2M 首轮：non-editable/neutral/deny-network materialized pytest 为 `840 passed, 2 failed`；两个失败都来自 macOS
  `/var -> /private/var`，neutral HOME 的文本路径触发产品正确的 no-symlink state-root 拒绝。修复只 canonicalize
  verifier 创建的临时 HOME，没有放宽产品安全边界。
- E2M Green：`.venv/bin/python scripts/verify_014_materialized_tree.py --content` → exit 0，
  `842 passed in 124.80s`，并输出 `014 content gate: ALL CHECKS PASSED`；neutral test env 不继承 host credential/
  provider/runtime 配置。membership → exit 0，`143 exact entries`；control seal → exit 0。
- Focused delivery/012/013/cutover：`15 passed in 9.07s`；unconfigured Web + 013 + 014 delivery：
  `11 passed in 3.68s`。`.venv/bin/ruff check .` 与 `git diff --check` 均 exit 0，输出完整。
- 未调用真实 provider/Tavily，未读取 secret/private/runtime，未触碰用户未跟踪根目录 `tui/`。

### U9 harness evidence（2026-08-04）

- Red：新增 `tests/reference/test_014_e3_harness.py` 后首次 focused run `7 failed`，准确缺失
  `scripts/run_014_e3.py`；未用 Fake/Scripted/Mock 或 helper direct call 伪造真实路径。
- Runner：五项显式配置在任何网络前 closed 校验；每次新 temp HOME/state/workspace A/B，non-secret provider/Web
  profiles，所有用户旅程调用无参数 `product_main.main([])`。只 patch production Model/Web HTTP client seam 记录
  host/path/status/count，实际 adapter、Runtime、ToolRuntime、approval、checkpoint、evidence 和 restart composition
  保持产品路径；clients 均 `trust_env=False`、no redirect、有限时/次数。
- Frozen journeys：真实模型必须建立 workspace A decision + goal-less binding、workspace B isolation fact；释义查询只
  召回 A history；workspace search + Tavily Search/Extract 回答；新 Goal 中 history/workspace/two extracted Web
  receipts 生成 artifact + canonical citation sidecar，在首个 write approval 前退出并重启，read-back +
  `RESEARCH_PROVENANCE` 后才 `VERIFIED_DONE`。hostile-source authority 由离线 stop-ship oracle + live untrusted
  projection/no-unexpected-write 共同约束；另跑 disabled history/Web baseline。
- Receipt：19 个 frozen claims 必须全 true；只输出 provider/model、destination/request/opaque Goal/artifact/sentinel
  digests、journey verdict 和 offline gate identity。key、header/body/query、绝对 temp path、正文、protocol ID 均不
  输出；Model/Web adapter error 映射为准确 secret-free marker。
- Focused harness：`7 passed in 1.76s`；014 harness/reference/research/history/Web/workspace broad：
  `87 passed in 9.72s`；Ruff/diff exit 0。
- 第一次 full source run：`846 passed, 3 failed in 146.04s`；三个失败均为 012/013/014 missing-config subprocess
  在一次主机高负载下撞测试的 10 秒 timeout。没有把 timeout 记为 pass；单独计时三入口为 0.61–1.10 秒且三项
  focused `3 passed in 4.81s`，证明无稳定启动回归。第二次完整未截断 run → exit 0，
  `849 passed in 165.69s`。
- 014 seal 随 U9 ordinary runner/tests/docs 重算为 `145 exact entries`；membership/control、Ruff、diff exit 0。
  最新 materialized content → exit 0，`849 passed in 57.67s`，`ALL CHECKS PASSED`。
- 只检查配置名称的 presence：五项全部缺失；随后权威命令
  `.venv/bin/python scripts/run_014_e3.py` → exit 2，准确输出
  `NEEDS_014_E3_CONFIG(required=FIRST_AGENT_014_E3_PROVIDER,FIRST_AGENT_014_E3_BASE_URL,FIRST_AGENT_014_E3_MODEL,FIRST_AGENT_014_E3_API_KEY,FIRST_AGENT_014_E3_WEB_API_KEY)`；
  零真实 Model/Tavily request。（当时状态：U9 尚未闭合；U9 + U10 后续已全 closed，最终权威见 §9.3。）

### U9 live evidence（2026-08-05，**已被 §9 取代的历史证据；最终权威 receipt 为 §9 的当前树 39/39/41**）

- 用户明确授权使用其提供的 DeepSeek 与 Tavily 凭据进行真实产品验收。credential values 仅通过关闭终端回显的
  stdin wrapper 注入 E3 子进程环境；未写入仓库、命令参数、receipt、checkpoint、event 或输出。
- 首个正式 attempt 使用了先前已失效的 Model credential，runner 在进入产品旅程前准确返回
  `014_E3_BLOCKED(reason=model_auth)`；不计连续成功。换用用户最新提供的 credential 后，一个正式 attempt
  返回 `014_E3_BLOCKED(reason=provider_protocol)`；instrumented runner 定位为真实模型偶发重复发送 malformed
  `goal_proposal`，随后同代码的 bounded repair 能完整闭合。没有把这两个失败计为 pass。
- 修复/稳定性工作覆盖：baseline 与 J2 的精确单次工具约束、artifact exact read-back、citation marker/source
  pair、invented URL rejection、mutation 后 workspace observation freshness、artifact criterion supersession 与
  exact source-kind admission。最后 focused gate：`70 passed in 1.91s`；touched Ruff 与 `git diff --check` exit 0。
- 用户随后明确要求：合理推进中的任务不得因累计 token、model 或 tool 调用量停止。新增公开接口 Red 证明三个
  materially different 未执行工具尝试会被旧共享计数误杀；新增 batch Red 证明同一 ModelResponse 的六个并行
  未执行工具会在模型看到反馈前耗尽 allowance。最小 Green 在唯一 `AgentRuntime` 内加入连续停滞指纹，并按
  model response 而非 tool call 计 replan opportunity；换工具/参数/错误、真实 product result 或新 evidence 重置。
  `InvocationLimits` 保留显式有限 caller 行为，但 Everyday 的累计 model/tool/input/output 为 `None`；协议修复
  `max_invalid_repairs=4`，独立紧急停滞熔断 `max_no_progress_replans=16`。没有新增外层/第二套 loop。
- 真实稳定性诊断没有计入 accepted receipt：旧共享计数首次得到
  `last_safe_result.error_code=no_progress`；batch 修复后又准确复现跨独立响应的 `product_no_progress`。E3 runner
  因此增加 secret-free closed Runtime error marker，测试证明不投影内部 message。所有失败都重置连续成功计数。
  相关 focused 为 `64 passed in 1.11s`；当前 full source gate为 `912 passed in 58.01s`，Ruff/diff exit 0。
- （以下为**早期树**证据，refactor 前；**最终权威 receipt 是 §9 的当前树 39/39/41**，本小节仅作历史保留，不构成当前树
  acceptance。）当时入口身份：五项 `FIRST_AGENT_014_E3_*` 仅在子进程内存中配置，然后执行
  `.venv/bin/python scripts/run_014_e3.py`。当时 code tree、provider `openai_compatible`、model
  `deepseek-v4-flash`、Model destination 与 Tavily destination 在三次 accepted run 间保持不变；每次创建新的
  temp HOME/state/workspaces。
- 当时 code tree（早期树）的连续 run 1（`2026-08-05T00:23:33.422982+00:00`）：exit 0，19/19 claims true，
  5 journeys passed，34 Model requests，2 Search + 5 Extract。
- 连续 run 2（`2026-08-05T00:25:16.516603+00:00`）：exit 0，19/19 claims true，5 journeys passed，
  33 Model requests，2 Search + 5 Extract。
- 连续 run 3（`2026-08-05T00:27:02.477691+00:00`）：exit 0，19/19 claims true，5 journeys passed，
  35 Model requests，2 Search + 5 Extract。
- Secret-free evidence（早期树，**已被 §9 取代**）：早期树 receipt（34/33/35）。**最终权威**：§9 当前树 receipt
  `docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_E3_RECEIPTS.json`（accepted，39/39/41）。U9 + U10 现已全
  closed（见 §9.3）。

## 4. Active handoff

- Current owner：Claude Code（014 主执行者）。
- Active unit：**无（全部闭合）**。U0–U10 全 closed；frozen E3 三连 accepted（39/39/41）、U10 mandatory held-out
  PASSED、完整 final gates（154 entries）Green、fresh independent reviewer no P0/P1/P2。
- 权威最终状态见 §9.3；receipts：`docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_E3_RECEIPTS.json`
  （frozen，accepted）与 `docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_HELDOUT_VALUE.json`（held-out，passed）。
- 无 first required action（loop 已终态）；如未来重开，从 §9.3 第一个未闭合项接力。
- Do not touch：未跟踪根目录 `tui/`、`.env`、secret/private/runtime、Claude/Codex config、remote/git history。
- Legal stop markers：仅见 014 handoff §9。

## 5. E3 evidence

Status（权威当前树状态）：**accepted**。当前物化树真实 Model + Tavily E3 已连续 3 次 exit 0、19/19 claims 全 true、
journeys 全 passed（attempts #7–#9，2026-08-05T08:52–08:55 UTC，每次新 temp root；code tree / provider family+model /
Model destination digest / Tavily destination digest 不变）；脱敏 receipts 见
`docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_E3_RECEIPTS.json`（顶层 `acceptance.status=accepted`）。
详情、命令身份与 model flakiness 诚实披露见 §9。下方原"U9 live evidence"（早期树，refactor 前）保留为历史，已被
§9 的当前树证据取代，不构成当前树 acceptance。

## 6. Review evidence

> **历史阶段证据（config-gated 时期；当前树权威状态见 §9.3，非 §7）**。本节 "U10 executor handoff evidence" 描述的
> held-out production value journey 发生在更早的 code tree（convergence/no-progress refactor 与 925-test 增长之前），
> 属于**历史证据**，不构成当前树 acceptance。当时的 fresh 只读 review 因 config 缺失限于 offline（**当时**真实 E3 与
> held-out 均未运行/被认为 config-gated；二者现均已闭合，见 §9.3）。

### U10 executor handoff evidence（2026-08-05）

- U9 receipt/documentation 后重新封印：014 overlay `147 exact entries`；membership 与 control seal exit 0。
- Verification Contract source gates（输出完整）：`git diff --check` exit 0；`.venv/bin/ruff check .` exit 0；
  `.venv/bin/python -m pytest -q -rx` → `876 passed in 57.80s`；materialized `--content` →
  `876 passed in 54.48s` 与 `014 content gate: ALL CHECKS PASSED`。
- `ce-simplify-code` 三个独立只读 reviewer 完成。应用 4 个行为保持项：复用 2 个 canonical digest、复用 1 个
  history content digest、删除 1 个无调用的旧 walker；跳过会引入跨模块私有 helper、profile persistence
  framework、signed ref 或大范围 hot-path/index 重构的建议。首次 Ruff 暴露 `Iterator` 仍被另一注解使用，未记
  pass；恢复 import 后 touched Ruff 与 31 个 focused tests Green。
- 早期 held-out production value（发生在最新 Runtime convergence 改动之前）：临时 HOME/workspace、同一 production composition/adapter/approval/checkpoint 路径；
  使用未写入 fixture 的 `active workspace review-notes` 历史释义，成功取得 current-workspace
  `history_excerpt` 并召回 verified delivery。不同公开主题为 PostgreSQL 17 首次发布日期，真实 Tavily Search +
  Extract；两条旅程 4/4 claims true、10 Model requests、2 Web requests、无额外 Goal/文件。临时诊断脚本已删除，
  未保存 key、正文、query、绝对路径或 checkpoint。该结果是历史证据，不替代 latest-tree fresh reviewer held-out。
- Latest-tree held-out production value（`2026-08-05T00:38:02.552185+00:00`）：fresh reviewer 先只读选择
  两个未写入 fixture 的题目，executor 再用临时 HOME、两个隔离 workspace、无参数 `main`、production
  DeepSeek/Tavily adapters、真实 disclosure/approval/checkpoint 运行。历史题先生成并验证“对外发布说明首段列出
  SPDX identifier”的 canonical delivery，再以释义询问；6/6 claims true，包括 current exact workspace
  binding、`history_excerpt`、`verified_delivery`、准确召回、同题 cross-workspace marker 缺席以及无额外 Goal/文件。
  Web 题改为 Node.js 20 官方 EOL；Tavily Search 后 Extract 官方 Node.js 来源，6/6 claims true，包括审批先于
  send、`web_extracted_content` 官方来源、观察到的日期、URL/观察时间/计划可调整限制、Tavily-only 以及无额外
  Goal/文件。合计 15 Model requests、2 Search、1 Extract；只保留本段脱敏 verdict，未保存 credential、query、
  response body、绝对临时路径或 checkpoint。
- Executor marker：`014_EXECUTOR_READY_FOR_REVIEW`。Fresh full review 尚未产生 verdict；本段不预填 pass。

### Pre-implementation document review

Status：**complete, findings incorporated**。Coverage：coherence、feasibility、product、design、security、scope、
adversarial；Claude cross-model judgment pass 被明确的 weekly spending limit 阻断，未产生 fold-in artifact，未把
失败伪装为 review pass。

主要闭合：唯一 Runtime 入口措辞、Search/Extract 双 approval、source contract 前置、v2/v3 binding migration、
256 total capacity、SourceAuthorityBinding、PUBLIC_NETWORK typed recovery、source-only ToolExecutionOutput、
CitationManifestV1、no-result/conflict/disclosure/resume UX、Tavily response cap 与第三方数据处理披露、held-out
retrieval/value gates、P3 advisory 和 implementation blocker marker。Round 2 又闭合 U10/交审循环、完整/部分 E3
配置 marker、source-producing 工具全集、Tavily streaming E3、trust-notice claim、Goal-bound receipt fields、
`RecoverUnknownObservation` exact action 与稳定 `approval_basis_revision`。

### Final implementation review

Status（**config-gated 时期的历史阶段**；当前权威 review 见 §9.3）：**fresh 只读 review 由主执行者在闭合 offline 项后
启动**；当时五项 `FIRST_AGENT_014_E3_*` 配置缺失，review 范围限于 offline（contracts / security / architecture /
tests / materialized seal / runner soundness），无法覆盖真实 E3 与 held-out value journey（二者**当时** config-gated；
现均已闭合，见 §9.3）。不得预填 reviewer pass。

## 7. Current-tree real E3 status（2026-08-05 早期 refresh，**历史阶段，已被 §9.3 取代**）

> 本节写于真实 E3 尚未闭合时（config-gated / `product_no_progress` 阶段），保留为历史诊断记录。**当前树真实 E3 已
> accepted、U10 mandatory held-out 已 PASSED，权威最终状态见 §9.3**（非本节）。

### 7.1 真实状态

- Offline gates（本次实测，输出完整未截断）：
  - `git diff --check` → exit 0。
  - `.venv/bin/ruff check .` → `All checks passed!`。
  - `.venv/bin/python -m pytest -q -rx` → `925 passed in 71.18s`，exit 0，到达 100%。
  - `.venv/bin/python scripts/run_014_e3.py`（无配置）→ `NEEDS_014_E3_CONFIG(...)`，exit 2，零网络。
- Delivery seal：刷新前 stale（overlay 期望 151、实际 153，root digest 漂移），原因是 convergence/no-progress
  refactor 与 925-test 增长后未重算；本次按 verifier 合同重算（见 §8）。
- Real E3：当前树**未产出权威 pass**。早期树（refactor 前）的三次 19/19 receipts 保留为历史证据，但顶层
  `acceptance.status` 已改为 `superseded_pending_current_tree_real_e3`。之后的当前树尝试报告过
  `014_E3_BLOCKED(reason=product_no_progress)`，stage-8 artifact restart 在真实 model HTTP 调用中被操作者中断；
  二者均不计为 pass。
- 本执行进程五项 `FIRST_AGENT_014_E3_*` 配置全部缺失，无法在此重跑真实 E3。

### 7.2 审计结论（基于当前物化树与可重跑证据）

- U0-U8 代码完整、offline E1/E2/E2M 在当前树 Green；U9 E3 runner sound（真实 `httpx.Client(trust_env=False)`
  + recording event hooks，非 MockTransport/scripted；19 claims 从真实 journey state 计算，任一 false 即
  `014_E3_BLOCKED`，无伪造路径；无配置正确 fail-closed）。
- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop；未发现第二套 loop / service locator / compat
  fallback / dormant flag。no-progress 熔断（`max_no_progress_replans=16`，按 model response 计数、signature 变化
  重置、同 response batch 不重复计数）逻辑健全且有 convergence 测试覆盖；真实模型下的 `product_no_progress`
  属真实模型行为，需凭配置迭代，不能靠离线改代码或放宽 acceptance 解决。
- 未读 `.env`/secret/private/runtime/Claude 配置；未触碰未跟踪根目录 `tui/`；未 commit/push/tag/改 remote。

### 7.3 本次闭合项与剩余缺口（**config-gated 时期的历史阶段；当前无缺口，见 §9.3**）

- 当时已闭合：stale 文档诚实化（receipts JSON、E3 验收 frontmatter+§10、本 log §4/§5/§6/§7/§8、handoff）、
  handoff 协议纠正（去 `--model fable` 硬编码与 Codex 接管，改为 alias-independent + stop-on-quota + current-run
  note）、delivery seal 重算（151→153，并在每次 ordinary 改动后重算）、完整未截断 offline gates、fresh 只读
  reviewer（见 §8）。
- 当时剩余唯一缺口：真实 Model + Web E3（需五项 `FIRST_AGENT_014_E3_*` 配置，当时本进程缺失）。**此缺口现已闭合**
  （§9：frozen E3 accepted；§9.3：held-out PASSED）。
- 当时权威 marker：`NEEDS_014_E3_CONFIG`（config-gated 暂停态）。**当前权威 marker 为 `014_REVIEW_PASS`（见 §9.3）**。
  （历史诊断：配置齐备后若当时树仍 `product_no_progress`，则转 `014_E3_BLOCKED(reason=product_no_progress)`，需凭真实
  模型迭代，不得放宽 acceptance 或伪造 pass。）

## 8. Fresh reviewer 与 boundary deviation（2026-08-05，**config-gated 时期的历史 review cycle；当前权威 review 见 §9.3**）

### 8.1 Reviewer boundary deviation（必须记录，不得当 pass）

本次曾启动一个 `project-auditor` 只读 reviewer。**尽管被明确禁止**，它仍读取了
`.claude/agent-memory/project-auditor/MEMORY.md` 及其 S5 memory 文件，违反 no-Claude-memory 边界；随后该 agent
被 stopped、**无完成记录**。因此：

- 该 review **不构成 qualifying fresh reviewer evidence**。
- 主执行者**不读取、不回显**其 transcript（避免传播泄漏的 memory 内容），不把其任何结论当 pass。
- 已在 014 handoff §1 current-state note 与 §7 记录该 deviation，并从 handoff 协议中移除 `project-auditor` 作为
  reviewer 选项（改为 `general-purpose` 只读 reviewer，明确禁止 `.claude/`、memory、private/runtime）。
- 未读取 `.env`、secret/credential、Claude/Codex settings/auth；未触碰未跟踪根目录 `tui/`。

### 8.2 Fresh `general-purpose` 只读 reviewer（含 listing-boundary deviation）

随后启动 fresh `general-purpose` 只读 reviewer，prompt 中明确：不得使用 project-auditor；不得读取/列举
`.claude/`、`memory/`、`.codex/`、`.ua/`、agent-memory、settings、auth、private/runtime、`.env`；只读仓库权威文件
（AGENTS.md、docs/、agent/、tests/、scripts/、main.py）与当前 git diff；先用 graphify（graphify-out 是仓库本地
图，非 Claude memory）。**当时**真实 E3 config-gated，故该次 review 范围限 offline（真实 E3 + held-out 现已闭合，见 §9.3）。

**Reviewer verdict（当时）**：`offline review: no P0/P1/P2 findings (real E3 config-gated, out of scope)`。reviewer 未输出
`014_REVIEW_PASS`（**当时**真实 E3 未验证，全 DoD 未达，正确；真实 E3 + held-out 后续闭合，见 §9.3）。reviewer 未修改文件、未 commit/push，未进入或读取任何受限
目录的**内容**，未读 `.env`/secret/credential 或废弃 reviewer transcript。**但该 reviewer 不是完美 boundary-compliant**：
它在仓库根执行过 `ls -la`，其输出列出了 `.claude`、`.codex`、`.ua`、`memory`、`sessions`、`tui` 等**目录名称**
（仅目录名，未进入或读取这些目录的内容）——这违反 review prompt 中"不得读取/列举 `.claude/`/memory/..."的边界，
构成 listing-boundary deviation。因此该 reviewer 的 12 个攻击面 / no P0/P1/P2 产品审查事实仅作**辅助证据**；
offline 闭合主要由主执行者亲自重跑的 gate（§8.3）+ architecture/contract 测试 + 该辅助发现共同支撑，而非单凭该
reviewer 的 boundary 声明。

**Reviewer 独立重跑的 offline gates**（完整未截断）：`git diff --check` exit 0；`.venv/bin/ruff check .` exit 0
（All checks passed）；`.venv/bin/python -m pytest -q -rx` → `925 passed in 72.00s` exit 0；
`scripts/run_014_e3.py`（无配置）→ `NEEDS_014_E3_CONFIG(...)` exit 2 零网络；
`verify_014_materialized_tree.py --check-membership` → `153 exact entries` exit 0；`--control-seal` exit 0。
（`--content` reviewer 未自跑，由主执行者另行最终重跑，见 §8.3。）

**12 个攻击面 reviewer 逐条 file:line 确认**（摘要）：唯一 `AgentRuntime`/`.generate(`/`KernelToolRuntime`，capability
模块对 runtime 零引用；HistoryCatalog exact-workspace + 排除 current conversation/legacy unbound/cross-workspace，
256/16 容量；workspace walker `O_NOFOLLOW`+inode 重验+8 个独立 budget；Web URL admission 拒 userinfo/private/
metadata/credential-query，client `trust_env=False`+streaming byte cap+strict JSON，fetch 只接 opaque ref + returned_url
精确匹配；PUBLIC_NETWORK unknown reducer 恰好一次无 receipt fact、不发网络；`SourceReceiptV1` 由 Kernel 从 draft+intent
铸造、data class 闭集映射；admission 只认 `USER_MESSAGE` 完全相等；citation oracle 从 `state.facts` 重算、拒
search-snippet-as-extracted/artifact 篡改/虚构 URL；VERIFIED_DONE 只产 `verified_delivery`、`user_confirmed_acceptance`
需独立 USER_CONFIRMATION；restart 不重放 observation、workspace mutation 后允许 re-read；`_NoProgressTracker` 按
model response 计数、signature 变化 reset；materialized verifier 排除 control、neutral env 不传 credential。

**P3 advisory（不阻止，未实现，避免范围蔓延）**：
- P3-1：citation oracle 依赖"callable 不能直接写 `state.facts`"不变式（事实上由构造保证：state 推进只经 `loop.py`
  reducer，tool func 只返回值）。建议后续在 `evidence.py`/delivery 文档显式声明该不变式。
- P3-2：`private_roots` 只在路径首段检查（`path_safety.py:750`），嵌套私有根依赖 `_SENSITIVE_COMPONENTS` denylist
  （设计，非漏洞）。
- P3-3：E3 runner 19-claim 失败统一映射 `014_E3_BLOCKED(reason=provider_protocol)`（闭合集合、secret-free，可接受）。
- P3-4：`_TraversalBudget.stop` 首因胜出（行为符合 truncated，非问题）。

### 8.3 主执行者最终 offline gates（**held-out 前、config-gated 时期的历史阶段；当时 153 entries；当前最终树权威 gate 见 §9.3 的 154**）

- `git diff --check` → exit 0。
- `.venv/bin/ruff check .` → `All checks passed!`，exit 0。
- `.venv/bin/python -m pytest -q -rx` → `925 passed in 66.50s`，到达 100%，exit 0。
- `scripts/verify_014_materialized_tree.py --check-membership` → `153 exact entries`，exit 0。
- `scripts/verify_014_materialized_tree.py --control-seal` → `014 control seal ok`，exit 0。
- `scripts/verify_014_materialized_tree.py --content` → 前台完整未截断运行，materialized non-editable/neutral/deny-network
  pytest `925 passed in 63.36s`、`014 content gate: ALL CHECKS PASSED`，exit 0。
- `scripts/run_014_e3.py`（无配置）→ `NEEDS_014_E3_CONFIG(...)`，exit 2，零网络。

offline reviewer：返回 no P0/P1/P2，但存在 listing-boundary deviation（根 `ls -la` 暴露目录名，见 §8.2），故仅作
辅助证据、**不声称完美 boundary-compliant**。offline 闭合由主执行者亲自重跑的上述 gate + architecture/contract
测试 + reviewer 辅助发现共同支撑。当时（config 缺失阶段）唯一缺口为真实 Model + Web E3；该缺口已由 §9 闭合
（用户随后注入配置，当前树真实 E3 已 3 连续 accepted）。

## 9. Real Model + Web E3 acceptance（2026-08-05，权威当前状态，取代 §7）

用户明确授权并经外层注入五项 `FIRST_AGENT_014_E3_*` 临时 env（仅子进程内存，**未写入** args/receipt/checkpoint/
event/log/docs/.env；主执行者不读取/回显 key 值）。固定配置：`provider=openai_compatible`、
`base_url=https://api.deepseek.com`、`model=deepseek-v4-flash`；Web 走产品既有 Tavily contract（`https://api.tavily.com`
`/search`+`/extract`）。运行的是**未改动**的 `scripts/run_014_e3.py`（production adapter/http_client，非 mock/script）。

### 9.1 命令身份与结果

- 权威命令：`.venv/bin/python scripts/run_014_e3.py`（前台，未截断）。
- 连续 3 次 accepted（attempts #7–#9，2026-08-05T08:52:28Z / 08:54:00Z / 08:55:39Z，每次新 temp root）：
  - 三次均 exit 0、19/19 claims 全 true、journeys 全 passed。
  - model requests 39/39/41（< 128 上限）、web 7/7/7（< 64 上限）。
  - 三次 provider family+model（`openai_compatible`/`deepseek-v4-flash`）、Model destination digest
   （`9ccd2042…`）、Tavily destination digest（`088debf4…` = `sha256("https://api.tavily.com")`）完全一致。
- secret-free receipts：`docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_E3_RECEIPTS.json`（顶层
  `acceptance.status=accepted`）；无 key、Authorization/header/body/query、绝对 temp path、checkpoint 正文（长 hex 串为
  opaque sha256 digest）。

### 9.2 Model flakiness 诚实披露（未放宽任何 acceptance）

hosted 模型即使 `temperature=0`（production adapter `agent/provider/openai_http.py` 已强制 `temperature=0`）仍有固有
nondeterminism。为取得首次三连成功，期间若干**非连续** run 因真实模型 flakiness 失败并被丢弃（不计 pass）：

- `014_E3_BLOCKED(reason=provider_protocol)`：源于 `malformed_control`（模型发送的 goal_frame 不满足 strict 18 键
  exact 匹配，`agent/provider/normalize.py:_control_exact_keys`）；4 次 repair allowance 内未纠正。
- `014_E3_BLOCKED(reason=product_no_progress)`：模型连续无产品进展响应触发 16-response 停滞熔断
  （`AgentRuntime.run_turn` 内 `_NoProgressTracker`，`max_no_progress_replans=16`）。
- 重启三源 journey 上的显式 `BlockedClaim`（模型主动 block 而非完成 artifact+citation）。

诊断用 `/tmp/e3_diag.py`（observation-only monkeypatch，仅打印 journey 终态/error_code + redacted 异常，**未改**
runner 逻辑或产品代码）确认失败均位于真实模型行为，且产品代码对每种失败都**正确** fail-closed。所有 accepted
receipt 来自**未改动**的 runner。

**未放宽**：decoder strictness（18 键 exact）、no-progress 阈值（16）、安全/审批/重启 oracle、19 claims、温度（已 0）。
acceptance §8 的"连续三次"由 attempts #7–#9 满足（同 code tree、同配置、每次新 temp root）。

### 9.3 当前闭合状态（最终，DoD 全部满足）

- U9 frozen E3：**accepted**（当前树 3 连续，attempts #7–#9）。
- U10 fresh independent reviewer：`general-purpose` 只读 reviewer（禁 project-auditor、禁 ls/glob/read 受限路径）→
  **no P0/P1/P2**；唯一 P3（goal_frame 实际 18 键、文档误写 19）已订正（receipts/E3 §10/本 §9.2 共 4 处 19→18，
  纯 prose，未改代码、未动 19 claims、未重跑 E3）。reviewer 独立重跑 offline gates 全 Green。
- 最终完整 gates（held-out 闭合后的最终树，154 entries，主执行者亲自前台未截断运行）：`git diff --check` exit 0；
  `.venv/bin/ruff check .` All checks passed；`.venv/bin/python -m pytest -q -rx` → `925 passed in 66.25s` exit 0；
  `verify --check-membership` → `154 exact entries` exit 0；`--control-seal` exit 0；`--content` → materialized
  `925 passed in 62.21s`、`ALL CHECKS PASSED` exit 0。fresh independent reviewer 独立复核 offline gates 全 Green 且
  **no P0/P1/P2 — ready for `014_REVIEW_PASS`**（held-out 脚本/verdict/frozen receipts/acceptance 未放宽/单 loop 均独立确认）。
- 真实 E3（final-tree 权威证据）：上述 attempts #7–#9 三连 accepted；自此仅改 docs（无 .py 改动），runner/产品代码未变，
  故三连 receipt 仍是当前最终树的真实 E3 证据，无需再跑第 4 次（hosted 模型 flaky，单次重跑无 acceptance 增量）。
- delivery seal：按 verifier 真实算法重算（held-out 文件加入后 entry_count 154，overlay_root 随 ordinary 文档改动逐次刷新），
  membership/content/control 全 exit 0，证据与 seal 一致。
- 边界：未读/回显 key、未写 .env/checkpoint/event/receipt/log/docs；未碰未跟踪根 `tui/`；未 commit/push/tag/改 remote；
  未改 Claude 配置；未创建第二套 loop。
- **U10 mandatory held-out value journey 已 PASSED**（2026-08-05）：fresh independent reviewer（general-purpose 只读，
  禁 project-auditor / 受限路径）选未写入 frozen fixture/runner 的 novel topics——decision = "runtime 默认日志级别 WARN"
  （`decisions/logging-default.md`）、history 释义 query = `default log level`（recall_token `WARN`）、Web = "When did the
  IETF publish RFC 9114 defining HTTP/3?"（constraint_keyword `RFC number`）。executor 前台运行一次同预算 production value
  journey（`/tmp/heldout_value.py` 复用 frozen runner 的 production machinery：no-arg `product_main.main`、真实 DeepSeek
  `openai_compatible` + Tavily adapter、真实 ToolRuntime approval/checkpoint/evidence；不 mock/script/fake，不放宽
  安全/approval/oracle/budget，model≤128/web≤64）→ **verdict=passed**：decision_verified、history_recall_ok（HISTORY_EXCERPT
  receipt + `WARN` 召回 + 仅当前 workspace）、web_grounded_ok（≥2 search snippets + 1 extract、approval 先于 send、trust notice
  可见、无额外 Goal/文件）、tavily_only、within_budget（11 model / 2 web）、secret_free。verdict 固化于
  `docs/acceptance/014_GROUNDED_PERSONAL_KNOWLEDGE_AGENT_HELDOUT_VALUE.json`（**不改写** frozen E3 receipt；#7–#9 仍 accepted）。
  此前误把 held-out 当可选并过早输出 `014_REVIEW_PASS`，已撤回；held-out 现已闭合。
