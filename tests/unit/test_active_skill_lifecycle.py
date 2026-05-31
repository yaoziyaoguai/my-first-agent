"""Phase 4 unit tests: ActiveSkillLifecycle (L01-L06).

测试 Plan 3 核心——runtime-managed active_skill lifecycle 的状态管理。
"""

from __future__ import annotations

import pytest

from agent.skill_system.lifecycle import (
    ActiveSkill,
    ActiveSkillLifecycle,
    get_default_lifecycle,
    reset_default_lifecycle,
)


class TestActiveSkill:
    """ActiveSkill frozen dataclass 基本行为。"""

    def test_active_skill_is_immutable(self):
        """ActiveSkill 创建后不可修改。"""
        skill = ActiveSkill(
            skill_id="demo-note-maker",
            body="test body",
            allowed_tools=("demo.write_demo_note",),
            activated_at=1234567890.0,
            activated_by="model_selection",
        )
        assert skill.skill_id == "demo-note-maker"
        assert skill.body == "test body"
        assert skill.allowed_tools == ("demo.write_demo_note",)
        with pytest.raises(AttributeError):
            skill.skill_id = "other"  # type: ignore[misc]


class TestActiveSkillLifecycleCore:
    """L01-L03: activate / deactivate / switch 核心语义。"""

    def setup_method(self):
        self.lifecycle = ActiveSkillLifecycle()

    # L01
    def test_activate_creates_active_skill(self):
        """activate() → is_active() == True, get_active() 返回有效 ActiveSkill。"""
        skill = self.lifecycle.activate(
            "demo-note-maker",
            body="body content",
            allowed_tools=("demo.write_demo_note",),
        )
        assert self.lifecycle.is_active()
        active = self.lifecycle.get_active()
        assert active is not None
        assert active.skill_id == "demo-note-maker"
        assert active.body == "body content"
        assert active.allowed_tools == ("demo.write_demo_note",)
        assert skill == active  # activate() 返回值和 get_active() 一致

    # L02
    def test_deactivate_clears_active_skill(self):
        """deactivate() → is_active() == False, get_active() == None。"""
        self.lifecycle.activate("demo-note-maker", body="body")
        assert self.lifecycle.is_active()
        self.lifecycle.deactivate()
        assert not self.lifecycle.is_active()
        assert self.lifecycle.get_active() is None

    # L03
    def test_switch_replaces_active_skill(self):
        """switch() → 新 skill_id / body / allowed_tools。"""
        self.lifecycle.activate(
            "skill-a", body="body-a", allowed_tools=("tool.a",)
        )
        new_skill = self.lifecycle.switch(
            "skill-b", body="body-b", allowed_tools=("tool.b", "tool.c"),
        )
        assert self.lifecycle.is_active()
        active = self.lifecycle.get_active()
        assert active is not None
        assert active.skill_id == "skill-b"
        assert active.body == "body-b"
        assert set(active.allowed_tools) == {"tool.b", "tool.c"}
        assert new_skill == active

    def test_activate_sets_activated_by(self):
        """activated_by 字段正确记录激活来源。"""
        skill = self.lifecycle.activate(
            "demo", body="b", activated_by="keyword_fallback",
        )
        assert skill.activated_by == "keyword_fallback"

    def test_activate_records_timestamp(self):
        """activated_at 时间戳在合理范围内。"""
        import time
        before = time.time()
        skill = self.lifecycle.activate("demo", body="b")
        after = time.time()
        assert before - 1 <= skill.activated_at <= after + 1


class TestActiveSkillLifecycleHelpers:
    """get_active_skill_id / get_allowed_tools 便捷方法。"""

    def setup_method(self):
        self.lifecycle = ActiveSkillLifecycle()

    def test_get_active_skill_id_when_active(self):
        self.lifecycle.activate("demo-note-maker", body="b")
        assert self.lifecycle.get_active_skill_id() == "demo-note-maker"

    def test_get_active_skill_id_when_inactive(self):
        assert self.lifecycle.get_active_skill_id() is None

    def test_get_allowed_tools_when_active(self):
        self.lifecycle.activate(
            "demo", body="b",
            allowed_tools=("demo.write_demo_note", "demo.echo"),
        )
        tools = self.lifecycle.get_allowed_tools()
        assert tools == frozenset({"demo.write_demo_note", "demo.echo"})

    def test_get_allowed_tools_when_inactive(self):
        """无 active_skill 时返回空 frozenset——表示无约束。"""
        tools = self.lifecycle.get_allowed_tools()
        assert tools == frozenset()


class TestDefaultLifecycle:
    """模块级默认 lifecycle 实例。"""

    def teardown_method(self):
        reset_default_lifecycle()

    def test_default_lifecycle_is_singleton(self):
        """get_default_lifecycle() 返回同一实例。"""
        lc1 = get_default_lifecycle()
        lc2 = get_default_lifecycle()
        assert lc1 is lc2

    def test_reset_default_lifecycle_creates_new_instance(self):
        """reset 后获取新实例。"""
        lc1 = get_default_lifecycle()
        lc1.activate("test", body="b")
        reset_default_lifecycle()
        lc2 = get_default_lifecycle()
        assert lc1 is not lc2
        assert not lc2.is_active()

    def test_default_lifecycle_persists_state(self):
        """跨调用 get_default_lifecycle() 保持状态。"""
        lc = get_default_lifecycle()
        lc.activate("demo", body="persist")
        # 再次获取应看到同一状态
        lc2 = get_default_lifecycle()
        assert lc2.is_active()
        assert lc2.get_active_skill_id() == "demo"


class TestActiveSkillLifecycleEdgeCases:
    """边界情况。"""

    def setup_method(self):
        self.lifecycle = ActiveSkillLifecycle()

    def test_deactivate_when_already_inactive(self):
        """连续 deactivate 不抛异常。"""
        self.lifecycle.deactivate()
        self.lifecycle.deactivate()
        assert not self.lifecycle.is_active()

    def test_activate_overwrites_previous(self):
        """activate() 覆盖已有 active_skill。"""
        self.lifecycle.activate("skill-a", body="a")
        self.lifecycle.activate("skill-b", body="b")
        assert self.lifecycle.get_active_skill_id() == "skill-b"

    def test_allowed_tools_defaults_to_empty(self):
        """allowed_tools 默认空 tuple。"""
        skill = self.lifecycle.activate("demo", body="b")
        assert skill.allowed_tools == ()


class TestActiveSkillLifecycleCheckpointSupport:
    """L06: checkpoint save/load 含 active_skill state。"""

    def setup_method(self):
        self.lifecycle = ActiveSkillLifecycle()

    def test_to_dict_when_active(self):
        """active 状态序列化为 dict。"""
        self.lifecycle.activate(
            "demo-note-maker",
            body="body content",
            allowed_tools=("demo.write_demo_note",),
        )
        data = self.lifecycle.to_dict()
        assert data["skill_id"] == "demo-note-maker"
        assert data["body"] == "body content"
        assert data["allowed_tools"] == ["demo.write_demo_note"]
        assert data["activated_by"] == "model_selection"
        assert data["namespace"] == "default"

    def test_to_dict_when_inactive(self):
        """无 active_skill 时返回空 dict。"""
        data = self.lifecycle.to_dict()
        assert data == {}

    def test_to_dict_truncates_long_body(self):
        """body 超过 500 字符时截断。"""
        long_body = "x" * 1000
        self.lifecycle.activate("demo", body=long_body)
        data = self.lifecycle.to_dict()
        assert len(data["body"]) == 500

    def test_restore_from_dict(self):
        """从 checkpoint dict 恢复状态。"""
        data = {
            "skill_id": "restored-skill",
            "body": "restored body",
            "allowed_tools": ["tool.x", "tool.y"],
            "activated_at": 1234567890.0,
            "activated_by": "checkpoint_resume",
        }
        lc = ActiveSkillLifecycle()
        lc.restore_from_dict(data)
        assert lc.is_active()
        active = lc.get_active()
        assert active is not None
        assert active.skill_id == "restored-skill"
        assert active.body == "restored body"
        assert set(active.allowed_tools) == {"tool.x", "tool.y"}
        # checkpoint_resume 标记被覆盖为 restore 时刻的标记
        assert active.activated_by == "checkpoint_resume"

    def test_restore_from_empty_dict(self):
        """空 dict 恢复不改变状态（保持 inactive）。"""
        self.lifecycle.restore_from_dict({})
        assert not self.lifecycle.is_active()

    def test_restore_from_dict_clears_previous(self):
        """restore 替换已有状态。"""
        self.lifecycle.activate("old", body="old")
        self.lifecycle.restore_from_dict({
            "skill_id": "new",
            "body": "new body",
            "allowed_tools": [],
        })
        assert self.lifecycle.get_active_skill_id() == "new"


class TestActiveSkillLifecycleB7Extension:
    """Phase 7 B7 extension points。"""

    def setup_method(self):
        self.lifecycle = ActiveSkillLifecycle()

    def test_namespace_default(self):
        """默认 namespace 为 "default"。"""
        assert self.lifecycle.namespace == "default"

    def test_namespace_custom(self):
        """自定义 namespace 可设置。"""
        lc = ActiveSkillLifecycle(namespace="instance-1")
        assert lc.namespace == "instance-1"

    def test_activate_in_namespace_works_in_phase4(self):
        """Phase 4 中 activate_in_namespace() 接受 namespace 参数但不隔离状态。"""
        self.lifecycle.activate_in_namespace(
            "some-ns", "demo", body="b",
        )
        assert self.lifecycle.is_active()
        assert self.lifecycle.get_active_skill_id() == "demo"
        # namespace 参数被忽略（Phase 7 前不影响状态）
        assert self.lifecycle.namespace == "default"

    def test_activate_in_namespace_with_different_namespaces_shares_state(self):
        """Phase 4 中不同 namespace 共享状态（B7 前行为）。"""
        self.lifecycle.activate_in_namespace("ns-a", "skill-a", body="a")
        self.lifecycle.activate_in_namespace("ns-b", "skill-b", body="b")
        # Phase 4: 第二个调用覆盖第一个（共享状态）
        assert self.lifecycle.get_active_skill_id() == "skill-b"
