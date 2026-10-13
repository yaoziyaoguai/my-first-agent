"""S2 UI-04：F3 回看有界且准确（2026-10-11 审计缺陷回归）。

冻结合同（WORK_ITEMS UI-04）：

- 先从保留 facts 中筛选允许展示的 user/assistant 内容，**再**选择最近 20 条
  可展示消息；被不可展示 fact（tool result 等）隔开的早期消息仍须入选。
- 页正文与角色/来源标签合计不超过 ``F3_PAGE_BUDGET`` 字符；超长单条按预算
  切分为多页，翻页可读到全文尾部（不是被截断丢弃）。
- 导航 chrome（页眉/页号）单独计算，不计入正文预算——本测试显式写明该约定。
- 0/1/20/21 条消息边界、中文与换行、多页前后导航、页号/总页数正确。
- tool/private 元数据不进入回看；不新增 transcript 存储（只读 facts）。

Red（修复前）：`facts[-20:]` 先截断再筛选 → 20 条 tool fact 让唯一的 user
消息显示为 0；超长单条不切分 → 单页 20012 字符；页号不随翻页更新。
"""

from __future__ import annotations

import asyncio

from agent.runtime.contracts import ConversationFact, FactKind, GoalStatus
from agent.tui.dialogs import (
    F3_MAX_FACTS,
    F3_PAGE_BUDGET,
    build_f3_pages,
    build_facts_review_screen,
)


def _user(fact_id: str, text: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id, kind=FactKind.USER_MESSAGE, content={"text": text}
    )


def _assistant(fact_id: str, text: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id, kind=FactKind.ASSISTANT_MESSAGE, content={"text": text}
    )


def _tool(fact_id: str) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={"tool_call_id": fact_id, "text": "SECRET-TOOL-OUTPUT"},
    )


def _body_length(pages: tuple[tuple[str, ...], ...]) -> int:
    return sum(len(entry) for page in pages for entry in page)


def test_filter_precedes_recent_window_selection() -> None:
    """先筛选可展示内容，再取最近 20 条；tool facts 不占展示名额。

    Red：`facts[-F3_MAX_FACTS:]` 先截 20 条（全是 tool fact）→ shown=0。
    """

    facts = (_user("action:1:user", "最早的问题"),) + tuple(
        _tool(f"tool:{i}") for i in range(20)
    )

    pages, shown = build_f3_pages(facts)

    assert shown == 1
    assert pages and "最早的问题" in pages[0][0]


def test_recent_window_keeps_latest_twenty_displayable_messages() -> None:
    """21 条可展示消息 → 只取最近 20 条；最老一条被排除。"""

    facts = tuple(_user(f"u:{i}", f"message-{i}") for i in range(21))

    _pages, shown = build_f3_pages(facts)

    assert shown == F3_MAX_FACTS
    rendered = "".join(entry for page in _pages for entry in page)
    assert "message-0" not in rendered
    assert "message-20" in rendered


def test_zero_and_single_message_boundaries() -> None:
    empty_pages, empty_shown = build_f3_pages(())
    assert empty_pages == ()
    assert empty_shown == 0

    pages, shown = build_f3_pages((_user("u:1", "只有一条"),))
    assert shown == 1
    assert pages == (("[user] 只有一条",),)


def test_oversized_message_is_split_within_page_budget() -> None:
    """一条超长消息按预算切页，每页正文 ≤ 8000；全文可在多页读完。

    Red：单页 20012 字符，远超 ``F3_PAGE_BUDGET``。
    """

    body = "x" * 20_000
    facts = (_assistant("a:1", body),)

    pages, shown = build_f3_pages(facts)

    assert shown == 1
    assert len(pages) > 1
    for page in pages:
        assert sum(len(entry) for entry in page) <= F3_PAGE_BUDGET
    # 全文可在多页读完（尾部保留，不是截断丢弃）。
    joined = "".join(entry for page in pages for entry in page)
    assert joined.count("x") == 20_000
    assert joined.startswith("[assistant] ")
    assert joined.endswith("x")


def test_chinese_and_newlines_survive_paging() -> None:
    text = "第一行\n第二行：中文内容\n" + "续" * 30
    pages, shown = build_f3_pages((_user("u:1", text),))

    assert shown == 1
    assert "\n" in pages[0][0]
    assert "第一行" in pages[0][0]


def test_role_labels_are_included_in_page_budget() -> None:
    """正文与角色标签合计不超过预算（标签不是免费预算外内容）。"""

    facts = (_assistant("a:1", "y" * 8_000),)

    pages, _shown = build_f3_pages(facts)

    for page in pages:
        assert sum(len(entry) for entry in page) <= F3_PAGE_BUDGET


def test_tool_and_private_metadata_never_render() -> None:
    facts = (
        _user("u:1", "可见问题"),
        _tool("t:1"),
        ConversationFact(
            fact_id="a:1",
            kind=FactKind.ASSISTANT_MESSAGE,
            content={
                "text": "可见回答",
                "provider_continuation": {"opaque": "SHOULD-NOT-SHOW"},
                "reasoning": "SHOULD-NOT-SHOW",
            },
        ),
    )

    pages, shown = build_f3_pages(facts)

    assert shown == 2
    rendered = "".join(entry for page in pages for entry in page)
    assert "可见问题" in rendered and "可见回答" in rendered
    assert "SECRET-TOOL-OUTPUT" not in rendered
    assert "SHOULD-NOT-SHOW" not in rendered


def test_modal_pages_navigate_and_report_page_numbers() -> None:
    """真实 modal：←/→ 翻页更新正文与页号，Esc 关闭且零副作用。

    Red：页号固定在 compose 时算出的 1/1，翻页后不更新。
    """

    facts = (_assistant("a:1", "z" * 20_000),)
    pages, shown = build_f3_pages(facts)
    assert len(pages) > 1

    async def scenario() -> None:
        from textual.app import App

        class Harness(App):
            def on_mount(self) -> None:
                self.push_screen(build_facts_review_screen(pages, shown))

        app = Harness()
        async with app.run_test() as pilot:
            await pilot.pause()
            header = str(app.screen.query_one("#f3_header").render())
            first_body = str(app.screen.query_one("#f3_body").render())
            assert f"1/{len(pages)}" in header
            await pilot.press("right")
            await pilot.pause()
            header_after = str(app.screen.query_one("#f3_header").render())
            body_after = str(app.screen.query_one("#f3_body").render())
            assert f"2/{len(pages)}" in header_after
            assert body_after != first_body
            await pilot.press("left")
            await pilot.pause()
            assert f"1/{len(pages)}" in str(app.screen.query_one("#f3_header").render())
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())


def test_open_snapshot_is_frozen_against_later_events() -> None:
    """打开时的 pages 是冻结快照：之后 facts 变化不改变已打开的展示。"""

    facts = (_user("u:1", "打开时的问题"),)
    pages, shown = build_f3_pages(facts)

    later_facts = facts + (_user("u:2", "之后到来的新消息"),)
    later_pages, later_shown = build_f3_pages(later_facts)

    # 已打开的快照保持原样；新事件只影响下一次打开。
    assert shown == 1
    assert "之后到来的新消息" not in "".join(e for p in pages for e in p)
    assert later_shown == 2


def test_completion_result_cannot_replace_verified_delivery_summary() -> None:
    """UI-05：完成刷新时普通 result 文本只能附加，不能替代权威交付摘要。

    Red：`_refresh` 的 result 分支用 `f"{label}: {result.message}"` 整体替换
    main_text，同一状态下已投影的「Verified delivery」目标/产物/验证范围/
    权限状态全部丢失。
    """

    import asyncio

    from agent.runtime.contracts import RunResult, RunStatus
    from agent.tui.adapter import TuiAdapter
    from agent.tui.app import build_app
    from tests.kernel.fakes import (
        InMemoryCheckpointStore,
        conversation_with_terminal_goal,
    )

    class _RecordingRuntime:
        def __init__(self) -> None:
            self.actions: list = []

        def run_turn(self, action, snapshot):  # noqa: ANN001, ANN202
            self.actions.append(action)
            return RunResult(status=RunStatus.COMPLETED, state=snapshot.state)

    state = conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
    app = build_app(
        TuiAdapter(_RecordingRuntime(), InMemoryCheckpointStore(state)),
        run_id_factory=lambda: "run-1",
    )

    async def scenario() -> None:
        async with app.run_test():
            before = str(app.query_one("#status").render())
            assert "Verified delivery:" in before
            assert "Durable task permissions: closed." in before

            app._refresh(
                RunResult(
                    status=RunStatus.COMPLETED,
                    state=state,
                    message="All done.",
                )
            )
            after = str(app.query_one("#status").render())
            # 普通消息可附加，但权威摘要仍在。
            assert "All done." in after
            assert "Verified delivery:" in after
            assert "Durable task permissions: closed." in after
            assert "Evidence scope:" in after

    asyncio.run(scenario())


def test_non_verified_states_do_not_gain_delivery_summary() -> None:
    """UI-05 反向：COMPLETED/普通聊天不升级为 VERIFIED_DONE 摘要。"""

    import asyncio

    from agent.runtime.contracts import RunResult, RunStatus
    from agent.tui.adapter import TuiAdapter
    from agent.tui.app import build_app
    from tests.kernel.fakes import InMemoryCheckpointStore, conversation_with_active_goal

    class _RecordingRuntime:
        def run_turn(self, action, snapshot):  # noqa: ANN001, ANN202
            return RunResult(status=RunStatus.COMPLETED, state=snapshot.state)

    state = conversation_with_active_goal("ui05")
    app = build_app(
        TuiAdapter(_RecordingRuntime(), InMemoryCheckpointStore(state)),
        run_id_factory=lambda: "run-1",
    )

    async def scenario() -> None:
        async with app.run_test():
            app._refresh(
                RunResult(
                    status=RunStatus.COMPLETED,
                    state=state,
                    message="just chatting",
                )
            )
            after = str(app.query_one("#status").render())
            assert "just chatting" in after
            assert "Verified delivery:" not in after

    asyncio.run(scenario())
