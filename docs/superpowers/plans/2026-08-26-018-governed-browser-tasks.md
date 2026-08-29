# 018 Governed Browser Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Claude Code GLM 5.3 `[1m]`, `effort=max` is the preferred single writer; Codex owns
> plan/audit and bounded failure assistance. Do not dispatch product-code subagents.

**Goal:** 让 First Agent 在专属 Chromium 中完成有界公开读取与 site-bound 网页任务，
同时把 profile、network、登录接管、后果性 action、upload/download 与 unknown outcome
锁在既有 Runtime/ToolRuntime authority 内。

**Architecture:** Playwright 只实现注入式 `BrowserEnvironment` external-effect port；
纯 `BrowserActionPolicy` 从 durable observation 生成 approval binding，真实 browser I/O
只发生在既有 `EXECUTING` checkpoint 之后。`BrowserEgressGuard`、profile/session store 与
quarantine 是 browser-owned deep modules，不调用模型、不修改 ConversationState；唯一
`AgentRuntime.run_turn`、`ContextManager`、`KernelToolRuntime` owners 不变。

**Tech Stack:** Python 3.11、`playwright==1.62.0` optional extra、bundled Chromium、
stdlib `socket/ipaddress/pathlib/fcntl/hashlib/json`、现有 Runtime/ToolRuntime/Checkpoint、pytest。

**Spec:** `docs/superpowers/specs/2026-08-28-governed-browser-tasks-design.md`

## Global Constraints

- 只实现 frozen 018；不进入 019 scheduler。
- 不 attach/copy/import/export 个人 Chrome/profile/storage-state/cookies/history/extensions。
- Base install 不依赖 Playwright/Chromium；无 browser extra/binary 时准确 fail closed。
- `PUBLIC_READ_EPHEMERAL` 与 `SITE_BOUND_INTERACTIVE` 是 closed modes，不静默升级。
- 所有 page/frame/popup/redirect/subresource/WebSocket request 经 production egress guard；
  无 permissive fallback；test-only loopback admission只能构造注入。
- 页面/ARIA/download 永远是 untrusted data，不能授予 Goal/tool/origin/profile authority。
- `DISCLOSE`/`DOWNLOAD`/`UPLOAD`/`COMMIT` 每次 exact approval；unknown=`COMMIT`。
- takeover 期间 provider/tool/observe/recording 为零；交还后 fresh observation。
- download 只进入 browser-owned quarantine；不实现 workspace import/ChangeBundle。
- 所有 effect 仍走 ToolRuntime approval → `EXECUTING` → invoke → result checkpoint。
- 行为/架构变化先 Red；每 Task 只跑 focused gate。Task 9 冻结 source 后跑一次 full；
  Task 10 跑一次 materialized/full/真实 E3。失败、timeout、截断都不是 PASS。
- 不读取 `.env`、secret、credential、private/runtime 或未跟踪 `tui/` 内容；不 commit/push。

## File Map

- `agent/browser/contracts.py`：immutable profile/session/observation/action/receipt contracts。
- `agent/browser/ports.py`：`BrowserEnvironment`、resolver/clock/file-hash ports。
- `agent/browser/url_policy.py`：canonical URL/origin、public-address/SSRF admission。
- `agent/browser/observation.py`：bounded ARIA projection、secret redaction、digest。
- `agent/browser/action_policy.py`：纯 consequence classification 与 exact approval binding。
- `agent/browser/profile_store.py`：owner-only persistent profile metadata/locking/revoke/clear。
- `agent/browser/session_store.py`：opaque session/action lifecycle ledger。
- `agent/browser/playwright_adapter.py`：唯一 Playwright/Chromium lifecycle 与真实 action adapter。
- `agent/browser/quarantine.py`：owner-only download quarantine 与 upload staging。
- `agent/browser/tools.py`：唯一 governed browser tool registrations。
- `agent/runtime/*`：最小 browser candidate/lease/takeover/receipt persistence 与 projection。
- `agent/composition.py`, `main.py`, `pyproject.toml`：optional static composition/setup UX。
- `tests/browser/*`、018 reference/harness/runner/verifier/seal/review：行为与真实证据。

---

### Task 1: Freeze typed contracts, URL policy and observation projection

**Files:**
- Create: `agent/browser/__init__.py`
- Create: `agent/browser/contracts.py`
- Create: `agent/browser/ports.py`
- Create: `agent/browser/url_policy.py`
- Create: `agent/browser/observation.py`
- Create: `tests/browser/test_contracts.py`
- Create: `tests/browser/test_url_policy.py`
- Create: `tests/browser/test_observation.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces `BrowserMode`, `BrowserActionKind`, `BrowserConsequence`,
  `BrowserSessionSpecV1`, `BrowserHandleV1`, `BrowserObservationV1`,
  `BrowserActionV1`, `BrowserActionReceiptV1`, `BrowserCleanupReceiptV1`.
- Produces `BrowserEnvironment.open/observe/execute/close` protocol.
- Produces `BrowserURLPolicy.admit(url, *, mode, allowed_origins) -> AdmittedURLV1`.
- Produces `project_aria_snapshot(raw, identity, limits) -> BrowserObservationV1`.

- [ ] **Step 1: Write contract Reds**

```python
def test_interactive_spec_requires_exact_origin_and_profile_revision():
    with pytest.raises(ValueError):
        BrowserSessionSpecV1.site_bound(
            goal_id="goal-1", goal_revision=1, profile_ref=None,
            allowed_origins=(), action_budget=8,
        )

def test_action_identity_binds_observation_target_and_parameters():
    action = BrowserActionV1.click("a" * 64, "page-1", "frame-1", "ref-7")
    assert action.identity_digest != replace(action, target_ref="ref-8").identity_digest
```

- [ ] **Step 2: Run contract Reds**

Run: `.venv/bin/python -m pytest -q tests/browser/test_contracts.py -rx`
Expected: collection/import failure because `agent.browser` contracts do not exist.

- [ ] **Step 3: Implement strict immutable contracts and the port**

```python
class BrowserEnvironment(Protocol):
    def open(self, spec: BrowserSessionSpecV1) -> BrowserHandleV1: ...
    def observe(self, handle: BrowserHandleV1) -> BrowserObservationV1: ...
    def execute(
        self, handle: BrowserHandleV1, action: BrowserActionV1,
        *, upload_staging: BrowserUploadStagingV1 | None = None,
    ) -> BrowserActionReceiptV1 | KnownNotExecuted: ...
    def begin_takeover(self, handle: BrowserHandleV1) -> None: ...
    def takeover_session_active(self, session_ref: str) -> bool: ...
    def close(self, handle: BrowserHandleV1) -> BrowserCleanupReceiptV1: ...
```

All identities use `canonical_json_digest`; enums reject unknown strings; positive limits reject
bool; receipts cannot claim executed without pre/post identity and an outcome class.

- [ ] **Step 4: Write and run URL-policy Reds**

Cover HTTPS public positive plus HTTP/userinfo/IP literal/localhost/loopback/RFC1918/link-local/
multicast/unspecified/reserved/cloud metadata/mixed public-private DNS/redirect-origin drift Reds.
Inject a deterministic resolver; never read host resolver config in tests.

Run: `.venv/bin/python -m pytest -q tests/browser/test_url_policy.py -rx`
Expected before Green: missing `BrowserURLPolicy`; after Green: PASS.

- [ ] **Step 5: Implement URL policy and bounded observation**

`BrowserURLPolicy` canonicalizes scheme/IDNA host/default port, validates every A/AAAA answer with
`ipaddress`, and returns an immutable origin/address-set digest. `project_aria_snapshot` caps at
400 nodes/64 KiB/depth 15, strips password/secret/hidden values, binds page/frame/navigation/profile
revisions, and stores no HTML/cookie/header/body/screenshot.

- [ ] **Step 6: Verify Task 1 and record**

Run:
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/browser/test_contracts.py tests/browser/test_url_policy.py tests/browser/test_observation.py -rx`
then touched Ruff and `git diff --check`. Record exact counts and `next_task=2`.

---

### Task 2: Build owner-only profile and session stores

**Files:**
- Create: `agent/browser/profile_store.py`
- Create: `agent/browser/session_store.py`
- Create: `tests/browser/test_profile_store.py`
- Create: `tests/browser/test_profile_locking.py`
- Create: `tests/browser/test_session_store.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Consumes `BrowserSessionSpecV1`, browser/profile identity digests.
- Produces `BrowserProfileRefV1`, `BrowserProfileStore.create/open/acquire_writer/release_writer/
  revoke/clear`, `BrowserSessionStore.begin/compare_and_swap/record_observation/
  begin_action/record_result/close`.

- [ ] **Step 1: Write store safety Reds**

```python
def test_profile_metadata_is_owner_only_and_opaque(tmp_path):
    ref = store(tmp_path).create(site_policy_digest="a" * 64,
                                 account_label="alice@example.test",
                                 browser_identity_digest="b" * 64)
    assert "alice" not in ref.profile_id
    assert stat.S_IMODE((tmp_path / ref.profile_id).stat().st_mode) == 0o700

def test_uncertain_writer_identity_never_steals_lock(tmp_path):
    current = make_store(tmp_path).create(
        site_policy_digest="a" * 64,
        account_label="test account",
        browser_identity_digest="b" * 64,
    )
    write_corrupt_live_lock(current)
    with pytest.raises(ProfileLockUnknownError):
        make_store(tmp_path).acquire_writer(current)
```

- [ ] **Step 2: Run Reds, then implement descriptor-safe profile store**

Use `os.open`/`O_NOFOLLOW`/exclusive create, 0700 directories, 0600 metadata, revision CAS and
pid/start identity lock. `clear` first revokes, closes writer, deletes only canonical owned root,
and returns `CLEANUP_UNKNOWN` on partial/identity uncertainty. Never expose or parse storage-state.

- [ ] **Step 3: Write session-ledger Reds**

Prove exact transitions `OPENING→ACTIVE→ACTION_PREPARED→EXECUTING→RESULT_OBSERVED→CLOSED`,
exclusive initialize, CAS, corruption fail closed, action/observation identity binding, and no raw
URL text/page body/form value/cookie/account label in ledger.

- [ ] **Step 4: Implement bounded session ledger**

Store only opaque IDs/digests, closed phases and last action outcome. An `EXECUTING` record without
result is recoverable unknown, never converted to not-executed. Profile revision drift blocks open.

- [ ] **Step 5: Verify Task 2 and record**

Run all three Task 2 tests, touched Ruff, `git diff --check`; record exact counts and `next_task=3`.

---

### Task 3: Implement real Chromium public-read adapter and egress guard

**Files:**
- Create: `agent/browser/playwright_adapter.py`
- Create: `tests/browser/test_public_read.py`
- Create: `tests/browser/test_egress_guard.py`
- Create: `tests/browser/test_browser_cleanup.py`
- Modify: `pyproject.toml`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Consumes Task 1 ports/policy/observation and Task 2 stores.
- Produces `PlaywrightBrowserEnvironment` and `BrowserQualificationV1`.

- [ ] **Step 1: Add optional dependency Reds**

Assert base wheel metadata has no Playwright dependency and `browser` extra is exactly
`playwright==1.62.0`. Importing base CLI with Playwright unavailable must succeed; constructing
browser resources returns closed `browser_package_missing`, not traceback/fallback.

- [ ] **Step 2: Write fake-Playwright public-read Reds**

Assert fresh non-persistent context, headless, extensions absent, no storage-state import,
`accept_downloads=False` for public-read, timeout/cap values, ARIA projection, and only
navigate/observed-link/back/reload/scroll/observe actions. Fill/upload/download/submit reject before
Playwright calls.

- [ ] **Step 3: Write egress routing Reds**

Every request event—document, redirect, popup, frame, subresource, WebSocket—must invoke the same
guard with current mode/origins. A rejected request increments guard-attempt count but network-send
count remains zero. Test-only resolver/transport injection must be constructor-only; production
factory has no `allow_private`/`disable_guard` option.

- [ ] **Step 4: Implement adapter-owned Playwright thread**

Start Playwright sync API and Chromium in one adapter-owned worker thread; callers use bounded
request/response messages, not Playwright objects. Public-read uses one browser + fresh context;
all timeouts are nonzero and capped. `close` closes page/context/browser/Playwright and confirms
worker exit; uncertainty marks handle unusable.

- [ ] **Step 5: Verify Task 3 and record**

Run Task 1–3 browser tests only, touched Ruff, diff-check. Do not install/download Chromium in this
focused gate. Record counts and `next_task=4`.

---

### Task 4: Add site-bound actions and pure consequence policy

**Files:**
- Create: `agent/browser/action_policy.py`
- Modify: `agent/browser/playwright_adapter.py`
- Create: `tests/browser/test_action_policy.py`
- Create: `tests/browser/test_interactive_actions.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces `BrowserActionPolicy.prepare(observation, action) -> BrowserActionBindingV1`.
- `BrowserActionBindingV1` contains exact consequence, identity digest and bounded preview.
- Adapter `execute` revalidates binding and returns receipt/KnownNotExecuted.

- [ ] **Step 1: Write closed consequence matrix Reds**

Observed same-origin links/scroll/back/reload=`OBSERVE`; any fill/model-built query=`DISCLOSE`;
download=`DOWNLOAD`; upload=`UPLOAD`; submit/send/publish/purchase/book/delete/cancel/account/
security/privacy/legal and unknown=`COMMIT`. Model `risk=low` is ignored.

- [ ] **Step 2: Write mutation Reds**

Mutate observation/page/frame/profile revision, ref, role/name/type, form action/method/origin,
field/value digest, upload digest, action params and approval use; every case must return
`KnownNotExecuted(stale_browser_target|browser_binding_changed)` with action send count zero.

- [ ] **Step 3: Implement pure policy**

The module imports only contracts; it does not import Playwright/Runtime/ToolRuntime. It builds
preview from typed metadata, never page prose. Unknown is commit. It must not call resolver/browser.

- [ ] **Step 4: Implement adapter preflight and interactive actions**

Persistent context uses only owner profile root and exact origins. Immediately before effect,
re-observe and compare the complete binding. Use role/label/ref-derived Playwright locators only;
do not accept CSS/XPath/JS/coordinates/keyboard/clipboard/CDP. Record fresh post-observation.

- [ ] **Step 5: Verify Task 4 and record**

Run action policy + interactive + prior browser focused tests; touched Ruff/diff-check;
record counts and `next_task=5`.

---

### Task 5: Add Runtime-owned browser authority and takeover state

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/context.py`
- Modify: `agent/runtime/views.py`
- Modify: `agent/runtime/loop.py`
- Create: `tests/continuity/test_browser_authority.py`
- Create: `tests/continuity/test_browser_takeover.py`
- Create: `tests/continuity/test_browser_recovery.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Adds `ExecutionAuthorityClass.BROWSER_SESSION`.
- Produces `BrowserActionCandidateV1`, `BrowserAuthorityLeaseV1`,
  `BrowserTakeoverRequestV1`, typed `CompleteBrowserTakeover` and `CancelBrowserTakeover`.
- `ApprovalRequest` carries at most one strict browser candidate; checkpoint codec stays exact.

- [ ] **Step 1: Write browser candidate/lease Reds**

Approval binds Goal/revision/profile/session/browser/origins/page/frame/observation/target/params/
consequence/expiry/single-use. Goal correction/cancel, profile/browser revision, origin expansion,
expiry or reuse invalidates lease. Public-read lease cannot authorize interactive action.

- [ ] **Step 2: Write takeover state-machine Reds**

Browser tool result may request takeover; Runtime persists pending state before exposing the user
action. While pending, context advertises only complete/cancel controls and provider/tool counters
remain unchanged. Complete validates exact request/session/profile, increments expected revision,
clears pending, and requires browser_observe; it does not mint commit approval.

- [ ] **Step 3: Write restart/security Reds**

LocalCheckpointStore reopen projects “browser takeover waiting” and `/browser-done`/`/cancel`, not
“resuming”. Lost/mismatched session becomes needs-human. Scan serialized state/events/views/context
for test credential, cookie/storage-state/password/form-value sentinels; all absent.

- [ ] **Step 4: Implement minimal Runtime transitions**

Reuse existing approval/action reducer patterns; do not add a browser runner. `AgentRuntime` only
interprets typed browser ToolResult/takeover controls and continues the existing `_drive` loop.
CLI 只翻译 typed complete/cancel；complete 的 exact live-session 校验与幂等 profile revision
推进经 composition 注入的 browser lifecycle port 由同一 `AgentRuntime` 调用。其他 browser
state mutations 仍只经既有 ToolRuntime invocation。

- [ ] **Step 5: Verify Task 5 and record**

Run three new continuity files plus existing approval/effect-order/context/codec focused suites;
touched Ruff/diff-check; record counts and `next_task=6`.

---

### Task 6: Register governed browser tools without a second policy owner

**Files:**
- Create: `agent/browser/tools.py`
- Modify: `agent/runtime/tool_governance.py`
- Modify: `agent/runtime/tools.py`
- Create: `tests/browser/test_tools.py`
- Create: `tests/browser/test_tool_authority.py`
- Modify: `tests/kernel/test_tool_governance.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces registrations `browser_open`, `browser_observe`, `browser_act`, `browser_close`,
  `browser_begin_takeover`.
- Profile list/revoke/clear remain user controls, not model tools.

- [ ] **Step 1: Write registration surface Reds**

Assert exact five names, strict schemas, no raw JS/CSS/XPath/CDP/launch args/host path, bounded
results, browser execution authority, and no registration callable can access provider/checkpoint/
ContextManager. Unknown browser action rejects before adapter call.

- [ ] **Step 2: Write approval/effect-order Reds**

`browser_open` binds mode/origins/profile; `browser_observe` is read-only inside matching session;
`browser_act` uses `BrowserActionPolicy` binding; every non-OBSERVE consequence returns exact
`ApprovalRequired`. Denial => adapter execute count 0. Approval => checkpoint phase EXECUTING is
saved before exactly one adapter execute and result checkpoint after.

- [ ] **Step 3: Implement registrations and the narrow governance seam**

`prepare_binding` uses only typed args + durable observation/store lookup; no browser I/O.
`func` invokes the adapter only after ToolRuntime intent validation. Extend existing governance
through a typed browser candidate branch; do not create `BrowserToolRuntime` or self-authorizing
callable.

- [ ] **Step 4: Write false-authority Reds**

Forged/partial/stale lease, changed origin/action/value, prompt-injection text requesting expanded
origin, old approval after correction and double use all fail closed. Same-origin safe observation
remains usable without extra prompts.

- [ ] **Step 5: Verify Task 6 and record**

Run browser tool/authority plus runtime tools/governance/effect-order suites; touched Ruff/diff;
record counts and `next_task=7`.

---

### Task 7: Govern upload staging and download quarantine

**Files:**
- Create: `agent/browser/quarantine.py`
- Modify: `agent/browser/playwright_adapter.py`
- Modify: `agent/browser/tools.py`
- Create: `tests/browser/test_upload.py`
- Create: `tests/browser/test_download.py`
- Create: `tests/browser/test_quarantine.py`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces `BrowserQuarantine.store/inspect/delete/clear_session` and
  `QuarantinedDownloadV1` 与 opaque `BrowserUploadStagingV1` capability。
- Upload consumes workspace-relative `path` + exact digest；ToolRuntime 只传 one-shot opaque
  capability，adapter 内部重新解析 owner-owned staging path/quarantine。

- [ ] **Step 1: Write upload Reds**

Regular workspace file <=25 MiB positive. Reject absolute/traversal/symlink/directory/device/
protected/private/runtime path, changed inode/digest/size, wrong origin/ref/field and missing exact
UPLOAD approval. Positive server receives exactly approved digest once.

- [ ] **Step 2: Write download Reds**

Approved download stays below owner-only quarantine, <=100 MiB, normalized opaque filename,
source/suggested-name digest/MIME/size/sha256/action identity receipt. Workspace tree stays unchanged.
Unapproved/oversize/partial has no consumable receipt; no open/execute/unarchive/import call.

- [ ] **Step 3: Implement descriptor-safe quarantine and staging**

Use exclusive files, no-follow parent walk, bounded streaming hash and fsync/replace. Quarantine
paths never enter model/event/checkpoint; receipts use opaque ID/digests. Cleanup uncertainty marks
session unusable and never fabricates deletion.

- [ ] **Step 4: Integrate Playwright download events**

Persistent context uses dedicated quarantine downloads path. Only a current approved DOWNLOAD
token may become a receipt; all other downloads are canceled/deleted or quarantined-unclaimed.
Upload staging is deleted after action; deletion uncertainty is explicit.

- [ ] **Step 5: Verify Task 7 and record**

Run three file tests plus actions/tools/recovery; touched Ruff/diff; record counts/`next_task=8`.

---

### Task 8: Compose optional browser resources, CLI UX and evidence closure

**Files:**
- Modify: `agent/composition.py`
- Modify: `main.py`
- Modify: `agent/runtime/evidence.py`
- Modify: `agent/runtime/views.py`
- Create: `tests/browser/test_composition.py`
- Create: `tests/cli/test_018_browser_experience.py`
- Create: `tests/continuity/test_browser_verified_done.py`
- Modify: `tests/architecture/test_runtime_owner.py`
- Modify: `README.md`
- Modify: `STRATEGY.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces `BrowserResources(registrations, closeables, readiness, reason_code)` and
  `build_browser_resources(workspace, state_root, *, enabled, resolver=None,
  playwright_factory=None) -> BrowserResources`. Production passes neither injection; tests may
  inject closed fakes. The function exposes no `allow_private` or guard-disable parameter.
- Adds user-only CLI actions for profile create/list/revoke/clear and takeover complete/cancel.

- [ ] **Step 1: Write optional-composition Reds**

Base startup with no Playwright remains Green. Explicit browser configuration performs read-only
qualification; missing package/binary/profile-permission/egress readiness returns one closed reason
and zero registration, no Chrome/Safari/CDP fallback. Reverse close stack closes sessions/worker.

- [ ] **Step 2: Write UX Reds**

Startup renders exactly one readiness state and next action. Approval preview contains exact site/
action/consequence/bounded fields but no raw secret/internal path. Takeover restart text is accurate.
Errors have no traceback/schema/cookie/account-label/profile-path. Profile management is user-only.

- [ ] **Step 3: Integrate browser receipts into evidence closure**

Add a closed browser receipt oracle to `ClosedEvidenceRegistry`; browser DOM success/prose alone
cannot verify. Tests cover durable action receipt + fresh read-back positive and fake/stale/unknown/
denied/old-profile negatives. Keep evidence as pure derivation; it cannot call browser/tools.

- [ ] **Step 4: Compose and document conservative capability**

Construct stores/adapter/registrations only in composition root. README/STRATEGY/status say
“018 candidate” until U3; explicitly exclude personal browser/desktop/arbitrary-site/production-ready.

- [ ] **Step 5: Verify Task 8 and record**

Run composition/CLI/evidence/owner plus all `tests/browser`; touched Ruff/diff; record counts and
`next_task=9`. Do not run full suite yet.

---

### Task 9: Close deterministic 018, freeze source and run one full source gate

**Files:**
- Create: `tests/reference/test_018_governed_browser_tasks.py`
- Create: `tests/reference/test_018_e3_harness.py`
- Create: `scripts/run_018_e3.py`
- Create: `scripts/verify_018_materialized_tree.py`
- Create: `docs/implementation/018_DELIVERY_SEAL.json`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`

**Interfaces:**
- Produces deterministic 018 journey/claim matrix and strict seal/receipt schemas.
- Produces verifier modes `--check-membership`, `--control-seal`, `--content`, `--attestation`.

- [x] **Step 1: Write deterministic journey and mutation oracles**

Map every U1 claim to exact tests. Use independent counters for provider, browser prepare/execute,
network guard/send, submit/upload/download, profile revision, quarantine/workspace mutation and
completion. False-positive mutation of any closed bool/counter must fail the harness.

- [x] **Step 2: Implement runner/verifier closed schemas**

Runner emits only bounded booleans/enums/counts/digests; no transcript/page/profile path/credential.
Receipt binds materialized root/seal/verifier/runner/wheel/Playwright/Chromium/fixture and three
attempts. Verifier separately validates identity, shape and every claim; old receipt mismatch fails.

- [x] **Step 3: Run the final focused gate**

Run all browser/reference/harness plus affected continuity/kernel/CLI/architecture tests. Fix only
within frozen scope. Once Green, stop ordinary source edits except final gate fixes.

- [x] **Step 4: Run one source full gate**

Run, without pipes/truncation:

```bash
git diff --check
.venv/bin/ruff check --no-cache .
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -rx
```

All must complete exit 0. Record exact counts/duration/identity. A fix after this invalidates the
full gate; rerun only after the new fix set is complete, not after every edit.

- [ ] **Step 5: Seal ordinary overlay**

Seal exact admitted ordinary paths; exclude `.env`, secrets, credentials, private/runtime, profile/
quarantine/browser binary caches, untracked `tui/`, Coding Agent artifacts. Verify membership and
control seal Green; record `next_task=10`.

---

### Task 10: Run materialized real Chromium E3 and fresh independent review

**Files:**
- Create: `docs/implementation/018_E3_RECEIPT.json`
- Create: `docs/acceptance/018_GOVERNED_BROWSER_TASKS_INDEPENDENT_REVIEW.md`
- Modify: `docs/implementation/018_EXECUTION_LOG.md`
- Modify: `README.md`
- Modify: `STRATEGY.md`
- Modify: `docs/architecture/CURRENT_CAPABILITY_STATUS.md`

**Interfaces:**
- Consumes sealed source and frozen E3.
- Produces one current-identity 3×13 receipt and detached U3 review.

- [ ] **Step 1: Materialize and install clean artifacts**

Materialize only admitted source, build wheel once, test base install in clean venv, install browser
extra, explicitly install/qualify receipt-bound bundled Chromium, then run materialized full suite.
Do not inherit host site-packages; do not use user browser profile/cache as evidence.

- [ ] **Step 2: Start deterministic hostile site and guarded test transport**

Create fresh test-only TLS site/profile/quarantine roots. Fixture injection is constructor-only and
identity-bound. Separately prove production guard rejects a real loopback listener with control
reachability and server request count zero.

- [ ] **Step 3: Run three real attempts without overwrite**

Run all 13 frozen journeys per attempt with real Chromium. Any failure ends the attempt and U2;
never rerun over the same attempt number. At completion confirm browser worker/process, profile lock,
test server and quarantine cleanup; unknown cleanup blocks receipt.

- [ ] **Step 4: Write current receipt and verify attestation**

Write receipt only after source/materialized/real gates Green. Run membership, control-seal and
attestation; require `3 real attempts × 13 true journeys` and exact current identity.

- [ ] **Step 5: Fresh two-axis review**

Fresh Spec/Product reviewer and Standards/Architecture reviewer independently read frozen contract,
diff, current receipt and run adversarial reducers. They must verify unique owners, exact approvals,
send/effect counters, profile secrecy, takeover, SSRF/injection, quarantine, recovery, false
completion, cleanup and identity. Any fix invalidates seal/receipt and returns to the smallest
affected gate, followed by one final full/materialized/real rerun after fixes settle.

- [ ] **Step 6: Promote conservative status**

Only after both reviewers PASS, bind detached review to current identity and update docs from
candidate to accepted/delivered. Final user capability statement: governed tasks in a dedicated
Chromium profile with exact approvals; not personal browser/desktop control, arbitrary website
compatibility, background autonomy or production-ready third-party integration. Record 018 complete
and hand off to 019 research; do not start 019 implementation in the same unreviewed change set.
