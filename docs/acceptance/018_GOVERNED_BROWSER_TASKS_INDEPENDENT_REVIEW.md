# 018 Governed Browser Tasks — Independent Review

- Date: 2026-08-28
- Status: **PASS**
- Review axes: fresh Spec/Product reviewer + fresh Standards/Architecture reviewer
- Scope: frozen 018 dedicated-Chromium governed browser tasks only

## Bound delivery identity

- ordinary overlay root：
  `a32e575cbe248618d3c1468cbcb64e38b4d0dde0e026c15406ae966a4a052363`
- entry count：`309`
- delivery seal SHA-256：
  `5d187b2794c282c5ec8f3ac71aff337a441088c1123799b86e76c2aec67ed421`
- base manifest SHA-256：
  `4da6fe1f158bf0c57ef6c2160ce9076a90b1125404e32f5ee2d81fd86460e74f`
- 017 parent seal SHA-256：
  `527f47ce26a9eb2f8311fa4a78684dd6854f0e9dfe81dac91a31bc89817989d1`
- verifier SHA-256：
  `5b10ae6d053ee09d4775bc8886fc84d15841b17e2825a377fe396569b01d0a21`
- runner SHA-256：
  `a7955735c3cd77855603cfcdd6c070587c4343c29b5ef490fde90fbc85ea7480`
- materialized root SHA-256：
  `5d8490689aec430c625d7086c5bb53d7a92130ac4a3aba4d3abb1d8715152d41`
- materialized wheel SHA-256：
  `07bab579db23314fc29f5befa2ddf6ecbbe0ee14e9cbfe8abf90e0dcc5ee146b`
- U2 receipt SHA-256：
  `c731b59dc7941decdf680a622278c97df135c8d24268137322c6313bdba1d1ba`
- Playwright：`1.62.0`
- Chromium revision：`1234`
- Chromium executable SHA-256：
  `a596b1cfc6353e987fcec8d71a23a28cd6a9e7a6b4e20b908e4c4fcffe51158e`
- hostile egress fixture SHA-256：
  `c6d1cdc276882f4c34cddf36cd3ef1d60da9f2af3276e69500e4ecb5ca4e6f52`

## Delivery gates

- Source full：`2203 passed in 284.31s`，exit 0。
- Materialized full：`2201 passed, 2 skipped in 250.07s`，exit 0。
- Membership：`309 exact entries`，exit 0。
- Control seal：base + 017 parent + verifier + 018 overlay Green，exit 0。
- Attestation：`3 real attempts × 13 true journeys`，exit 0。
- 每次 attempt 的 claim gate 都是 `63/63`，三份 profile/session/quarantine identity
  均为 fresh receipt-bound identities。

## Spec/Product independent review

Fresh reviewer 没有复用旧 seal 的结论，亲验 current membership、control-seal、attestation、
544 个 018 focused tests，以及真实 Chromium mutation：

- J2 删除全部 seed、只保留 cookie、只保留 localStorage 时，storage subcheck 和整旅程均
  fail closed；fresh session 复用任一 storage 也不能通过。
- J4 分别移除 redirect、popup、frame、subresource、WebSocket trigger 时，对应 closed
  subcheck 与整旅程均失败；per-kind send 必须保持零。
- J6 把 headed takeover 变成 no-op 时，`headed_activation_observed` 与整旅程均失败。
- J8 opposite denial、J10–J13 mutation/non-vacuity、takeover、unknown recovery、profile
  secrecy 与 receipt secrecy 均闭合；receipt 不含 credential、cookie、host path、页面正文
  或 transcript。

Verdict: **PASS**，无 Spec/Product promotion blocker。

## Standards/Architecture independent review

Fresh reviewer 亲验 current identity 三门、229 个 browser/continuity/reference/architecture
focused tests、touched Ruff 与 `git diff --check`：

- `AgentRuntime.run_turn` 仍是唯一 production state/model/tool loop；`ContextManager` 与
  `ToolRuntime` ownership 未漂移，CLI 只提交 typed actions。
- Browser adapter 不拥有 approval/state progression；takeover pending 在 headed activation
  前 durable，pending 期间 provider/tool/observe 保持零。
- J4 telemetry 只有 closed `RequestKind -> integer` counters，不保存 URL、页面正文或请求
  内容，也不构成第二条 egress policy/authority seam。
- J2 使用真实 seed/readback/clean close/fresh readback；不是静态文案 oracle。
- cleanup unknown、profile writer、session ledger、quarantine 与 process cleanup 继续
  fail closed；没有 compatibility fallback、personal-browser reuse 或第二套 loop。

Verdict: **PASS**，无 Standards/Architecture promotion blocker。

## Promotion decision

**PASS.** 上述 exact identity 在 frozen 018 v1 scope 内为 `accepted/delivered`。

该结论只覆盖 dedicated Chromium、bounded sites/actions、exact approval、explicit user
takeover、closed egress guard 与 download quarantine。它不宣称 personal Chrome/Edge、
desktop/OS control、任意网站或第三方兼容、后台常驻调度、任意 JS/CDP、credential export，
也不宣称 production-ready 或跨平台保证。
