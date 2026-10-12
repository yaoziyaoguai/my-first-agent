"""020 长会话压缩的 turn grammar 与移除校验（窄 leaf）。

只依赖 ``agent.runtime.contracts`` 与标准库：state（reducer）与 context
（candidate 选择、pack 构建）都从本 leaf 取用同一套 fail-closed 规则，
禁止反向依赖或把规则复制回巨石模块。这里不调用模型、工具、持久化，
也不修改任何 state。
"""

from __future__ import annotations

from agent.runtime.contracts import ConversationFact, ConversationState, FactKind
from agent.runtime.resource_lifecycle import active_task_resources


class CompactionIneligibleHistoryError(ValueError):
    """合法但保守不可压缩的历史:未终止段后出现新的 user 边界。

    精确条件:某个 USER_MESSAGE 开始的 conversational segment 尚未收到
    ASSISTANT_MESSAGE 终结,就出现了下一个新的 USER_MESSAGE(如上一轮
    failed_fatal 只留下 user/policy/tool facts),且段内此前的 TOOL_CALLS
    批次均已通过 exact-result 覆盖检查。这是 reducer 可产出的合法历史,
    不得按畸形结构 fatal 会话;选择侧捕获本类型降级为空候选,
    移除校验侧不捕获、继续拒绝缩减。
    """


def parse_compaction_turns(
    facts: tuple[ConversationFact, ...],
) -> tuple[str | None, tuple[frozenset[str], ...], frozenset[str]]:
    """把整个 facts 从头到尾解析为 summary 段与 turn 段。

    返回 ``(summary_id, closed_turn_ids, open_turn_ids)``:至多一个
    ``CONTEXT_SUMMARY``,可位于完整 turn 之间的边界或末尾(非首位 summary
    是第一批压缩后的合法中间产物);若干以 USER_MESSAGE 开始、
    ASSISTANT_MESSAGE 结束的 closed turns;结尾允许恰好一个未闭合尾 turn
    (active_run 存在时最新 turn 常处于该状态)。turn 内 TOOL_CALLS 批次的
    tool_call_id 必须由紧随其后的连续 TOOL_RESULT 恰好覆盖,批次与结果不能
    拆;POLICY_RESULT 在 turn 内是普通 fact。未终止段(无 ASSISTANT_MESSAGE
    终结)之后出现新的 USER_MESSAGE 边界时抛
    ``CompactionIneligibleHistoryError``:这是合法但保守不可压缩的历史,
    不是畸形结构。其余结构违例(含多个 summary、turn 内 summary、孤立
    TOOL_RESULT 与规则未覆盖的 fact)一律普通 ValueError:compaction 校验
    与候选选择共享同一套 fail-closed 判定,而不是只把出错 turn 标记为
    不可移除。
    """
    total = len(facts)
    summary_id: str | None = None
    closed_turn_ids: list[frozenset[str]] = []
    open_turn_ids: frozenset[str] = frozenset()
    index = 0
    while index < total:
        kind = facts[index].kind
        if kind is FactKind.CONTEXT_SUMMARY:
            # summary 只能出现在 turn 边界(上一个 turn 已闭合或 EOF);
            # turn 内出现会落入下方 turn 解析的默认拒绝分支。
            if summary_id is not None:
                raise ValueError("conversation allows at most one CONTEXT_SUMMARY")
            summary_id = facts[index].fact_id
            index += 1
            continue
        if kind is not FactKind.USER_MESSAGE:
            raise ValueError("conversation facts must decompose into closed turns")
        turn_ids = {facts[index].fact_id}
        index += 1
        closed = False
        while index < total:
            kind = facts[index].kind
            if kind is FactKind.ASSISTANT_MESSAGE:
                turn_ids.add(facts[index].fact_id)
                index += 1
                closed = True
                break
            if kind is FactKind.POLICY_RESULT:
                turn_ids.add(facts[index].fact_id)
                index += 1
                continue
            if kind is FactKind.TOOL_CALLS:
                calls = facts[index].content.get("calls")
                if not isinstance(calls, list) or not calls:
                    raise ValueError("tool call fact must contain a non-empty calls list")
                expected_ids: set[str] = set()
                for call in calls:
                    tool_call_id = (
                        call.get("tool_call_id") if isinstance(call, dict) else None
                    )
                    if not isinstance(tool_call_id, str) or not tool_call_id:
                        raise ValueError(
                            "tool call batch entries must carry string tool_call_id"
                        )
                    if tool_call_id in expected_ids:
                        raise ValueError("tool_call_id must be unique within a batch")
                    expected_ids.add(tool_call_id)
                turn_ids.add(facts[index].fact_id)
                index += 1
                covered: set[str] = set()
                while index < total and facts[index].kind is FactKind.TOOL_RESULT:
                    result_call_id = facts[index].content.get("tool_call_id")
                    if not isinstance(result_call_id, str):
                        raise ValueError("tool result must bind a string tool_call_id")
                    if result_call_id not in expected_ids or result_call_id in covered:
                        raise ValueError("tool result must exactly cover the preceding batch")
                    covered.add(result_call_id)
                    turn_ids.add(facts[index].fact_id)
                    index += 1
                if covered != expected_ids:
                    raise ValueError("tool batch and its results cannot be split")
                continue
            if kind is FactKind.USER_MESSAGE:
                # 未终止段(无 ASSISTANT_MESSAGE 终结)后出现新的 user 边界:
                # 合法但保守不可压缩的历史,抛窄类型子异常;段内 tool 批次
                # 完整性已由上方批次分支先行检查,拆批在此前就已拒绝。
                raise CompactionIneligibleHistoryError(
                    "new user boundary precedes ASSISTANT_MESSAGE termination; "
                    "history is legitimately non-compactable"
                )
            # 其余 kind(含 turn 内 CONTEXT_SUMMARY、孤立 TOOL_RESULT 与规则
            # 未覆盖的 fact)破坏 closed turn 结构,一律拒绝。
            raise ValueError("conversation facts must decompose into closed turns")
        if closed:
            closed_turn_ids.append(frozenset(turn_ids))
        else:
            # 内层循环只在闭合时 break,未闭合意味着到达 EOF:唯一的未闭合尾 turn。
            open_turn_ids = frozenset(turn_ids)
    return summary_id, tuple(closed_turn_ids), open_turn_ids


def protected_compaction_fact_ids(
    state: ConversationState,
) -> tuple[frozenset[str], frozenset[str]]:
    """返回 ``(goal_source_ids, evidence_source_ids)``。

    被 Goal ``created_from_fact_ids`` 或任一 ``evidence_records`` 的
    ``source_fact_ids`` 引用的 fact 所在 turn 受 compaction 保护;两类
    引用分开返回,便于校验方报告各自的失败原因。
    """
    goal = state.goal
    goal_source_ids = (
        frozenset(goal.created_from_fact_ids) if goal is not None else frozenset()
    )
    evidence_source_ids: set[str] = set()
    for record in state.evidence_records:
        evidence_source_ids.update(record.source_fact_ids)
    # 未清理资源的 open/start receipt 是 durable ownership 事实；在对应 close/stop
    # 到达前不得被摘要替换，否则 completion 会失去收尾义务。
    goal_source_ids = goal_source_ids | active_task_resources(state.facts).owner_fact_ids
    return goal_source_ids, frozenset(evidence_source_ids)


def validate_compaction_removal(
    state: ConversationState,
    removable_fact_ids: tuple[str, ...],
) -> tuple[ConversationFact, ...]:
    """020 长会话压缩:判定一段 ids 是否构成可整体移除的完整 closed turn 集。

    纯校验函数:只读取 state,不修改任何字段,也不负责 summary 应用、archive
    或 CAS。保守规则:

    - ids 非空、无重复、全部存在;
    - ``state.facts`` 从头到尾必须能解析为:至多一个 ``CONTEXT_SUMMARY``
      (位置可在 turn 之间或末尾),加若干以 USER_MESSAGE 开始、
      ASSISTANT_MESSAGE 结束的 turn;结尾允许恰好一个未闭合 turn,它天然
      不可选择(active_run 存在时最新 turn 常处于该状态);未终止段后紧跟
      新 user 边界的合法 ineligible 历史由 parser 抛
      ``CompactionIneligibleHistoryError``,本函数不捕获,移除自动被拒;
    - turn 内 TOOL_CALLS 批次的 tool_call_id 必须由紧随其后的连续 TOOL_RESULT
      恰好覆盖,批次与结果不能拆;POLICY_RESULT 在 turn 内是普通 fact;
    - removable ids 必须精确等于至少一个可移除 closed turn 的并集(可非连续,
      不再要求是 ``state.facts`` 的连续前缀),可额外包含已有 summary,但
      不能只含 summary;
    - turn 内任一 fact 被 ``goal.created_from_fact_ids`` 或 ``evidence_records``
      的 ``source_fact_ids`` 引用时,整个 turn 不可移除。

    返回按 ``state.facts`` 原顺序排列的待移除 facts。
    """
    if not removable_fact_ids:
        raise ValueError("removable fact ids must not be empty")
    if len(set(removable_fact_ids)) != len(removable_fact_ids):
        raise ValueError("removable fact ids must not contain duplicates")
    selected_ids = frozenset(removable_fact_ids)
    facts = state.facts
    if not selected_ids <= frozenset(fact.fact_id for fact in facts):
        raise ValueError("removable fact ids must exist in conversation state")

    # 结构解析与 protected 引用判定共享给 candidate helper,保证选择与校验
    # 永不背离同一套 fail-closed 规则;合法 ineligible 历史在此抛
    # CompactionIneligibleHistoryError,缩减自动被拒,不做任何捕获。
    summary_id, closed_turn_ids, open_turn_ids = parse_compaction_turns(facts)
    if selected_ids & open_turn_ids:
        raise ValueError("unclosed trailing turn is not removable")
    goal_source_ids, evidence_source_ids = protected_compaction_fact_ids(state)
    covered_ids = {summary_id} if summary_id is not None else set()
    selected_turns = 0
    for turn_ids in closed_turn_ids:
        if not selected_ids & turn_ids:
            continue
        if not turn_ids <= selected_ids:
            raise ValueError("removable facts must cover whole closed turns")
        if turn_ids & goal_source_ids:
            raise ValueError(
                "removable facts must not include goal or active-resource owner turns"
            )
        if turn_ids & evidence_source_ids:
            raise ValueError("removable facts must not include evidence source turns")
        selected_turns += 1
        covered_ids |= turn_ids
    if selected_turns < 1:
        raise ValueError("removable facts must include at least one closed turn")
    if not selected_ids <= covered_ids:
        raise ValueError(
            "removable facts must equal whole closed turns plus at most the summary"
        )
    return tuple(fact for fact in facts if fact.fact_id in selected_ids)
