# Profile Writer 生命周期线性化计划

- Date: 2026-09-08
- Status: frozen-for-implementation
- Source: Oracle Web r5（最高档）+ Codex production composition/Runtime/call-graph 复核
- Supersedes: `2026-09-08-002-browser-open-authority-lifecycle-plan.md` 的最终完成结论

## Outcome

`site_bound_interactive` 的获批 profile snapshot 与真实 persistent-context open 之间由
一份 exact、持续有效的 writer lease 保护。同一 profile 的 mutation 与 writer
acquisition 具有一个明确线性化顺序：

- mutation 先成功：旧 binding 的 acquisition/open 为 `KnownNotExecuted`，
  `BrowserEnvironment.open` 零调用；
- writer acquisition 先成功：普通 revoke/clear 明确返回 busy 且状态不变，open 只能消费
  lease acquisition 时验证过的 snapshot；
- takeover completion 只有持有原 session exact lease 时才能把 revision 幂等推进一次。

## User-visible contract

- active browser session（含 takeover）期间执行 `/browser-profiles revoke|clear`：告诉用户
  profile 正在使用，未撤销/未清除；先结束浏览器会话再重试。
- writer identity 无法确定：告诉用户状态不可确认且未执行，不删除 lock/profile。
- browser `CLEANED` close 并释放 writer 后，同一 revoke/clear 命令正常成功。
- 本轮不提供“强制撤销并关闭浏览器”；busy 不是 cleanup unknown，也不是成功。

## Non-goals

- 不改 `AgentRuntime.run_turn`、Runtime action/checkpoint/approval schema、
  `BrowserSessionSpecV1` 或 `BrowserEnvironment` port。
- 不新增 authority broker、service locator、第二套 loop、全局 lease registry、自动重试、
  自动迁移或兼容 fallback。
- 不增加 scheduler browser 能力、profile selector、强制 revoke、后台恢复或跨进程 takeover。
- 不把 cooperative store lock 宣称为可阻止任意同 UID 程序直接修改浏览器目录。
- 不顺带重写 metadata durability；I/O/identity 不确定继续 fail closed。

## Architecture invariants

1. `AgentRuntime.run_turn` 仍是唯一 model/tool loop 与 state mutation owner；
   `KernelToolRuntime` 仍独占 tool admission/approval/invoke。
2. `BrowserProfileStore` 只拥有 profile lifecycle consistency，不判断用户授权或任务完成。
3. 同一个 browser tool owner 同时产生 registrations 与 typed takeover completion callback；
   composition 静态注入 callback，不从 registration 反射、不使用动态 registry。
4. exact lease/nonce 只在 browser owner/store 内存与 owner-only `writer.lock` 中存在，不进入
   model arguments、checkpoint、event、receipt 或 CLI 输出。
5. adapter 前可证明零 effect 的 drift/busy 保持 `KnownNotExecuted`；调用
   `BrowserEnvironment.open` 之后的异常仍按 existing unknown/quarantine 处理。

## Internal contracts

### Exact acquisition lease

`ProfileWriterLeaseV1` 变为一次 acquisition 的 immutable 身份：

- `profile: BrowserProfileRefV1`：在 acquisition 线性化点验证过的完整 snapshot；
- `lease_id`：每次 acquisition 新的 32-lowercase-hex nonce；
- `pid` + `started_at`：保留现有 holder liveness identity。

`writer.lock` closed schema 同步为 `pid/started_at/lease_id/acquired_revision`。旧两字段 lock
不静默升级，按 unknown 阻断。profile metadata 形状不变。

### One per-profile protocol

所有操作顺序固定为 `owned root fd → stable root-level guard → canonical profile dir fd →
metadata/writer.lock`。`open`、`acquire_writer`、`release_writer`、`advance_revision`、
`revoke`、`clear` 参加同一个短临界区协议；guard 不跨浏览器启动或用户 takeover 长期持有。

- `acquire_writer(expected_ref)`：guard 内验证 exact ref/ACTIVE、处理 confirmed-stale lock、
  创建 nonce lock，返回含 validated snapshot 的 lease。
- `release_writer(lease)`：只删除四字段与 exact lease 全等的 lock；迟到的旧 lease 为 no-op，
  不得删除同进程后续 acquisition 的 lock（消除 ABA）。
- `revoke(ref)` / `clear(ref)`：live writer → `ProfileLockHeldError`；unknown/corrupt writer →
  `ProfileLockUnknownError`；只有无 writer 或 confirmed-stale writer 被安全移除后才 mutation。
  active clear 不删除 lock、profile 或浏览器数据，也不返回 `CLEANED`。
- `advance_revision(lease, expected_revision=...)`：ownerless API 删除。guard 内要求当前调用进程、
  lock nonce/owner/acquired revision、lease snapshot immutable identity 与 ACTIVE metadata 全部匹配；
  `expected_revision` 必须等于 acquisition revision。当前 revision 为 `r` 时 CAS 到 `r+1`；
  仍由同一 lease/lock 调用且当前为 `r+1` 时幂等返回；其他情况拒绝。

### Static takeover wiring

现有 browser tool builder 改为返回一个小型 immutable bundle：

- `registrations`：现有五个 governed tools；
- `complete_takeover(request)`：绑定创建 registrations 的同一个 browser tool owner。

callback 从 `_Session` 取得原 `writer_lease`，验证 request/session/spec/environment headed
identity 后调用 lease-bound takeover helper。composition 的 `BrowserResources` 继续只暴露
registrations、closeables、readiness 与 typed callback，不暴露 store/environment/lease。
不保留旧 builder compatibility wrapper。

## Scope

### Production

- `agent/browser/profile_store.py`
- `agent/browser/tools.py`
- `agent/browser/takeover.py`
- `agent/composition.py`
- `main.py`（只改 profile command 的 busy/unknown/stale 文案映射）

### Tests/callers

- `tests/browser/test_profile_locking.py`
- `tests/browser/test_profile_store.py`
- `tests/browser/test_tools.py`
- `tests/browser/test_composition.py`
- `tests/cli/test_018_browser_experience.py`
- direct browser-tool builder callers discovered by `rg`（tests + sealed E3 script），只做机械接线更新。

不得修改 Runtime/core contracts、Playwright adapter、scheduler、Memory/MCP/Skill/SubAgent、
untracked `tui/` 或 unrelated WIP。

## Vertical TDD acceptance

按一个行为一个 Red→Green，不能把新签名的 `TypeError` 当核心 Red：

1. **Lease ABA**：L1 acquire/release、L2 acquire、迟到 `release(L1)` 不删除 L2 lock；第三个
   writer 仍被拒，L1/L2 nonce 不同。
2. **Active mutation**：live exact writer 期间，独立 store 的 revoke 与 clear 都明确拒绝；
   metadata/目录/lock 原样保留；release 后命令成功。
3. **Unknown mutation**：corrupt/unknown lock 时 revoke/clear 不删除、不 quarantine、不报告成功。
4. **Mutation wins**：final tool check 后、acquisition 线性化前先完成 revoke/revision change，
   旧 approved open 返回 binding changed，environment open-entry count=0，无 writer 泄漏。
5. **Writer wins**：在 tool 的 execution clock seam（acquisition 已返回、adapter 尚未调用）
   尝试另一 store revoke/clear；mutation busy、metadata 不变，adapter 恰好按 acquisition
   snapshot open 一次。
6. **等待旧 revision**：A 在进入 acquisition guard 前停靠；原 lease holder 完成 exact takeover
   R1→R2 并 CLEANED release；A 恢复后必须重读 R2 并拒绝旧 R1，open-entry count=0。
   使用 Event/Pipe 明确阶段，不用 sleep 猜竞态，也不得在持有 guard 时等待另一 guard actor。
7. **Lease-bound advance**：wrong nonce/profile/owner/released lease 全拒且 revision 不变；同一
   lease 的 R1→R2 及 retry 幂等，不到 R3；新 R2 lease 不能冒充旧 R1 completion。
8. **Takeover vertical**：governed open 持有 lease → begin takeover/headed → Runtime typed complete
   通过同一 owner callback → revision 只加一；旧 session 仍可 CLEANED close/release，后续需
   fresh open/observe。pending 期间 provider/tool/observe 为零的既有证明继续 Green。
9. **CLI honesty**：active/unknown/stale profile command 不显示 revoked/cleared；close/release 后
   成功文案保持。输出不含 path、account label、digest、lease/nonce。
10. **Deadline/public-read**：002 的 execution-time deadline、independent reopen、legacy digest、
    expired action zero effect 与 public-read 行为继续 Green。

每个 fake environment 的 open-entry counter 必须在方法入口累加，区分“adapter 零调用”与
`BrowserOpenNotStartedError` 的“一次调用但 typed not-started”。

## Verification

1. Focused profile/tool/takeover/composition/CLI tests。
2. 全部 `tests/browser/` + `tests/continuity/test_browser_takeover*.py` +
   `tests/cli/test_018_browser_experience.py` + architecture ownership/freshness gates。
3. fresh Pi 只读独立审计；任何 P0/P1/P2 修复后重新 focused review。
   （2026-09-08 修复批 2：fresh reviewer 提出的 P2（CLI list/create 异常穿透）
   与 writer.lock 写入确认逃逸已 Red→Green 修复，记录见「Slice 3 修复批 2」；
   该批按约束只做 touched-area focused 验证，未跑全量/全仓 gates。）
4. 稳定后只跑一次 final：
   - `git diff --check`
   - `.venv/bin/ruff check .`
   - `.venv/bin/python -m pytest -q -rx`
5. 不访问真实 profile、credential 或第三方网站；本轮用真实 filesystem locks、独立 store/
   process interleaving、public Runtime path 与 injected browser entry counter 作为证据。

## Codex review decision

Oracle 的 A（再读一次）只移动竞态；单独 B 会破坏 takeover；单独 C 不能约束 clear/revoke；
采用 D 的最薄实现并合并 B/C 的必要规则。production call graph 已确认 ownerless
`advance_revision` 只有 takeover helper 一个调用者；main 的 profile commands 通过另一 store
实例访问同一 root；composition 可以将 registrations 与 completion callback 静态绑定到同一
tool owner，无需 Runtime 变更。设计满足最小闭环，批准交给 Pi 实现。

## 003 Implementation Notes（Pi 执行记录）

### Slice 1：profile_store writer lease 与 per-profile 协议（Red → Green）

**Red（先行锁定，全部为真实行为断言失败，非 `TypeError`）：**

- `test_profile_locking.py::test_acquire_writer_issues_verified_lease_with_random_nonce`
  — Red：`store` 无 `acquire_writer`（`AttributeError` 于 public 调用点）；随后逐条 Red：
  随机数 32 位小写 hex 且两次 acquire 不重复、lease 快照与 store 验证一致。
- `test_profile_locking.py::test_release_writer_requires_exact_lease_fields`
  — Red：迟来/伪造 lease 删除锁（断言 lock 仍在失败），Green 后四字段全等才删。
- `test_profile_locking.py::test_advance_revision_binds_exact_lease_and_is_one_shot`
  — Red：ownerless `advance_revision` 不存在（计划删除项）；Green 后仅 lease 绑定、
  `expected_revision == acquired_revision` 的 r→r+1 一次性 CAS + r+1 幂等。
- `test_profile_locking.py::test_revoke_clear_refuse_live_or_unknown_writer`
  — Red：活跃/未知 writer 下 revoke/clear 沉默通过；Green 后
  `ProfileLockHeldError` / `ProfileLockUnknownError`，零 mutation。
- `test_profile_store.py` HEAD 重写（lease 绑定 API）：见下「锁 schema 迁移」。

**Green 关键实现**（`agent/browser/profile_store.py`）：

- `LEASE_ID_PATTERN`（32 位小写 hex）；`LOCK_KEYS = {pid, started_at, lease_id,
  acquired_revision}`；旧 2 字段 lock → `ProfileLockUnknownError`。
- `ProfileWriterLeaseV1 = (profile: 已验证快照, lease_id, pid, started_at)`；
  `acquire_writer` 先自探测进程身份，guard 内验证 ref、stale takeover、
  `secrets.token_hex(16)` 随机数、写 4 字段 lock。
- `release_writer` 仅四字段与 exact lease 全等才 unlink（迟来 release no-op，ABA 消除）。
- `advance_revision(lease, *, expected_revision)`：快照身份不匹配 →
  `ProfileIntegrityError`；非 ACTIVE → `ProfileRevokedError`；
  `expected != acquired` → `ProfileRevisionConflict`；lock 非当前 pid+nonce+owner →
  `ProfileLockUnknownError`；r→r+1 一次，重放幂等返回 r+1。
- `revoke`/`clear` 经 `_require_no_live_writer`：live → Held；unknown → Unknown；
  confirmed-stale（明确 ESRCH / started_at 不符的 pid 复用）→ 删锁再变更。
- `clear` 重构为全程 guard 覆盖（Held/Unknown 向外传播，不隔离）。
- ownerless `advance_revision(ref, expected_revision=)` 删除。

### 锁 schema 迁移与 HEAD 测试重写

- 旧 2 字段（pid/started_at）lock 视为 unknown：所有读取点统一
  `ProfileLockUnknownError`，绝不按 stale 垃圾清理。
- `tests/browser/test_profile_store.py` HEAD 测试改为 lease 绑定 API：
  `test_revision_advance_requires_matching_acquisition_revision`、
  `test_revoke_blocks_reuse`、`test_forged_digest_reference_cannot_mutate_profile`、
  `test_stale_revision_reference_cannot_revoke`；CAS_PROBE_SCRIPT 先 acquire lease。
- `test_profile_locking.py` HEAD：4 字段 payload 断言 + 解码参数化；
  CONTENDER_SCRIPT BarrierProbe 的停车点移至「进入 guard 前、自探测后」（协议变更：
  自探测发生在 guard 之外）。

### 发现并修复的真实 bug：macOS 并发 `openat(O_CREAT)` 瞬时 ENOENT

- 复现：最小化 2 进程探测（同目录并发 `openat(dir_fd, O_CREAT)` guard 名），约 6% 概率
  返回 ENOENT（父目录稳定、无删除竞争）。
- 修复：`_open_guard_fd` 带 syscall 级有界重试（8 次、退避休眠）。这不是协议层重试：
  guard 线性化协议未变，只吸收 macOS openat 的瞬时伪 ENOENT。
- 验证：8 次完整文件运行全绿 + 2 进程 5 秒 `_serialized` 压测（约 82k 迭代零失败）。
- 调试注记：期间竞争测试偶发 `['missing','missing']` 曾有三个叠加原因（真实 ENOENT 竞争、
  一次批量编辑部分失败导致 `import time` 缺失、调试补丁损坏嵌入脚本），全部解决后删除
  全部调试脚手架。

### Slice 2：takeover helper、tools bundle、composition、CLI（Red → Green）

- **Red**：`test_tools.py::test_takeover_revision_invalidates_old_session_but_still_allows_close`
  （原 ownerless advance 调用点，Red 为真实契约失败）；composition/CLI 沿用 002 断言。
- `agent/browser/takeover.py::complete_browser_takeover_profile(request, store, *, lease,
  browser_identity_digest)`：删除 `session_is_active` 参数（会话/headed/身份校验上移到
  owner）；digest/profile/revision 三重绑定后 lease-bound CAS，store 异常统一
  `ValueError`（“browser profile could not be advanced”）零 mutation。
- `agent/browser/tools.py`：`BrowserToolBundle(registrations, complete_takeover)`；
  `build_browser_tools` 取代 tuple builder（无 compatibility wrapper，旧名删除）；
  `_BrowserTools.complete_takeover` 校验 session/spec/goal/headed
  （`environment.takeover_session_active`）后调用 helper；工具 `open()` 的 spec 一律
  取 `writer.profile`（acquisition 快照），不再信任外部 ref。
- `agent/composition.py`：`BrowserResources(registrations=tools.registrations,
  complete_takeover=tools.complete_takeover)`——lambda wrapper 删除，callback 与
  registrations 静态绑定同一 owner（`tests/browser/test_composition.py::
  test_bundle_registrations_and_complete_takeover_share_one_owner` 断言
  `complete_takeover.__self__` 即 registrations callable owner）。
- `main.py`：revoke/clear 捕获 `ProfileLockHeldError` →
  “Browser profile {id} is in use; it was not revoked/cleared. Finish the browser session
  first, then retry.”；`ProfileLockUnknownError` → “Browser profile {id} writer state
  cannot be confirmed; nothing was revoked/cleared.”（无 path/label/digest/nonce）。

### 003 新测试（tests/browser/test_open_authority.py + 相关文件）

002 迁入（行为不变，builder 改为 `.registrations`）：session duration 到执行时刻、
顺序独立 deadline、final drift / reacquire drift KnownNotExecuted 零 effect、
active profile 二次 open unavailable、revoked prepare 拒绝。

新增：

- `test_writer_acquisition_wins_against_mutation_at_clock_seam`（revoke/clear 参数化）：
  acquisition 成功后在 execution clock seam 注入 mutation → 明确 `ProfileLockHeldError`
  busy、状态不变、adapter 恰按 acquisition snapshot open 一次；close 后同一命令成功。
- `test_parked_acquisition_rereads_new_revision_after_exact_takeover`：线程 A 的
  acquire_writer 停靠在 guard 前（Event/Pipe 同步，非 sleep）；主线程同 owner
  `tools.complete_takeover`（R1→R2）+ CLEANED close；恢复 A →
  `KnownNotExecuted browser_open_binding_changed`、open entry 计数不增（零新 adapter 调用）。
- `tests/continuity/test_browser_takeover_flow.py::
  test_run_turn_consumes_bundle_complete_takeover_with_exact_lease`：完整
  `AgentRuntime(browser_takeover_complete=tools.complete_takeover)` 垂直：begin → durable
  pending（provider 恰 2 调用）→ typed complete 恰好推进一次 → 二次 complete
  `RunStatus.CONFLICT` 拒绝、revision 不漂移。
- CLI 诚实（`test_018_browser_experience.py`）：活跃 writer → busy 文案（release 后成功）；
  良构外进程 lock + `exists=None` 探测 → unknown 文案、零 secret、lock/profile 原样保留。
- `RecordingEnvironment` 增加 `begin_takeover`/`takeover_session_active` 伪造
  （`_headed` 集合）；open-entry counter 维持「方法入口即记录」语义。

### 偏差与说明

- 停车点适配：计划描述的 acquire 前停车落到 store wrapper 层（`GuardParkedStore`，
  仅第二次 armed acquire 在 guard 前停靠）；协议本身未加等待点。
- `test_018` 三个 helper 调用点改为显式 `store.acquire_writer(...)` 传 lease（003 契约
  要求）；`session_is_active` 断言语义由 owner 层 headed 校验接替。
- E3 脚本 `scripts/browser_e3_journeys.py`：flow 持有 `self.tools` bundle，J6 的
  `browser_takeover_complete` 直接用 `self.flow.tools.complete_takeover`（lambda wrapper
  删除）。本轮未运行真实浏览器 journey（约束：无真实浏览器/网络）。
- 018 设计文档 §5 本轮未改动（helper 签名描述与实现一致性留给文档轮次；如需我可补）。

### 验证记录

- focused：`tests/browser/`（含新 `test_open_authority.py`）+ `tests/continuity/` +
  `tests/cli/test_018_browser_experience.py` + `tests/architecture/` →
  805 + 69 passed。
- final：`git diff --check` 干净；`.venv/bin/ruff check .` 全绿；
  `.venv/bin/python -m pytest -q -rx` 全量通过（见下方最终记录）。
- 测试计数：`tests/browser/test_profile_store.py` + `test_profile_locking.py` = 59；
  `test_open_authority.py` = 11（5 项 002 迁入含参数化展开 + writer-wins 2 + parked 1）。
- 未完成/限制：真实浏览器 E3 journey 未运行（按约束）；018 设计文档 §5 未更新（可选）。

### Slice 3（2026-09-08 修复批）：clear 顺序、open 零 mutation、锁分类、CLI 诚实

**Red（先行，全部为真实行为断言失败，非 `TypeError`）：**

- `test_clear_with_live_writer_and_unreadable_metadata_fails_busy_without_quarantine`
  （corrupt/missing 参数化）：clear 把 live writer 的 canonical profile（连同
  writer.lock）先 quarantine，DID NOT RAISE `ProfileLockHeldError`。
- `test_clear_with_unknown_lock_and_unreadable_metadata_fails_closed_without_quarantine`：
  malformed lock + 损坏 metadata 同样被 quarantine 而非 `ProfileLockUnknownError`。
- `test_open_for_missing_profile_leaves_root_untouched`：open 对不存在的 profile
  先 O_CREAT guard，root 残留 `guard-profile-0000000000000000`。
- `test_acquire_writer_classifies_lock_stat_failure_as_unknown`：`_lock_exists`
  吞掉非 ENOENT OSError（PermissionError 逃出 public `acquire_writer`）。
- `test_acquire_writer_classifies_lock_create_failure_as_unknown`：
  `_create_lock_fd` 把非 FileExistsError 的 OSError 伪装成 `ProfileLockHeldError`。
- `test_advance_revision_rejects_forged_non_active_lease_snapshot`：
  `_verify_lease_snapshot` 未校验 acquisition snapshot status，伪造 REVOKED
  status 的 lease 完成 advance（DID NOT RAISE）。
- CLI：double revoke 的 `ProfileRevokedError` 与 corrupt metadata 的
  `ProfileIntegrityError` 逃出 `browser_profile_user_command`（应为 closed
  ValueError/安全文本，不泄漏 path/digest/label）。

**Green（最小实现）：**

- `clear` phase 1 在同一 root guard 与同一 profile fd 内先
  `_require_no_live_writer` 再读 metadata：live → Held、unknown → Unknown 均原样
  传播（不 quarantine、不删 lock/profile）；无 writer/confirmed-stale 被安全移除
  后，corrupt/missing metadata 仍保持既有 CLEANUP_UNKNOWN + quarantine 语义；
  forged ref 的 `ProfileIntegrityError` 仍在 `_verify_reference` 阶段传播、
  绝不误当 quarantine。
- `open` guard 前非权威 lstat 预筛（仅 ENOENT → `ProfileNotFoundError`）：失败
  查询零 root mutation；预筛与 guard 之间的创建竞态仍由 guard 内
  `_profile_dir_fd` 的权威失败兜底，无兼容层、无第二套协议；
  `_open_guard_fd` 的 macOS ENOENT 有界重试保持。
- `_lock_exists`：非 ENOENT 的 OSError → `ProfileLockUnknownError`；
  `_create_lock_fd`：仅 FileExistsError → Held，其余 OSError → Unknown。
- `_verify_lease_snapshot`：acquisition snapshot status 非 ACTIVE →
  `ProfileRevokedError`（`acquire_writer` 只会发出 ACTIVE lease）。
- CLI：open 阶段 `ProfileIntegrityError`/`ProfileLockUnknownError` → closed
  `ValueError("browser profile state cannot be confirmed")`；mutation 阶段
  `ProfileRevokedError`（revoke）→ "already revoked; nothing done"；
  `ProfileNotFoundError`/`ProfileRevisionConflict` → "changed while the command
  ran; nothing was …"；`ProfileIntegrityError` → closed ValueError；busy/unknown
  既有文案不变。
- `test_root_replaced_by_symlink_fails_closed_before_any_write` 的 advance_revision
  分支改为替换 root 前先取得 exact lease（不再把 `BrowserProfileRefV1` 传给
  lease API）。
- 删除 `test_composition.py::test_bundle_registrations_and_complete_takeover_share_one_owner`
  及其专属两个 fake（`__self__` 是实现细节断言）；同 owner exact lease 消费已由
  `tests/continuity/test_browser_takeover_flow.py` 以真实 run_turn 行为证明。

**实证与边界记录：**

- macOS openat 瞬时 ENOENT 再实证（本机 4 进程 `_serialized` 压测）：约
  304292 次 openat 中出现 3 次 errno=2（约 1/10万），全部被 `_open_guard_fd`
  有界重试吸收、零失败，确认重试不是掩盖协议层竞争。
- `release_writer` 的 guard 阶段失败（`ProfileLockUnknownError`）向上传播、
  不静默吞掉——绝不表面成功但锁残留；仅 canonical root 已消失/不可信
  （`ProfileNotFoundError`/`ProfileIntegrityError`）按迟来 release no-op。
- 状态更正：上一批“018 设计文档 §5 未更新”已完成——本批同步了设计文档
  §2/§5（writer.lock 为 exact nonce/acquisition-revision lease、同一
  per-profile 协议、live/unknown writer 不 revoke/clear、completion 由同一
  静态 browser tool owner callback 消费原 session exact lease 且幂等
  revision+1）；真实浏览器 E3 journey 仍未运行（按约束）。
- 本批验证（按修复批约束只跑 touched area）：
  `tests/browser/test_profile_store.py tests/browser/test_profile_locking.py
  tests/browser/test_composition.py tests/cli/test_018_browser_experience.py`
  → 108 passed；允许的 Python 文件定向 ruff 全绿；未跑全量 pytest/全仓
  ruff/final gates。

### Slice 3 修复批 2（2026-09-08，fresh reviewer）：CLI list/create closed 异常 + writer.lock 写入确认

**背景**：fresh reviewer 复审提出两项——(P2) `browser_profile_user_command` 的
list 只捕 OSError、create 裸调用，而 `BrowserProfileStore` 在 root 缺失/损坏时抛
`ProfileNotFoundError`/`ProfileIntegrityError`（非 OSError），异常可穿透 handler
乃至 run_repl；(2) `_create_lock_fd` 的 os.fdopen/json.dump/flush/fsync 阶段
OSError 原样逃逸并留下已创建的 writer.lock——browser adapter 尚未调用该路径，
但 Runtime 会把逃逸的 OSError 归为 external unknown-outcome。

**Red（先行，全部为真实行为断言失败）：**

- `test_018_browser_experience.py::test_profile_list_with_unusable_root_surfaces_closed_value_error`
  （root-missing/root-symlink 参数化）：list 面对 root 缺失/替换为 symlink 时
  `ProfileNotFoundError`/`ProfileIntegrityError` 逃出 handler（应为 closed
  ValueError，消息不含 tmp path/internal exception）。
- `test_018_browser_experience.py::test_profile_create_with_unusable_root_surfaces_closed_value_error`：
  root 位置被普通文件占用（无法创建 owned root）时 create 让
  `ProfileIntegrityError` 逃出 handler（消息不得含 tmp path/account label）。
- `test_profile_locking.py::test_acquire_writer_classifies_lock_write_confirmation_failure_as_unknown`：
  注入 lock 写入的 fsync OSError，当前原样逃出 public `acquire_writer`（应为
  `ProfileLockUnknownError`）。

**Green（最小实现）：**

- `main.py`：create 捕获 store closed 异常
  （`ProfileNotFoundError`/`ProfileIntegrityError`）→
  `ValueError("browser profile store unavailable")`；list 的 except 子句扩为
  `(OSError, ProfileNotFoundError, ProfileIntegrityError)` 同文案。不 catch
  Exception、不改 store API、无 fallback。
- `agent/browser/profile_store.py::_create_lock_fd`：fdopen→json.dump→flush→
  fsync 包裹 try/except OSError →
  `ProfileLockUnknownError("lock write could not be confirmed")`。不吞掉、不改判
  Held、不 best-effort unlink 不确定状态（残留 lock 由既有 unknown/takeover
  判定处理）；Red 测试同时断言 lock 保留、metadata/revision 不变、后续 writer
  被明确拒绝。

**验证（按本批约束）**：
`.venv/bin/python -m pytest -q tests/browser/test_profile_locking.py
tests/cli/test_018_browser_experience.py -rx` → 61 passed（32 + 29，含 4 个新
测试实例）；两个产品文件与两个测试文件定向 ruff 全绿；未跑全量 pytest/全仓
ruff/final gates，未访问真实 browser/network。
