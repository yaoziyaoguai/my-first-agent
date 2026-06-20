"""RT-02: CLI command boundary characterization tests.

中文学习边界：这些测试验证 CLI meta-command 快捷路径的**当前行为**和
**架构边界**——不做行为变更测试，只做回归保护和边界分类测试。

关键断言：
- detect 函数是纯函数（无 IO、无副作用）
- CommandIntent/CommandCategory 类型可分类每个命令
- core.chat() 仍是唯一用户入口
- 这些快捷路径被标记为 CLI-ONLY / DEMO-ONLY
"""

from __future__ import annotations

import pytest


class TestCommandCategoryTypedClassification:
    """验证 CommandCategory 和 CommandIntent typed classification 可用。"""

    def test_command_category_constants_defined(self):
        """CommandCategory 定义 READ_ONLY / MUTATING / DELEGATING 三个分类。"""
        from agent.cli_commands import CommandCategory
        assert CommandCategory.READ_ONLY == "read_only"
        assert CommandCategory.MUTATING == "mutating"
        assert CommandCategory.DELEGATING == "delegating"

    def test_command_intent_is_frozen_dataclass(self):
        """CommandIntent 是 frozen dataclass——创建后不可变。"""
        from agent.cli_commands import CommandCategory, CommandIntent
        intent = CommandIntent(
            category=CommandCategory.READ_ONLY,
            label="show memories",
        )
        assert intent.category == "read_only"
        assert intent.label == "show memories"
        # frozen: 不可修改
        with pytest.raises(Exception):  # noqa: B017 frozen
            intent.category = "mutating"  # type: ignore[misc]

    def test_command_intent_classifies_each_command_type(self):
        """每个 CLI 命令都可被 CommandCategory 正确分类。"""
        from agent.cli_commands import CommandCategory, CommandIntent

        intents = {
            "show memories": CommandIntent(CommandCategory.READ_ONLY, "show memories"),
            "forget memory": CommandIntent(CommandCategory.MUTATING, "forget memory"),
            "show subagents": CommandIntent(CommandCategory.READ_ONLY, "show subagents"),
            "delegate to subagent": CommandIntent(CommandCategory.DELEGATING, "delegate"),
            "NL delegation": CommandIntent(CommandCategory.DELEGATING, "NL delegation"),
        }
        for name, intent in intents.items():
            assert intent.category in (
                CommandCategory.READ_ONLY,
                CommandCategory.MUTATING,
                CommandCategory.DELEGATING,
            ), f"{name} should have valid CommandCategory"


class TestDetectFunctionsArePure:
    """验证 detect 函数是纯函数——无 IO、无副作用、不修改 os.environ。"""

    def test_detect_show_memories_is_pure(self):
        """detect_show_memories 不产生副作用。"""
        import os

        from agent.cli_commands import detect_show_memories

        env_before = dict(os.environ)
        result1 = detect_show_memories("show memories")
        result2 = detect_show_memories("hello world")
        env_after = dict(os.environ)

        assert result1 is True
        assert result2 is False
        assert env_before == env_after

    def test_detect_forget_memory_is_pure(self):
        """detect_forget_memory 不产生副作用。"""
        import os

        from agent.cli_commands import detect_forget_memory

        env_before = dict(os.environ)
        result1 = detect_forget_memory("forget something")
        result2 = detect_forget_memory("hello world")
        env_after = dict(os.environ)

        assert result1 == "something"
        assert result2 is None
        assert env_before == env_after

    def test_detect_show_subagents_is_pure(self):
        """detect_show_subagents 不产生副作用。"""
        import os

        from agent.cli_commands import detect_show_subagents

        env_before = dict(os.environ)
        result1 = detect_show_subagents("show subagents")
        result2 = detect_show_subagents("hello world")
        env_after = dict(os.environ)

        assert result1 is True
        assert result2 is False
        assert env_before == env_after

    def test_detect_nl_delegation_is_pure(self):
        """detect_nl_delegation 不产生副作用。"""
        import os

        from agent.cli_commands import detect_nl_delegation

        env_before = dict(os.environ)
        result1 = detect_nl_delegation("帮我统计文件")
        result2 = detect_nl_delegation("hello world")
        env_after = dict(os.environ)

        assert result1 == ("demo-stat", "文件")
        assert result2 is None
        assert env_before == env_after

    def test_cli_commands_module_does_not_import_core(self):
        """cli_commands.py 不应导入 core.py（避免循环依赖）。"""
        # 检查模块的 __dict__ 不包含 core.py 的顶层对象
        import agent.cli_commands as cli_mod

        # cli_commands 不应有 chat, TurnState, core 等来自 core.py 的符号
        assert not hasattr(cli_mod, "chat")
        assert not hasattr(cli_mod, "state")
        # CommandIntent 和 CommandCategory 是本模块定义的，不是从 core 导入的
        assert hasattr(cli_mod, "CommandIntent")
        assert hasattr(cli_mod, "CommandCategory")


class TestCommandShortcutsPreserved:
    """验证 CLI command shortcuts 行为不变（characterization tests）。"""

    def test_show_memories_triggers_on_both_languages(self):
        """show memories 中英文触发词都有效。"""
        from agent.cli_commands import detect_show_memories

        en_triggers = ["show memories", "list memories", "show my memories"]
        cn_triggers = ["显示记忆", "列出记忆", "查看记忆", "我的记忆", "记忆列表"]

        for t in en_triggers + cn_triggers:
            assert detect_show_memories(t), f"Should detect: {t}"

    def test_show_memories_does_not_trigger_on_normal_chat(self):
        """普通聊天不应触发 show memories。"""
        from agent.cli_commands import detect_show_memories

        normal = ["hello", "你好", "今天天气怎么样", "帮我写代码", "what is python"]
        for t in normal:
            assert not detect_show_memories(t), f"Should NOT detect: {t}"

    def test_forget_id_prefix_detection(self):
        """forget id:<id> 正确提取含 id: 前缀的剩余字符串。

        detect_forget_memory 返回完整 remainder（含 id: 前缀）；
        core.py 负责 strip 前缀并分派到 prefix matching 或 keyword matching 路径。
        """
        from agent.cli_commands import detect_forget_memory

        # detect 返回完整 remainder（含 id: 前缀）
        assert detect_forget_memory("forget id:abc123") == "id:abc123"
        assert detect_forget_memory("忘记 id:abc123") == "id:abc123"

    def test_forget_keyword_detection(self):
        """forget <keyword> 正确提取关键词。"""
        from agent.cli_commands import detect_forget_memory

        assert detect_forget_memory("forget python") == "python"
        assert detect_forget_memory("忘记 python") == "python"

    def test_delegate_to_subagent_detection(self):
        """delegate to <name>: <task> 正确解析。"""
        from agent.cli_commands import detect_delegate_to_subagent

        result = detect_delegate_to_subagent("delegate to demo-stat: count files")
        assert result == ("demo-stat", "count files")

    def test_nl_delegation_defaults_to_demo_stat(self):
        """NL delegation 默认委托给 demo-stat。"""
        from agent.cli_commands import detect_nl_delegation

        result = detect_nl_delegation("帮我统计 demo workspace")
        assert result is not None
        assert result[0] == "demo-stat"


class TestCommandShortcutAllowlist:
    """PF-02: command shortcut freeze/allowlist 的 characterization tests。

    新增 shortcut 必须先走 Architecture Decision 并更新 KNOWN_COMMAND_SHORTCUTS，
    否则这些测试会失败。这是工程纪律约束，不是 runtime enforcement。
    """

    def test_allowlist_covers_all_detect_functions(self):
        """KNOWN_COMMAND_SHORTCUTS 必须覆盖 cli_commands.py 中所有 detect_* 函数。"""
        import agent.cli_commands as cli_mod

        known = cli_mod.get_known_command_shortcuts()
        # 反射获取所有 detect_ 前缀的函数
        actual_detect_fns = {
            name for name in dir(cli_mod)
            if name.startswith("detect_") and callable(getattr(cli_mod, name))
        }

        # allowlist 中不应有已删除的函数
        extra_in_allowlist = known - actual_detect_fns
        assert not extra_in_allowlist, (
            f"KNOWN_COMMAND_SHORTCUTS 包含不存在的 detect 函数: {extra_in_allowlist}"
        )

        # 所有 detect 函数都必须在 allowlist 中
        missing_from_allowlist = actual_detect_fns - known
        assert not missing_from_allowlist, (
            f"新增 detect 函数未注册到 KNOWN_COMMAND_SHORTCUTS: {missing_from_allowlist}\n"
            f"新增 command shortcut 必须先走 Architecture Decision。"
        )

    def test_allowlist_size_matches_expected(self):
        """allowlist 大小应与预期一致——防止意外增删。"""
        from agent.cli_commands import get_known_command_shortcuts

        known = get_known_command_shortcuts()
        # 当前恰好 5 个 detect 函数
        assert len(known) == 5, (
            f"Expected 5 known shortcuts, got {len(known)}: {sorted(known)}"
        )

    def test_each_allowlist_entry_is_detect_function(self):
        """allowlist 中每项都应对应一个可调用的 detect_* 函数。"""
        import agent.cli_commands as cli_mod

        known = cli_mod.get_known_command_shortcuts()
        for name in known:
            fn = getattr(cli_mod, name, None)
            assert fn is not None, f"{name} not found in cli_commands"
            assert callable(fn), f"{name} is not callable"

    def test_allowlist_prevents_accidental_new_shortcuts(self):
        """如果有人新增 detect_* 函数但不更新 allowlist，此测试失败。

        这是 freeze boundary 的核心防护：新增 shortcut 必须显式更新 allowlist，
        从而在 code review 阶段被拦截。
        """
        import agent.cli_commands as cli_mod

        known = cli_mod.get_known_command_shortcuts()
        all_names = set(dir(cli_mod))
        detect_fns = {
            n for n in all_names if n.startswith("detect_") and callable(getattr(cli_mod, n))
        }

        unregistered = detect_fns - known
        assert not unregistered, (
            f"UNREGISTERED COMMAND SHORTCUT DETECTED: {unregistered}\n"
            f"新增 command shortcut 必须先走 Architecture Decision，\n"
            f"然后在 agent/cli_commands.py 的 KNOWN_COMMAND_SHORTCUTS 中注册。\n"
            f"这防止 command shortcuts 在无审查的情况下膨胀为第二 capability runtime。"
        )
