# TDD: Evidence Overclaim Prevention — SubAgent Target

Date: 2026-05-24
Status: active
Parent SPEC: [SPEC.md](SPEC.md)

## 测试文件

`tests/runtime_integration/test_runtime_action_contract.py`（追加 2 个测试）

## T1: ForgedTargetLabel — arbitrary callable 标为 SubAgentExecutor 被拒绝

**test name**: `test_forged_target_label_as_subagent_executor_is_not_runtime_e2e`

**purpose**: 验证 handler 将 arbitrary lambda 标为 `SubAgentExecutor` 时，evidence 不被分类为 runtime_e2e。

**setup**:
1. `_ForgedTargetLabelHandler("SubAgentExecutor")` 注册到 `RuntimeActionType.SUBAGENT_DELEGATE_L0`
2. 通过 `dispatcher.route()` 发送 `SUBAGENT_DELEGATE_L0` 请求

**expected**:
- `result.evidence["target_module"] == "SubAgentExecutor"`
- `result.evidence["evidence_level"] != "runtime_e2e"`
- `_assert_not_runtime_e2e(result.evidence)` 通过

**pattern reference**: `test_forged_target_label_as_checkpoint_is_not_runtime_e2e` (line 477)

## T2: CatalogAllowedForgedCallable — catalog 允许但 arbitrary callable 被拒绝

**test name**: `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_subagent_executor`

**purpose**: 验证即使 handler identity 在 catalog 中，传入 arbitrary lambda（非 `_subagent_delegate_once_adapter`）时，evidence 仍被拒绝。

**setup**:
1. `_CatalogAllowedForgedCallableHandler("SubAgentExecutor")` 注册到 `RuntimeActionType.SUBAGENT_DELEGATE_L0`
2. 通过 `dispatcher.route()` 发送请求

**expected**:
- `result.evidence["target_module"] == "SubAgentExecutor"`
- `result.evidence["target_catalog_allowed"] is False`
- `result.evidence["target_identity_valid"] is False`
- `result.evidence["target_module_proof"]["target_identity_valid"] is False`
- `_assert_not_runtime_e2e(result.evidence)` 通过

**pattern reference**: `test_catalog_allowed_handler_cannot_label_arbitrary_callable_as_checkpoint` (line 528)

## T3: regression

已有 `test_runtime_action_contract.py` 全部测试通过。
