"""测试 ActionPlan schema 验证 — validate_action_plan_raw() + SCHEMA_REPAIR_PROMPT。

覆盖：
- 合法 ActionPlan JSON 被接受
- 禁止的旧 schema pattern 被拒绝（steps/tool/step_id/args）
- 缺少关键字段被拒绝
- repair prompt 格式化
"""

from agent.planner import SCHEMA_REPAIR_PROMPT, validate_action_plan_raw

# ═══════════════════════════════════════════════════════════════════════════════
# validate_action_plan_raw() — 合法输入
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateActionPlanRawAccept:
    """合法 ActionPlan schema 应通过验证。"""

    def test_full_valid_action_plan(self):
        """完整合法 JSON → (True, "")。"""
        raw = {
            "steps_estimate": 3,
            "plan_id": "test_001",
            "entry_node_id": "step_1",
            "nodes": [
                {
                    "node_id": "step_1",
                    "action_type": "TOOL_CALL",
                    "target": "web_search",
                    "params": {"query": "test"},
                    "depends_on": [],
                    "recovery": {"on_failure": "halt"},
                    "condition": None,
                    "description": "search step",
                },
                {
                    "node_id": "step_2",
                    "action_type": "MEMORY_RETAIN",
                    "target": "session_key",
                    "params": {"content": "result"},
                    "depends_on": ["step_1"],
                    "recovery": {"on_failure": "skip"},
                    "condition": None,
                    "description": "retain result",
                },
                {
                    "node_id": "step_3",
                    "action_type": "SKILL_SELECT",
                    "target": "code_review",
                    "params": {},
                    "depends_on": ["step_2"],
                    "recovery": {"on_failure": "halt"},
                    "condition": "needs_review",
                    "description": "optional review",
                },
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert is_valid, f"expected valid, got: {reason}"
        assert reason == ""

    def test_minimal_valid(self):
        """最小合法 ActionPlan（单 node，无可选字段）→ 通过。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "minimal",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "action_type": "TOOL_CALL",
                    "target": "read_file",
                    "params": {"path": "/tmp/test"},
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert is_valid, f"expected valid minimal plan, got: {reason}"

    def test_steps_estimate_as_float(self):
        """steps_estimate 为浮点数 3.0 时 >1 → 通过。"""
        raw = {
            "steps_estimate": 3.0,
            "plan_id": "float_test",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "action_type": "TOOL_CALL",
                    "target": "test",
                }
            ],
        }
        is_valid, _ = validate_action_plan_raw(raw)
        assert is_valid


# ═══════════════════════════════════════════════════════════════════════════════
# validate_action_plan_raw() — 拒绝旧 schema
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateActionPlanRawReject:
    """禁止的旧 schema pattern 应被拒绝。"""

    def test_rejects_steps_instead_of_nodes(self):
        """顶层使用 "steps" 而非 "nodes" → 拒绝。"""
        raw = {
            "steps_estimate": 3,
            "plan_id": "old_format",
            "entry_node_id": "step_1",
            "steps": [  # ❌ 旧 key
                {
                    "step_id": "step_1",
                    "tool": "web_search",
                    "args": {"query": "test"},
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert '"steps"' in reason

    def test_rejects_step_id_instead_of_node_id(self):
        """node 中使用 "step_id" 而非 "node_id" → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "step_id_format",
            "entry_node_id": "step_1",
            "nodes": [
                {
                    "step_id": "step_1",  # ❌ 旧 key
                    "action_type": "TOOL_CALL",
                    "target": "test",
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "step_id" in reason
        assert "node_id" in reason

    def test_rejects_tool_instead_of_action_type_target(self):
        """node 中使用 "tool" 而非 "action_type"+"target" → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "tool_format",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool": "web_search",  # ❌ 旧 key
                    "args": {"query": "test"},
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "tool" in reason
        assert "action_type" in reason

    def test_rejects_args_instead_of_params(self):
        """node 中使用 "args" 而非 "params" → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "args_format",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "action_type": "TOOL_CALL",
                    "target": "test",
                    "args": {"query": "test"},  # ❌ 旧 key
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "args" in reason
        assert "params" in reason

    def test_rejects_missing_steps_estimate(self):
        """缺少 steps_estimate → 拒绝。"""
        raw = {
            "plan_id": "no_estimate",
            "entry_node_id": "n1",
            "nodes": [
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "test"}
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "steps_estimate" in reason

    def test_rejects_steps_estimate_equals_zero(self):
        """steps_estimate=0 → 拒绝（多步任务必须 >1）。"""
        raw = {
            "steps_estimate": 0,
            "plan_id": "zero_estimate",
            "entry_node_id": "n1",
            "nodes": [
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "test"}
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "steps_estimate" in reason

    def test_rejects_steps_estimate_equals_one(self):
        """steps_estimate=1 → 拒绝（单步任务不应生成 ActionPlan）。"""
        raw = {
            "steps_estimate": 1,
            "plan_id": "one_estimate",
            "entry_node_id": "n1",
            "nodes": [
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "test"}
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "steps_estimate" in reason

    def test_rejects_missing_entry_node_id(self):
        """缺少 entry_node_id → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "no_entry",
            "nodes": [
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "test"}
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "entry_node_id" in reason

    def test_rejects_missing_nodes_key(self):
        """既无 nodes 也无 steps → 拒绝。"""
        raw = {
            "steps_estimate": 3,
            "plan_id": "no_nodes",
            "entry_node_id": "n1",
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "nodes" in reason

    def test_rejects_node_missing_node_id(self):
        """node 缺少 node_id → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "missing_node_id",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "action_type": "TOOL_CALL",
                    "target": "test",
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "node_id" in reason

    def test_rejects_node_missing_action_type(self):
        """node 缺少 action_type → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "missing_at",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "target": "test",
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "action_type" in reason

    def test_rejects_node_missing_target(self):
        """node 缺少 target → 拒绝。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "missing_target",
            "entry_node_id": "n1",
            "nodes": [
                {
                    "node_id": "n1",
                    "action_type": "TOOL_CALL",
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        assert "target" in reason

    def test_multiple_errors_reported(self):
        """多个 schema 错误应同时报告全部（用分号分隔）。"""
        raw = {
            "steps_estimate": 0,
            "steps": [
                {
                    "step_id": "s1",
                    "tool": "web_search",
                    "args": {"q": "x"},
                }
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert not is_valid
        # 应报告多类问题：steps_estimate/steps vs nodes/step_id vs node_id/tool vs action_type
        error_count = reason.count(";")
        assert error_count >= 2, f"expected multiple errors, got: {reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# validate_action_plan_raw() — 边界条件
# ═══════════════════════════════════════════════════════════════════════════════


class TestValidateActionPlanRawEdgeCases:
    """边界条件测试。"""

    def test_empty_nodes_list_with_steps_estimate_greater_than_1(self):
        """nodes 为空但 steps_estimate>1 和 entry_node_id 存在，不报 node 级错误。"""
        raw = {
            "steps_estimate": 3,
            "plan_id": "empty_nodes",
            "entry_node_id": "n1",
            "nodes": [],
        }
        # 空 nodes 列表不触发 node 级错误（因为列表为空）
        is_valid, reason = validate_action_plan_raw(raw)
        # 没有 node 级错误 + steps_estimate>1 + entry_node_id 存在 → 通过
        assert is_valid, f"empty valid nodes should pass, got: {reason}"

    def test_non_dict_node_skipped(self):
        """非 dict 类型的 node 被跳过（不 crash）。"""
        raw = {
            "steps_estimate": 2,
            "plan_id": "non_dict",
            "entry_node_id": "n1",
            "nodes": [
                "not_a_dict",
                {"node_id": "n1", "action_type": "TOOL_CALL", "target": "test"},
            ],
        }
        is_valid, reason = validate_action_plan_raw(raw)
        assert is_valid, f"non-dict node should be skipped, got: {reason}"


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA_REPAIR_PROMPT 格式化
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaRepairPrompt:
    """SCHEMA_REPAIR_PROMPT 格式化。"""

    def test_wrong_patterns_placeholder_format(self):
        """{wrong_patterns} 占位符正确替换。"""
        errors = '顶层使用了 "steps"（应使用 "nodes"）; node[0] 缺少 "node_id"'
        formatted = SCHEMA_REPAIR_PROMPT.format(wrong_patterns=errors)
        assert "steps" in formatted
        assert "nodes" in formatted
        assert "node_id" in formatted
        assert "action_type" in formatted
        assert "params" in formatted

    def test_repair_prompt_contains_key_corrections(self):
        """repair prompt 包含所有关键纠正指导。"""
        formatted = SCHEMA_REPAIR_PROMPT.format(wrong_patterns="test error")
        assert "nodes" in formatted
        assert "node_id" in formatted
        assert "action_type" in formatted
        assert "target" in formatted
        assert "params" in formatted
        assert "steps_estimate" in formatted
        assert "entry_node_id" in formatted

    def test_repair_prompt_asks_for_json_only(self):
        """repair prompt 末尾要求只输出 JSON。"""
        formatted = SCHEMA_REPAIR_PROMPT.format(wrong_patterns="test")
        assert "只输出 JSON" in formatted
        assert "不要任何解释" in formatted
