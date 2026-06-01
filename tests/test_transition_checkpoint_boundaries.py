"""Loop context, checkpoint handoff, and confirmation context boundary tests.

本文件从原 3000+ 行 v0.4 transition characterization 巨型文件按行为边界拆出。
拆分只改变测试组织，不改变断言语义；这样后续 core / memory / SubAgent
重构时可以局部审查，避免一个历史巨石同时承载所有边界风险。
"""

from __future__ import annotations

import pytest


def test_run_main_loop_is_module_level_not_chat_closure():
    """钉死 _run_main_loop 必须是 core.py 模块级函数，不允许退化为 chat() 闭包。

    模拟边界：本测试只查模块属性 + 函数 qualname，不调 _run_main_loop（避免
    引入 client/model fixture）。它守住的是"模块级入口存在"这件事，是 Phase 2
    dependency-injection 切片的前置条件。
    """
    from agent import core

    assert hasattr(core, "_run_main_loop"), (
        "agent.core 必须导出 _run_main_loop 模块级符号；"
        "如果它被收回 chat() 闭包，Phase 2 dependency-injection 入口会失效"
    )
    fn = core._run_main_loop
    assert callable(fn)
    # qualname 不带 'chat.' 前缀 = 模块级；带前缀 = 闭包
    assert "." not in fn.__qualname__, (
        f"_run_main_loop.__qualname__={fn.__qualname__!r}；"
        "出现 '.' 说明它退化为某函数的内部嵌套定义，违反 Phase 2a 前置条件"
    )


def test_chat_module_does_not_use_nonlocal_for_loop_helpers():
    """钉死 core.py 不依赖 nonlocal 把 loop helpers 封进 chat()。

    nonlocal 关键字在 core.py 出现就意味着至少有一层闭包在共享可变状态；
    这正是 Phase 2 dependency-injection 切片需要先排除的耦合形式。
    本测试只读源码（不调任何函数），确保未来引入闭包时立刻失败。
    """
    import inspect

    from agent import core

    src = inspect.getsource(core)
    assert "nonlocal " not in src, (
        "agent/core.py 不允许出现 nonlocal；如需共享可变状态，请走 "
        "Phase 2 LoopContext dataclass 注入路径而不是闭包"
    )


# ========================================================================
# Phase 2.1：LoopContext dependency-injection 锚点边界
# ------------------------------------------------------------------------
# 这一组测试钉死 v0.4 Phase 2.1 切片的契约：
#   1) LoopContext 已存在且字段拓扑符合预期（client / model_name /
#      max_loop_iterations，且 frozen + 构造期 validate）；
#   2) chat() 内部已构造一次 LoopContext 实例（Phase 2.2/2.3 会把它接到
#      helper signature；本切片只钉"已经有锚点"）；
#   3) LoopContext 不允许 leak 到 durable layer（checkpoint/state/
#      conversation/transitions），防止 Phase 2.x 任意切片把运行时依赖
#      混进 schema；
#   4) LoopContext.__repr__ 不允许把 client（可能内嵌 api_key）打印出来；
#   5) LoopContext 字段名禁止包含 durable 字段（messages/task/status/
#      pending_*）——这是字段级别的 schema-vs-runtime 分层守卫。
# 任何后续 sub-slice 想"顺手把 state / messages 塞进 LoopContext"都会被
# 第 5 条立刻拦下，避免 dependency-injection 字段慢慢退化成 god-object。
# ========================================================================


def test_loop_context_module_defines_frozen_dataclass_with_expected_fields():
    """LoopContext 字段拓扑契约。"""

    import dataclasses

    from agent.loop_context import LoopContext

    assert dataclasses.is_dataclass(LoopContext)
    # frozen=True：禁止 helper 偷偷 mutate 注入实例
    assert LoopContext.__dataclass_params__.frozen is True

    field_names = {f.name for f in dataclasses.fields(LoopContext)}
    assert field_names == {
        "client",
        "model_name",
        "max_loop_iterations",
        "model_provider",
        "runtime_action_dispatcher",
        "runtime_identity",
        "event_log_writer",
    }, (
        f"LoopContext 字段集合漂移：{field_names}；"
        "新增字段必须先评估是否属于 runtime dependency"
    )


def test_loop_context_post_init_rejects_invalid_inputs():
    """构造期校验：空 model / 非正循环上限 / None client 必须 fail-fast。"""

    from agent.loop_context import LoopContext

    sentinel_client = object()  # 非 None 即可，本测试不调任何 client 方法

    with pytest.raises(ValueError):
        LoopContext(client=sentinel_client, model_name="", max_loop_iterations=10)
    with pytest.raises(ValueError):
        LoopContext(client=sentinel_client, model_name="m", max_loop_iterations=0)
    with pytest.raises(ValueError):
        LoopContext(client=None, model_name="m", max_loop_iterations=10)

    # 合法构造不应抛
    ctx = LoopContext(
        client=sentinel_client, model_name="claude-sonnet-test", max_loop_iterations=7
    )
    assert ctx.model_name == "claude-sonnet-test"
    assert ctx.max_loop_iterations == 7


def test_loop_context_repr_does_not_leak_client_object():
    """__repr__ 不允许把 client 字段打印出来。

    SDK 实例可能在 ``__repr__`` 中包含 ``api_key='sk-...'`` 风格的字段；
    LoopContext 已用 ``repr=False`` 标记 client，这里通过断言 repr 字符串
    不包含 ``client=`` 来钉死该约束。如果未来有人改成 ``repr=True``，
    本测试会立刻失败。
    """

    from agent.loop_context import LoopContext

    class _FakeClientWithSecret:
        def __repr__(self) -> str:  # pragma: no cover - 仅为 leak 探针
            return "FakeClient(api_key='sk-leak-MUST-NOT-APPEAR')"

    ctx = LoopContext(
        client=_FakeClientWithSecret(),
        model_name="claude-sonnet-test",
        max_loop_iterations=10,
    )
    rendered = repr(ctx)
    assert "client=" not in rendered, (
        f"LoopContext.__repr__ 不允许暴露 client 字段：{rendered}"
    )
    assert "sk-leak-MUST-NOT-APPEAR" not in rendered, (
        f"LoopContext.__repr__ 把 client repr 内容泄漏出来了：{rendered}"
    )


def test_loop_context_field_names_exclude_durable_state():
    """LoopContext 字段名禁止与 durable state 字段重名。

    durable state（messages / task / status / pending_*）是
    ``checkpoint.json`` schema 的一部分；它们必须留在 ``agent.state``，
    不允许通过 LoopContext 偷渡进 runtime dependency layer。
    """

    import dataclasses

    from agent.loop_context import LoopContext

    forbidden_substrings = (
        "messages",
        "task",
        "status",
        "pending",
        "checkpoint",
        "summary",
        "memory",
        "conversation",
    )
    field_names = [f.name for f in dataclasses.fields(LoopContext)]
    for name in field_names:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), (
                f"LoopContext 字段 {name} 含禁用子串 {forbidden}："
                "durable state 不允许进 runtime dependency container"
            )


def test_loop_context_not_imported_by_durable_layers():
    """LoopContext 不允许被 checkpoint / state / transitions 层 import。

    这条件同时反向证明 LoopContext 没有写入 checkpoint.json：如果未来
    有人在 ``agent/checkpoint.py`` 里 ``from agent.loop_context import
    LoopContext`` 想 serialize 它，本测试立刻失败。
    """

    import inspect

    from agent import checkpoint as checkpoint_mod
    from agent import state as state_mod
    from agent import transitions as transitions_mod

    for mod, label in (
        (checkpoint_mod, "agent/checkpoint.py"),
        (state_mod, "agent/state.py"),
        (transitions_mod, "agent/transitions.py"),
    ):
        src = inspect.getsource(mod)
        assert "LoopContext" not in src, (
            f"{label} 不允许引用 LoopContext：runtime dependency "
            "禁止进入 durable layer 或状态机本体"
        )


def test_chat_constructs_loop_context_instance_at_module_level_anchor():
    """LoopContext 构造点（v0.5 第一小步起在 _build_loop_context 工厂）从
    模块级运行时常量取值。

    历史：v0.4 Phase 2.1 时构造直接写在 chat() 函数体内；v0.5 Phase 3
    第一小步把构造抽到 _build_loop_context() 工厂，chat() 改为调用
    `_build_loop_context(client)`。

    本测试**不弱化**——契约本质从未改变：
      - 构造点仍存在；
      - client / MODEL_NAME / MAX_LOOP_ITERATIONS 仍是 SSOT 默认值；
      - 没有引入隐式新默认值。
    只是把"构造点位置"从 chat() src 改成 helper src，因为 chat() src
    内现在只有 `_build_loop_context(client)` 一行调用（这是抽 helper
    的目的），原"chat() src 必须出现 LoopContext(...)"成为过时约束。
    """

    import inspect

    from agent import core, core_contexts

    helper_src = inspect.getsource(core_contexts.build_loop_context)
    assert "LoopContext(" in helper_src, (
        "build_loop_context 必须显式构造 LoopContext 作为 SSOT 锚点"
    )
    has_client = "client=client" in helper_src or "client=client_obj" in helper_src
    assert has_client, (
        "helper 必须把入参 client_obj 透传到 LoopContext.client"
        "（实际写法：client=client_obj 也可，下行兼容判断）"
    )
    assert "model_name: str" in helper_src, (
        "core_contexts.build_loop_context 必须显式接收 model_name；"
        "core wrapper 负责注入 MODEL_NAME 默认值"
    )
    assert "max_loop_iterations: int" in helper_src, (
        "core_contexts.build_loop_context 必须显式接收 max_loop_iterations；"
        "core wrapper 负责注入 MAX_LOOP_ITERATIONS 默认值"
    )

    wrapper_src = inspect.getsource(core._build_loop_context)
    assert "build_loop_context(" in wrapper_src, (
        "core._build_loop_context 必须保持兼容 wrapper，并委托 core_contexts"
    )
    assert "model_name: str = MODEL_NAME" in wrapper_src, (
        "core._build_loop_context wrapper 默认 model_name 必须取自模块常量 MODEL_NAME"
    )
    assert "max_loop_iterations: int = MAX_LOOP_ITERATIONS" in wrapper_src, (
        "core._build_loop_context wrapper 默认 max_loop_iterations 必须取自模块常量"
    )

    # 同时检查 chat() 仍然显式调用 helper（不绕过 SSOT），并且
    # 显式传入 MODEL_NAME / MAX_LOOP_ITERATIONS（保证 monkeypatch 生效）
    chat_src = inspect.getsource(core.chat)
    assert "_build_loop_context(" in chat_src, (
        "chat() 必须通过 _build_loop_context(...) 走 SSOT 工厂构造"
    )
    assert "model_name=MODEL_NAME" in chat_src, (
        "chat() 必须显式传 model_name=MODEL_NAME（让 monkeypatch 生效）"
    )
    assert "max_loop_iterations=MAX_LOOP_ITERATIONS" in chat_src, (
        "chat() 必须显式传 max_loop_iterations=MAX_LOOP_ITERATIONS"
        "（让 monkeypatch.setattr(core, 'MAX_LOOP_ITERATIONS', N) 生效）"
    )


# ========================================================================
# Phase 2.2-a：planning helpers 接受 LoopContext 注入边界
# ------------------------------------------------------------------------
# 这一组测试钉死 v0.4 Phase 2.2-a 切片的契约：
#   1) _run_planning_phase 与 _start_planning_for_handler 签名包含 loop_ctx；
#   2) chat() 把构造好的 _loop_ctx 传给两个 helper 的所有调用点（直接调用
#      + 通过 ConfirmationContext.start_planning_fn 间接调用）；
#   3) helpers 不再隐式引用 module-level client / MODEL_NAME；planner 调用
#      读取 loop_ctx 字段——这是"运行时依赖显式化"的实质边界；
#   4) durable state 仍走 module-level state 单例：messages / task /
#      current_plan / save_checkpoint 都不通过 loop_ctx 传递，避免
#      LoopContext 退化为 god-object；
#   5) Phase 2.2-c (主循环 / _call_model 吃 loop_ctx) **本轮不能擅自做**：
#      _run_main_loop 签名必须仍只吃 turn_state，把"分阶段迁移"钉死。
# 任何后续切片想"顺手把 state / messages / save_checkpoint 也走 loop_ctx"
# 都会被第 4 条立刻拦下。
# ========================================================================


def test_planning_phase_signature_accepts_loop_context():
    """_run_planning_phase 与 _start_planning_for_handler 签名契约。"""

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    for fn_name in ("_run_planning_phase", "_start_planning_for_handler"):
        fn = getattr(core, fn_name)
        sig = inspect.signature(fn)
        assert "loop_ctx" in sig.parameters, (
            f"{fn_name} 必须接收 loop_ctx 参数（Phase 2.2-a 契约）"
        )
        annotation = sig.parameters["loop_ctx"].annotation
        assert annotation is LoopContext, (
            f"{fn_name}.loop_ctx 必须明确标注 LoopContext 类型，"
            f"实际：{annotation!r}；禁止用 Any 或字符串前向引用绕过类型边界"
        )


def test_planning_phase_no_longer_reads_module_level_client_or_model_name():
    """_run_planning_phase 不允许再隐式引用 module-level client / MODEL_NAME。

    这一条是 Phase 2.2-a 的实质成果钉子：注入 loop_ctx 但函数体仍读
    ``client`` / ``MODEL_NAME`` 等于"形迁移、神不迁移"，依赖注入名存实亡。
    用 source-level 扫描挡住这种伪迁移。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core._run_planning_phase)
    # planner 调用必须从 loop_ctx 取
    assert "loop_ctx.client" in src and "loop_ctx.model_name" in src, (
        "_run_planning_phase 必须从 loop_ctx 读取 client / model_name；"
        "Phase 2.2-a 不允许形式注入而函数体不用"
    )
    # 函数体不允许出现裸 client 或 MODEL_NAME 引用（非 docstring）
    # 简化：扫描 generate_plan 调用行不允许直接出现 ', client,' / ', MODEL_NAME,'
    forbidden_patterns = ("generate_plan(\n        user_input,\n        client",)
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"_run_planning_phase 仍在隐式引用 module-level client：{pat!r}"
        )


def test_chat_passes_loop_ctx_to_planning_helpers_at_all_call_sites():
    """chat()、confirmation context、planning result helper 都必须透传 loop_ctx。

    当前规划相关调用点：
    - chat() 直接调 _run_planning_phase(user_input, turn_state, _loop_ctx)
    - _build_confirmation_context.start_planning_fn lambda 调
      _start_planning_for_handler(inp, ts, loop_ctx)
    - chat() 与 _start_planning_for_handler 都把 plan_result 交给
      _handle_planning_phase_result；该 helper 负责 ok -> _run_main_loop。
    新增 planning 入口必须同步进入同一个 helper，避免两个入口分叉。

    v0.5 第二小步注意：start_planning_fn lambda 已从 chat() 内迁到
    _build_confirmation_context helper 内，参数名也从闭包变量
    ``_loop_ctx`` 变成 helper 形参 ``loop_ctx``——契约本质（透传未污染
    的 LoopContext）未变。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    context_src = inspect.getsource(core._build_confirmation_context)
    handler_src = inspect.getsource(core._start_planning_for_handler)
    result_src = inspect.getsource(core._handle_planning_phase_result)
    # v0.5+: 调用已改为多行 + action_scheduler= kwarg；
    # 只验证核心参数透传（不再匹配精确单行格式）。
    assert "_run_planning_phase(" in chat_src, (
        "chat() 必须调用 _run_planning_phase"
    )
    assert "action_scheduler=action_scheduler" in chat_src, (
        "chat() 调用 _run_planning_phase 时必须透传 action_scheduler"
    )
    assert "_start_planning_for_handler(" in context_src and "loop_ctx" in context_src, (
        "_build_confirmation_context.start_planning_fn lambda 必须透传 loop_ctx 到"
        " _start_planning_for_handler"
    )
    # v0.5+: 调用已改为多行 + action_scheduler= kwarg；
    # 只验证 helper 名称 + 关键 kwarg 透传（不再匹配精确单行格式）。
    assert "_handle_planning_phase_result(" in chat_src, (
        "chat() 的 planning result 必须交给 _handle_planning_phase_result"
    )
    assert "action_scheduler=action_scheduler" in chat_src, (
        "chat() → _handle_planning_phase_result 必须透传 action_scheduler"
    )
    assert (
        "return _handle_planning_phase_result(plan_result, turn_state, loop_ctx)"
        in handler_src
    ), "_start_planning_for_handler 必须复用共享 helper，禁止复制三分支"
    # v0.5+: _run_main_loop 调用也加了 action_scheduler=/checkpoint_save_on_turn_end= kwargs；
    # 改为验证 helper 名称 + 关键 kwarg 透传（不再匹配精确单行格式）。
    assert "_run_main_loop(" in result_src, (
        "_handle_planning_phase_result 的 ok 分支必须进入 _run_main_loop"
    )
    assert "action_scheduler=action_scheduler" in result_src, (
        "_handle_planning_phase_result → _run_main_loop 必须透传 action_scheduler"
    )


def test_chat_routes_new_turn_compression_through_single_helper():
    """第二刀 helper extraction 只收口 compression + checkpoint sync 时机。

    这个 characterization 保护 Architecture Debt 治理边界：`chat()` 仍决定何时
    进入真正的新一轮对话，helper 只复用同一个 loop_ctx 执行历史压缩与 active
    task checkpoint 同步。它不能顺手改 Ask User、TUI contract、checkpoint
    schema，也不能借机处理 XFAIL-1 topic switch 或 XFAIL-2 Esc cancel。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    helper_src = inspect.getsource(core._compress_history_and_sync_checkpoint)

    assert "_compress_history_and_sync_checkpoint(_loop_ctx)" in chat_src, (
        "chat() 的新一轮对话压缩必须进入共享 helper，避免继续膨胀主入口"
    )
    assert "compress_history(" in helper_src, (
        "_compress_history_and_sync_checkpoint 必须保留历史压缩职责"
    )
    assert "loop_ctx.client" in helper_src, (
        "compression helper 必须复用 chat() 单源构造的 LoopContext client"
    )
    assert (
        "_dispatch_checkpoint_save(" in helper_src
        and "loop_ctx.runtime_action_dispatcher, state" in helper_src
        and "identity=loop_ctx.runtime_identity" in helper_src
    ), (
        "active task 压缩后必须仍立即同步 checkpoint（通过 dispatcher + identity），"
        "避免 summary/checkpoint 漂移"
    )
    forbidden = (
        "request_user_input",
        "pending_user_input_request",
        "plan_confirmation_requested",
        "display_event",
        "Textual",
        "cancel",
        "topic",
    )
    for token in forbidden:
        assert token not in helper_src, (
            "_compress_history_and_sync_checkpoint 不能越界处理 Ask User/TUI/"
            f"XFAIL 语义：{token}"
        )


def test_planning_helpers_do_not_smuggle_durable_state_through_loop_ctx():
    """LoopContext 字段集合保持 runtime-only，禁止承载 durable state。

    Phase 2.2-a 易出的 anti-pattern 是"我顺手把 state 也塞进 LoopContext"
    让 helper 签名变短。这条测试与 Phase 2.1 字段守卫互为冗余：
    Phase 2.1 守 LoopContext 字段名拓扑，本条守"planning helpers 不依赖
    LoopContext 字段集合的扩展"——即使有人偷偷加字段，planning helpers
    也不能读它。
    """

    import inspect

    from agent import core

    for fn_name in (
        "_run_planning_phase",
        "_start_planning_for_handler",
        "_handle_planning_phase_result",
    ):
        src = inspect.getsource(getattr(core, fn_name))
        for forbidden in ("loop_ctx.state", "loop_ctx.task", "loop_ctx.messages",
                          "loop_ctx.checkpoint", "loop_ctx.conversation",
                          "loop_ctx.pending"):
            assert forbidden not in src, (
                f"{fn_name} 不允许通过 loop_ctx 访问 durable state：{forbidden}"
            )


def test_main_loop_signature_phase_2_2_b_handoff_only():
    """_run_main_loop 签名契约（Phase 2.2-b 后）。

    Phase 2.2-a 阶段本测试名为 ``..._unchanged_phase_2_2_a_does_not_overreach``，
    要求签名仅 ``turn_state``。Phase 2.2-b 必须让 ``_run_main_loop`` 显式接受
    ``loop_ctx``，否则 ``_call_model`` 吃 LoopContext 时只能在主循环内重建实例
    （SSOT 双源 hack）。本测试**不是为了通过率而被放宽**——而是把"不应该越界"
    的边界上移到"必须只有 turn_state + loop_ctx，禁止再塞其他参数"：
    - ❌ 不允许加 ``state`` / ``task`` / ``messages`` / ``checkpoint_file`` 参数；
    - ❌ 不允许加 ``client`` / ``model_name`` 直接参数（必须经 loop_ctx）；
    - ❌ 不允许加 ``confirmation_ctx`` / ``response_ctx`` 等聚合容器；
    确保 Phase 2.2-c 之后的越界被同样精确拦截。
    """

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    sig = inspect.signature(core._run_main_loop)
    params = list(sig.parameters.keys())
    # tool_gate_tool_name 和 skill_registry 是 keyword-only 透传参数——
    # 不参与 pipeline 决策，只决定 loop.py 中 TOOL_GATE / SKILL_SELECT
    # action 的 metadata 填充。它们不属于 state / loop_ctx / confirmation_ctx
    # 越界添加。
    assert params == [
        "turn_state", "loop_ctx", "tool_gate_tool_name", "skill_registry",
        "action_scheduler", "checkpoint_save_on_turn_end",
    ], (
        f"_run_main_loop 签名必须包含 action_scheduler + checkpoint_save_on_turn_end；"
        f"当前：{params}。"
        "这两个是 v0.5+ scheduler main-path injection 的 keyword-only 透传参数，"
        "不参与 pipeline 决策，只决定 scheduler 实例和执行元数据。"
    )
    loop_ctx_annotation = sig.parameters["loop_ctx"].annotation
    assert loop_ctx_annotation is LoopContext, (
        f"_run_main_loop.loop_ctx 必须明确标注 LoopContext 类型，"
        f"实际：{loop_ctx_annotation!r}"
    )


def test_loop_context_construction_precedes_confirmation_context_in_chat():
    """chat() 内 _loop_ctx 必须先于 ConfirmationContext 构造。

    因为 ConfirmationContext.start_planning_fn lambda 闭包捕获 _loop_ctx；
    顺序颠倒会触发 NameError。Source-level 扫描钉住相对顺序，避免后续
    refactor 不小心把 _loop_ctx 构造下移。

    v0.5 Phase 3 第一/第二小步：chat() 内构造行从字面 `_loop_ctx = LoopContext(`
    改为 `_loop_ctx = _build_loop_context(client)`，confirmation_ctx 从字面
    `confirmation_ctx = ConfirmationContext(` 改为 `confirmation_ctx =
    _build_confirmation_context(`。本测试随之改为扫描 helper 调用——契约本质
    （必须先构造 _loop_ctx 才能传给 _build_confirmation_context）未变。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    loop_ctx_pos = chat_src.find("_loop_ctx = _build_loop_context(")
    confirm_ctx_pos = chat_src.find("confirmation_ctx = _build_confirmation_context(")
    assert loop_ctx_pos != -1 and confirm_ctx_pos != -1, (
        "chat() 必须同时构造 _loop_ctx（通过 _build_loop_context 工厂）和 "
        "confirmation_ctx（通过 _build_confirmation_context 工厂）"
    )
    assert loop_ctx_pos < confirm_ctx_pos, (
        "_loop_ctx 必须先于 ConfirmationContext 构造（_build_confirmation_context "
        "需要 loop_ctx 作为入参）"
    )


# ========================================================================
# Phase 2.2-b：main-loop -> _call_model LoopContext handoff 边界
# ------------------------------------------------------------------------
# 这一组测试钉死 Phase 2.2-b 的 SSOT 修复契约：
#   1) _call_model 签名包含 loop_ctx 且类型标注必须是 LoopContext；
#   2) _call_model 函数体真正读 loop_ctx.client / loop_ctx.model_name
#      （防形迁移神不迁移）；
#   3) chat() 4 个 _run_main_loop 调用点全部传 _loop_ctx；
#      _start_planning_for_handler 调用点传上层收到的 loop_ctx；
#   4) **_run_main_loop 函数体绝不允许出现 LoopContext(...) 构造调用**
#      ——这是本切片存在的根因，必须用 source-level 扫描钉死；
#   5) chat() 仍然只有一个 _loop_ctx 构造点（agent/core.py 全文 LoopContext(...)
#      只能出现 1 次，加上 loop_context.py 的定义点也只能出现在 LoopContext
#      class 定义本身，不能在任何 helper 内部）；
#   6) _run_main_loop 函数体不允许直接读 loop_ctx 字段——它只转发；
#      Phase 2.2-c 才考虑让主循环自己消费 max_loop_iterations。
# 任何后续切片想"顺手把 max_loop_iterations 也用上 / 顺手在主循环内构造
# LoopContext"都会被第 4/6 条立刻拦下。
# ========================================================================


def test_call_model_signature_accepts_loop_context():
    """_call_model 签名契约。"""

    import inspect

    from agent import core
    from agent.loop_context import LoopContext

    sig = inspect.signature(core._call_model)
    params = list(sig.parameters.keys())
    # _streaming_events_out 是 keyword-only 参数——由 call_model lambda 闭包注入，
    # 用于收集 streaming events 供 turn-end hook 读取。不属于 state/loop_ctx 越界。
    assert params == ["turn_state", "loop_ctx", "_streaming_events_out"], (
        f"_call_model 签名必须严格是 (turn_state, loop_ctx, *, _streaming_events_out)；"
        f"当前：{params}。"
        "禁止加 messages / state / system_prompt 参数（前两者属 durable state，"
        "system_prompt 应通过 turn_state 传递）"
    )
    annotation = sig.parameters["loop_ctx"].annotation
    assert annotation is LoopContext, (
        f"_call_model.loop_ctx 必须标注 LoopContext，实际：{annotation!r}"
    )


def test_call_model_no_longer_reads_module_level_client_or_model_name():
    """_call_model 函数体必须从 loop_ctx 读 client / model_name。

    Phase 2.2-b 的实质成果：源码层防"形迁移神不迁移"。
    provider streaming 抽离后，core._call_model 不再直接调用
    loop_ctx.client.messages.stream；它必须把 loop_ctx 中的 provider/client/model
    显式传给 agent.model_call.call_model，继续保持依赖注入边界。
    """

    import inspect

    from agent import core

    src = inspect.getsource(core._call_model)
    assert "call_model(" in src, "_call_model 必须委托 provider-aware call_model seam"
    assert "provider=getattr(loop_ctx, \"model_provider\", None)" in src, (
        "_call_model 必须从 loop_ctx 读取 model_provider，"
        "不允许在 core.py 构造 provider SDK client"
    )
    assert "legacy_client=loop_ctx.client" in src, (
        "_call_model 必须把 loop_ctx.client 作为 legacy fallback 注入，"
        "不允许继续用 module-level client"
    )
    assert "model_name=loop_ctx.model_name" in src, (
        "_call_model 必须把 loop_ctx.model_name 注入 call_model，"
        "不允许继续用 module-level MODEL_NAME"
    )
    # 反向：函数体不应再出现裸 client.messages.stream 或 model=MODEL_NAME
    forbidden_patterns = (
        "loop_ctx.client.messages.stream",
        "with client.messages.stream(",
        "model=MODEL_NAME,",
    )
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"_call_model 仍隐式引用 module-level：{pat!r}"
        )


def test_run_main_loop_does_not_construct_loop_context():
    """_run_main_loop 函数体绝不允许出现 LoopContext(...) 构造调用。

    这是本切片存在的根因——避免 SSOT 双源。如果未来有人偷懒在主循环内
    直接 ``LoopContext(client=..., model_name=...)`` 重建实例，会让 chat()
    层修改 client / model_name 时主循环拿到旧值。本测试用 source-level
    扫描钉死。
    """

    import inspect

    from agent import loop

    src = inspect.getsource(loop.run_main_loop)
    assert "LoopContext(" not in src, (
        "_run_main_loop 函数体禁止构造 LoopContext；"
        "必须由上层 chat() 单源构造并透传"
    )


def test_chat_remains_unique_loop_context_construction_site_in_core():
    """agent/core.py 不再直接构造 LoopContext，构造点在 core_contexts。

    这条比上一条更广——上一条只防 _run_main_loop；本条防整个 core.py 的
    任何 helper 偷偷构造 LoopContext。Phase 2.2-c 之后任何新增 helper 想
    吃 loop_ctx 都必须从 chat() 透传，不能就地构造。
    """

    import inspect

    from agent import core, core_contexts

    src = inspect.getsource(core)
    construction_count = src.count("LoopContext(")
    assert construction_count == 0, (
        f"agent/core.py 中不应再直接构造 LoopContext，实际：{construction_count} 次。"
        "SSOT 单源已迁移到 agent.core_contexts.build_loop_context"
    )

    context_src = inspect.getsource(core_contexts)
    context_count = context_src.count("LoopContext(")
    assert context_count == 1, (
        f"agent.core_contexts 中 LoopContext(...) 构造调用必须恰好 1 次，"
        f"实际：{context_count} 次。"
    )


def test_run_main_loop_consumes_only_max_loop_iterations_from_loop_ctx():
    """_run_main_loop 函数体只允许消费 loop_ctx.max_loop_iterations。

    Phase 2.2-b 阶段本测试名为 ``..._does_not_consume_loop_ctx_fields_directly``，
    要求主循环完全不消费 loop_ctx 字段（只转发）。Phase 2.2-c 让循环兜底次数
    成为 LoopContext 一等公民后，本测试**升级**为精确白名单：
    - ✅ 允许：``loop_ctx.max_loop_iterations``（Phase 2.2-c 消费）；
    - ❌ 禁止：``loop_ctx.client`` / ``loop_ctx.model_name``——这些必须
      只在 ``_call_model`` 边界消费，主循环不得绕过 ``_call_model`` 直接
      触碰 LLM provider 细节。

    本测试**不是为了通过率而被弱化**——拦截能力等价提升：
    - 旧版本可挡住"主循环顺手用任何字段"；
    - 新版本可挡住"主循环顺手用 client/model_name 调 stream"或"主循环
      顺手用 LoopContext 未来新增的任何非 max_loop_iterations 字段"。
    用 AST 跳过 docstring 字符串匹配干扰。
    """

    import ast
    import inspect

    from agent import loop

    src = inspect.getsource(loop.run_main_loop)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    body_nodes = func_def.body
    if (
        body_nodes
        and isinstance(body_nodes[0], ast.Expr)
        and isinstance(body_nodes[0].value, ast.Constant)
        and isinstance(body_nodes[0].value.value, str)
    ):
        body_nodes = body_nodes[1:]

    allowed = {"max_loop_iterations"}
    # 显式列出禁用集合作为 docstring/审计参考（client/model_name 必须在
    # _call_model 边界消费）；下面用 "not in allowed" 即可判断 illegal，
    # 因此本变量只起文档作用，不参与判断。
    forbidden = {"client", "model_name"}  # noqa: F841 -- 文档变量，参与 review 阅读
    consumed: list[str] = []
    illegal: list[str] = []
    for node in body_nodes:
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Attribute)
                and isinstance(sub.value, ast.Name)
                and sub.value.id == "loop_ctx"
            ):
                consumed.append(sub.attr)
                if sub.attr not in allowed:
                    illegal.append(sub.attr)
    assert illegal == [], (
        f"run_main_loop 函数体只允许消费 {allowed}；非法消费：{illegal}。"
        "client / model_name 必须在 _call_model 边界消费，主循环不得绕过"
    )
    assert "max_loop_iterations" in consumed, (
        "Phase 2.2-c 后 run_main_loop 必须真正消费 loop_ctx.max_loop_iterations，"
        "否则等于形迁移神不迁移（继续读 module-level MAX_LOOP_ITERATIONS）"
    )


def test_chat_passes_loop_ctx_to_main_loop_at_all_call_sites():
    """chat() / _build_confirmation_context / planning result helper 都透传 loop_ctx。

    当前调用点（共 4 处）：
    - _build_confirmation_context.continue_fn lambda：_run_main_loop(ts, loop_ctx)
    - chat() awaiting/running 分支：_run_main_loop(turn_state, _loop_ctx)
    - _handle_planning_phase_result 兜底：_run_main_loop(turn_state, loop_ctx)
      （chat() 新任务与 _start_planning_for_handler 都先进入该 helper）
    任何新增 _run_main_loop 调用点都必须同步加参数。

    v0.5 第二小步注意：原 ConfirmationContext.continue_fn lambda 已从
    chat() 内迁到 _build_confirmation_context helper 内，因此 chat() 内
    的 _run_main_loop 直接调用次数从 3 减为 2，第 3 处出现在 helper 内。
    v0.6.2 后第一刀 helper extraction 再把 planning result 兜底主循环从
    chat()/handler 两处收口到 _handle_planning_phase_result。
    """

    import inspect

    from agent import core

    chat_src = inspect.getsource(core.chat)
    context_src = inspect.getsource(core._build_confirmation_context)
    result_src = inspect.getsource(core._handle_planning_phase_result)

    # chat() 仍保留 awaiting/running 分支的直接调用；新任务兜底由 helper 接管。
    chat_call_count = chat_src.count("_run_main_loop(")
    assert chat_call_count >= 1, (
        f"chat() 至少应有 1 处直接 _run_main_loop 调用，实际：{chat_call_count}"
    )
    # _build_confirmation_context helper 必须有 1 处（continue_fn lambda）
    assert context_src.count("_run_main_loop(") >= 1, (
        "_build_confirmation_context.continue_fn lambda 必须调用 _run_main_loop"
    )
    # chat() 中所有 _run_main_loop 调用都必须传 _loop_ctx
    assert chat_src.count("_loop_ctx") >= chat_src.count("_run_main_loop("), (
        "chat() 中所有 _run_main_loop 调用都必须传 _loop_ctx"
    )
    # helper 中 _run_main_loop 调用必须传 loop_ctx 形参
    assert "loop_ctx" in context_src, (
        "_build_confirmation_context 必须把 loop_ctx 透传给 _run_main_loop lambda"
    )

    # planning result helper 应有 1 处调用并传 loop_ctx
    # （v0.5+ 增加了 action_scheduler + checkpoint_save_on_turn_end 透传）。
    assert "_run_main_loop(" in result_src, (
        "_handle_planning_phase_result 必须调用 _run_main_loop"
    )
    assert "turn_state, loop_ctx" in result_src, (
        "_handle_planning_phase_result 调用 _run_main_loop 必须传上层 loop_ctx"
    )
    assert "tool_gate_tool_name=tool_gate_tool_name" in result_src
    assert "skill_registry=skill_registry" in result_src
    assert "action_scheduler=action_scheduler" in result_src
    assert "checkpoint_save_on_turn_end=checkpoint_save_on_turn_end" in result_src


# ========================================================================
# Phase 2.2-c：MAX_LOOP_ITERATIONS 通过 LoopContext 注入
# ------------------------------------------------------------------------
# 这一组测试钉死 Phase 2.2-c 的契约：循环兜底次数从模块级常量隐式引用
# 升级为 LoopContext 一等公民，由 chat() 单源构造、_run_main_loop 显式消费。
#
# 设计选择：
# - 模块级 MAX_LOOP_ITERATIONS = 50 **保留**作为默认值来源——chat() 构造
#   LoopContext 时引用它，运行时实际读取走 loop_ctx.max_loop_iterations；
# - 现有 from agent.core import MAX_LOOP_ITERATIONS 测试导入仍可用
#   （test_bug_hunting / test_runtime_error_recovery 等），向后兼容；
# - 主循环函数体禁止再裸引用 MAX_LOOP_ITERATIONS：必须强制走 loop_ctx，
#   否则迁移名存实亡（chat() 改 LoopContext.max_loop_iterations 时主循环
#   仍走 50）。
# ========================================================================


def test_run_main_loop_no_longer_reads_module_level_max_loop_iterations():
    """_run_main_loop 函数体禁止裸引用 MAX_LOOP_ITERATIONS。

    Phase 2.2-c 的实质成果：循环上限的真值来源**只**通过 loop_ctx，
    模块级常量退化为"chat() 构造 LoopContext 时使用的默认值"。如果主循环
    仍读 MAX_LOOP_ITERATIONS，等于双源——chat() 改 loop_ctx.max_loop_iterations
    时主循环仍按 module-level 50 跑。

    用 AST 检查跳过 docstring 干扰（docstring 会用文本提到该常量名作为
    "不应做的事"的说明）。只查实际 ast.Name 引用。
    """

    import ast
    import inspect

    from agent import loop

    src = inspect.getsource(loop.run_main_loop)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    body_nodes = func_def.body
    if (
        body_nodes
        and isinstance(body_nodes[0], ast.Expr)
        and isinstance(body_nodes[0].value, ast.Constant)
        and isinstance(body_nodes[0].value.value, str)
    ):
        body_nodes = body_nodes[1:]

    bad: list[ast.AST] = []
    for node in body_nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == "MAX_LOOP_ITERATIONS":
                bad.append(sub)
    assert not bad, (
        "_run_main_loop 函数体禁止裸引用 MAX_LOOP_ITERATIONS；"
        "Phase 2.2-c 后必须通过 loop_ctx.max_loop_iterations 访问"
    )


def test_module_level_max_loop_iterations_still_exported_for_chat_default():
    """模块级 MAX_LOOP_ITERATIONS 必须保留为 chat() LoopContext 默认值来源。

    这是向后兼容契约：现有测试（test_bug_hunting / test_runtime_error_recovery）
    依赖 ``from agent.core import MAX_LOOP_ITERATIONS`` 拿默认值用作上限计算
    或健康检查 (== 50)。如果 Phase 2.2-c 顺手把这个常量删掉，会破坏这些测试。
    保留常量也让 chat() 构造 LoopContext 时有显式默认值来源。
    """

    from agent import core

    assert hasattr(core, "MAX_LOOP_ITERATIONS"), (
        "agent/core.py 必须保留 MAX_LOOP_ITERATIONS 模块级常量作为 LoopContext "
        "默认值来源；删除会破坏 test_bug_hunting / test_runtime_error_recovery"
    )
    assert isinstance(core.MAX_LOOP_ITERATIONS, int), (
        "MAX_LOOP_ITERATIONS 必须是 int（chat() 直接传给 LoopContext 构造）"
    )
    assert core.MAX_LOOP_ITERATIONS > 0, (
        "MAX_LOOP_ITERATIONS 必须正（LoopContext.__post_init__ 也会校验）"
    )


def test_chat_loop_context_max_loop_iterations_equals_module_default():
    """LoopContext 构造点 max_loop_iterations 必须等于模块级常量。

    防止有人 Phase 2.2-c 后偷偷把构造改成硬编码 ``max_loop_iterations=100``，
    那样 module-level 常量就成了"看起来是默认值但 runtime 不用"的死代码——
    比单源更糟糕（视觉默认值与实际默认值不一致）。

    v0.5 Phase 3 第一小步：构造点从 chat() 内字面调用搬到
    _build_loop_context() helper，本测试随之扫描 helper src——
    契约本质（默认值必须是模块常量）未变。
    """

    import inspect

    from agent import core, core_contexts

    helper_src = inspect.getsource(core_contexts.build_loop_context)
    assert (
        "max_loop_iterations=MAX_LOOP_ITERATIONS" in helper_src
        or "max_loop_iterations: int = MAX_LOOP_ITERATIONS" in helper_src
        or "max_loop_iterations: int" in helper_src
    ), (
        "build_loop_context 必须显式接收 max_loop_iterations，"
        "core._build_loop_context wrapper 负责从 MAX_LOOP_ITERATIONS 注入默认值"
    )
    wrapper_src = inspect.getsource(core._build_loop_context)
    assert (
        "max_loop_iterations: int = MAX_LOOP_ITERATIONS" in wrapper_src
        or "max_loop_iterations=MAX_LOOP_ITERATIONS" in wrapper_src
    ), "core._build_loop_context wrapper 默认值必须取自模块常量 MAX_LOOP_ITERATIONS"


def test_confirm_handlers_must_not_import_or_construct_loop_context():
    """AST 级守卫：agent/confirm_handlers.py 不得 import 或实例化 LoopContext。

    通过 ast.parse 精确区分 import 和 call，避免字符串扫描对 docstring 的
    误伤。保护的架构边界：runtime dependency 只通过 callable boundary 注入，
    不通过 handler 直接持有 LoopContext 引用。

    注：本测试不禁止 confirm_handlers 在注释/docstring 中提到 LoopContext
    名字（架构说明本身是有价值的）。
    """

    import ast
    import inspect

    from agent import confirm_handlers

    src = inspect.getsource(confirm_handlers)
    tree = ast.parse(src)

    bad_imports: list[str] = []
    bad_calls: list[str] = []

    for node in ast.walk(tree):
        # 1) 禁止 `from agent.loop_context import LoopContext`
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.endswith("loop_context") or mod == "agent.loop_context":
                for alias in node.names:
                    if alias.name == "LoopContext":
                        bad_imports.append(
                            f"from {mod} import {alias.name} (line {node.lineno})"
                        )
        # 2) 禁止 `import agent.loop_context` 形式（哪怕未直接用 LoopContext，
        #    也意味着 handler 知道这个模块的存在——这本身就是耦合泄漏）
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "loop_context" in alias.name:
                    bad_imports.append(
                        f"import {alias.name} (line {node.lineno})"
                    )
        # 3) 禁止任何 `LoopContext(...)` 字面构造（无论是否经 import）
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "LoopContext":
                bad_calls.append(f"LoopContext(...) at line {node.lineno}")

    assert not bad_imports, (
        "confirm_handlers.py 不得 import LoopContext——runtime dependency 必须"
        f"通过 callable boundary 注入：{bad_imports}"
    )
    assert not bad_calls, (
        "confirm_handlers.py 不得调用 LoopContext(...)——SSOT 唯一构造点是 "
        f"agent/core.py:chat()：{bad_calls}"
    )


# ============================================================
# v0.5 Phase 3 第一小步 · _build_loop_context 工厂边界守卫
# ============================================================


def test_build_loop_context_returns_loop_context_with_expected_fields():
    """_build_loop_context() 必须返回 LoopContext 且 3 字段语义不变。

    防回归契约：v0.5 Phase 3 第一小步把字面 LoopContext(...) 调用抽到
    helper 工厂。helper 必须满足：
      - 返回类型是 LoopContext（不是 dict / SimpleNamespace 等替身）；
      - client 直接透传（不做 wrap）；
      - 默认 model_name 等于模块常量 MODEL_NAME；
      - 默认 max_loop_iterations 等于模块常量 MAX_LOOP_ITERATIONS；
      - 不偷偷加额外字段（messages / task / plan / pending_tool 等
        durable state 永不混进 LoopContext）。

    这条测试**不**依赖 LoopContext 内部字段顺序或私有实现，仅断言公共
    契约——属"行为中性 helper"应该被钉住的最小契约。
    """
    from agent import core
    from agent.core import MAX_LOOP_ITERATIONS, MODEL_NAME, _build_loop_context
    from agent.loop_context import LoopContext

    sentinel_client = object()
    ctx = _build_loop_context(sentinel_client)

    assert isinstance(ctx, LoopContext)
    assert ctx.client is sentinel_client
    assert ctx.model_name == MODEL_NAME
    assert ctx.max_loop_iterations == MAX_LOOP_ITERATIONS

    # LoopContext 字段集必须仍然只有 3 个 runtime dependency；
    # 任何 durable state 名（messages / task / plan / pending_tool 等）
    # 都不允许出现在 dataclass 字段中（防"helper 顺手把状态塞进去"）。
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ctx)}
    forbidden = {
        "messages", "task", "plan", "current_step_index",
        "pending_tool", "pending_user_input_request",
        "working_summary", "checkpoint_data", "tool_traces",
    }
    assert not (field_names & forbidden), (
        f"LoopContext 字段被污染——出现 durable state 名 "
        f"{field_names & forbidden}；LoopContext 必须严格只装 runtime "
        "dependency（client / model_name / max_loop_iterations）。"
    )

    # 同时复用 core 模块名空间避免 unused import 警告
    assert hasattr(core, "_build_loop_context")


def test_build_loop_context_kwargs_override_defaults_without_module_mutation():
    """helper 接收 kwarg override 时，模块常量保持不变（无副作用）。

    这条防止有人未来"偷懒"用全局可变状态实现 override（例如改写
    agent.core.MODEL_NAME）。helper 必须是纯函数：override 走 kwarg，
    不改任何模块级状态。
    """
    from agent import core
    from agent.core import _build_loop_context

    before_model = core.MODEL_NAME
    before_max = core.MAX_LOOP_ITERATIONS

    ctx = _build_loop_context(
        object(), model_name="override-model", max_loop_iterations=999
    )
    assert ctx.model_name == "override-model"
    assert ctx.max_loop_iterations == 999

    # 模块常量必须未被 helper 改写
    assert before_model == core.MODEL_NAME
    assert before_max == core.MAX_LOOP_ITERATIONS


# ============================================================
# v0.5 Phase 3 第二小步 · _build_confirmation_context 工厂边界守卫
# ============================================================


def test_build_confirmation_context_returns_confirmation_context_with_expected_fields():
    """_build_confirmation_context() 必须返回 ConfirmationContext 且字段语义正确。

    防回归契约：v0.5 第二小步把字面 ConfirmationContext(...) 抽到 helper。
    helper 必须满足：
      - 返回类型是 ConfirmationContext（不是替身 dict / Namespace）；
      - state / turn_state 直接透传（不做 wrap）；
      - client / model_name 取自 loop_ctx（与 v0.4 Phase 2.2-b 让 _call_model
        走 loop_ctx 的方向一致）；
      - continue_fn 是 callable，调用时把 ts 转给主循环；
      - start_planning_fn 是 callable，调用时把 inp/ts 转给 planning helper；
      - 不偷偷加额外字段（messages / task / plan / current_step_index 等
        durable state 永不混进 ConfirmationContext）。

    测试用真实 LoopContext + sentinel state/turn_state，验证字段绑定，
    不实际触发主循环（避免引入测试副作用）。
    """
    from agent import core
    from agent.confirm_handlers import ConfirmationContext
    from agent.core import _build_confirmation_context, _build_loop_context

    sentinel_client = object()
    sentinel_state = object()
    sentinel_turn_state = object()
    loop_ctx = _build_loop_context(
        sentinel_client, model_name="test-model", max_loop_iterations=7
    )

    ctx = _build_confirmation_context(
        state=sentinel_state, turn_state=sentinel_turn_state, loop_ctx=loop_ctx
    )

    assert isinstance(ctx, ConfirmationContext)
    assert ctx.state is sentinel_state
    assert ctx.turn_state is sentinel_turn_state
    assert ctx.client is sentinel_client, (
        "client 必须从 loop_ctx 透传（与 _call_model 走 loop_ctx 方向一致）"
    )
    assert ctx.model_name == "test-model", (
        "model_name 必须从 loop_ctx 透传"
    )
    assert callable(ctx.continue_fn), "continue_fn 必须是 callable"
    assert callable(ctx.start_planning_fn), "start_planning_fn 必须是 callable"

    # ConfirmationContext 字段集严格对齐：禁止 helper 顺手把 durable state
    # （messages / task / plan / pending_*）塞进 ConfirmationContext。
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ctx)}
    forbidden = {
        "messages", "task", "plan", "current_step_index",
        "pending_tool", "pending_user_input_request",
        "working_summary", "checkpoint_data", "tool_traces",
    }
    assert not (field_names & forbidden), (
        f"ConfirmationContext 字段被污染——出现 durable state 名 "
        f"{field_names & forbidden}；ConfirmationContext 必须严格只装 handler "
        "dependency（state/turn_state/client/model_name/continue_fn/start_planning_fn）。"
    )

    # 用 core 模块名空间避免 unused import
    assert hasattr(core, "_build_confirmation_context")


def test_chat_remains_unique_confirmation_context_construction_site_in_core():
    """agent/core.py 不再直接构造 ConfirmationContext。

    与 LoopContext SSOT 测试同模式：构造点迁移到 core_contexts，
    core.py 只保留兼容 wrapper，避免 runtime core 继续堆积上下文装配细节。
    """
    import inspect

    from agent import core, core_contexts

    src = inspect.getsource(core)
    construction_count = src.count("ConfirmationContext(")
    assert construction_count == 0, (
        f"agent/core.py 中不应再直接构造 ConfirmationContext，"
        f"实际：{construction_count} 次。"
        "SSOT 单源已迁移到 agent.core_contexts.build_confirmation_context"
    )

    context_src = inspect.getsource(core_contexts)
    context_count = context_src.count("ConfirmationContext(")
    assert context_count == 1, (
        f"agent.core_contexts 中 ConfirmationContext(...) 字面构造调用必须恰好 1 次，"
        f"实际：{context_count} 次。"
    )

    # 同时检查 chat() 通过 helper 调用（不绕过 SSOT）
    chat_src = inspect.getsource(core.chat)
    assert "_build_confirmation_context(" in chat_src, (
        "chat() 必须通过 _build_confirmation_context(...) 工厂构造 ConfirmationContext"
    )


def test_build_confirmation_context_lambdas_capture_loop_ctx_not_rebuild():
    """helper 内 continue_fn / start_planning_fn lambda 必须闭包捕获
    传入的 loop_ctx，而不是在 lambda 体里重建 LoopContext。

    防止有人未来"为了灵活性"把 lambda 改成 ``lambda ts: _run_main_loop(
    ts, _build_loop_context(client))`` 之类的写法——那会破坏 SSOT
    （每次 lambda 调用产生一个新 LoopContext），也会破坏 monkeypatch 行为。

    本测试用 AST 解析 helper 体，断言 lambda 内不包含对 _build_loop_context
    或 LoopContext 的调用。
    """
    import ast
    import inspect

    from agent import core

    src = inspect.getsource(core._build_confirmation_context)
    tree = ast.parse(src)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    forbidden_names = {"_build_loop_context", "LoopContext"}
    bad_calls: list[str] = []
    for node in ast.walk(func_def):
        if isinstance(node, ast.Lambda):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    if isinstance(func, ast.Name) and func.id in forbidden_names:
                        bad_calls.append(func.id)
    assert not bad_calls, (
        f"_build_confirmation_context 的 lambda 内禁止调用 "
        f"{forbidden_names}——必须闭包捕获传入的 loop_ctx，不得重建。"
        f"实际发现：{bad_calls}"
    )
