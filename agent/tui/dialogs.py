"""S2-B modal 对话框：F3 保留内容回看与 F4 多行编辑。

两个 modal 都是纯展示/编辑层：不提交 typed action、不调用 provider/tool、
不写任何状态；提交仍由 app 层的 displayed-state gate 与既有 SubmitMessage/
control 路径完成。所有正文先 safe_display 再分段，每页正文预算 8000 字符。
"""

from __future__ import annotations

from agent.runtime.contracts import ConversationFact, FactKind
from agent.tui.render import safe_display

# F3 每页正文预算（safe_display 处理后的字符数；页码/标题不计入正文预算）。
F3_PAGE_BUDGET = 8_000
F3_MAX_FACTS = 20

# CONTEXT_SUMMARY 只投影公开摘要字段；不展示 opaque payload / continuation。
_SUMMARY_PUBLIC_KEYS = (
    "objective",
    "constraints",
    "decisions",
    "completed",
    "open_items",
    "key_references",
)


def _displayable_entry(fact: ConversationFact) -> str | None:
    """把一条 fact 投影为可展示文本；不可展示（tool/private）返回 None。"""

    if fact.kind is FactKind.USER_MESSAGE:
        text = fact.content.get("text")
        if isinstance(text, str) and text:
            return f"[user] {text}"
        return None
    if fact.kind is FactKind.ASSISTANT_MESSAGE:
        text = fact.content.get("text")
        if isinstance(text, str) and text:
            return f"[assistant] {text}"
        return None
    if fact.kind is FactKind.CONTEXT_SUMMARY:
        lines = ["[summary — 压缩摘要，非原文]"]
        for key in _SUMMARY_PUBLIC_KEYS:
            value = fact.content.get(key)
            if isinstance(value, str) and value:
                lines.append(f"{key}: {value}")
            elif isinstance(value, (list, tuple)) and value:
                rendered = "; ".join(str(item) for item in value)
                if rendered:
                    lines.append(f"{key}: {rendered}")
        if len(lines) > 1:
            return "\n".join(lines)
    return None


def _split_within_budget(text: str) -> list[str]:
    """把单条 safe_display 文本切成每段 ≤ ``F3_PAGE_BUDGET`` 的连续片段。

    预算按**字符**（与 safe_display 输出一致，非字节）；超长单条不再整条独占
    一页，而是可在多页读完，尾部不丢失。
    """

    if len(text) <= F3_PAGE_BUDGET:
        return [text]
    return [
        text[offset : offset + F3_PAGE_BUDGET]
        for offset in range(0, len(text), F3_PAGE_BUDGET)
    ]


def build_f3_pages(
    facts: tuple[ConversationFact, ...],
) -> tuple[tuple[str, ...], int]:
    """最近 20 条**可展示**消息按原顺序分页；返回 (pages, shown_count)。

    顺序固定（UI-04 冻结合同）：先从保留 facts 中筛选允许展示的
    user/assistant/summary 内容，再取最近 ``F3_MAX_FACTS`` 条——被 tool
    result 等不可展示 fact 隔开的早期消息仍会入选，不可展示 fact 不占名额。
    USER_MESSAGE / ASSISTANT_MESSAGE 仅 content.text；CONTEXT_SUMMARY 仅公开
    摘要字段并明确标注"压缩摘要，非原文"。不展示 provider_continuation、
    opaque payload、reasoning、raw tool results 与 metadata/JSON。

    正文先做 safe_display 转义，再按 ``F3_PAGE_BUDGET`` 分段：页正文（含
    `[user]`/`[assistant]` 角色标签与 summary 来源标签）合计不超过预算；
    超长单条按预算切分为连续片段，翻页可读到全文尾部。页码/页眉等导航
    chrome 单独计算，不计入正文预算。
    """

    displayable = [
        entry
        for entry in (_displayable_entry(fact) for fact in facts)
        if entry is not None
    ][-F3_MAX_FACTS:]
    segments: list[str] = []
    for entry in displayable:
        segments.extend(_split_within_budget(safe_display(entry)))
    pages: list[tuple[str, ...]] = []
    current: list[str] = []
    budget = 0
    for segment in segments:
        if budget + len(segment) > F3_PAGE_BUDGET and current:
            pages.append(tuple(current))
            current = []
            budget = 0
        current.append(segment)
        budget += len(segment)
    if current:
        pages.append(tuple(current))
    return tuple(pages), len(displayable)


def build_facts_review_screen(pages: tuple[tuple[str, ...], ...], shown: int):
    """构造 F3 回看 modal（延迟导入 Textual；未安装时不影响 base import）。"""

    from textual.binding import Binding
    from textual.screen import ModalScreen
    from textual.widgets import Static

    class FactsReviewModal(ModalScreen):
        # F3：Esc 返回原界面；翻页只更新展示，不提交 action、不调用
        # provider/tool、不写状态。
        BINDINGS = [
            Binding("escape", "close", "Back"),
            Binding("right", "next_page", "Next page"),
            Binding("left", "prev_page", "Previous page"),
        ]

        def __init__(self, page_tuple: tuple[tuple[str, ...], ...], shown_count: int) -> None:
            super().__init__()
            self._pages = page_tuple
            self._page_index = 0

        def compose(self):
            from textual.containers import Vertical

            with Vertical():
                yield Static("", id="f3_header")
                yield Static("", id="f3_body")

        def on_mount(self) -> None:
            self._render_page()

        def _render_header(self) -> None:
            # 页号必须随翻页更新：header 在每次 _render_page 时重算，而不是
            # 在 compose 时固定（UI-04：翻页页号不更新的缺陷）。
            header = self.query_one("#f3_header", Static)
            note = (
                f"当前 checkpoint 最近 {F3_MAX_FACTS} 条保留内容；不是完整历史"
                f"（本页 {self._page_index + 1}/{max(1, len(self._pages))}，"
                f"←/→ 翻页，Esc 返回）"
            )
            header.update(safe_display(note))

        def _render_page(self) -> None:
            from rich.text import Text

            self._render_header()
            body = self.query_one("#f3_body", Static)
            if not self._pages:
                body.update(Text(safe_display("当前没有可展示的保留内容。")))
                return
            entries = self._pages[self._page_index]
            body.update(Text("\n\n".join(entries)))

        def action_close(self) -> None:
            self.dismiss(None)

        def action_next_page(self) -> None:
            if self._pages and self._page_index < len(self._pages) - 1:
                self._page_index += 1
                self._render_page()

        def action_prev_page(self) -> None:
            if self._page_index > 0:
                self._page_index -= 1
                self._render_page()

    return FactsReviewModal(pages, shown)


def build_multiline_edit_screen(initial_text: str):
    """构造 F4 多行编辑 modal（延迟导入 Textual；TextArea 为既有可选依赖）。"""

    from textual.binding import Binding
    from textual.screen import ModalScreen
    from textual.widgets import Button, Static, TextArea

    class MultiLineEditModal(ModalScreen):
        # F4：Enter 仅换行；F6/发送按钮只提交一次；Esc 保存为草稿返回。
        # TextArea 原生占用 F6，这里用 priority 绑定确保先于编辑器内部键位。
        # modal 内 slash 文本是普通消息内容，不解析成命令。
        BINDINGS = [
            Binding("escape", "save_draft", "Save draft", priority=True),
            Binding("f6", "send", "Send", priority=True),
        ]

        def __init__(self, initial: str) -> None:
            super().__init__()
            self._initial = initial
            self._submitted = False

        def compose(self):
            from textual.containers import Vertical

            with Vertical():
                yield Static(
                    safe_display(
                        "多行编辑：Enter 换行；F6 或「发送」提交一次；Esc 存草稿返回。"
                        "此处的 /xxx 是普通文本，不作为命令。"
                    ),
                    id="f4_header",
                )
                yield TextArea(self._initial, id="f4_editor")
                yield Button("发送", id="f4_send")

        @property
        def _editor(self):
            return self.query_one("#f4_editor", TextArea)

        def on_button_pressed(self, event) -> None:  # noqa: ANN001
            event.stop()
            self.action_send()

        def action_send(self) -> None:
            if self._submitted:
                return  # 只提交一次
            self._submitted = True
            self.dismiss(("send", self._editor.text))

        def action_save_draft(self) -> None:
            if self._submitted:
                return
            self._submitted = True
            self.dismiss(("draft", self._editor.text))

    return MultiLineEditModal(initial_text)
