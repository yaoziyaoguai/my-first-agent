---
title: "018 Governed Browser Tasks Design"
date: 2026-08-28
status: frozen-user-approved-2026-08-28
authority: user-approved-design-summary-2026-08-28
supersedes: docs/superpowers/specs/2026-08-26-governed-execution-program-design.md §5 and docs/superpowers/plans/2026-08-26-018-governed-browser-tasks.md where they depend on Docker, ChangeBundle, a SandboxEnvironment, or an implicit personal-browser profile
---

# 018 Governed Browser Tasks Design

> 用户已于 2026-08-28 批准本设计摘要：First Agent 专属隔离 Chromium、
> Runtime/ToolRuntime 唯一治理、精确操作审批、显式登录接管、SSRF 与 prompt
> injection 防护、下载隔离，不增加第二套 Agent loop。本文把该摘要收敛为
> 可实现的书面合同；用户已于 2026-08-28 review 并批准本文，现为 frozen
> authority。任何产品边界变更必须先回到 design review。

## 0. 研究结论与方向裁决

018 不嵌入 `browser-use`、BrowserGym 或 Playwright MCP 的 agent loop。它们可作为
对照或评测工具，但产品仍只有一个 `AgentRuntime.run_turn`。018 只把 Playwright
Chromium 包装成一个受注入的 `BrowserEnvironment` external-effect adapter，并把
所有模型决策、Goal、approval、checkpoint 与 completion 语义留在既有 Runtime。

采用 Playwright 的理由：

- `BrowserContext` 是隔离的 cookie/local-storage/session-storage 边界，适合公开
  读取的 fresh session；
- `launch_persistent_context(user_data_dir)` 支持 First Agent 自己拥有的持久
  profile，且 Playwright 官方明确警告不要自动化用户日常 Chrome profile；
- role/label/ARIA locator 和 `aria_snapshot(mode="ai")` 提供 bounded、可重建的
  structured observation；locator 会在 action 时重新解析，因此 approval 不能只绑
  locator 字符串，必须绑 observation 与 action identity；
- Playwright 是 browser adapter，不是安全边界。网页 prompt injection 仍是未解决的
  行业问题，所以页面内容永远是 untrusted data，不能授予 authority。

017 已经是 macOS native Seatbelt，不存在旧计划假设的 Docker snapshot、
`SandboxEnvironment`、artifact store 或 ChangeBundle。018 因而拥有自己的 quarantine；
下载不会自动进入 workspace，也不会虚构 017 尚不存在的 bundle/import API。

## 1. 用户结果与准确声明

用户可以要求 First Agent：

1. 在 fresh Chromium session 中访问公开 HTTPS 页面并读取、比较、整理内容；
2. 在 First Agent 专属 site-bound profile 中完成登录后的有界网页任务；
3. 在用户接管窗口完成密码、2FA、CAPTCHA 或支付验证，然后把控制权交还；
4. 填写表单草稿，并在发送、提交、购买、删除、上传等后果性动作前查看 exact
   preview 并批准或拒绝；
5. 把批准的下载保存到 First Agent quarantine，得到 bounded metadata/digest，
   但不会自动执行或写入 workspace。

018 不宣称个人 Chrome 接管、任意网站兼容、桌面/鼠标/键盘控制、验证码绕过、
无监督购买、浏览器扩展、任意 JavaScript/CDP、下载执行或 production-ready。

## 2. 不可破坏的 owner 合同

- `AgentRuntime.run_turn` 仍是唯一 production model/tool loop 与 state mutation owner。
- `ContextManager` 仍独占 context selection；网页正文只以 bounded untrusted tool
  result/context source 进入，不得进入 system/control frame。
- `KernelToolRuntime` 仍独占 tool admission、risk classification、approval、
  `EXECUTING` checkpoint、invoke 与 result checkpoint。
- `BrowserEnvironment` 只消费已治理的 typed request 并返回 typed observation/receipt；
  不认识 Provider、Goal、ContextPack、checkpoint 或 approval，不调用模型、不声明
  completion、不自行重试 unknown effect。
- browser profile/session/quarantine store 只拥有 browser lifecycle state；profile
  存在不等于网页 action authority。
- CLI/headless/scheduler 只能翻译 typed user action 与渲染结果，不新增 browser loop。

## 3. Deep-module 边界

### 3.1 `BrowserEnvironment`

```text
open(spec) -> BrowserHandle
observe(handle) -> BrowserObservation
execute(handle, approved_action, opaque_upload_staging?) -> BrowserActionReceipt | KnownNotExecuted
begin_takeover(handle) -> None
takeover_session_active(session_ref) -> bool
close(handle) -> BrowserCleanupReceipt
```

`BrowserActionPolicy.prepare(observation, action)` 是纯函数：从 durable bounded
observation 产生 ToolRuntime approval binding，不访问 browser。`execute` 只在既有
`EXECUTING` checkpoint 后运行；它必须立即 re-observe/re-resolve target，并只执行未漂移
的 exact approved action。这样 approval preview 不会在 checkpoint 外偷偷触发 browser
I/O。adapter 不接受 raw JavaScript、CSS/XPath、CDP method、shell、host path 或任意
browser launch args。upload staging 只以 browser-owned opaque capability 传入；真实 host
path 与 `BrowserQuarantine` 实例始终由 adapter 内部拥有并在 effect 前重新校验。

### 3.2 `BrowserProfileStore`

- First Agent owner-only root；目录 0700、metadata 0600、no-follow、canonical path；
- profile filename 只含 opaque ID，不含 site/account 原文；
- 一份 persistent profile 同时最多一个 writer；锁身份不确定时 fail closed；
- public interface 只返回 profile ID/revision、site-policy digest、account-label digest、
  browser identity digest、状态；不导出 cookie/storage-state/history/password；
- revoke/clear 是 user-only typed action，不作为模型工具；clear 不完整则 quarantine
  profile 并阻止复用。

### 3.3 `BrowserEgressGuard`

Playwright 本身不是 SSRF 防线。所有 browser request 必须经过一个 adapter-owned
egress guard；production composition 不允许替换成 permissive fallback。

- 只允许 `https`；拒绝 userinfo、非规范 host/port、IP literal、localhost、
  loopback、private、link-local、multicast、unspecified、reserved、cloud metadata；
- 对每个 hostname 的全部 A/AAAA answer 做 public-address 验证；redirect、popup、
  iframe、subresource、WebSocket 与新 page 都重新判定；DNS/address 漂移 fail closed；
- `SITE_BOUND_INTERACTIVE` 还要求 canonical origin 属于 session 的 exact allowlist；
- page text、redirect target、service worker、CSP 或 model 参数都不能扩大 allowlist；
- 实现必须提供可测试的 resolver/transport port；test-only loopback fixture admission
  只通过构造注入，production composition 不暴露该开关。

v1 不声称 Playwright URL routing 等于 OS network sandbox。U2 必须对 loopback/private
fixture 做 non-vacuous zero-request oracle，并准确记录被验证的 guard 边界。

## 4. 两种不可静默切换的 session policy

### 4.1 `PUBLIC_READ_EPHEMERAL`

- 每个 session 使用 fresh non-persistent `BrowserContext`；关闭后不保存 cookies、
  local storage 或 session storage；
- headless Chromium；无扩展、无 existing profile、无 storage-state import；
- 允许 HTTPS navigate、follow observed link、back、reload、scroll、observe；
- 不允许 fill/select/upload/submit/download、登录或读取 password/secret input；
- 用户给出的 exact URL 或当前页面 observed link 可导航；模型构造的 URL 若含 query、
  fragment 或把用户/本地文本编码进 URL，按 `DISCLOSE` exact approval 处理；
- session 不升级为 interactive；需要交互时关闭并新建明确的
  `SITE_BOUND_INTERACTIVE` session。

### 4.2 `SITE_BOUND_INTERACTIVE`

- 使用 First Agent 专属 persistent profile 或用户明确选择的 fresh profile；
- session spec 绑定 exact canonical origins、profile revision、browser identity、Goal/
  revision、expiry 与 bounded action budget；
- origin 扩展、profile revision 变化、browser restart、Goal correction/cancel 均使
  authority 失效；
- site-bound 不等于 commit authority。每个 `DISCLOSE`、`DOWNLOAD`、`UPLOAD`、
  `COMMIT` action 仍需 exact approval；
- 一个 session 只有一个 active page writer。popup/new page 必须先经过 egress/origin
  gate，再成为新的明确 page identity。

## 5. Observation、element ref 与 action

### 5.1 Bounded observation

主要 observation 使用 Playwright `aria_snapshot(mode="ai")` 或等价的 role/name/state
投影；v1 不把整页 HTML、network body、cookie/header、console、trace 或任意 screenshot
直接送入模型。

每个 observation 绑定：

- session/profile/browser revision；
- page ID、frame tree digest、canonical URL/origin、navigation revision；
- bounded ARIA snapshot（最多 400 nodes、64 KiB、depth 15）；
- opaque element refs 与最小 role/name/type/form metadata；
- observation digest、截断事实、observed_at。

password/secret/hidden input 的 value 永不投影；普通 input 也只投影是否为空及 bounded
公开 label，不回显 takeover 期间用户输入。截图仅可在后续独立设计中作为 user-visible
辅助；018 v1 receipt 最多保存 screenshot digest，不保存图片。

### 5.2 Closed actions

v1 只支持：`navigate`、`back`、`reload`、`scroll`、`click`、`select`、
`fill_form`（一组 exact fields）、`upload`、`download`、`close`。`observe/find` 是
read-only query，不是 browser effect。

- action 必须引用 current observation digest、page/frame、element ref（适用时）和
  exact parameters；
- `execute` 在 effect 前重新解析同一 ref，并比较 role/name/type/form action/origin；
  漂移 → `KnownNotExecuted(stale_browser_target)`；
- 不接收 model supplied `risk=low`；未知 action/element/form semantics 一律 `COMMIT`；
- 不开放 arbitrary JS/evaluate、CSS/XPath、keyboard typing、mouse coordinates、
  extension、DevTools filesystem、system file picker、clipboard 或打印。

## 6. Consequence policy 与精确批准

| class | 例子 | v1 authority |
| --- | --- | --- |
| `OBSERVE` | observe、scroll、back/reload、approved origin 内 observed link | matching session lease 内可执行 |
| `DISCLOSE` | 向网页填入任何 user/local/model text、构造 query URL | exact approval，展示 origin + fields/value digest/可读摘要 |
| `DOWNLOAD` | 触发并保存下载 | exact approval，展示 origin、target、size cap、quarantine-only |
| `UPLOAD` | 选择 workspace file | exact approval，绑定 no-follow path + digest + field + origin |
| `COMMIT` | send/submit/publish/purchase/book/delete/cancel/account/security/privacy/legal action，或 unknown | 每次 exact approval |

approval candidate 绑定 Goal/revision、session/profile/browser revision、origin allowlist、
page/frame/observation、target metadata、action/parameters、consequence、expiry 与 single use。
任一字段漂移即失效。denial 必须产生零相应 browser effect；仍可做的 safe read-only
分析先继续，只有没有 authority-free progress 且必要 outcome 被拒绝时才 blocked。

## 7. Login 与 user takeover

password、2FA、CAPTCHA、passkey、支付验证或用户明确要求人工处理时：

1. Runtime 在 opening/foregrounding headed window 前 durable 保存 takeover request；
   site-bound 自动化 context 在此之前保持 headless，保存成功后才关闭它并以同一 owner
   profile 打开 headed context；
2. adapter 停止 automation；Runtime 不再调用 provider 或任何 tool；
3. 用户只在 First Agent 专属 profile/window 中操作；产品不 attach 日常 Chrome；
4. takeover 期间不 observe、截图、录屏、trace、读取 DOM/form values、记录 key/mouse；
5. 用户通过 typed `CompleteBrowserTakeover` 或 `CancelBrowserTakeover` 交还；
6. CLI 只提交 typed action；唯一 Runtime 通过 composition 注入的 browser lifecycle port
   校验 exact live headed session、幂等递增 profile revision，再要求 fresh observation；它不批准
   后续 commit；
7. restart 只投影“等待用户完成浏览器接管”及 `/browser-done`、`/cancel`；丢失窗口
   或 profile identity 漂移 → needs-human，不伪称恢复。

checkpoint/event/rendering 只保存 opaque request/profile/session identity 和状态，不保存
credential 或 storage state。浏览器 profile 本身可能包含 cookie，所以整个 profile root
按 credential 等级保护，永不 seal/materialize/提交。

adapter caller ledger 只有在 `CLEANED` receipt 后才删除 session；open/close outcome unknown
保留 writer/quarantine authority并阻止 profile 复用。restart 若不能从当前 composition 证明
exact headed session 仍存活，一律投影 needs-human，不能仅凭旧 checkpoint 显示 waiting。
只有 adapter 在 open request 入队前返回 typed `BrowserOpenNotStartedError`，ToolRuntime 才能
安全释放 writer 并归类 `KnownNotExecuted`；入队后的 error/timeout 一律按 unknown 隔离。

## 8. Prompt injection 边界

- 网页、iframe、下载、alt/ARIA 文本和 browser error 均为 untrusted data；
- 页面指令不能修改 Goal、system policy、origin allowlist、profile、tool definitions、
  approval 或 file/network authority；
- 任何“忽略规则/读取本机秘密/访问其他站点/授权插件/粘贴 token”只会成为 bounded
  observation；若它与 Goal 或 safety policy 冲突，Runtime 给用户一条 bounded risk
  summary 并停止相关 action；
- hard gates 不能依赖模型识别 prompt injection。即使模型服从恶意页面，ToolRuntime/
  egress/action policy 仍必须拒绝越权 effect。

## 9. Upload 与 download quarantine

### 9.1 Upload

- 只接受 workspace-relative regular file；no-follow、size cap 25 MiB、读取时 digest；
- approval 绑定 exact file digest、origin、input ref、declared purpose；
- approval 后先复制到 browser-owned one-shot staging，再调用 Playwright upload；
- digest/path/target/origin 漂移零上传；目录、device、symlink、private/runtime path 拒绝。

### 9.2 Download

- Playwright persistent context 明确设置 dedicated downloads path；任何未批准 download
  只允许落在 owner-only transient quarantine 并立即取消/删除，不产生可消费 receipt；
- approved download 保存到 owner-only quarantine，最大 100 MiB，文件名不可信且重新
  规范化；receipt 记录 source origin、suggested-name digest、MIME、size、sha256、
  browser/session/action identity；
- 不自动 open/execute/unarchive，不写 workspace，不作为 completion evidence；
- 018 v1 不提供 host import/ChangeBundle。用户后续若要使用文件，需要独立、明确的
  workspace import 设计；不能通过 path 泄漏或任意 shell 绕过。

quarantine 位于 browser state root 下，owner-only；它不是 017 sandbox store。017 可以
处理 workspace 中用户已明确导入的文件，但 018 不建立隐式跨模块复制路径。

## 10. Durable lifecycle 与 unknown outcome

- Runtime 的通用 effect checkpoint 顺序不变；browser session ledger 只补充 adapter
  read-back 所需的 request/action identity 与 phase，不存页面正文；
- effect 前明确失败 → `KnownNotExecuted`；
- effect 已知执行 → receipt + fresh observation/read-back，不重复；
- click/submit/download 后 crash 且无法分类 → unknown outcome，session 不自动复用，
  Runtime 要求 re-observe 或用户裁决；
- close/cleanup 不可确认 → `CLEANUP_UNKNOWN`，profile/session writer lock 不被偷取；
- `VERIFIED_DONE` 必须由 existing ClosedEvidenceRegistry 根据 durable browser receipt +
  task-specific read-back evidence 推导；网页成功文案或模型 prose 不是完成证明。

## 11. Composition、安装与 UX

- base install 不依赖 Playwright 或 Chromium；`browser` optional extra 精确 pin 经过
  qualification 的 Playwright version；browser binary 单独显式安装/探测；
- startup 只读 qualification：package、bundled Chromium executable/version、profile
  root permissions、egress guard readiness；不可用时一条 actionable fail-closed 状态，
  不自动下载 binary、不降级到 Safari/Chrome/CDP；
- browser resources 只在 composition root 显式配置时构造，reverse close stack 关闭；
- startup/render 只显示 `browser unavailable / public-read ready / interactive profile
  available` 与一条 next action，不显示 cookie、account 原文、内部 path 或 traceback；
- 018 不把 profile 管理暴露给模型；用户通过 typed CLI action
  create/list/revoke/clear。create 只接受一个 canonical HTTPS origin 与 account
  label，输出只返回 opaque profile ID；profile 的 site-policy digest 必须与后续
  site-bound session 的 exact origin set 一致。

## 12. E3 与 promotion

权威验收见 `docs/acceptance/018_GOVERNED_BROWSER_TASKS_E3.md`。

- U1 用 fake adapter/guard 验证 deterministic authority 与 mutation oracles；
- U2 从 sealed materialized source 构建 wheel，在 clean venv 安装 `.[browser]` 与 receipt-
  bound Chromium，驱动真实 Chromium + deterministic hostile test site，三次全 Green；
- test fixture 可以通过构造注入映射到 loopback，但 production composition 必须继续拒绝
  localhost/private address，并有独立 non-vacuous oracle；
- U3 fresh reviewer 独立审 owner、profile secrecy、exact approval、network/action send
  count、unknown recovery、receipt identity 与 UX，不以旧 receipt 或源码测试代替真实
  Chromium evidence；
- 任何普通 source 变化使 seal/receipt 失效；最终只跑一次 frozen full/materialized/real
  E3，不在每个小 fix 后重跑全套。

## 13. Non-goals

个人 Chrome/Edge profile、Chrome extension、desktop/OS control、任意 JS/CDP、绕过
CAPTCHA/2FA、自动购买/转账、password manager/keychain、浏览器云服务、录屏、cookie
export、跨站共享 profile、任意第三方兼容保证、mobile browser、Firefox/WebKit、后台
常驻调度（019 才处理）、下载导入/执行、production-ready 声明。

## 14. Primary sources

- Playwright BrowserContext isolation:
  https://playwright.dev/python/docs/browser-contexts
- Playwright BrowserType / persistent profile warning / download defaults:
  https://playwright.dev/python/docs/api/class-browsertype
- Playwright authentication state security warning:
  https://playwright.dev/docs/auth
- Playwright locators and ARIA snapshot:
  https://playwright.dev/docs/locators
  https://playwright.dev/python/docs/api/class-locator
- Playwright pages, frames, popups and navigation:
  https://playwright.dev/python/docs/pages
  https://playwright.dev/python/docs/navigations
- Chrome DevTools Protocol security surface and compatibility warning:
  https://chromedevtools.github.io/devtools-protocol/
- OWASP SSRF Prevention Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- Anthropic browser prompt-injection defenses:
  https://www.anthropic.com/research/prompt-injection-defenses
- OpenAI ChatGPT agent system card:
  https://cdn.openai.com/pdf/839e66fc-602c-48bf-81d3-b21eacc3459d/chatgpt_agent_system_card.pdf
- WebArena benchmark and paper:
  https://github.com/web-arena-x/webarena
  https://arxiv.org/abs/2307.13854
- BrowserGym (research/evaluation reference, not product runtime):
  https://github.com/ServiceNow/BrowserGym
- browser-use (comparative implementation; its agent loop/profile reuse is not embedded):
  https://github.com/browser-use/browser-use
