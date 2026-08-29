# 018 Governed Browser Tasks Design

- Date: 2026-08-28
- Status: frozen-user-approved-2026-08-28
- Authority: `docs/superpowers/specs/2026-08-28-governed-browser-tasks-design.md`
- Supersedes: the 018 section of the 2026-08-26 program design and stale 018 plan
  wherever they require Docker, `SandboxEnvironment`, ChangeBundle, personal Chrome,
  or a browser-owned Agent loop.

本文是 018 的 compact architecture contract。完整 rationale、threat model、profile、
observation/action、takeover、quarantine 与 research sources 见 authority spec。

## 1. User outcome

First Agent 可在专属 Chromium 中读取公开网页、在 site-bound profile 完成登录后任务，
并在提交、披露、上传、下载等边界要求 exact approval。它不接管个人 Chrome/桌面，
不宣称任意网站兼容。

## 2. Owner invariants

- `AgentRuntime.run_turn`：唯一 model/tool loop 与 state mutation owner。
- `ContextManager`：唯一 context selection owner；网页为 untrusted data。
- `KernelToolRuntime`：唯一 admission/approval/invoke owner。
- `BrowserEnvironment`：纯 typed external-effect adapter；不认识 Goal/provider/checkpoint。
- adapter 内部拥有 quarantine/host path；ToolRuntime 只传 one-shot opaque upload staging
  capability，不把 concrete store/path 反向注入 port。
- profile/session/quarantine store：只拥有 browser lifecycle state；state 不是 authority。
- profile create/list/revoke/clear 是 user-only CLI control；create 只返回 opaque ID，
  并把一个 canonical HTTPS origin 的 policy digest 与当前 browser identity 固定进 profile。

## 3. Closed session modes

- `PUBLIC_READ_EPHEMERAL`：fresh non-persistent context；HTTPS public read/navigation only；
  无 login/fill/upload/download/submit；不升级。
- `SITE_BOUND_INTERACTIVE`：First Agent-owned profile + exact origins + revision/budget；
  新 origin、profile/browser/Goal drift 使 authority 失效。

个人 Chrome profile、storage-state import/export、CDP attach、extension、arbitrary JS 全拒绝。

## 4. Egress and observation

- 所有 request 经 `BrowserEgressGuard`；HTTPS only；拒绝 localhost/private/link-local/
  metadata/reserved；每次 redirect/popup/iframe/subresource/WebSocket 重验。
- production 无 permissive fallback；test-only loopback fixture 只通过构造注入。
- observation 使用 bounded ARIA projection（400 nodes、64 KiB、depth 15），绑定
  session/page/frame/origin/navigation revision/digest；secret values 永不投影。
- action 只引用 opaque element ref + current observation；adapter 在执行前 re-resolve，
  漂移即 `KnownNotExecuted(stale_browser_target)`。

## 5. Consequence and takeover

- `OBSERVE` 可在 matching session lease 内执行。
- `DISCLOSE`、`DOWNLOAD`、`UPLOAD`、`COMMIT` 每次 exact approval；unknown=`COMMIT`。
- approval 绑定 Goal/profile/session/browser/origin/page/frame/observation/target/params/
  consequence/expiry/single-use；任一漂移失效。
- takeover 前 Runtime durable pause；takeover 期间 provider/tool/observation/recording 为零；
  site-bound 自动化阶段保持 headless；同一 owner profile 只有在 pending checkpoint
  成功后才由既有 ToolRuntime 调 adapter 切换为 headed，不能提前显示窗口；
  CLI 只提交 typed complete；Runtime 经注入的 browser lifecycle port 校验 exact live headed
  session，幂等完成 profile revision++ 并 fresh observe；takeover 不批准后续 commit。

## 6. Files and recovery

- upload 只接受 workspace regular file，no-follow、25 MiB cap、exact digest approval。
- download 只进入 browser-owned owner-only quarantine，100 MiB cap；不 open/execute/
  import workspace；018 不虚构 017 ChangeBundle。
- effect 前失败可 replan；executed 要 receipt+read-back；unknown 不重放；cleanup unknown
  保留 writer/session quarantine 并禁复用；只有 `CLEANED` 才从 caller ledger 删除；
  `VERIFIED_DONE` 仍由 durable evidence 推导。
- open 只有在 request 入队前的 typed not-started classification 才可释放 writer；入队后
  error/timeout outcome unknown，禁止自动重开同 profile。

## 7. Installation and E3

Base install 无 Playwright/Chromium。browser extra + binary 显式 qualification，不自动下载、
不 fallback。U2 用 sealed source、clean venv、receipt-bound real Chromium 与 hostile local
fixture 三连；production private-address rejection 单独 non-vacuous 验证。U3 fresh reviewer
PASS 后才声明 018 delivered。
