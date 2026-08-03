# Capability Reference Task Protocol

## Purpose

本协议把“代码接通”“本地 fixture 通过”和“能力值得保留”分开，防止自动测试被写成产品验收结论。

它不授权真实 provider、credential、private workspace 或外部 MCP 调用。每次需要真实外部调用时，必须由用户单独批准任务、数据范围、provider/server destination 和可接受副作用。

## Evidence ladder

| Level | Name | Evidence | Can prove |
|---|---|---|---|
| E0 | static contract | architecture tests、call-site search、type/schema checks | 边界形状 |
| E1 | deterministic behavior | unit/property/fault tests | 已覆盖输入下的行为 |
| E2 | local integration | FakeProvider、repo-owned fixture、temp state | 本地 wiring 与 failure classification |
| E3 | operator-approved reference task | 明确任务、真实入口、safe data、人工核对 | capability 对一个真实任务有价值 |

E0-E2 不能替代 E3。E3 也不能替代安全 fault matrix。

## Common preflight

每个 reference task 开始前记录：

- capability、代码 revision 或 worktree digest。
- 用户批准的目标和成功判据。
- provider/server/profile 的非秘密 identity。
- 输入数据范围，确认不含 secret/private runtime data。
- 最大 model/tool/effect count、timeout 和人工停止条件。
- 是否允许写入；若允许，精确目标和回滚方法。
- 对照组或 baseline。

执行时保留 bounded evidence：typed actions、approval preview、RunStatus、调用计数、checkpoint terminal state、可核对输出。不得保存 credential、raw private prompt、完整 Memory inventory 或绝对私有路径。

## Capability tasks

### Skill

- **Task:** 用户提供一个 operator-approved 临时 Skill 和一个 resource，让 Agent 通过正常工具发现、激活并完成一个领域回答。
- **Baseline:** 不配置 Skill 的同一任务。
- **Pass:** Agent 没有 system/prompt hook，完整 guidance 与 resource 经 paired tool result 进入 context；最终答案正确应用至少一条 baseline 不具备的规则；scripts/URL 不可执行。
- **Evidence:** tool trace、未裁剪 activation/resource digest、答案差异、model/tool counts。

### MCP

- **Task:** 用户批准一个 local operator-trusted MCP server，用无敏感数据完成一次可独立核对的 benign effect。
- **Baseline:** 直接调用同一 fixture 的 expected result，或只读 local oracle。
- **Pass:** preview 完整显示 executable/server/tool/profile/generation/canonical arguments；approval → EXECUTING → one call → result checkpoint；server-side effect/result 与 report 一致；重复 action 不增加 effect count。
- **Stop:** executable/profile/arguments 漂移、preview overflow、latch ARMED、unknown outcome 或 cleanup uncertainty。

### Memory

- **Task:** conversation A 经完整 preview 批准保存一条非敏感项目约定；独立 conversation B 在相关查询中召回并正确应用。
- **Baseline:** 不配置 Memory 的 conversation B。
- **Pass:** recall candidate 在预算内以 untrusted context 进入；答案有可核对改善；不相关 query 不召回；update/forget preview 可核对且下一次 build 才生效。
- **Evidence:** store revision、candidate ID/digest、BudgetReport included/excluded/clipped、provider destination identity。

### SubAgent

- **Eligibility:** composition exposes a provider-native hard total-deadline/termination receipt within the child cap；current OpenAI/Anthropic HTTP adapters are not eligible for v1 SubAgent E3.
- **Task:** 对一个 bounded 设计提案分别运行 parent direct answer 与 parent + child review。
- **Baseline:** parent direct answer。
- **Pass:** child 只调用一次同 trust-domain provider、无工具/Memory/workspace；在 deadline 内结束；产生至少一个经人工确认的增量观点，且成本/时长被记录。
- **Fail:** 无增量、超时无法证明请求终止、handoff 泄露超出批准范围或 child 请求工具。

### Scheduler

- **Task:** 外部 caller fire 一个 benign occurrence，使其先进入 `needs_human`；人类从相对 checkpoint reference 完成 resolution；再次 duplicate fire。
- **Pass:** 首次 action identity deterministic；人类 resolution 使用新 seq；最终 duplicate report 反映 authoritative terminal state；provider/effect count 不增加；同 ID 漂移和并发 loser fail closed。

### TUI

- **Task:** 纯键盘走完 submit → approval/reject 或 recovery → terminal，并从 durable pending checkpoint 重启一次。
- **Baseline:** CLI 对同一 state 构造的 actions/digests/results。
- **Pass:** action digest、checkpoint revision、terminal result 与 CLI 等价；worker active 时没有 in-flight cancel；events 丢失/重复不改变 controls；close 等 worker 收口后才关闭 resources。

## Acceptance record template

每次 E3 产生一个 repo-relative record，建议路径 `docs/acceptance/records/YYYY-MM-DD-<capability>-<task>.md`，至少包含：

```markdown
# <Capability> Reference Task

- Revision/worktree digest:
- User-approved task:
- Destination/profile identity:
- Data/effect scope:
- Baseline:
- Success criteria:
- Result: pass | fail | inconclusive
- Model/tool/effect counts:
- Checkpoint terminal status:
- Observable delta:
- Limitations and unverified claims:
```

`inconclusive` 不能被改写为 pass；timeout、截断输出、缺失调用计数或无法核对 effect 都是 inconclusive/fail。
