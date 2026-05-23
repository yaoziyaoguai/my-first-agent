# SPEC: Evidence Overclaim Prevention — SubAgent Target

Date: 2026-05-24
Status: active
Parent: [First Agent Subsystem Integration Roadmap](../../plans/first-agent-subsystem-integration-roadmap.md)
Contract: [Unified Runtime Flow Contract](../../real-e2e/UNIFIED_RUNTIME_FLOW_CONTRACT.md)

## A. Gap 判断

`test_runtime_action_contract.py` 已为以下 cataloged target 建立了 overclaim 防护：

| ActionType | Target | ForgedTargetLabel | CatalogAllowedForgedCallable |
|---|---|---|---|
| `tool.request` | ToolRegistry | ✅ | ✅ |
| `skill.select` | SkillLoader, SkillRegistry | ✅ | ✅ |
| `checkpoint.safe_summary` | CheckpointSafeSummary | ✅ | ✅ |
| `streaming.provider_call` | StreamingProtocol | ❌ | ✅ |
| **`subagent.delegate_l0`** | **SubAgentExecutor** | **❌** | **❌** |

`subagent.delegate_l0 → SubAgentExecutor` 是唯一一个两种 overclaim 测试都缺失的 cataloged target。

这不是新 capability milestone，不是新 branch point。这是已有 overclaim prevention 基础设施的覆盖补齐。

## B. 当前状态

`evidence.py` 中已有:
- `RuntimeActionTargetCatalog` descriptor: `subagent.delegate_l0` + `SubAgentDelegateL0Handler` → `SubAgentExecutor` + `delegate_once`
- `_subagent_delegate_once_adapter` — catalog-owned invocation adapter
- `is_runtime_e2e_evidence()` 中对 `subagent.delegate_l0` 的特殊规则：`parent_adjudicated is True`

但 `test_runtime_action_contract.py` 中没有:
- `_ForgedTargetLabelHandler("SubAgentExecutor")` 注册到 `SUBAGENT_DELEGATE_L0` 的测试
- `_CatalogAllowedForgedCallableHandler("SubAgentExecutor")` 注册到 `SUBAGENT_DELEGATE_L0` 的测试

## C. 目标

新增 2 个测试到 `test_runtime_action_contract.py`，补齐 SubAgent target 的 overclaim 防护：

1. **T1: ForgedTargetLabel** — handler 将 arbitrary lambda 标为 `SubAgentExecutor`，验证被分类器拒绝
2. **T2: CatalogAllowedForgedCallable** — handler 在 catalog 中但传入 arbitrary lambda（非 catalog adapter），验证被拒绝

## D. 实现策略

零生产代码改动。严格复用现有测试 infrastructure：
- `_ForgedTargetLabelHandler` (line 183)
- `_CatalogAllowedForgedCallableHandler` (line 210)
- `_request()` (line 255)
- `_assert_not_runtime_e2e()` (line 276)

## E. fake/real 边界

- 纯 harness 测试，不涉及 core.chat()
- 不读 .env / 不调真实 API
- HOME 隔离

## F. 复用关系

| 模块 | 改动 |
|------|------|
| `agent/` | 零改动 |
| `tests/runtime_integration/test_runtime_action_contract.py` | 新增 2 个测试函数 |
| 其他测试文件 | 零改动 |

## G. Review Checklist

- [x] 不需要新增 branch point
- [x] 不需要新增 Anchor
- [x] 不需要新增 RuntimeActionType
- [x] 不修改 production 代码
- [x] 不涉及真实 API / .env
- [x] 可以进入 TDD
