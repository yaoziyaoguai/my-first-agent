# Tool Invoke not_found L3 TDD

Date: 2026-05-24
基于: docs/specs/tool-invoke-not-found-l3/SPEC.md

## T1: core.chat() → TOOL_INVOKE not_found L3

**Given**: dummy tool 注册在 TOOL_REGISTRY（confirmation="never"）
**When**: `core.chat()` with FakeProvider，spy 在 TOOL_GATE 通过后从
        TOOL_REGISTRY 移除工具
**Then**:
- TOOL_GATE 返回 allowed
- TOOL_INVOKE 返回 disposition="not_found"、tool_invoked=False
- evidence_level = `real_core_loop_runtime_e2e`
- dispatcher_origin = "runtime_loop"

## T2: TOOL_RESULT 正确处理 not_found

**Given**: TOOL_INVOKE 返回 not_found
**When**: pipeline 继续到 TOOL_RESULT
**Then**: TOOL_RESULT 仍触发（不因 not_found 而中断 pipeline）

## T3: 不读真实 API / .env

与 `test_tool_invoke_error_l3.py::T3` 同模式。
