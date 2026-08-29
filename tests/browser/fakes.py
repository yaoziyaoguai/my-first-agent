"""018 Task 3 测试专用 fake Playwright 栈（真实 API surface）。

只实现真实 Playwright 1.62 存在的接口（goto/go_back/reload/mouse.wheel/
locator/get_by_role/evaluate/route/on/close 等）；fake 不提供任何
fake-only 方法，adapter 调用不存在的方法会立即 AttributeError。
evaluate 只接受 adapter 的固定 element-refs 脚本（按 marker 识别）。
"""

from __future__ import annotations

import threading

REFS_SCRIPT_MARKER = "__first_agent_collect_element_refs__"


class Journal:
    """调用日志：(target, method, kwargs) 三元组序列。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def record(self, target: str, method: str, **kwargs) -> None:
        self.events.append((target, method, kwargs))

    def calls(self, target: str, method: str) -> list[tuple[str, str, dict]]:
        return [event for event in self.events if event[0] == target and event[1] == method]

    def method_called(self, method: str) -> list[tuple[str, str, dict]]:
        return [event for event in self.events if event[1] == method]


class FakeMouse:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.journal.record("mouse", "wheel", delta_x=delta_x, delta_y=delta_y)


class FakeLocator:
    def __init__(self, page: FakePage, *, role: str | None, name: str | None) -> None:
        self.page = page
        self.role = role
        self.name = name

    def count(self) -> int:
        # 真实 Playwright Locator.count()：当前 DOM 匹配数。
        if self.role is None:
            return len(self.page.nodes)
        return sum(
            1
            for node in self.page.nodes
            if node.get("role") == self.role and node.get("name") == self.name
        )

    def click(self) -> None:
        self.page.journal.record("page", "click", role=self.role, name=self.name)
        self.page._emit_download()
        self.page.navigation_revision += 1

    def fill(self, value: str) -> None:
        self.page.journal.record(
            "page", "fill", role=self.role, name=self.name, value=value
        )

    def select_option(self, value: str) -> None:
        self.page.journal.record(
            "page", "select_option", role=self.role, name=self.name, value=value
        )

    def set_input_files(self, path: str) -> None:
        self.page.journal.record("page", "set_input_files", path=path)


class FakeDownload:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.suggested_filename = page.download_suggested_name

    def save_as(self, path: str) -> None:
        from pathlib import Path

        Path(path).write_bytes(self.page.download_payload)
        self.page.journal.record("download", "save_as", path=path)

    def cancel(self) -> None:
        self.page.journal.record("download", "cancel")


class FakeDownloadInfo:
    def __init__(self, page: FakePage) -> None:
        self.page = page
        self.value = FakeDownload(page)

    def __enter__(self):
        self.page._expected_download = self.value
        return self

    def __exit__(self, *exc_info):
        self.page._expected_download = None
        return False


class FakeFrame:
    def __init__(
        self,
        *,
        parent: FakeFrame | None = None,
        url: str = "about:blank",
        name: str = "",
    ) -> None:
        self.parent_frame = parent
        self.url = url
        self.name = name


class FakeRequest:
    def __init__(
        self,
        url: str,
        *,
        resource_type: str = "document",
        navigation: bool = False,
        redirected_from: FakeRequest | None = None,
        frame: FakeFrame | None = None,
        response_status: int = 200,
        response_headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.resource_type = resource_type
        self._navigation = navigation
        self._redirected_from = redirected_from
        self.frame = frame
        self.response_status = response_status
        self.response_headers = dict(response_headers or {})

    def is_navigation_request(self) -> bool:
        return self._navigation

    # 真实 Playwright API：redirected_from 是 property，不是方法。
    @property
    def redirected_from(self) -> FakeRequest | None:
        return self._redirected_from


class FakeRoute:
    def __init__(self, request: FakeRequest, journal: Journal) -> None:
        self.request = request
        self.journal = journal

    def continue_(self) -> None:
        self.journal.record("route", "continue", url=self.request.url)

    def abort(self) -> None:
        self.journal.record("route", "abort", url=self.request.url)

    def fetch(self, *, max_redirects: int):
        self.journal.record(
            "route",
            "fetch",
            url=self.request.url,
            max_redirects=max_redirects,
        )
        return FakeResponse(
            status=self.request.response_status,
            headers=self.request.response_headers,
        )

    def fulfill(self, *, response) -> None:  # noqa: ANN001
        self.journal.record("route", "fulfill", status=response.status)


class FakeResponse:
    def __init__(self, *, status: int, headers: dict[str, str]) -> None:
        self.status = status
        self.headers = dict(headers)


class FakeWebSocketRoute:
    def __init__(self, url: str, journal: Journal) -> None:
        self.url = url
        self.journal = journal

    def connect_to_server(self):
        self.journal.record("websocket", "connect", url=self.url)
        return self

    def close(self) -> None:
        self.journal.record("websocket", "close", url=self.url)


class FakePage:
    def __init__(
        self,
        context: FakeContext | None,
        journal: Journal,
        *,
        url: str = "https://site.example.test/page",
    ) -> None:
        self.context = context
        self.journal = journal
        self._url = url
        self.navigation_revision = 1
        self.frame_tree_digest = "f" * 64
        self.main_frame = FakeFrame(url=url, name="main")
        self.frames = [self.main_frame]
        self._navigation_callbacks: list = []
        # DOM 真源：adapter 的固定 evaluate 脚本从这里投影 element refs。
        self.nodes: list[dict] = []
        self.closed = False
        self.fail_on_close = False
        self.hang_on_close = False
        self.raise_on_goto: Exception | None = None
        self.redirect_after_goto: str | None = None
        self.goto_responses: dict[str, tuple[int, dict[str, str]]] = {}
        self.fail_on_nth_evaluate: int | None = None
        self.evaluate_error: Exception | None = None
        self._evaluate_calls = 0
        self.hang_on_goto = threading.Event()
        self.hang_on_goto.set()  # 默认不挂起
        self.mouse = FakeMouse(journal)
        self.download_payload = b"download"
        self.download_suggested_name = "download.bin"
        self._expected_download = None
        self._download_callbacks: list = []

    @property
    def url(self) -> str:
        return self._url

    def goto(self, url: str) -> None:
        if self.raise_on_goto is not None:
            raise self.raise_on_goto
        if not self.hang_on_goto.wait(timeout=30):
            return
        # 真实请求流：goto 产生的导航请求经过 context 的 route handler。
        if self.context is not None:
            status, headers = self.goto_responses.get(url, (200, {}))
            self.context.emit_request(
                url,
                navigation=True,
                response_status=status,
                response_headers=headers,
            )
        self.journal.record("page", "goto", url=url)
        # 服务器端重定向：最终 URL 可能与请求不同（canonical 必须取真实值）。
        self._url = self.redirect_after_goto or url
        self.main_frame.url = self._url
        self.navigation_revision += 1
        for callback in self._navigation_callbacks:
            callback(self.main_frame)

    def go_back(self) -> None:
        self.journal.record("page", "go_back")
        self.navigation_revision += 1
        for callback in self._navigation_callbacks:
            callback(self.main_frame)

    def reload(self) -> None:
        self.journal.record("page", "reload")
        self.navigation_revision += 1
        for callback in self._navigation_callbacks:
            callback(self.main_frame)

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.journal.record("page", "wait_for_timeout", milliseconds=milliseconds)

    def locator(self, selector: str) -> FakeLocator:
        self.journal.record("page", "locator", selector=selector)
        return FakeLocator(self, role=None, name=None)

    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = False,
    ) -> FakeLocator:
        self.journal.record(
            "page", "get_by_role", role=role, name=name, exact=exact
        )
        return FakeLocator(self, role=role, name=name)

    def on(self, event: str, callback) -> None:
        self.journal.record("page", "on", event=event)
        if event == "download":
            self._download_callbacks.append(callback)
        elif event == "framenavigated":
            self._navigation_callbacks.append(callback)

    def expect_download(self):
        return FakeDownloadInfo(self)

    def _emit_download(self) -> None:
        if self._expected_download is None:
            return
        for callback in self._download_callbacks:
            callback(self._expected_download)

    def evaluate(self, script: str):
        self.journal.record("page", "evaluate", marker=REFS_SCRIPT_MARKER in script)
        self._evaluate_calls += 1
        if self.fail_on_nth_evaluate == self._evaluate_calls:
            raise self.evaluate_error or RuntimeError("observation failed")
        if REFS_SCRIPT_MARKER not in script:
            raise AssertionError("fake only supports the fixed adapter refs script")
        secret_types = {"password", "secret", "hidden"}
        refs = []
        for node in self.nodes:
            input_type = node.get("input_type")
            is_secret = input_type is not None and input_type in secret_types
            refs.append(
                {
                    "ref": node["ref"],
                    "role": node.get("role"),
                    "name": node.get("name"),
                    "depth": node.get("depth", 0),
                    "input_type": input_type,
                    "form_action": node.get("form_action"),
                    "form_method": node.get("form_method"),
                    "value_empty": (
                        None if is_secret or "value" not in node else node["value"] == ""
                    ),
                }
            )
        return refs

    def close(self) -> None:
        if self.hang_on_close:
            threading.Event().wait(timeout=30)
            return
        if self.fail_on_close:
            raise RuntimeError("page close failed")
        self.closed = True
        self.journal.record("page", "close")


class FakeContext:
    def __init__(self, browser: FakeBrowser, journal: Journal) -> None:
        self.browser = browser
        self.journal = journal
        self.pages: list[FakePage] = []
        self.closed = False
        self.fail_on_close = False
        self.default_timeouts: dict[str, int] = {}
        self._route_handlers: list = []
        self._websocket_handlers: list = []
        self._page_callbacks: list = []

    def set_default_timeout(self, milliseconds: int) -> None:
        self.journal.record("context", "set_default_timeout", milliseconds=milliseconds)
        self.default_timeouts["default"] = milliseconds

    def set_default_navigation_timeout(self, milliseconds: int) -> None:
        self.journal.record(
            "context", "set_default_navigation_timeout", milliseconds=milliseconds
        )
        self.default_timeouts["navigation"] = milliseconds

    def route(self, pattern: str, handler) -> None:
        self.journal.record("context", "route", pattern=pattern)
        self._route_handlers.append(handler)

    def route_web_socket(self, pattern: str, handler) -> None:
        self.journal.record("context", "route_web_socket", pattern=pattern)
        self._websocket_handlers.append(handler)

    def on(self, event: str, callback) -> None:
        self.journal.record("context", "on", event=event)
        if event == "page":
            self._page_callbacks.append(callback)

    def emit_request(self, url: str, **request_kwargs) -> None:
        """模拟一个真实 request 事件到达 route handler。"""
        request = FakeRequest(url, **request_kwargs)
        route = FakeRoute(request, self.journal)
        for handler in self._route_handlers:
            handler(route, request)

    def emit_popup(self, page: FakePage) -> None:
        for callback in self._page_callbacks:
            callback(page)

    def emit_websocket(self, url: str) -> None:
        route = FakeWebSocketRoute(url, self.journal)
        for handler in self._websocket_handlers:
            handler(route)

    def new_page(self) -> FakePage:
        self.journal.record("context", "new_page")
        page = FakePage(self, self.journal)
        self.pages.append(page)
        # 真实时序：context.new_page() 同样触发 on("page") 事件。
        for callback in self._page_callbacks:
            callback(page)
        return page

    def close(self) -> None:
        if self.fail_on_close:
            raise RuntimeError("context close failed")
        self.closed = True
        self.journal.record("context", "close")


class FakeBrowser:
    def __init__(self, journal: Journal) -> None:
        self.journal = journal
        self.contexts: list[FakeContext] = []
        self.closed = False
        self.fail_on_close = False

    def is_closed(self) -> bool:
        return self.closed

    def new_context(self, **kwargs) -> FakeContext:
        self.journal.record("browser", "new_context", **kwargs)
        context = FakeContext(self, self.journal)
        self.contexts.append(context)
        return context

    def launch_persistent_context(self, **kwargs):
        # 真实 Playwright Browser 没有 launch_persistent_context（那是
        # BrowserType 的方法）：保留断言防止 adapter 走错 API surface。
        self.journal.record("browser", "launch_persistent_context", **kwargs)
        raise AssertionError(
            "launch_persistent_context belongs to chromium (BrowserType), not browser"
        )

    def close(self) -> None:
        if self.fail_on_close:
            raise RuntimeError("browser close failed")
        self.closed = True
        self.journal.record("browser", "close")


class FakeChromium:
    def __init__(self, journal: Journal, *, launch_error: Exception | None = None) -> None:
        self.journal = journal
        self.launch_error = launch_error
        self.last_browser: FakeBrowser | None = None
        self.persistent_contexts: list[FakeContext] = []

    def launch(self, **kwargs) -> FakeBrowser:
        self.journal.record("chromium", "launch", **kwargs)
        if self.launch_error is not None:
            raise self.launch_error
        browser = FakeBrowser(self.journal)
        self.last_browser = browser
        return browser

    def launch_persistent_context(self, **kwargs) -> FakeContext:
        # 真实 Playwright API：BrowserType.launch_persistent_context。
        self.journal.record("chromium", "launch_persistent_context", **kwargs)
        context = FakeContext(None, self.journal)
        self.persistent_contexts.append(context)
        return context


class FakePlaywrightHandle:
    def __init__(self, chromium: FakeChromium, journal: Journal) -> None:
        self.chromium = chromium
        self.journal = journal
        self.stopped = False

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True
        self.journal.record("playwright", "stop")

    @property
    def last_context(self) -> FakeContext:
        if self.chromium.persistent_contexts:
            return self.chromium.persistent_contexts[-1]
        browser = self.chromium.last_browser
        assert browser is not None and browser.contexts, "adapter has not opened yet"
        return browser.contexts[-1]

    @property
    def last_page(self) -> FakePage:
        context = self.last_context
        assert context.pages, "adapter has not created a page yet"
        return context.pages[-1]


class _FactoryContext:
    def __init__(self, handle: FakePlaywrightHandle) -> None:
        self._handle = handle

    def __enter__(self) -> FakePlaywrightHandle:
        return self._handle

    def __exit__(self, *exc_info) -> bool:
        # 真实 sync_playwright 的 with 退出会 stop——fake 同样只 stop 一次。
        self._handle.stop()
        return False


def make_fake_factory(
    journal: Journal, *, launch_error: Exception | None = None,
) -> tuple[FakePlaywrightHandle, object]:
    """返回 (handle, factory)：factory() 返回 with 上下文。"""

    handle = FakePlaywrightHandle(
        FakeChromium(journal, launch_error=launch_error), journal
    )

    def factory() -> _FactoryContext:
        journal.record("factory", "start")
        return _FactoryContext(handle)

    return handle, factory


class FakeResolver:
    """deterministic 注入 resolver（url_policy/guard 测试共用）。"""

    def __init__(self, mapping: dict[str, tuple[str, ...]] | None = None) -> None:
        self.mapping = {host: tuple(addrs) for host, addrs in (mapping or {}).items()}

    def resolve(self, host: str) -> tuple[str, ...]:
        return self.mapping.get(host, ())


class FakeTransport:
    """记录真实 network send 的 fake transport。"""

    def __init__(self) -> None:
        self.sends: list[str] = []

    def send(self, url: str) -> None:
        self.sends.append(url)
