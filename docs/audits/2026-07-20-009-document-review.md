---
title: 009 Implementation Plan Document Review
date: 2026-07-20
type: audit
---

# 009 Implementation Plan Document Review

## Scope

本审查覆盖：

- `docs/plans/2026-07-20-009-close-capability-evidence-gaps-plan.md`
- `docs/architecture/CAPABILITY_EVIDENCE_CLOSURE_CONTRACT.md`
- `docs/implementation/009_CODING_AGENT_HANDOFF.md`
- `docs/implementation/009_EXECUTION_LOG.md`
- `docs/implementation/009_INDEPENDENT_REVIEW.md`
- current-status、roadmap 与六项 capability design 的 009 closure gate。

审查目标是判断文档能否指导廉价 Coding Agent 连续实施，同时避免执行器用 test name、source shape、dirty-tree import、安全拒绝或自签 claim 重新制造 false Green。

## Coverage

| Lens | Result |
|---|---|
| coherence | 三轮；标识、顺序、blocked/global seal 与 control ownership 已闭合 |
| feasibility | 两轮；Darwin no-follow admission、`sandbox-exec` deny-network 与 U8A/U8B 可实施，post-seal cycle 已移除 |
| security | 两轮；allowed-path file type/link 与 descendant network boundary 已闭合 |
| product | capability-scoped verdict 不再被 SubAgent limitation 全局阻断 |
| design | TUI keyboard/reopen/lifecycle 范围无新增缺口 |
| scope | 未发现新增 capability、第二套 loop 或 speculative abstraction |
| adversarial | executor self-attestation 被独立 reviewer-owned content rerun 与 promotion receipt 切断 |

Cross-model review 未运行：该路径会把完整文档发送给外部 provider，本轮没有这项内容外发授权。它不是本地多视角审查失败。

## Applied corrections

1. Key flow 使用 `KF1-KF4`，审计 finding 保留 `F1-F9`，避免 execution log 证据挂错对象。
2. U1 只建立 admission/evidence scaffolding；最终 materialized proof 归 U8。
3. SubAgent 只有 positive supported-provider E2 才可能晋级；safe rejection 保持 `implemented-candidate + safe-unavailable + E3-blocked`。
4. Manifest add/modify entry 在读内容前执行 descriptor-relative no-follow、regular-file、link-count 与 Git mode/type admission；symlink、hardlink、特殊文件 fail closed。
5. 当前 Darwin final gate 使用 verifier-owned `/usr/bin/sandbox-exec` deny-network boundary，并用可区分 policy denial 的 DNS/TCP 负向探针验证 descendants。
6. U8 分成 executor-owned U8A 与 independent-reviewer-owned U8B。实现执行器只提交 provisional verdict，不能自签 `locally-verified` 或运行 control seal。
7. Reviewer 在修改 controls 前必须独立重跑 `--content`；不是只阅读 executor 输出。
8. 单项证据不足只阻止该 capability 晋级；admission/private/network/origin/ordinary drift、缺失独立 receipt 或未处置全局 P0/P1 才阻止整个 control seal。
9. Review、execution log、current status 是三个 post-content controls。它们先冻结 digest，再运行 read-only control seal；seal exit 只进入仓库外最终报告，避免 post-seal 自引用修改。
10. `verified` finding 要有 same-oracle Red/Green/boundary；evidence-backed blocked finding 保留准确 Red、具体 blocker、安全最终行为与未晋级 claim，不能把安全拒绝冒充 Green。

## Final judgment

009 文档集已达到 implementation-ready：Coding Agent 可以从 U1 连续做到 U8A；完成报告随后交给不同 agent/session 按独立 review template 执行 U8B。

这不是“六项已完成”的声明。
代码、009 manifest、behavior gates、review receipt、control seal 与全部 E3 仍待执行。

## Residual limits

- Distinct-actor identity 是程序性 attestation，不是密码学身份；文档没有把它误称为不可伪造签名。
- `/usr/bin/sandbox-exec` 是当前 Darwin target 的实施约束；缺失或负向探针无法证明 policy denial 时 E2M fail closed。
- Memory 仍是 owner-only plaintext；MCP executable 仍是 operator-trusted local process；这些不因 009 变成 sandboxed production service。
- SubAgent 如果没有满足 receipt/deadline contract 的 supported provider，U8B 必须继续拒绝其本地晋级和 E3 eligibility。

