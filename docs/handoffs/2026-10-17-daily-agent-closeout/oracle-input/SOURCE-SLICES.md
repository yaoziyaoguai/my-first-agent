# Oracle代码输入（2026-10-17，只读快照）

## agent/runtime/state.py:1559-1740

```python
 1559 def record_completion_claim(
 1560     state: ConversationState,
 1561     claim: CompletionClaim,
 1562 ) -> ConversationState:
 1563     goal = _require_goal_revision(
 1564         state,
 1565         goal_id=claim.goal_id,
 1566         expected_revision=claim.goal_revision,
 1567     )
 1568     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
 1569         raise ValueError("completion claim requires an executable goal")
 1570     if any(
 1571         receipt.correlation_id == claim.correlation_id
 1572         for receipt in state.control_receipts
 1573     ):
 1574         raise ValueError("control correlation_id was already accepted")
 1575     evidence_ids = {record.evidence_id for record in state.evidence_records}
 1576     if not set(claim.criterion_evidence_refs).issubset(evidence_ids):
 1577         raise ValueError("completion claim references unknown evidence")
 1578     accepted_revision = state.revision + 1
 1579     # receipt payload 身份绑定全部语义相关字段：R2 的 requirement_coverage 改写
 1580     # （相同其他字段、不同 coverage）不得复用同一 digest。历史 receipt 不重算。
 1581     payload_digest = canonical_json_digest(
 1582         {
 1583             "goal_id": claim.goal_id,
 1584             "goal_revision": claim.goal_revision,
 1585             "criterion_evidence_refs": claim.criterion_evidence_refs,
 1586             "requirement_coverage": [
 1587                 {
 1588                     "requirement_id": item.requirement_id,
 1589                     "requirement": item.requirement,
 1590                     "source_fact_ids": item.source_fact_ids,
 1591                     "status": item.status,
 1592                     "criterion_ids": item.criterion_ids,
 1593                 }
 1594                 for item in claim.requirement_coverage
 1595             ],
 1596         }
 1597     )
 1598     receipt = ControlReceipt.create(
 1599         correlation_id=claim.correlation_id,
 1600         control_kind="completion_claim",
 1601         goal_id=goal.goal_id,
 1602         goal_revision=goal.revision,
 1603         accepted_state_revision=accepted_revision,
 1604         payload_digest=payload_digest,
 1605     )
 1606     return replace(
 1607         state,
 1608         revision=accepted_revision,
 1609         completion_claim=claim,
 1610         control_receipts=(*state.control_receipts, receipt),
 1611     )
 1612 
 1613 
 1614 def record_evidence(
 1615     state: ConversationState,
 1616     records: tuple[EvidenceRecord, ...],
 1617 ) -> ConversationState:
 1618     goal = state.goal
 1619     if goal is None or not records:
 1620         raise ValueError("evidence requires a current goal and at least one record")
 1621     criteria = {criterion.criterion_id: criterion for criterion in goal.admitted_criteria}
 1622     for record in records:
 1623         criterion = criteria.get(record.criterion_id)
 1624         if (
 1625             record.goal_id != goal.goal_id
 1626             or record.goal_revision != goal.revision
 1627             or criterion is None
 1628             or record.oracle_kind is not criterion.oracle_kind
 1629             or record.predicate_digest != canonical_json_digest(criterion.predicate)
 1630         ):
 1631             raise ValueError("evidence does not bind the current admitted criterion")
 1632     # R2-C：同 id 记录按位刷新（derive 对 append-only facts 的当前重导出），
 1633     # 绑定校验不放宽；新记录按提交顺序追加。被后续写入失效的旧证据由此获得
 1634     # 可修复的刷新路径，而不是把 Goal 永久卡在陈旧缓存上。
 1635     merged = {record.evidence_id: record for record in state.evidence_records}
 1636     known_order = [record.evidence_id for record in state.evidence_records]
 1637     for record in records:
 1638         if record.evidence_id not in merged:
 1639             known_order.append(record.evidence_id)
 1640         merged[record.evidence_id] = record
 1641     refreshed = tuple(merged[evidence_id] for evidence_id in known_order)
 1642     if refreshed == state.evidence_records:
 1643         return state
 1644     return replace(
 1645         state,
 1646         revision=state.revision + 1,
 1647         evidence_records=refreshed,
 1648     )
 1649 
 1650 
 1651 def _require_requirement_coverage(
 1652     state: ConversationState,
 1653     claim: CompletionClaim,
 1654     *,
 1655     goal: GoalFrame,
 1656     mandatory: tuple[AdmittedCriterion, ...],
 1657 ) -> None:
 1658     """R2 完成门：物理证据齐全是必要条件，不是完整业务完成的充分条件。
 1659 
 1660     最终结束必须经过针对当前 Goal revision 与当前权威用户输入/最新 correction
 1661     的逐项覆盖复核（模型提供语义映射，Runtime 校验结构与版本/来源/证据绑定）。
 1662     缺失时拒绝并给出可修复的下一步；不铸造 evidence/permission，不引入第二
 1663     模型裁判。引用整条 fact、空列表或首个文件 digest 的组合不能充当逐项复核。
 1664     """
 1665 
 1666     coverage = claim.requirement_coverage
 1667     if not coverage:
 1668         raise ValueError(
 1669             "completion claim must include per-requirement coverage of the current "
 1670             "authoritative user input and corrections before the goal can be verified"
 1671         )
 1672     source_ids = set(goal.created_from_fact_ids)
 1673     authoritative_ids = {
 1674         fact.fact_id
 1675         for fact in state.facts
 1676         if fact.fact_id in source_ids and fact.kind is FactKind.USER_MESSAGE
 1677     }
 1678     cited: set[str] = set()
 1679     for item in coverage:
 1680         cited.update(item.source_fact_ids)
 1681         if any(fact_id not in source_ids for fact_id in item.source_fact_ids):
 1682             raise ValueError(
 1683                 "requirement coverage must cite the authoritative source facts of "
 1684                 "the current goal"
 1685             )
 1686     uncited = authoritative_ids - cited
 1687     if uncited:
 1688         raise ValueError(
 1689             "requirement coverage does not cite every authoritative user input or "
 1690             f"correction: {sorted(uncited)}"
 1691         )
 1692     mandatory_ids = {criterion.criterion_id for criterion in mandatory}
 1693     pending = tuple(item for item in coverage if item.status == "pending")
 1694     if pending:
 1695         raise ValueError(
 1696             "completion claim lists pending requirements that are not yet satisfied: "
 1697             + ", ".join(item.requirement_id for item in pending)
 1698         )
 1699     for item in coverage:
 1700         unknown = set(item.criterion_ids) - mandatory_ids
 1701         if unknown:
 1702             raise ValueError(
 1703                 "requirement coverage binds criterion ids that are not current "
 1704                 f"admitted mandatory criteria: {sorted(unknown)}"
 1705             )
 1706     covered = {
 1707         criterion_id
 1708         for item in coverage
 1709         for criterion_id in item.criterion_ids
 1710     }
 1711     uncovered = mandatory_ids - covered
 1712     if uncovered:
 1713         raise ValueError(
 1714             "requirement coverage does not bind every mandatory criterion: "
 1715             f"{sorted(uncovered)}"
 1716         )
 1717 
 1718 
 1719 def verify_goal_completion(state: ConversationState) -> ConversationState:
 1720     goal = state.goal
 1721     claim = state.completion_claim
 1722     if goal is None or claim is None:
 1723         raise ValueError("completion verification requires a current claim")
 1724     if _has_unknown_effect(state):
 1725         raise ValueError("unknown effect recovery has priority over goal verification")
 1726     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
 1727         raise ValueError("goal status is not eligible for completion verification")
 1728     if claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
 1729         raise GoalRevisionConflictError("completion claim is stale")
 1730     if state.browser_takeover_pending is not None:
 1731         raise ValueError("browser takeover must be resolved before goal verification")
 1732     active_task_resources(state.facts).require_closed()
 1733     referenced = {
 1734         record.evidence_id: record
 1735         for record in state.evidence_records
 1736         if record.evidence_id in claim.criterion_evidence_refs
 1737     }
 1738     mandatory = tuple(
 1739         criterion for criterion in goal.admitted_criteria if criterion.mandatory
 1740     )
```

## agent/runtime/state.py:1843-1890

```python
 1843 def _goal_target_authorization_scope(
 1844     state: ConversationState,
 1845     pending: ApprovalRequest,
 1846     active: ActiveRun,
 1847     *,
 1848     directory: bool,
 1849 ) -> str | None:
 1850     goal = state.goal
 1851     call = active.tool_calls[active.batch_cursor]
 1852     target = call.arguments.get("path")
 1853     if not (
 1854         goal is not None
 1855         and pending.tool_name in {"write_file", "edit_file"}
 1856         and call.name == pending.tool_name
 1857         and pending.side_effect == SideEffectClass.WRITE.value
 1858         and pending.egress in {None, EgressClass.NONE.value}
 1859         and isinstance(target, str)
 1860     ):
 1861         return None
 1862     if not directory:
 1863         return (
 1864             target
 1865             if target in goal.targets and safe_goal_authorization_target(target)
 1866             else None
 1867         )
 1868     target_parts = target.split("/")
 1869     candidates = []
 1870     for goal_target in goal.targets:
 1871         goal_parts = goal_target.split("/")
 1872         if (
 1873             len(target_parts) > len(goal_parts)
 1874             and safe_goal_authorization_target(target)
 1875             and safe_goal_authorization_target(goal_target)
 1876             and all(part not in {"", ".", ".."} for part in (*target_parts, *goal_parts))
 1877             and target_parts[: len(goal_parts)] == goal_parts
 1878         ):
 1879             candidates.append(goal_target)
 1880     return max(candidates, key=lambda item: len(item.split("/")), default=None)
 1881 
 1882 
 1883 def _action_is_legal(state: ConversationState, action: Action) -> tuple[bool, str | None]:
 1884     active = state.active_run
 1885     if isinstance(action, AcknowledgeProviderDisclosure):
 1886         request = state.provider_disclosure_request
 1887         if (
 1888             request is None
 1889             or request.request_digest != action.request_digest
 1890             or active is None
```

## agent/runtime/state.py:2472-2543

```python
 2472     state: ConversationState,
 2473     pending: ApprovalRequest,
 2474     action: ResolveApproval,
 2475     *,
 2476     active: ActiveRun,
 2477 ) -> ConversationState:
 2478     """把用户 opt-in 绑定为当前 Goal 的文件或明确目录目标。"""
 2479 
 2480     if not (action.authorize_goal_target or action.authorize_goal_directory):
 2481         return state
 2482     directory = action.authorize_goal_directory
 2483     authorized_target = _goal_target_authorization_scope(
 2484         state,
 2485         pending,
 2486         active,
 2487         directory=directory,
 2488     )
 2489     if authorized_target is None:
 2490         raise ValueError(
 2491             "goal authorization requires a current Goal file or directory target"
 2492         )
 2493     goal = state.goal
 2494     assert goal is not None
 2495     if action.approved_at is None:
 2496         raise ValueError("approved_at is required for goal target authorization")
 2497     issued_at = _require_zoned_rfc3339(action.approved_at)
 2498     binding = GoalAuthorizationBinding.create(
 2499         binding_id=f"goal-target-authority:{pending.request_id}",
 2500         goal_id=goal.goal_id,
 2501         goal_revision=goal.revision,
 2502         workspace_identity_digest=goal.workspace_identity_digest,
 2503         operation=pending.tool_name,
 2504         normalized_target=authorized_target,
 2505         scope=(
 2506             GoalAuthorizationScope.DIRECTORY
 2507             if directory
 2508             else GoalAuthorizationScope.EXACT_FILE
 2509         ),
 2510         source_kind=AuthoritySourceKind.HUMAN_APPROVAL,
 2511         source_id=pending.request_id,
 2512         source_digest=canonical_action_digest(action),
 2513         issued_at=issued_at,
 2514         expires_at=_add_minutes_rfc3339(
 2515             issued_at,
 2516             GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES,
 2517         ),
 2518     )
 2519     retained = tuple(
 2520         item
 2521         for item in state.goal_authorizations
 2522         if not (
 2523             item.operation == binding.operation
 2524             and item.normalized_target == binding.normalized_target
 2525             and item.scope is binding.scope
 2526         )
 2527     )
 2528     return replace(state, goal_authorizations=(*retained, binding))
 2529 
 2530 
 2531 def _apply_action(state: ConversationState, action: Action) -> ConversationState:
 2532     if isinstance(action, ExecuteOperatorTool):
 2533         return start_operator_tool(state, action)
 2534     if isinstance(action, AcknowledgeProviderDisclosure):
 2535         return acknowledge_provider_disclosure(state, action)
 2536     if isinstance(action, ConfirmCriterion):
 2537         goal = state.goal
 2538         if goal is None:
 2539             raise ValueError("criterion confirmation requires a goal")
 2540         fact = ConversationFact(
 2541             fact_id=f"action:{action.action_seq}:criterion-confirmation",
 2542             kind=FactKind.USER_MESSAGE,
 2543             content={
```

## agent/runtime/loop.py:2751-2998

```python
 2751                             ),
 2752                         )
 2753                     no_progress_since_product_action = True
 2754                     current = self._save(
 2755                         current,
 2756                         append_policy_result(
 2757                             current.state,
 2758                             code="blocked_claim_not_verified",
 2759                             message=(
 2760                                 "The blocked_claim was not accepted because no relevant "
 2761                                 "product tool attempt supports a still-pending Runtime-owned "
 2762                                 "Goal obligation. Required next tool: "
 2763                                 f"{', '.join(required_tools)}. Unrelated workspace reads do "
 2764                                 "not establish this blocker. Call the tool that can advance "
 2765                                 "trusted_goal now; claim blocked only after a concrete safe "
 2766                                 "attempt produces a durable blocker."
 2767                                 if pending_obligation_tools
 2768                                 else "The blocked_claim was not accepted because no product "
 2769                                 "tool attempt supports it. Available product tools: "
 2770                                 f"{', '.join(available_tools)}. Call the tool that can "
 2771                                 "advance trusted_goal now; claim blocked only after a "
 2772                                 "concrete safe attempt produces a durable blocker."
 2773                             ),
 2774                         ),
 2775                     )
 2776                     continue
 2777                 goal_frame = current.state.goal
 2778                 mandatory_refs = tuple(
 2779                     ClosedEvidenceRegistry.evidence_id(
 2780                         goal_frame.goal_id,
 2781                         goal_frame.revision,
 2782                         criterion.criterion_id,
 2783                     )
 2784                     for criterion in goal_frame.admitted_criteria
 2785                     if criterion.mandatory
 2786                 )
 2787                 # 用户拒绝当前 Goal 仍需要的 authority 时，blocked 是合法终态；
 2788                 # 但 correction 后拒绝旧 target，或已持有 closed Web receipt 后
 2789                 # 拒绝重复检索，只是在维护现有 authority，不得据此把已经可证明
 2790                 # 的 Goal 终化为 blocked（016 J11 真实三连实测）。
 2791                 if mandatory_refs and not self._rejection_still_blocks_current_goal(
 2792                     current.state
 2793                 ):
 2794                     probe = CompletionClaim(
 2795                         correlation_id=control.correlation_id,
 2796                         goal_id=goal_frame.goal_id,
 2797                         goal_revision=goal_frame.revision,
 2798                         criterion_evidence_refs=mandatory_refs,
 2799                     )
 2800                     try:
 2801                         self._evidence_registry.derive(
 2802                             current.state,
 2803                             probe,
 2804                             observed_at=self._evidence_time_factory(),
 2805                         )
 2806                     except EvidenceVerificationError as error:
 2807                         evidence_gap = str(error)
 2808                         gap_repair = self._evidence_registry.assess_gap(
 2809                             evidence_gap,
 2810                             available_tools=available_tools,
 2811                         )
 2812                         if gap_repair.repairable_tools:
 2813                             if no_progress.repair_exhausted(
 2814                                 (
 2815                                     "blocked_claim_with_repairable_evidence",
 2816                                     *gap_repair.repairable_tools,
 2817                                 ),
 2818                                 allowance=self._limits.max_no_progress_replans,
 2819                                 observation_id=model_calls,
 2820                             ):
 2821                                 return self._finish_no_progress(
 2822                                     current,
 2823                                     action,
 2824                                     warnings,
 2825                                     message=(
 2826                                         "Provider repeated blocked claims while an "
 2827                                         "available tool could close the evidence gap."
 2828                                     ),
 2829                                 )
 2830                             no_progress_since_product_action = True
 2831                             current = self._save(
 2832                                 current,
 2833                                 append_policy_result(
 2834                                     current.state,
 2835                                     code="blocked_claim_not_verified",
 2836                                     message=(
 2837                                         "The blocked_claim was not accepted because the "
 2838                                         "current evidence gap is repairable with an "
 2839                                         "advertised product tool. Required next tool: "
 2840                                         f"{', '.join(gap_repair.repairable_tools)}. "
 2841                                         + gap_repair.repair_instruction
 2842                                     ),
 2843                                 ),
 2844                             )
 2845                             continue
 2846                     else:
 2847                         # 016 第 96 轮 a2 J7:edit+process 均成功(exit 0、durable
 2848                         # receipts)后模型以 blocked 收尾。守卫合同要求 attempt
 2849                         # "produces a durable blocker";完成证据已可推导时
 2850                         # "无安全动作可推进"不成立,受理会把可完成 Goal 终化为
 2851                         # blocked(false-completion 的对偶)。拒绝并给 completion
 2852                         # 修复指引;证据不可推导时 blocked 语义照旧成立。
 2853                         if no_progress.repair_exhausted(
 2854                             ("blocked_claim_with_derivable_evidence",),
 2855                             allowance=self._limits.max_no_progress_replans,
 2856                             observation_id=model_calls,
 2857                         ):
 2858                             return self._finish_no_progress(
 2859                                 current,
 2860                                 action,
 2861                                 warnings,
 2862                                 message=(
 2863                                     "Provider repeated blocked claims while complete "
 2864                                     "evidence was derivable."
 2865                                 ),
 2866                             )
 2867                         no_progress_since_product_action = True
 2868                         current = self._save(
 2869                             current,
 2870                             append_policy_result(
 2871                                 current.state,
 2872                                 code="completion_evidence_available",
 2873                                 message=(
 2874                                     "The blocked_claim was not accepted: every "
 2875                                     "mandatory criterion already has derivable "
 2876                                     "evidence from durable facts, so a safe action "
 2877                                     "can advance this Goal. Resend completion_claim "
 2878                                     "after reviewing the current authoritative user "
 2879                                     "input and consumed corrections item by item: "
 2880                                     "each requirement_coverage entry must state its "
 2881                                     "requirement, cite its source facts, and bind "
 2882                                     "the current admitted mandatory criteria, and "
 2883                                     "criterion_evidence_refs must be copied "
 2884                                     "exactly, element for element and in order, "
 2885                                     "from the CURRENT trusted_goal block's "
 2886                                     "expected_completion_evidence_refs; do not "
 2887                                     "report this Goal as blocked."
 2888                                 ),
 2889                             ),
 2890                         )
 2891                         continue
 2892                 run_id = active.run_id
 2893                 accepted_control = self._ground_rejected_process_blocker(
 2894                     current.state,
 2895                     control,
 2896                 )
 2897                 try:
 2898                     blocked = accept_blocked_claim(current.state, accepted_control)
 2899                 except ValueError as error:
 2900                     # 016 真实 E3 第 87 轮 J10:correlation 复用等可修复控制输入
 2901                     # 不得升级为 runtime_failure;与 CompletionClaim 同型的有界修复
 2902                     # (§18 先例),额度与 fatal 语义不变。
 2903                     if invalid_repairs >= self._limits.max_invalid_repairs:
 2904                         failed = fail_run(
 2905                             current.state,
 2906                             code="invalid_model_control",
 2907                             message="Provider repeated an invalid control after repair allowance.",
 2908                         )
 2909                         return self._finish(
 2910                             current,
 2911                             action,
 2912                             status=RunStatus.FAILED_FATAL,
 2913                             warnings=warnings,
 2914                             event_kind=RuntimeEventKind.FAILED,
 2915                             error_code="invalid_model_control",
 2916                             outcome_state=failed,
 2917                         )
 2918                     invalid_repairs += 1
 2919                     current = self._save(
 2920                         current,
 2921                         append_policy_result(
 2922                             current.state,
 2923                             code="invalid_model_control",
 2924                             message=(
 2925                                 "Control rejected by current trusted state: "
 2926                                 f"{error}. Use trusted_goal values and a new correlation_id."
 2927                             ),
 2928                         ),
 2929                     )
 2930                     continue
 2931                 return self._finish(
 2932                     current,
 2933                     action,
 2934                     status=RunStatus.COMPLETED,
 2935                     warnings=warnings,
 2936                     event_kind=RuntimeEventKind.COMPLETED,
 2937                     run_id=run_id,
 2938                     message=accepted_control.blocker,
 2939                     outcome_state=blocked,
 2940                 )
 2941             if isinstance(control, CompletionClaim):
 2942                 try:
 2943                     records = self._evidence_registry.derive(
 2944                         current.state,
 2945                         control,
 2946                         observed_at=self._evidence_time_factory(),
 2947                     )
 2948                     stored = {
 2949                         record.evidence_id: record
 2950                         for record in current.state.evidence_records
 2951                     }
 2952                     # 新证据入库，被后续写入失效后重新导出的旧证据按 id 原位
 2953                     # 刷新（R2-C：claim 被拒后继续写入并重新读回是可修复路径，
 2954                     # 不能因陈旧缓存硬失败）。
 2955                     pending_records = tuple(
 2956                         record
 2957                         for record in records
 2958                         if stored.get(record.evidence_id) != record
 2959                     )
 2960                     if pending_records:
 2961                         current = self._save(
 2962                             current,
 2963                             record_evidence(current.state, pending_records),
 2964                         )
 2965                         no_progress.reset()
 2966                     current = self._save(
 2967                         current,
 2968                         record_completion_claim(current.state, control),
 2969                     )
 2970                     current = self._save(
 2971                         current,
 2972                         verify_goal_completion(current.state),
 2973                     )
 2974                 except EvidenceVerificationError as error:
 2975                     if no_progress.repair_exhausted(
 2976                         (
 2977                             "unverified_completion",
 2978                             str(error),
 2979                             canonical_json_digest(list(control.criterion_evidence_refs)),
 2980                         ),
 2981                         allowance=self._limits.max_no_progress_replans,
 2982                         observation_id=model_calls,
 2983                     ):
 2984                         return self._finish_no_progress(
 2985                             current,
 2986                             action,
 2987                             warnings,
 2988                             message=(
 2989                                 "Provider repeated completion claims without adding "
 2990                                 "the required verification evidence."
 2991                             ),
 2992                         )
 2993                     no_progress_since_product_action = True
 2994                     current = self._save(
 2995                         current,
 2996                         append_policy_result(
 2997                             current.state,
 2998                             code="completion_not_verified",
```

## agent/runtime/context.py:1635-1676

```python
 1635     def _pin_groups(
 1636         self,
 1637         groups: tuple[_ContextGroup, ...],
 1638         state: ConversationState,
 1639     ) -> tuple[_ContextGroup, ...]:
 1640         pinned_fact_ids: set[str] = set()
 1641         user_fact_ids = [fact.fact_id for fact in state.facts if fact.kind is FactKind.USER_MESSAGE]
 1642         if user_fact_ids:
 1643             pinned_fact_ids.add(user_fact_ids[-1])
 1644         # R2：Goal 的权威用户原文（初始输入 + 已消费 correction）是完成复核的
 1645         # 必要材料。只固定 Goal 当前 created_from_fact_ids 命中的组——有界于
 1646         # Goal 自身的来源链，不固定无限历史；预算连它们都放不下时保持既有
 1647         # ContextLimitError 的可读失败，不静默裁成"只剩来源 ID"。
 1648         if state.goal is not None:
 1649             pinned_fact_ids.update(state.goal.created_from_fact_ids)
 1650 
 1651         tool_groups = [group for group in groups if group.has_tool_result]
 1652         if tool_groups:
 1653             pinned_fact_ids.update(tool_groups[-1].fact_ids)
 1654 
 1655         pending_call_id: str | None = None
 1656         if state.active_run is not None:
 1657             if state.active_run.pending_request is not None:
 1658                 pending_call_id = state.active_run.pending_request.tool_call_id
 1659             elif state.active_run.executing_intent is not None:
 1660                 pending_call_id = state.active_run.executing_intent.tool_call_id
 1661 
 1662         pinned: list[_ContextGroup] = []
 1663         for group in groups:
 1664             is_pinned = bool(pinned_fact_ids.intersection(group.fact_ids))
 1665             if pending_call_id is not None and pending_call_id in group.tool_call_ids:
 1666                 is_pinned = True
 1667             pinned.append(replace(group, pinned=is_pinned))
 1668         return tuple(pinned)
 1669 
 1670 
 1671 def advertised_browser_controls(state: ConversationState) -> tuple[str, ...]:
 1672     """pending takeover 期间 context 只 advertise complete/cancel 控件。"""
 1673     if state.browser_takeover_pending is None:
 1674         return ()
 1675     return ("/browser-done", "/cancel")
 1676 
```

## agent/runtime/context_control.py:1-330

```python
    1 """上下文层使用的控制 schema 与运行进度投影。"""
    2 
    3 from __future__ import annotations
    4 
    5 import json
    6 
    7 from agent.runtime.contracts import (
    8     RESERVED_CONTROL_NAME,
    9     ConversationState,
   10     FactKind,
   11     JSONValue,
   12 )
   13 
   14 # kind 闭集只含模型→内核方向的控制变体；control_receipt 是内核→模型的回放，
   15 # 不进入 incoming enum，模型无法伪造已受理回执。
   16 _CONTROL_KINDS = (
   17     "direct_response",
   18     "begin_answer",
   19     "clarification_request",
   20     "goal_proposal",
   21     "goal_progress",
   22     "goal_delta_proposal",
   23     "completion_claim",
   24     "blocked_claim",
   25 )
   26 
   27 
   28 def goal_correction_pending(state: ConversationState) -> bool:
   29     """当前 Goal 是否还有一条尚未进入 authority source 的用户纠正。"""
   30 
   31     goal = state.goal
   32     if goal is None:
   33         return False
   34     return any(
   35         fact.kind is FactKind.USER_MESSAGE
   36         and fact.content.get("control") == "goal_correction"
   37         and fact.fact_id not in goal.created_from_fact_ids
   38         for fact in state.facts
   39     )
   40 
   41 
   42 def goal_progress_available(state: ConversationState) -> bool:
   43     goal = state.goal
   44     active = state.active_run
   45     run_prefix = f"run:{active.run_id}:" if active is not None else None
   46     return (
   47         goal is not None
   48         and goal.progress_summary is None
   49         and any(
   50             fact.kind is FactKind.TOOL_RESULT
   51             and (run_prefix is None or fact.fact_id.startswith(run_prefix))
   52             and fact.content.get("executed") is True
   53             and fact.content.get("is_error") is False
   54             for fact in state.facts
   55         )
   56     )
   57 
   58 
   59 def web_fetch_source_refs(state: ConversationState) -> tuple[str, ...]:
   60     active = state.active_run
   61     if active is None:
   62         return ()
   63     run_prefix = f"run:{active.run_id}:"
   64     call_name_by_id: dict[str, str] = {}
   65     offered_refs: list[str] = []
   66     fetch_ref_by_call_id: dict[str, str] = {}
   67     result_call_ids: set[str] = set()
   68     unknown_call_ids: set[str] = set()
   69     for fact in state.facts:
   70         if not fact.fact_id.startswith(run_prefix):
   71             continue
   72         if fact.kind is FactKind.TOOL_CALLS:
   73             raw_calls = fact.content.get("calls")
   74             if not isinstance(raw_calls, list):
   75                 continue
   76             for raw_call in raw_calls:
   77                 if not isinstance(raw_call, dict):
   78                     continue
   79                 call_id = raw_call.get("tool_call_id")
   80                 name = raw_call.get("name")
   81                 arguments = raw_call.get("arguments")
   82                 if isinstance(call_id, str) and isinstance(name, str):
   83                     call_name_by_id[call_id] = name
   84                 if name == "web_fetch" and isinstance(arguments, dict):
   85                     source_ref = arguments.get("source_ref")
   86                     if isinstance(call_id, str) and isinstance(source_ref, str):
   87                         fetch_ref_by_call_id[call_id] = source_ref
   88             continue
   89         if fact.kind is not FactKind.TOOL_RESULT:
   90             continue
   91         call_id = fact.content.get("tool_call_id")
   92         metadata = fact.content.get("metadata")
   93         if isinstance(call_id, str):
   94             result_call_ids.add(call_id)
   95         if (
   96             isinstance(call_id, str)
   97             and isinstance(metadata, dict)
   98             and (
   99                 metadata.get("code") == "observation_unknown"
  100                 or metadata.get("observation_outcome") == "observation_unknown"
  101             )
  102         ):
  103             unknown_call_ids.add(call_id)
  104         if (
  105             fact.content.get("executed") is not True
  106             or fact.content.get("is_error") is not False
  107         ):
  108             continue
  109         if not isinstance(call_id, str) or call_name_by_id.get(call_id) != "web_search":
  110             continue
  111         raw_refs = metadata.get("source_refs") if isinstance(metadata, dict) else None
  112         if not isinstance(raw_refs, list):
  113             continue
  114         for item in raw_refs:
  115             source_ref = item.get("source_ref") if isinstance(item, dict) else None
  116             if isinstance(source_ref, str) and source_ref not in offered_refs:
  117                 offered_refs.append(source_ref)
  118     attempted_refs = {
  119         source_ref
  120         for call_id, source_ref in fetch_ref_by_call_id.items()
  121         if call_id in result_call_ids and call_id not in unknown_call_ids
  122     }
  123     return tuple(source_ref for source_ref in offered_refs if source_ref not in attempted_refs)
  124 
  125 
  126 def web_fetch_available(state: ConversationState) -> bool:
  127     return state.active_run is None or bool(web_fetch_source_refs(state))
  128 
  129 
  130 def reserved_control_schema(
  131     *,
  132     goal_present: bool = False,
  133     goal_id: str | None = None,
  134     goal_revision: int | None = None,
  135     expected_completion_evidence_refs: tuple[str, ...] | None = None,
  136     answer_mode_active: bool = False,
  137     begin_answer_is_available: bool = False,
  138     goal_progress_is_available: bool = False,
  139     goal_proposal_is_available: bool = True,
  140     goal_correction_is_pending: bool = False,
  141     explicit_non_prose_outcome: bool = False,
  142     strict: bool = False,
  143 ) -> dict[str, JSONValue]:
  144     # 真实模型必须能从 wire schema 独立构造完整控制消息；只暴露 kind/correlation_id
  145     # 会让 mock parser Green、真实 Provider 却稳定产出 malformed control。
  146     # 每次 build 构造独立副本，避免跨 ContextPack 共享可变嵌套结构。
  147     # 只使用 DeepSeek/OpenAI-compatible 普遍接受的基础 JSON Schema 子集。
  148     # non-empty/array cardinality 等安全不变量由下游 immutable contracts 严格校验。
  149     string = {"type": "string"}
  150     string_array = {"type": "array", "items": string}
  151     trusted_goal_id = (
  152         {**string, "enum": [goal_id]}
  153         if goal_present and goal_id is not None
  154         else string
  155     )
  156     trusted_goal_revision = (
  157         {"type": "integer", "enum": [goal_revision]}
  158         if goal_present and goal_revision is not None
  159         else {"type": "integer", "minimum": 1}
  160     )
  161     trusted_completion_refs = (
  162         {
  163             **string_array,
  164             "enum": [list(expected_completion_evidence_refs)],
  165         }
  166         if goal_present and expected_completion_evidence_refs is not None
  167         else string_array
  168     )
  169     proposed_criterion = {
  170         "type": "object",
  171         "properties": {
  172             "criterion_id": string,
  173             "description": string,
  174             "oracle_kind": {
  175                 "type": "string",
  176                 "enum": [
  177                     "filesystem_digest",
  178                     "tool_receipt",
  179                     "user_confirmation",
  180                     "research_provenance",
  181                     "web_source_receipt",
  182                 ],
  183                 "description": (
  184                     "Evidence oracle: public/current Web needs web_source_receipt; explicit "
  185                     "run/test/build/validate/check needs tool_receipt."
  186                 ),
  187             },
  188             "artifact_path": {
  189                 **string,
  190                 "description": (
  191                     "filesystem_digest: exact relative target, or one empty value until "
  192                     "the first approved write binds it. Other oracles: empty string."
  193                 ),
  194             },
  195         },
  196         "required": ["criterion_id", "description", "oracle_kind", "artifact_path"],
  197         "additionalProperties": False,
  198     }
  199     goal_draft_fields = {
  200         "user_outcome": string,
  201         "beneficiary": string,
  202         "targets": {**string_array, "description": "Must contain at least one target."},
  203         "scope": {**string_array, "description": "Must contain at least one scope item."},
  204         "non_goals": string_array,
  205         "assumptions": string_array,
  206         "proposed_criteria": {
  207             "type": "array",
  208             "items": proposed_criterion,
  209             "description": "Must contain at least one proposed criterion.",
  210         },
  211         "requires_public_web": {
  212             "type": "boolean",
  213             "description": (
  214                 "True for an explicit public/current Web outcome; requires Web evidence."
  215             ),
  216         },
  217         "requires_local_process": {
  218             "type": "boolean",
  219             "description": (
  220                 "True for an explicit run/test/build/validate/check command outcome; "
  221                 "requires a successful local_process receipt, not file output alone."
  222             ),
  223         },
  224     }
  225 
  226     goal_delta = {
  227         "type": "object",
  228         "properties": {
  229             "goal_id": trusted_goal_id,
  230             "expected_revision": trusted_goal_revision,
  231             "reason": string,
  232             "updates": {
  233                 "type": "object",
  234                 "properties": {
  235                     "user_outcome": string,
  236                     "beneficiary": string,
  237                     "targets": {
  238                         **string_array,
  239                         "description": "When present, must contain at least one target.",
  240                     },
  241                     "scope": {
  242                         **string_array,
  243                         "description": "When present, must contain at least one scope item.",
  244                     },
  245                     "non_goals": string_array,
  246                     "assumptions": string_array,
  247                     "proposed_criteria": {
  248                         "type": "array",
  249                         "items": proposed_criterion,
  250                         "description": "When present, must contain at least one criterion.",
  251                     },
  252                 },
  253                 "additionalProperties": False,
  254             },
  255             "updated_at": {"type": "string"},
  256         },
  257         "required": ["goal_id", "expected_revision", "reason", "updates", "updated_at"],
  258         "additionalProperties": False,
  259     }
  260     if goal_correction_is_pending:
  261         allowed_kinds = ("goal_delta_proposal",)
  262     else:
  263         allowed_kinds = tuple(
  264             kind
  265             for kind in _CONTROL_KINDS
  266             if (
  267                 (
  268                     not goal_present
  269                     and (
  270                         kind == "clarification_request"
  271                         or (kind == "direct_response" and not explicit_non_prose_outcome)
  272                         or (
  273                             kind == "begin_answer"
  274                             and begin_answer_is_available
  275                             and not answer_mode_active
  276                             and not explicit_non_prose_outcome
  277                         )
  278                         or (kind == "goal_proposal" and goal_proposal_is_available)
  279                     )
  280                 )
  281                 or (
  282                     goal_present
  283                     and kind not in {"goal_proposal", "direct_response", "begin_answer"}
  284                     and kind != "goal_delta_proposal"
  285                     and (kind != "goal_progress" or goal_progress_is_available)
  286                 )
  287             )
  288         )
  289     if goal_correction_is_pending:
  290         # 真实模型曾以三种方式弄错 delta wire(缺 updated_at、摊平嵌套、复用
  291         # correlation_id);closed 解码不动摇,用精确示例让模型一次构造正确。
  292         # 第 59/68 轮 J11 实测:示例若只示范 targets-only delta,带 filesystem
  293         # criterion 的 Goal 照抄必败于原子对齐校验,示例必须示范原子形状。
  294         lifecycle_description = (
  295             " A user correction is pending. Return goal_delta_proposal before any product "
  296             "tool; no product tool or other control kind is currently authorized. "
  297             "Exact payload shape: "
  298             '{"kind":"goal_delta_proposal","correlation_id":"<id you have not used '
  299             'before>","delta":{"goal_id":"<trusted_goal.goal_id>","expected_revision":'
  300             '<trusted_goal.revision>,"reason":"<the user\'s change>",'
  301             '"updates":{"targets":["<new target>"],"proposed_criteria":'
  302             '[{"criterion_id":"<existing criterion_id>","description":"<same description>",'
  303             '"oracle_kind":"filesystem_digest","artifact_path":"<new target>"}]},'
  304             '"updated_at":null}} — '
  305             "nest the five delta fields inside \"delta\" (never at the top level), "
  306             "include \"updated_at\" (null is fine), and use a correlation_id you have not "
  307             "used before. When targets change, copy every filesystem criterion from "
  308             "trusted_goal.proposed_criteria into updates.proposed_criteria with its "
  309             "artifact_path set to the new target; omit proposed_criteria when the goal has "
  310             "no filesystem criteria (satisfied web criteria carry over automatically)."
  311         )
  312     elif goal_present:
  313         progress_lifecycle = (
  314             "goal_progress is currently available once because a successful product tool "
  315             "result exists; it records material progress already achieved, is not a planning "
  316             "loop, and must not repeat an intended next step. Keep summary concise but "
  317             "restart-ready: name completed work, relevant changed/read files, the latest "
  318             "valid check, and any failed approach that must not be repeated. Put unfinished "
  319             "work only in next_step, including the next check or cleanup when applicable. "
  320             "This record is advisory and never grants authority. Exact goal_progress payload "
  321             "shape: "
  322             + json.dumps(
  323                 {
  324                     "kind": "goal_progress",
  325                     "correlation_id": "<id you have not used before>",
  326                     "goal_id": goal_id,
  327                     "goal_revision": goal_revision,
  328                     "summary": "<material progress already achieved>",
  329                     "next_step": "<next concrete action>",
  330                 },
```

## agent/runtime/contracts.py:677-749

```python
  677     """R2：completion claim 对当前权威用户要求的逐项覆盖复核（模型语义映射）。
  678 
  679     Runtime 只校验结构与版本/来源/证据绑定，不做自然语言解析；requirement
  680     文本由模型给出，其正确性由独立业务验收揭露。
  681     """
  682 
  683     requirement_id: str
  684     requirement: str
  685     source_fact_ids: tuple[str, ...]
  686     status: str
  687     criterion_ids: tuple[str, ...] = ()
  688 
  689     def __post_init__(self) -> None:
  690         if not self.requirement_id or not self.requirement.strip():
  691             raise ValueError("requirement coverage identity must not be empty")
  692         if self.status not in {"satisfied", "pending"}:
  693             raise ValueError("requirement coverage status must be satisfied or pending")
  694         if not self.source_fact_ids or any(not item for item in self.source_fact_ids):
  695             raise ValueError("requirement coverage must cite at least one source fact")
  696         if self.status == "satisfied" and not self.criterion_ids:
  697             raise ValueError(
  698                 "satisfied requirement coverage must bind admitted criterion ids"
  699             )
  700         if self.status == "pending" and self.criterion_ids:
  701             raise ValueError(
  702                 "pending requirement coverage must not bind criterion ids"
  703             )
  704         if any(not item for item in self.criterion_ids):
  705             raise ValueError("requirement coverage criterion ids must not be empty")
  706         object.__setattr__(self, "source_fact_ids", tuple(self.source_fact_ids))
  707         object.__setattr__(self, "criterion_ids", tuple(self.criterion_ids))
  708 
  709 
  710 @dataclass(frozen=True, slots=True)
  711 class CompletionClaim:
  712     correlation_id: str
  713     goal_id: str
  714     goal_revision: int
  715     criterion_evidence_refs: tuple[str, ...]
  716     requirement_coverage: tuple[RequirementCoverage, ...] = ()
  717 
  718     def __post_init__(self) -> None:
  719         if not self.correlation_id or not self.goal_id:
  720             raise ValueError("completion claim identity must not be empty")
  721         if self.goal_revision < 1:
  722             raise ValueError("completion claim goal_revision must be positive")
  723         if any(not item for item in self.criterion_evidence_refs):
  724             raise ValueError("completion claim evidence refs must not be empty strings")
  725         if len(set(self.criterion_evidence_refs)) != len(self.criterion_evidence_refs):
  726             raise ValueError("completion claim evidence refs must be unique")
  727         if any(
  728             not isinstance(item, RequirementCoverage)
  729             for item in self.requirement_coverage
  730         ):
  731             raise TypeError(
  732                 "completion claim requirement_coverage must contain RequirementCoverage"
  733             )
  734         coverage_ids = [item.requirement_id for item in self.requirement_coverage]
  735         if len(set(coverage_ids)) != len(coverage_ids):
  736             raise ValueError("requirement coverage ids must be unique")
  737         object.__setattr__(
  738             self,
  739             "criterion_evidence_refs",
  740             tuple(self.criterion_evidence_refs),
  741         )
  742         object.__setattr__(
  743             self,
  744             "requirement_coverage",
  745             tuple(self.requirement_coverage),
  746         )
  747 
  748 
  749 @dataclass(frozen=True, slots=True)
```

## agent/runtime/contracts.py:1571-1616

```python
 1571 class GoalDraftProposal:
 1572     """模型只提出 Goal 语义；身份、权威、状态与时间由 Runtime 铸造。"""
 1573 
 1574     correlation_id: str
 1575     user_outcome: str
 1576     beneficiary: str
 1577     targets: tuple[str, ...]
 1578     scope: tuple[str, ...]
 1579     non_goals: tuple[str, ...]
 1580     assumptions: tuple[str, ...]
 1581     proposed_criteria: tuple[ProposedCriterion, ...]
 1582     next_step: str | None = None
 1583     # 模型只做语义提案；只有 authoritative user fact 明确要求时，Runtime 才会
 1584     # 铸造 closed Web receipt criterion。
 1585     requires_public_web: bool = False
 1586     # authoritative user fact 明确要求 run/test/build/validate 时，Runtime
 1587     # 铸造不可被文件证据替代的 process receipt 义务。
 1588     requires_local_process: bool = False
 1589 
 1590     def __post_init__(self) -> None:
 1591         _require_control_identity(self.correlation_id)
 1592         if not self.user_outcome.strip() or not self.beneficiary.strip():
 1593             raise ValueError("goal draft outcome and beneficiary must not be empty")
 1594         if not self.targets or any(not item for item in self.targets):
 1595             raise ValueError("goal draft targets must not be empty")
 1596         if not self.scope or any(not item for item in self.scope):
 1597             raise ValueError("goal draft scope must not be empty")
 1598         if not self.proposed_criteria or any(
 1599             not isinstance(item, ProposedCriterion) for item in self.proposed_criteria
 1600         ):
 1601             raise ValueError("goal draft criteria must contain ProposedCriterion values")
 1602         if self.next_step is not None and (
 1603             not isinstance(self.next_step, str) or not self.next_step.strip()
 1604         ):
 1605             raise ValueError("goal draft next step must not be empty")
 1606         if not isinstance(self.requires_public_web, bool):
 1607             raise TypeError("goal draft public Web requirement must be boolean")
 1608         if not isinstance(self.requires_local_process, bool):
 1609             raise TypeError("goal draft local process requirement must be boolean")
 1610         object.__setattr__(self, "targets", tuple(self.targets))
 1611         object.__setattr__(self, "scope", tuple(self.scope))
 1612         object.__setattr__(self, "non_goals", tuple(self.non_goals))
 1613         object.__setattr__(self, "assumptions", tuple(self.assumptions))
 1614         object.__setattr__(self, "proposed_criteria", tuple(self.proposed_criteria))
 1615 
 1616 
```

## agent/runtime/views.py:173-224

```python
  173     return lease.readable_command
  174 
  175 
  176 def project_goal_authorization_scopes(
  177     state: ConversationState,
  178 ) -> tuple[str | None, str | None]:
  179     """R4：当前 pending 文件审批的 (精确文件 scope, 目录 scope) 纯投影。
  180 
  181     与 Runtime 铸授权共用 agent.runtime.state 的同一 scope 判定，None 表示
  182     对应无参数短命令不适用；不得触发 Runtime、Provider、Tool 或持久化。
  183     """
  184 
  185     from agent.runtime.state import _goal_target_authorization_scope
  186 
  187     active = state.active_run
  188     if (
  189         active is None
  190         or active.status is not ActiveRunStatus.AWAITING_APPROVAL
  191         or not isinstance(active.pending_request, ApprovalRequest)
  192         or not active.tool_calls
  193         or active.batch_cursor >= len(active.tool_calls)
  194     ):
  195         return (None, None)
  196     pending = active.pending_request
  197     return (
  198         _goal_target_authorization_scope(state, pending, active, directory=False),
  199         _goal_target_authorization_scope(state, pending, active, directory=True),
  200     )
  201 
  202 
  203 def project_goal_target_reuse_unavailable(state: ConversationState) -> bool:
  204     """目标写入审批的复用透明度纯投影（与 R4 共用同一 scope 判定）。
  205 
  206     spec 驱动 Goal 的 targets 常为散文，write_file/edit_file 不在其中时
  207     复用授权静默不适用（E1-A 实测 0/17）；True 表示"Goal 存在、本次是
  208     目标写入、但没有任何可复用 scope"，审批提示据此如实说明，不改语义。
  209     """
  210 
  211     if state.goal is None:
  212         return False
  213     file_scope, directory_scope = project_goal_authorization_scopes(state)
  214     if file_scope is not None or directory_scope is not None:
  215         return False
  216     active = state.active_run
  217     if (
  218         active is None
  219         or active.status is not ActiveRunStatus.AWAITING_APPROVAL
  220         or not isinstance(active.pending_request, ApprovalRequest)
  221     ):
  222         return False
  223     return active.pending_request.tool_name in {"write_file", "edit_file"}
  224 
```

## tests/acceptance/test_task_trust_completion.py:109-143

```python
  109 def _claim_for(context, correlation: str, *, hollow: bool = False) -> CompletionClaim:
  110     """按 trusted_goal 投影抄写 completion_claim（含逐项 coverage）。
  111 
  112     与真实模型同型：只引用投影下发的闭合 id；coverage 引用当前 Goal 的全部
  113     权威来源 fact 与全部 mandatory criterion。``hollow=True`` 抄写同样的
  114     evidence refs 但不带任何 coverage——用于复现"缺逐项复核就想收尾"的模型
  115     行为，真实完成门必须拒绝它。
  116     """
  117     goal = _context_goal(context)
  118     mandatory_ids = tuple(
  119         item["criterion_id"]
  120         for item in goal["admitted_criteria"]
  121         if item.get("mandatory") is True
  122     )
  123     return CompletionClaim(
  124         correlation_id=correlation,
  125         goal_id=goal["goal_id"],
  126         goal_revision=goal["goal_revision"],
  127         criterion_evidence_refs=tuple(goal["expected_completion_evidence_refs"]),
  128         requirement_coverage=(
  129             ()
  130             if hollow
  131             else (
  132                 RequirementCoverage(
  133                     requirement_id="requirement:task",
  134                     requirement="完成用户当前权威要求（含已消费 correction）",
  135                     source_fact_ids=tuple(goal["source_fact_ids"]),
  136                     status="satisfied",
  137                     criterion_ids=mandatory_ids,
  138                 ),
  139             )
  140         ),
  141     )
  142 
  143 
```

## tests/acceptance/test_task_trust_completion.py:424-440

```python
  424 D04_SERVICE_PATH = "retry_app/service.py"
  425 D04_CLI_PATH = "retry_app/cli.py"
  426 D04_TASK = (
  427     "完成 retry_app 的 bounded retry 行为：瞬态 RuntimeError 失败需要重试，新的"
  428     "公开参数名是 max_retries，命令行适配器 retry_app/cli.py 必须使用同一个值；"
  429     "负数限制无效，一次操作的执行次数上限是 1 + max_retries。同时保留旧的"
  430     " retry_count 关键字与 CLI 选项作为别名；旧名与新名同时提供时必须拒绝这个"
  431     "有歧义的请求。"
  432 )
  433 
  434 # 参考修正实现与 tests/acceptance/test_coding_autonomy_grader.py 的 D04 参考
  435 # 候选同源（本文件冻结独立拷贝）；修订中间版故意缺少 legacy 别名，供"新写入
  436 # 使旧验证失效"旅程使用。
  437 _D04_SERVICE_REFERENCE = (
  438     "from __future__ import annotations\n\n"
  439     "class RetryService:\n"
  440     "    def run(self, operation, *, max_retries=None, retry_count=None):\n"
```

## tests/acceptance/test_task_trust_completion.py:638-911

```python
  638 class _FileTaskSpec:
  639     """双文件业务旅程的冻结形状（D04 与改名同构例共用）。"""
  640 
  641     goal_id: str
  642     outcome: str
  643     targets: tuple[str, ...]
  644     proposed: tuple[ProposedCriterion, ...]
  645     first_path: str
  646     first_content: str
  647     second_path: str
  648     second_content: str
  649     revise_first_content: str | None = None
  650     hollow_claim: bool = False
  651 
  652 
  653 class _FileTaskProvider:
  654     """真实主 loop 的双文件业务旅程 provider。
  655 
  656     阶段序列按 spec 组合：draft → 写第一组件 →（可选修订）→（hollow 旅程：
  657     读回使 service 证据有效 → 空 coverage claim 被拒）→ 写第二组件 → 读回
  658     全部组件（读回必须晚于最后一次写入，晚写会使早读失效）→ 带 coverage 的
  659     显式 claim。写第二组件前断言原始任务文本仍可见（复核输入，R2-B 3.1）。
  660     """
  661 
  662     def __init__(self, spec: _FileTaskSpec, task: str, *, start_stage: str = "draft"):
  663         self.spec = spec
  664         self.task = task
  665         self.calls = 0
  666         self.stage = start_stage
  667         self.task_visible_at_review = False
  668 
  669     def _write(self, call_id: str, path: str, content: str) -> ModelResponse:
  670         return ModelResponse(
  671             (ModelToolCall(call_id, "write_file", {"path": path, "content": content}),)
  672         )
  673 
  674     def _read(self, call_id: str, path: str) -> ModelResponse:
  675         return ModelResponse((ModelToolCall(call_id, "read_file", {"path": path}),))
  676 
  677     def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
  678         self.calls += 1
  679         spec = self.spec
  680         stage = self.stage
  681 
  682         if stage == "draft":
  683             bootstrap = context.goal_bootstrap
  684             assert bootstrap is not None
  685             frame = GoalFrame(
  686                 goal_id=spec.goal_id,
  687                 revision=1,
  688                 created_from_fact_ids=(bootstrap.source_fact_id,),
  689                 workspace_identity_digest=bootstrap.workspace_identity_digest,
  690                 user_outcome=spec.outcome,
  691                 beneficiary="user",
  692                 targets=spec.targets,
  693                 scope=("workspace",),
  694                 non_goals=(),
  695                 assumptions=(),
  696                 proposed_criteria=spec.proposed,
  697                 admitted_criteria=(),
  698                 authority_snapshot=bootstrap.authority_snapshot,
  699                 status=GoalStatus.GOAL_READY,
  700                 created_at="2026-10-14T00:00:00Z",
  701                 updated_at="2026-10-14T00:00:00Z",
  702             )
  703             self.stage = "write-1"
  704             return ModelResponse(
  705                 (), control=goal_draft_from_frame(f"proposal-{spec.goal_id}", frame)
  706             )
  707 
  708         if stage == "write-1":
  709             self.stage = (
  710                 "revise-1"
  711                 if spec.revise_first_content
  712                 else "hollow-read-1"
  713                 if spec.hollow_claim
  714                 else "write-2"
  715             )
  716             return self._write("write-first", spec.first_path, spec.first_content)
  717 
  718         if stage == "revise-1":
  719             assert spec.revise_first_content is not None
  720             self.stage = "hollow-read-1" if spec.hollow_claim else "write-2"
  721             return self._write("revise-first", spec.first_path, spec.revise_first_content)
  722 
  723         if stage == "hollow-read-1":
  724             assert spec.hollow_claim
  725             self.stage = "hollow"
  726             return self._read("read-first", spec.first_path)
  727 
  728         if stage == "hollow":
  729             # 缺逐项复核的 claim：refs 抄自当前投影，coverage 为空。
  730             self.stage = "write-2"
  731             return ModelResponse(
  732                 (), control=_claim_for(context, f"hollow-{spec.goal_id}", hollow=True)
  733             )
  734 
  735         if stage == "write-2":
  736             # 复核发生在主 loop：原始权威任务文本必须仍然可见（R2-B 3.1）。
  737             self.task_visible_at_review = self.task in _context_text(context)
  738             assert self.task_visible_at_review, (
  739                 "the original authoritative task must stay visible for review"
  740             )
  741             self.stage = "reread-1" if spec.hollow_claim else "read-1"
  742             return self._write("write-second", spec.second_path, spec.second_content)
  743 
  744         if stage in {"read-1", "reread-1"}:
  745             # 晚写使早读失效：读回全部放在最后一次写入之后。
  746             self.stage = "read-2"
  747             return self._read(
  748                 "reread-first" if stage == "reread-1" else "read-first", spec.first_path
  749             )
  750 
  751         if stage == "read-2":
  752             self.stage = "claim"
  753             return self._read("read-second", spec.second_path)
  754 
  755         if stage == "claim":
  756             assert self.task in _context_text(context)
  757             return ModelResponse((), control=_claim_for(context, f"claim-{spec.goal_id}"))
  758 
  759         raise AssertionError(f"unexpected stage {self.stage}")
  760 
  761 
  762 def _d04_workspace(tmp_path: Path) -> Path:
  763     workspace = tmp_path / "workspace"
  764     shutil.copytree(D04_FIXTURE, workspace, ignore=shutil.ignore_patterns("__pycache__"))
  765     return workspace
  766 
  767 
  768 _BROAD_D04_SPEC = _FileTaskSpec(
  769     goal_id="d04-broad",
  770     outcome="retry_app implements the requested bounded retry behavior in both files",
  771     targets=(D04_SERVICE_PATH, D04_CLI_PATH),
  772     proposed=(
  773         ProposedCriterion(
  774             "criterion:d04-retry-behavior",
  775             "the requested bounded retry behavior is implemented",
  776             EvidenceOracleKind.FILESYSTEM_DIGEST,
  777             artifact_path=None,
  778         ),
  779     ),
  780     first_path=D04_SERVICE_PATH,
  781     first_content=_D04_SERVICE_REFERENCE,
  782     second_path=D04_CLI_PATH,
  783     second_content=_D04_CLI_REFERENCE,
  784 )
  785 
  786 
  787 def test_d04_broad_draft_completes_both_components_before_done(
  788     tmp_path: Path,
  789 ) -> None:
  790     """R2-C 正例 + 自动早收尾反例（当前树）：宽泛 draft 也必须两件都做完。
  791 
  792     修前（ff686bd 自动收尾）：service 写入/读回使首文件证据闭合即 VERIFIED_DONE，
  793     CLI 组件被截断、永不做。当前树：批次结束后回到模型，CLI 继续执行，完成门
  794     只接受带逐项 coverage 的显式 claim；grader 与补充判据同时通过。
  795     """
  796 
  797     workspace = _d04_workspace(tmp_path)
  798     provider = _FileTaskProvider(_BROAD_D04_SPEC, D04_TASK)
  799     opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())
  800 
  801     state = opened.store.load().state
  802     composition.runtime.run_turn(_submit(state, "run-d04-broad", D04_TASK), opened.store.load())
  803     _approve_pending(opened, composition)
  804 
  805     final = LocalCheckpointStore(opened.checkpoint_path).load().state
  806     goal = final.goal
  807     assert goal is not None
  808     assert goal.status is GoalStatus.VERIFIED_DONE, (
  809         goal.status,
  810         [c.criterion_id for c in goal.admitted_criteria],
  811     )
  812     # CLI 组件确实在完成之前执行：provider 走完全部 6 个阶段。
  813     assert provider.calls == 6, provider.calls
  814     assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
  815         _D04_SERVICE_REFERENCE
  816     )
  817     assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == _D04_CLI_REFERENCE
  818     assert len(goal.admitted_criteria) == 2, [
  819         c.criterion_id for c in goal.admitted_criteria
  820     ]
  821     # 外部业务判据：冻结 grader（过程项恒 False 是诚实声明）+ 独立补充探针。
  822     from scripts.coding_scenario_grader import grade_d04
  823 
  824     checks = grade_d04(workspace)
  825     assert checks["latest_correction"] is True, checks
  826     assert checks["final_validation"] is True, checks
  827     assert checks["resume_without_restatement"] is False
  828     assert checks["no_effect_replay"] is False
  829     supplemental = _supplemental_d04_checks(workspace)
  830     assert supplemental and all(supplemental.values()), supplemental
  831     # coverage 绑定当前全部 mandatory criterion 并引用权威来源。
  832     claim = final.completion_claim
  833     assert claim is not None and claim.requirement_coverage
  834     covered = {
  835         criterion_id
  836         for item in claim.requirement_coverage
  837         for criterion_id in item.criterion_ids
  838     }
  839     assert covered == {c.criterion_id for c in goal.admitted_criteria}
  840 
  841 
  842 def test_d04_omitted_component_requires_review_before_done(tmp_path: Path) -> None:
  843     """R2-C admission 遗漏反例：draft 漏 CLI 时空 coverage claim 不得完成。
  844 
  845     原始双组件要求 → 模型 draft 只提 service criterion → service 写入/读回
  846     证据有效 → 缺逐项复核的 claim 被完成门拒绝（目标未终化）→ 模型回主 loop
  847     复核（原始任务文本可见）→ 补做 CLI（审批时由 Runtime 铸 admitted
  848     criterion，测试不预补）→ 带 coverage claim → VERIFIED_DONE，业务判据全过。
  849     """
  850 
  851     workspace = _d04_workspace(tmp_path)
  852     spec = _FileTaskSpec(
  853         goal_id="d04-omission",
  854         outcome="retry_app implements the requested bounded retry behavior",
  855         targets=(D04_SERVICE_PATH,),
  856         proposed=(
  857             ProposedCriterion(
  858                 "criterion:d04-service",
  859                 "the service implements the requested retry behavior",
  860                 EvidenceOracleKind.FILESYSTEM_DIGEST,
  861                 artifact_path=D04_SERVICE_PATH,
  862             ),
  863         ),
  864         first_path=D04_SERVICE_PATH,
  865         first_content=_D04_SERVICE_REFERENCE,
  866         second_path=D04_CLI_PATH,
  867         second_content=_D04_CLI_REFERENCE,
  868         hollow_claim=True,
  869     )
  870     provider = _FileTaskProvider(spec, D04_TASK)
  871     opened, composition = _open_and_drive(tmp_path, provider, ControlInbox())
  872 
  873     state = opened.store.load().state
  874     composition.runtime.run_turn(_submit(state, "run-d04-omission", D04_TASK), opened.store.load())
  875     _approve_pending(opened, composition)
  876 
  877     final = LocalCheckpointStore(opened.checkpoint_path).load().state
  878     goal = final.goal
  879     assert goal is not None
  880     # 空 coverage claim 被拒的 durable 证据：可修复拒绝的策略结果落盘。
  881     rejection = next(
  882         (
  883             str(fact.content.get("text", ""))
  884             for fact in final.facts
  885             if fact.kind is FactKind.POLICY_RESULT
  886             and fact.content.get("code") == "invalid_model_control"
  887             and "per-requirement coverage" in str(fact.content.get("text", ""))
  888         ),
  889         "",
  890     )
  891     assert rejection, "the hollow claim must be rejected with coverage guidance"
  892     # 复核发生在主 loop：原始任务文本在补做 CLI 前仍然可见。
  893     assert provider.task_visible_at_review
  894     assert provider.calls == 8, provider.calls
  895     assert goal.status is GoalStatus.VERIFIED_DONE, goal.status
  896     assert (workspace / D04_CLI_PATH).read_text(encoding="utf-8") == _D04_CLI_REFERENCE
  897     assert (workspace / D04_SERVICE_PATH).read_text(encoding="utf-8") == (
  898         _D04_SERVICE_REFERENCE
  899     )
  900     assert len(goal.admitted_criteria) == 2, [
  901         c.criterion_id for c in goal.admitted_criteria
  902     ]
  903     from scripts.coding_scenario_grader import grade_d04
  904 
  905     checks = grade_d04(workspace)
  906     assert checks["latest_correction"] is True and checks["final_validation"] is True
  907     supplemental = _supplemental_d04_checks(workspace)
  908     assert supplemental and all(supplemental.values()), supplemental
  909 
  910 
  911 def test_d04_revised_write_invalidates_prior_file_verification(tmp_path: Path) -> None:
```

## tests/kernel/fakes.py:63-111

```python
   63     """显式占位符让 scripted test 引用 Runtime 铸造的 Goal 身份。"""
   64 
   65     trusted = _trusted_goal_projection(context)
   66     identity = runtime_goal_identity(context)
   67     control = response.control
   68     if identity is None or control is None:
   69         return response
   70     goal_id, goal_revision = identity
   71     if (
   72         isinstance(control, (BlockedClaim, CompletionClaim, GoalProgress))
   73         and control.goal_id == RUNTIME_GOAL_ID
   74     ):
   75         # 只绑定 Runtime 铸造的动态身份/引用（goal_id/revision/evidence refs）。
   76         # R2-B：不为缺失 requirement_coverage 自动创造"已满足"语义——缺复核的
   77         # claim 经本 helper 后仍为空，由真实完成门拒绝；确需正例 coverage 的
   78         # scripted fixture 显式用 completion_claim_from_trusted 声明其语义。
   79         evidence_refs = (
   80             trusted.get("expected_completion_evidence_refs")
   81             if isinstance(control, CompletionClaim) and trusted is not None
   82             else None
   83         )
   84         return replace(
   85             response,
   86             control=replace(
   87                 control,
   88                 goal_id=goal_id,
   89                 goal_revision=goal_revision,
   90                 **(
   91                     {"criterion_evidence_refs": tuple(evidence_refs)}
   92                     if isinstance(evidence_refs, list)
   93                     and all(isinstance(item, str) for item in evidence_refs)
   94                     else {}
   95                 ),
   96             ),
   97         )
   98     if (
   99         isinstance(control, GoalDeltaProposal)
  100         and control.delta.goal_id == RUNTIME_GOAL_ID
  101     ):
  102         return replace(
  103             response,
  104             control=replace(
  105                 control,
  106                 delta=replace(
  107                     control.delta,
  108                     goal_id=goal_id,
  109                     expected_revision=goal_revision,
  110                 ),
  111             ),
```

## tests/kernel/fakes.py:174-229

```python
  174 
  175 def completion_claim_from_trusted(
  176     correlation_id: str,
  177     *,
  178     requirement_id: str = "requirement:trusted-goal",
  179     requirement: str = "the current trusted goal is fully satisfied",
  180     text: str | None = None,
  181 ) -> Callable[[ContextPack], ModelResponse]:
  182     """按 trusted_goal 投影抄写 completion_claim（含 R2 requirement_coverage）。
  183 
  184     真实模型只能引用投影下发的闭合 id（source_fact_ids、
  185     expected_completion_evidence_refs）与 admitted criterion id；本 helper 与
  186     ``bind_runtime_goal`` 同型，让 scripted 测试不硬编码动态铸造的
  187     ``action:N:user`` fact id 或随 delta 变化的 criterion revision。可选
  188     ``text`` 附带最终回答文本；coverage 语义由调用方以参数显式声明。
  189     """
  190 
  191     def response(context: ContextPack) -> ModelResponse:
  192         trusted = _trusted_goal_projection(context)
  193         if trusted is None:
  194             raise AssertionError("trusted_goal is required for a completion claim")
  195         source_fact_ids = trusted.get("source_fact_ids")
  196         criterion_ids = tuple(
  197             item.get("criterion_id")
  198             for item in trusted.get("admitted_criteria", ())
  199             if isinstance(item, dict)
  200             and item.get("mandatory") is True
  201             and isinstance(item.get("criterion_id"), str)
  202         )
  203         if not isinstance(source_fact_ids, list) or not source_fact_ids:
  204             raise AssertionError("trusted_goal source_fact_ids are required")
  205         if not criterion_ids:
  206             raise AssertionError("trusted_goal mandatory criteria are required")
  207         return ModelResponse(
  208             (ModelTextBlock(text),) if text is not None else (),
  209             control=CompletionClaim(
  210                 correlation_id=correlation_id,
  211                 goal_id=RUNTIME_GOAL_ID,
  212                 goal_revision=1,
  213                 criterion_evidence_refs=(),
  214                 requirement_coverage=(
  215                     RequirementCoverage(
  216                         requirement_id=requirement_id,
  217                         requirement=requirement,
  218                         source_fact_ids=tuple(source_fact_ids),
  219                         status="satisfied",
  220                         criterion_ids=criterion_ids,
  221                     ),
  222                 ),
  223             ),
  224         )
  225 
  226     return response
  227 
  228 
  229 def conversation_with_active_goal(conversation_id: str = "conversation-1") -> ConversationState:
```

## scripts/run_task_trust_d04.py:1-1079

```python
    1 #!/usr/bin/env python3
    2 """E1-A/E1-B 薄真实旅程 driver（2026-10-14 任务结果可信接续包专用）。
    3 
    4 只做三件事：把冻结输入按治理边界交给真实 CLI、从 durable checkpoint 读
    5 typed 事实、用冻结 grader 与冻结补充探针做最终判定。不提示实现、不选文件、
    6 不解释失败、不按模型文字判 PASS；任何前置条件未满足或中途停住都如实
    7 incomplete（VALIDATION §3 最小真实旅程 / §4 冻结过程）。
    8 
    9 子命令：
   10 
   11 - ``prepare``  —— 物化后的 D04 候选：清 __pycache__；``--staged`` 时把 SPEC.md
   12   从冻结原文程序化派生为 ``D04 staged variant``（保留标题与原始有界重试段落，
   13   切除以 ``During the task`` 开头的未来纠正段落）并写标记文件、记录派生内容与
   14   SHA。拒绝在 SPEC 字节不等于冻结 SHA 时派生。
   15 - ``run``      —— 在**本进程**跑一段 REPL 旅程；模式 normal/inject/resume。
   16 - ``journey``  —— 编排：按模式 spawn ``run`` 子进程（真实新 PID、带样本级墙钟
   17   上限），再跑 grader + 补充探针 + ``evaluate_final`` 判定并落最终 result JSON。
   18 
   19 冻结输入（VALIDATION §4）：
   20 
   21 - 初始 prompt：``完成当前 SPEC.md 的有界重试功能，并运行 pytest -q 验证。``
   22 - correction：见 ``CORRECTION``（保留 retry_count 旧别名、同名歧义拒绝）。
   23 - 注入边界：已有当前 Goal、发生至少一次正常文件效果之后，第一个尚未终结且
   24   接受 correction 的安全治理交互点（approval 提示或空闲提示）；未观察到合法
   25   边界则如实失败，不换任务冒充。
   26 
   27 判定口径（按 VALIDATION §3 冻结）：
   28 
   29 - E1-A（normal）：D04 场景本身含「运行中追加旧参数名」，故 normal 模式同样在
   30   首个安全边界交付冻结 correction；须观测注入与 durable 落盘，消费/版本推进
   31   作为过程证据如实报告（不满足不判失败），不要求 pause→resume。业务门 =
   32   grader 的两个有界键（latest_correction / final_validation）为 true 且补充
   33   探针全部通过。
   34 - E1-B（staged）：在首个安全边界注入冻结 correction，须观测 durable/消费/版本
   35   推进，随后 pause→退出→新 PID resume→继续，并记录注入前别名行为尚未满足的
   36   前置检查。额外要求过程证据（见 ``REQUIRED_EVIDENCE``）。
   37 - ``resume_without_restatement`` / ``no_effect_replay`` 是 F3c 设计内恒 false 的
   38   过程声明，原样报告、不计入失败。
   39 - 版本变化取 goal revision 增长，或（noop 消费路径下）state revision 增长且
   40   correction fact 已绑入 goal.created_from_fact_ids——两条都要求 durable 推进。
   41 - 每样本独立 ledger（≤ manifest 窗口 40 请求），跨阶段累计不清零；样本墙钟
   42   默认 1800s，与 manifest 窗口一致。
   43 """
   44 
   45 from __future__ import annotations
   46 
   47 import argparse
   48 import hashlib
   49 import json
   50 import os
   51 import shutil
   52 import subprocess
   53 import sys
   54 import time
   55 from collections.abc import Callable
   56 from dataclasses import dataclass, field
   57 from pathlib import Path
   58 
   59 # 以文件方式直接运行（python scripts/run_task_trust_d04.py）时，仓库根不在
   60 # sys.path；先引导根目录再做本仓库导入（与 run_real_coding_scenario 同型）。
   61 _ROOT = Path(__file__).resolve().parents[1]
   62 if str(_ROOT) not in sys.path:
   63     sys.path.insert(0, str(_ROOT))
   64 
   65 MANIFEST = (
   66     _ROOT
   67     / "docs"
   68     / "handoffs"
   69     / "2026-09-13-coding-autonomy-repair"
   70     / "TASK-MANIFEST.json"
   71 )
   72 
   73 INITIAL_PROMPT = "完成当前 SPEC.md 的有界重试功能，并运行 pytest -q 验证。"
   74 CORRECTION = (
   75     "补充要求：保留 retry_count 关键字和 --retry-count CLI 选项作为旧别名；"
   76     "新旧名字同时提供时拒绝并报歧义。继续完成任务并运行 pytest -q 验证。"
   77 )
   78 ORIGINAL_SPEC_SHA256 = (
   79     "781ed941341a94acd3c9a39e51d221179cfbe652cbe63bc719eb77573c4e086c"
   80 )
   81 FUTURE_CORRECTION_MARKER = "\nDuring the task"
   82 VARIANT_MARKER = "D04-STAGED-VARIANT.txt"
   83 VARIANT_NOTICE = (
   84     "This workspace carries a D04 staged variant SPEC (derived for this journey;\n"
   85     "not the original fixture bytes).\n"
   86 )
   87 
   88 TERMINAL_GOAL_STATUSES = frozenset({"verified_done", "cancelled"})
   89 FILE_EFFECT_TOOLS = frozenset({"write_file", "edit_file", "make_directory"})
   90 CONTINUABLE_IDLE_STATUSES = frozenset({"needs_authority", "blocked", "goal_ready"})
   91 CONTINUE_MESSAGE = "继续当前任务"
   92 MAX_REQUESTS_PER_SAMPLE = 40
   93 BOUND_BUSINESS_KEYS = ("latest_correction", "final_validation")
   94 PROCESS_DECLARED_KEYS = ("resume_without_restatement", "no_effect_replay")
   95 REQUIRED_EVIDENCE = {
   96     "normal": ("correction_injected",),
   97     "staged": (
   98         "correction_injected",
   99         "correction_durable",
  100         "correction_consumed",
  101         "version_changed",
  102         "paused_after_consumption",
  103         "resumed_in_new_process",
  104         "resume_advanced",
  105         "precondition_alias_checks_pending",
  106     ),
  107 }
  108 
  109 ProbeFn = Callable[[Path], "dict[str, bool]"]
  110 
  111 
  112 # ---------------------------------------------------------------------------
  113 # durable 只读观察
  114 # ---------------------------------------------------------------------------
  115 
  116 
  117 def observe(candidate: Path, state_root: Path) -> dict | None:
  118     """只读加载本次合成会话的 durable 投影；零创建、零 mutation。"""
  119 
  120     from agent.continuity.sessions import inspect_workspace_sessions
  121     from agent.runtime.contracts import FactKind
  122 
  123     inspection = inspect_workspace_sessions(candidate, state_root=state_root, home=None)
  124     snapshots = tuple(inspection.snapshots)
  125     if not snapshots:
  126         return None
  127     if len(snapshots) != 1:
  128         raise ValueError(
  129             f"expected exactly one synthesized session, found {len(snapshots)}"
  130         )
  131     state = snapshots[0].state
  132     active = state.active_run
  133     status = active.status.value if active is not None else None
  134     pending = {
  135         "awaiting_approval": "approval",
  136         "awaiting_disclosure": "disclosure",
  137         "awaiting_recovery": "recovery",
  138         "paused_limit": "limit",
  139         "paused_retryable": "retryable",
  140     }.get(status or "")
  141     effects: dict[str, int] = {}
  142     correction_ids: list[str] = []
  143     for fact in state.facts:
  144         if (
  145             fact.kind is FactKind.USER_MESSAGE
  146             and fact.content.get("control") == "goal_correction"
  147         ):
  148             correction_ids.append(fact.fact_id)
  149             continue
  150         if (
  151             fact.kind is FactKind.TOOL_RESULT
  152             and fact.content.get("executed") is True
  153             and fact.content.get("is_error") is False
  154         ):
  155             metadata = fact.content.get("metadata")
  156             tool_name = metadata.get("tool_name") if isinstance(metadata, dict) else None
  157             if tool_name in FILE_EFFECT_TOOLS:
  158                 effects[str(tool_name)] = effects.get(str(tool_name), 0) + 1
  159     goal = state.goal
  160     return {
  161         "goal_status": goal.status.value if goal is not None else None,
  162         "goal_id": goal.goal_id if goal is not None else None,
  163         "goal_revision": goal.revision if goal is not None else None,
  164         "user_outcome": goal.user_outcome if goal is not None else None,
  165         "created_from_fact_ids": (
  166             list(goal.created_from_fact_ids) if goal is not None else []
  167         ),
  168         "proposed_criteria": (
  169             [item.criterion_id for item in goal.proposed_criteria]
  170             if goal is not None
  171             else []
  172         ),
  173         "admitted_criteria": (
  174             [item.criterion_id for item in goal.admitted_criteria]
  175             if goal is not None
  176             else []
  177         ),
  178         "active_run_status": status,
  179         "pending": pending,
  180         "executed_file_effects": sum(effects.values()),
  181         "effect_tools": effects,
  182         "correction_fact_ids": correction_ids,
  183         "state_revision": state.revision,
  184     }
  185 
  186 
  187 def _ledger_lines(path: Path) -> int:
  188     if not path.exists():
  189         return 0
  190     return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
  191 
  192 
  193 def _ensure_private_dir(path: Path) -> None:
  194     """owner-only(0700) 目录：transport ledger 的父目录必须是该模式。"""
  195 
  196     path.mkdir(mode=0o700, parents=True, exist_ok=True)
  197     os.chmod(path, 0o700)
  198 
  199 
  200 def _frozen_probe(candidate: Path) -> dict[str, bool]:
  201     """执行冻结在测试模块里的独立补充业务探针（与产品/grader 隔离）。"""
  202 
  203     import importlib.util
  204 
  205     path = _ROOT / "tests" / "acceptance" / "test_task_trust_completion.py"
  206     spec = importlib.util.spec_from_file_location("_frozen_task_trust_probe", path)
  207     if spec is None or spec.loader is None:
  208         raise RuntimeError(f"frozen probe module is unreadable: {path}")
  209     module = importlib.util.module_from_spec(spec)
  210     # dataclasses 在 Python 3.12 处理字符串注解时会读取 sys.modules[cls.__module__]，
  211     # 未注册的临时模块名会在这里变成 None 并抛 AttributeError——先注册再执行。
  212     sys.modules[spec.name] = module
  213     try:
  214         spec.loader.exec_module(module)
  215         return module._supplemental_d04_checks(candidate)  # noqa: SLF001
  216     finally:
  217         sys.modules.pop(spec.name, None)
  218 
  219 
  220 # ---------------------------------------------------------------------------
  221 # 旅程 operator：只交付冻结输入、只按 durable 事实决策
  222 # ---------------------------------------------------------------------------
  223 
  224 
  225 @dataclass
  226 class JourneyOperator:
  227     mode: str  # normal | inject | resume
  228     candidate: Path | None = None
  229     probe: ProbeFn | None = None
  230     max_consents: int = 40
  231     max_resumes: int = 2
  232     max_continues: int = 3
  233     task: str = INITIAL_PROMPT
  234     correction: str = CORRECTION
  235     task_sent: bool = False
  236     consent_decisions: int = 0
  237     resumes: int = 0
  238     continue_decisions: int = 0
  239     injected: bool = False
  240     injection_point: str | None = None
  241     injected_fact_id: str | None = None
  242     pre_injection: dict | None = None
  243     consumption: dict | None = None
  244     pause_sent: bool = False
  245     resume_sent: bool = False
  246     start_observation: dict | None = None
  247     last_observation: dict | None = None
  248     stop_reason: str | None = None
  249     events: list[dict] = field(default_factory=list)
  250 
  251     def next_input(self, obs: dict | None) -> str:
  252         if self.mode == "resume":
  253             return self._next_resume(obs)
  254         return self._next_standard(obs)
  255 
  256     # -- normal / inject：任务 + 治理 + 首个安全边界注入 --------------------
  257 
  258     def _next_standard(self, obs: dict | None) -> str:
  259         if not self.task_sent:
  260             self.task_sent = True
  261             self._event("send_task", obs)
  262             return self.task
  263         if obs is None:
  264             return self._stop(obs, "durable_state_unavailable")
  265         if self.start_observation is None:
  266             self.start_observation = obs
  267         self.last_observation = obs
  268         if self.injected and self.injected_fact_id is None and obs["correction_fact_ids"]:
  269             self.injected_fact_id = obs["correction_fact_ids"][-1]
  270         if self.injected:
  271             # 幂等记录 durable 消费投影（含终态轮：先记录再判终态）。
  272             self._consumed(obs)
  273 
  274         status = obs["goal_status"]
  275         pending = obs["pending"]
  276         active = obs["active_run_status"]
  277 
  278         # typed 终态优先：完成后不存在合法 pause/注入，文字不能覆盖事实。
  279         if status in TERMINAL_GOAL_STATUSES:
  280             return self._stop(
  281                 obs, "verified_done" if status == "verified_done" else "goal_cancelled"
  282             )
  283 
  284         if self.mode == "inject" and self.injected and not self.pause_sent:
  285             if self.consumption is not None:
  286                 self.pause_sent = True
  287                 self._event("pause", obs)
  288                 return "/pause"
  289             if pending == "recovery":
  290                 return self._stop(obs, "unknown_effect_requires_operator_classification")
  291             if pending in {"disclosure", "approval"}:
  292                 return self._consent(obs)
  293             if pending in {"limit", "retryable"}:
  294                 return self._resume(obs)
  295             if active is None:
  296                 # 未消费 correction 前不再追加消息（避免叠出第二条 correction）；
  297                 # 模型整轮未消费即如实停。
  298                 return self._stop(obs, "correction_not_consumed_before_idle")
  299             return self._stop(obs, "unexpected_active_run_without_pending")
  300 
  301         if self.mode == "inject" and self.pause_sent:
  302             if status == "paused" and active is None:
  303                 return self._stop(obs, "paused_for_resume")
  304             return self._stop(obs, "pause_not_effective")
  305 
  306         if pending == "disclosure":
  307             return self._consent(obs)
  308         if pending == "approval":
  309             if self._should_inject(obs):
  310                 return self._inject(obs, "approval")
  311             return self._consent(obs)
  312         if pending == "recovery":
  313             return self._stop(obs, "unknown_effect_requires_operator_classification")
  314         if pending in {"limit", "retryable"}:
  315             return self._resume(obs)
  316         if self._should_inject(obs):
  317             return self._inject(obs, "idle")
  318         if active is None and status in {"paused", "blocked"}:
  319             return self._resume(obs)
  320         if active is None and status in CONTINUABLE_IDLE_STATUSES:
  321             return self._continue(obs)
  322         return self._stop(obs, "unexpected_idle_before_verified_done")
  323 
  324     # -- resume 阶段（新进程）：只恢复与继续，绝不重述业务 -------------------
  325 
  326     def _next_resume(self, obs: dict | None) -> str:
  327         if obs is None:
  328             return self._stop(obs, "durable_state_unavailable")
  329         if self.start_observation is None:
  330             self.start_observation = obs
  331         self.last_observation = obs
  332         status = obs["goal_status"]
  333         pending = obs["pending"]
  334         active = obs["active_run_status"]
  335         if status in TERMINAL_GOAL_STATUSES:
  336             return self._stop(
  337                 obs, "verified_done" if status == "verified_done" else "goal_cancelled"
  338             )
  339         if not self.resume_sent:
  340             if status in {"paused", "blocked"} and active is None:
  341                 self.resume_sent = True
  342                 self._event("resume", obs)
  343                 return "/resume"
  344             return self._stop(obs, "resume_expected_paused_goal")
  345         if pending == "disclosure":
  346             return self._consent(obs)
  347         if pending == "approval":
  348             return self._consent(obs)
  349         if pending == "recovery":
  350             return self._stop(obs, "unknown_effect_requires_operator_classification")
  351         if pending in {"limit", "retryable"}:
  352             return self._resume(obs)
  353         if active is None and status in {"paused", "blocked"}:
  354             return self._resume(obs)
  355         if active is None and status in CONTINUABLE_IDLE_STATUSES:
  356             return self._continue(obs)
  357         return self._stop(obs, "unexpected_idle_before_verified_done")
  358 
  359     # -- 内部决策 ----------------------------------------------------------
  360 
  361     def _should_inject(self, obs: dict) -> bool:
  362         return (
  363             self.mode in {"normal", "inject"}
  364             and not self.injected
  365             and obs["goal_status"] is not None
  366             and obs["goal_status"] not in TERMINAL_GOAL_STATUSES
  367             and obs["executed_file_effects"] >= 1
  368         )
  369 
  370     def _inject(self, obs: dict, point: str) -> str:
  371         self.injected = True
  372         self.injection_point = point
  373         self.pre_injection = dict(obs)
  374         if self.probe is not None and self.candidate is not None:
  375             try:
  376                 self.pre_injection["alias_checks"] = self.probe(self.candidate)
  377             except Exception as error:  # noqa: BLE001 - 探针失败必须如实记录
  378                 self.pre_injection["alias_checks"] = {"probe_error": str(error)}
  379         self._event("inject_correction", obs)
  380         return self.correction
  381 
  382     def _consumed(self, obs: dict) -> bool:
  383         fact_id = self.injected_fact_id
  384         if fact_id is None or fact_id not in obs["created_from_fact_ids"]:
  385             return False
  386         if self.consumption is None:
  387             before = self.pre_injection or {}
  388             goal_before = before.get("goal_revision")
  389             state_before = before.get("state_revision")
  390             goal_after = obs["goal_revision"]
  391             state_after = obs["state_revision"]
  392             self.consumption = {
  393                 "fact_id": fact_id,
  394                 "goal_revision_before": goal_before,
  395                 "goal_revision_after": goal_after,
  396                 "state_revision_before": state_before,
  397                 "state_revision_after": state_after,
  398                 "goal_version_changed": bool(
  399                     goal_after is not None
  400                     and goal_before is not None
  401                     and goal_after > goal_before
  402                 ),
  403                 "state_version_changed": bool(
  404                     state_after is not None
  405                     and state_before is not None
  406                     and state_after > state_before
  407                 ),
  408                 "created_from_fact_ids": list(obs["created_from_fact_ids"]),
  409                 "user_outcome": obs["user_outcome"],
  410             }
  411         return True
  412 
  413     def _consent(self, obs: dict) -> str:
  414         if self.consent_decisions >= self.max_consents:
  415             return self._stop(obs, "consent_budget_exhausted")
  416         self.consent_decisions += 1
  417         self._event("consent", obs)
  418         return "y"
  419 
  420     def _resume(self, obs: dict) -> str:
  421         if self.resumes >= self.max_resumes:
  422             return self._stop(obs, "resume_budget_exhausted")
  423         self.resumes += 1
  424         self._event("resume", obs)
  425         return "/resume"
  426 
  427     def _continue(self, obs: dict) -> str:
  428         if self.continue_decisions >= self.max_continues:
  429             return self._stop(obs, "continue_budget_exhausted")
  430         self.continue_decisions += 1
  431         self._event("continue", obs)
  432         return CONTINUE_MESSAGE
  433 
  434     def _stop(self, obs: dict | None, reason: str) -> str:
  435         self.stop_reason = reason
  436         self._event("exit", obs)
  437         return "/exit"
  438 
  439     def _event(self, kind: str, obs: dict | None) -> None:
  440         self.events.append(
  441             {
  442                 "kind": kind,
  443                 "goal_status": obs["goal_status"] if obs else None,
  444                 "goal_revision": obs["goal_revision"] if obs else None,
  445                 "pending": obs["pending"] if obs else None,
  446                 "active_run_status": obs["active_run_status"] if obs else None,
  447                 "executed_file_effects": obs["executed_file_effects"] if obs else None,
  448             }
  449         )
  450 
  451 
  452 # ---------------------------------------------------------------------------
  453 # 判定：只依据 typed 终态 + 冻结业务判据 + 过程证据
  454 # ---------------------------------------------------------------------------
  455 
  456 
  457 def evaluate_final(
  458     *,
  459     mode: str,
  460     typed_terminal: bool,
  461     business: dict[str, bool],
  462     supplemental: dict[str, bool],
  463     stop_reason: str | None,
  464     exit_codes: list[int],
  465     physical_requests: int,
  466     max_requests: int,
  467     evidence: dict,
  468     extra_failures: list[str] | None = None,
  469 ) -> dict:
  470     """E1 最终判定。任何一项缺失都如实 incomplete，绝不按文字判 PASS。"""
  471 
  472     failures: list[str] = list(extra_failures or ())
  473     if not typed_terminal:
  474         failures.append("product did not reach typed VERIFIED_DONE in durable state")
  475     for name in BOUND_BUSINESS_KEYS:
  476         if not business.get(name, False):
  477             failures.append(f"business check false: {name}")
  478     for name, passed in sorted(supplemental.items()):
  479         if not passed:
  480             failures.append(f"supplemental check false: {name}")
  481     if stop_reason != "verified_done":
  482         failures.append(f"stop reason is not verified_done: {stop_reason!r}")
  483     for code in exit_codes:
  484         if code != 0:
  485             failures.append(f"non-zero process exit code: {code}")
  486     if physical_requests > max_requests:
  487         failures.append(
  488             f"physical requests {physical_requests} exceed the authorized budget {max_requests}"
  489         )
  490     for key in REQUIRED_EVIDENCE.get(mode, ()):
  491         if not evidence.get(key):
  492             failures.append(f"correction journey evidence missing: {key}")
  493     return {
  494         "mode": mode,
  495         "product_status": "completed" if not failures else "incomplete",
  496         "failures": failures,
  497         "typed_terminal": typed_terminal,
  498         "business_checks": {
  499             key: bool(business.get(key, False)) for key in BOUND_BUSINESS_KEYS
  500         },
  501         "business_declared_false": {
  502             key: bool(business.get(key, False)) for key in PROCESS_DECLARED_KEYS
  503         },
  504         "supplemental_checks": supplemental,
  505         "stop_reason": stop_reason,
  506         "exit_codes": exit_codes,
  507         "physical_requests": physical_requests,
  508         "max_requests": max_requests,
  509         "evidence": evidence,
  510     }
  511 
  512 
  513 def _consumption_view(phase: dict) -> dict:
  514     consumption = phase.get("consumption") or {}
  515     fact_id = consumption.get("fact_id")
  516     created = consumption.get("created_from_fact_ids") or []
  517     return {
  518         "fact_id": fact_id,
  519         "consumed": bool(fact_id and fact_id in created),
  520         "version_changed": bool(
  521             consumption.get("goal_version_changed")
  522             or consumption.get("state_version_changed")
  523         ),
  524         "goal_version_changed": bool(consumption.get("goal_version_changed")),
  525         "state_version_changed": bool(consumption.get("state_version_changed")),
  526         "user_outcome": consumption.get("user_outcome"),
  527     }
  528 
  529 
  530 def _staged_evidence(phase_a: dict, phase_b: dict, final_obs: dict | None) -> dict:
  531     a_final = phase_a.get("final_observation") or {}
  532     checks = (phase_a.get("pre_injection") or {}).get("alias_checks") or {}
  533     consumption = _consumption_view(phase_a)
  534     b_start = phase_b.get("start_observation") or {}
  535     effects_after = (final_obs or {}).get("executed_file_effects", 0)
  536     revision_after = (final_obs or {}).get("goal_revision")
  537     typed_terminal = bool(final_obs and final_obs.get("goal_status") == "verified_done")
  538     return {
  539         "correction_injected": bool(
  540             phase_a.get("injected") and phase_a.get("injection_point")
  541         ),
  542         "correction_durable": bool(
  543             phase_a.get("injected_fact_id")
  544             and phase_a.get("injected_fact_id") in a_final.get("correction_fact_ids", [])
  545         ),
  546         "correction_consumed": consumption["consumed"],
  547         "version_changed": consumption["version_changed"],
  548         "paused_after_consumption": bool(
  549             phase_a.get("pause_sent")
  550             and phase_a.get("stop_reason") == "paused_for_resume"
  551             and a_final.get("goal_status") == "paused"
  552         ),
  553         "resumed_in_new_process": bool(
  554             phase_b.get("pid")
  555             and phase_a.get("pid")
  556             and phase_b["pid"] != phase_a["pid"]
  557             and phase_b.get("resume_sent")
  558         ),
  559         "resume_advanced": bool(
  560             typed_terminal
  561             and (
  562                 effects_after > (b_start.get("executed_file_effects") or 0)
  563                 or (
  564                     revision_after is not None
  565                     and revision_after > (b_start.get("goal_revision") or 0)
  566                 )
  567             )
  568         ),
  569         "precondition_alias_checks_pending": bool(
  570             checks
  571             and "probe_error" not in checks
  572             and not (checks.get("legacy_alias") and checks.get("cli_both_names"))
  573         ),
  574         "phase_a_pid": phase_a.get("pid"),
  575         "phase_b_pid": phase_b.get("pid"),
  576         "injection_point": phase_a.get("injection_point"),
  577         "consumption": consumption if consumption["fact_id"] else None,
  578         "alias_checks_at_injection": checks or None,
  579     }
  580 
  581 
  582 # ---------------------------------------------------------------------------
  583 # 子命令
  584 # ---------------------------------------------------------------------------
  585 
  586 
  587 def _derive_staged_spec(original_text: str) -> str:
  588     """从冻结原文程序化派生 staged SPEC：标题 + 原始有界重试段落。"""
  589 
  590     head, separator, _tail = original_text.partition(FUTURE_CORRECTION_MARKER)
  591     if not separator:
  592         raise SystemExit(
  593             "refusing to stage: frozen SPEC does not carry the expected "
  594             f"future-correction marker {FUTURE_CORRECTION_MARKER!r}"
  595         )
  596     staged = head + "\n"
  597     if "During the task" in staged or "retry_count" in staged:
  598         raise SystemExit("refusing to stage: derived SPEC still leaks the correction")
  599     if "max_retries" not in staged or "# Retry feature" not in staged:
  600         raise SystemExit("refusing to stage: derived SPEC lost the frozen paragraphs")
  601     return staged
  602 
  603 
  604 def _prepare(args) -> dict:
  605     candidate = args.candidate.resolve(strict=True)
  606     spec = candidate / "SPEC.md"
  607     if not spec.is_file():
  608         raise SystemExit(f"refusing: no SPEC.md under {candidate}")
  609     original_bytes = spec.read_bytes()
  610     original_sha = hashlib.sha256(original_bytes).hexdigest()
  611     for cache in sorted(candidate.rglob("__pycache__")):
  612         shutil.rmtree(cache)
  613     record: dict = {
  614         "candidate": str(candidate),
  615         "original_spec_sha256": original_sha,
  616         "staged": bool(args.staged),
  617     }
  618     if args.staged:
  619         if original_sha != ORIGINAL_SPEC_SHA256:
  620             raise SystemExit(
  621                 "refusing to stage: SPEC.md does not match the frozen original "
  622                 f"(expected {ORIGINAL_SPEC_SHA256}, got {original_sha})"
  623             )
  624         staged = _derive_staged_spec(original_bytes.decode("utf-8"))
  625         spec.write_text(staged, encoding="utf-8")
  626         (candidate / VARIANT_MARKER).write_text(VARIANT_NOTICE, encoding="utf-8")
  627         record.update(
  628             {
  629                 "variant": "D04 staged variant",
  630                 "staged_spec_content": staged,
  631                 "staged_spec_sha256": hashlib.sha256(
  632                     staged.encode("utf-8")
  633                 ).hexdigest(),
  634                 "future_correction_hidden": (
  635                     "During the task" not in staged and "retry_count" not in staged
  636                 ),
  637             }
  638         )
  639     args.result.parent.mkdir(parents=True, exist_ok=True)
  640     args.result.write_text(
  641         json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
  642         encoding="utf-8",
  643     )
  644     print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
  645     return record
  646 
  647 
  648 def _run_journey(args) -> dict:
  649     from main import main as run_first_agent
  650 
  651     offline = args.provider == "fake"
  652     if not offline:
  653         from scripts.run_real_coding_scenario import _require_dispatch_authorized
  654 
  655         manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
  656         _require_dispatch_authorized(manifest, args)
  657 
  658     candidate = args.candidate.resolve(strict=True)
  659     state_root = args.state_root.resolve()
  660     _ensure_private_dir(state_root.parent)
  661     ledger = args.ledger.resolve()
  662     _ensure_private_dir(ledger.parent)
  663     messages: list[str] = []
  664 
  665     def write_fn(message: str) -> None:
  666         messages.append(message)
  667         print(message, flush=True)
  668 
  669     operator = JourneyOperator(
  670         mode=args.mode,
  671         candidate=candidate,
  672         probe=None if offline else _frozen_probe,
  673         max_consents=args.max_consents,
  674         max_resumes=args.max_resumes,
  675     )
  676 
  677     def input_fn(prompt: str) -> str:
  678         obs = observe(candidate, state_root)
  679         decision = operator.next_input(obs)
  680         if decision == operator.task:
  681             label = "<frozen-task>"
  682         elif decision == operator.correction:
  683             label = "<frozen-correction>"
  684         elif decision == "y":
  685             label = "<governance-consent>"
  686         else:
  687             label = decision
  688         print(f"{prompt}{label}", flush=True)
  689         return decision
  690 
  691     full = [
  692         "--workspace",
  693         str(candidate),
  694         "--state-root",
  695         str(state_root),
  696         "--provider",
  697         args.provider,
  698     ]
  699     if not offline:
  700         full.extend(
  701             (
  702                 "--model",
  703                 args.model,
  704                 "--base-url",
  705                 args.base_url,
  706                 "--credential-env",
  707                 args.credential_env,
  708                 "--thinking-mode",
  709                 args.thinking_mode,
  710                 "--timeout",
  711                 str(args.timeout),
  712             )
  713         )
  714     full.extend(
  715         (
  716             "--transport-audit-ledger",
  717             str(ledger),
  718             "--max-model-attempts",
  719             str(args.max_model_attempts),
  720             "--without-owner-preferences",
  721         )
  722     )
  723     entrypoint_error: str | None = None
  724     try:
  725         exit_code = run_first_agent(full, input_fn=input_fn, write_fn=write_fn)
  726     except Exception as error:  # noqa: BLE001 - 入口崩溃必须如实记录
  727         entrypoint_error = f"{type(error).__name__}: {error}"
  728         exit_code = 3
  729 
  730     final_obs = observe(candidate, state_root)
  731     terminal = bool(final_obs and final_obs["goal_status"] == "verified_done")
  732     if terminal:
  733         # typed 链已达 VERIFIED_DONE：文字诊断标签不能覆盖事实。
  734         operator.stop_reason = "verified_done"
  735     if args.mode == "inject":
  736         phase_ok = operator.pause_sent and operator.stop_reason == "paused_for_resume"
  737     else:
  738         phase_ok = terminal
  739     result = {
  740         "phase": args.mode,
  741         "pid": os.getpid(),
  742         "exit_code": exit_code,
  743         "entrypoint_error": entrypoint_error,
  744         "phase_ok": phase_ok,
  745         "stop_reason": operator.stop_reason,
  746         "terminal": terminal,
  747         "final_observation": final_obs,
  748         "start_observation": operator.start_observation,
  749         "task_sent": operator.task_sent,
  750         "consent_decisions": operator.consent_decisions,
  751         "resumes": operator.resumes,
  752         "continue_decisions": operator.continue_decisions,
  753         "injected": operator.injected,
  754         "injection_point": operator.injection_point,
  755         "injected_fact_id": operator.injected_fact_id,
  756         "pre_injection": operator.pre_injection,
  757         "consumption": operator.consumption,
  758         "pause_sent": operator.pause_sent,
  759         "resume_sent": operator.resume_sent,
  760         "ledger_lines": _ledger_lines(ledger),
  761         "events": operator.events,
  762         "frozen_inputs": {
  763             "initial_prompt": operator.task,
  764             "correction": operator.correction,
  765         },
  766         "tail_messages": messages[-12:],
  767     }
  768     args.result.parent.mkdir(parents=True, exist_ok=True)
  769     args.result.write_text(
  770         json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
  771         encoding="utf-8",
  772     )
  773     print(
  774         json.dumps(
  775             {
  776                 "phase": args.mode,
  777                 "pid": result["pid"],
  778                 "stop_reason": result["stop_reason"],
  779                 "terminal": terminal,
  780                 "phase_ok": phase_ok,
  781             },
  782             ensure_ascii=False,
  783             sort_keys=True,
  784         ),
  785         flush=True,
  786     )
  787     return result
  788 
  789 
  790 def _child(
  791     args,
  792     *,
  793     mode: str,
  794     result_path: Path,
  795     state_root: Path,
  796     ledger: Path,
  797     extra: list[str],
  798     timeout: float,
  799 ) -> subprocess.CompletedProcess:
  800     command = [
  801         sys.executable,
  802         str(Path(__file__).resolve()),
  803         "run",
  804         str(args.candidate.resolve(strict=True)),
  805         "--mode",
  806         mode,
  807         "--state-root",
  808         str(state_root),
  809         "--ledger",
  810         str(ledger),
  811         "--result",
  812         str(result_path),
  813         "--provider",
  814         args.provider,
  815         *extra,
  816     ]
  817     return subprocess.run(command, cwd=str(_ROOT), timeout=timeout, check=False)
  818 
  819 
  820 def _provider_extra(args) -> list[str]:
  821     if args.provider == "fake":
  822         return []
  823     return [
  824         "--model",
  825         args.model,
  826         "--base-url",
  827         args.base_url,
  828         "--credential-env",
  829         args.credential_env,
  830         "--thinking-mode",
  831         args.thinking_mode,
  832         "--timeout",
  833         str(args.timeout),
  834         "--max-model-attempts",
  835         str(args.max_model_attempts),
  836     ]
  837 
  838 
  839 def _finalize(args, phase_results: list[dict], *, mode: str, wall_seconds: float) -> dict:
  840     from scripts.coding_scenario_grader import grade_scenario
  841 
  842     candidate = args.candidate.resolve(strict=True)
  843     state_root = args.state_root.resolve()
  844     final_obs = observe(candidate, state_root)
  845     typed_terminal = bool(final_obs and final_obs["goal_status"] == "verified_done")
  846     extra_failures: list[str] = []
  847     try:
  848         business = grade_scenario("D04", candidate)
  849     except Exception as error:  # noqa: BLE001 - grader 崩溃必须如实记录而非伪装
  850         business = {}
  851         extra_failures.append(
  852             f"business grader failed to execute: {type(error).__name__}: {error}"
  853         )
  854     try:
  855         supplemental = _frozen_probe(candidate)
  856     except Exception as error:  # noqa: BLE001 - 探针崩溃必须如实记录而非伪装
  857         supplemental = {"probe_execution": False}
  858         extra_failures.append(
  859             f"supplemental probe failed to execute: {type(error).__name__}: {error}"
  860         )
  861     physical_requests = _ledger_lines(args.ledger.resolve())
  862     exit_codes = [int(item.get("exit_code", 1)) for item in phase_results]
  863     if mode == "staged":
  864         phase_a = phase_results[0] if phase_results else {}
  865         phase_b = phase_results[1] if len(phase_results) > 1 else {}
  866         evidence = _staged_evidence(phase_a, phase_b, final_obs)
  867         evidence["phase_a"] = {
  868             "pid": phase_a.get("pid"),
  869             "stop_reason": phase_a.get("stop_reason"),
  870             "phase_ok": phase_a.get("phase_ok"),
  871             "consent_decisions": phase_a.get("consent_decisions"),
  872             "continue_decisions": phase_a.get("continue_decisions"),
  873         }
  874         evidence["phase_b"] = {
  875             "pid": phase_b.get("pid"),
  876             "stop_reason": phase_b.get("stop_reason"),
  877             "phase_ok": phase_b.get("phase_ok"),
  878             "resume_sent": phase_b.get("resume_sent"),
  879             "continue_decisions": phase_b.get("continue_decisions"),
  880             "consent_decisions": phase_b.get("consent_decisions"),
  881         }
  882         stop_reason = (
  883             phase_a.get("stop_reason") if not phase_b else phase_b.get("stop_reason")
  884         )
  885         if typed_terminal:
  886             stop_reason = "verified_done"
  887     else:
  888         phase = phase_results[0] if phase_results else {}
  889         evidence = {
  890             "pid": phase.get("pid"),
  891             "stop_reason": phase.get("stop_reason"),
  892             "consent_decisions": phase.get("consent_decisions"),
  893             "continue_decisions": phase.get("continue_decisions"),
  894             "resumes": phase.get("resumes"),
  895             "correction_injected": bool(
  896                 phase.get("injected") and phase.get("injection_point")
  897             ),
  898         }
  899         stop_reason = phase.get("stop_reason")
  900         if typed_terminal:
  901             stop_reason = "verified_done"
  902     record = evaluate_final(
  903         mode=mode,
  904         typed_terminal=typed_terminal,
  905         business=business,
  906         supplemental=supplemental,
  907         stop_reason=stop_reason,
  908         exit_codes=exit_codes,
  909         physical_requests=physical_requests,
  910         max_requests=args.max_model_attempts,
  911         evidence=evidence,
  912         extra_failures=extra_failures,
  913     )
  914     record.update(
  915         {
  916             "driver": "scripts/run_task_trust_d04.py",
  917             "candidate": str(candidate),
  918             "state_root": str(state_root),
  919             "ledger": str(args.ledger.resolve()),
  920             "wall_seconds": round(wall_seconds, 3),
  921             "final_observation": final_obs,
  922             "frozen_inputs": {
  923                 "initial_prompt": INITIAL_PROMPT,
  924                 "correction": CORRECTION,
  925             },
  926         }
  927     )
  928     args.result.parent.mkdir(parents=True, exist_ok=True)
  929     args.result.write_text(
  930         json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
  931         encoding="utf-8",
  932     )
  933     print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
  934     return record
  935 
  936 
  937 def _journey(args) -> int:
  938     state_root = args.state_root.resolve()
  939     ledger = args.ledger.resolve()
  940     _ensure_private_dir(state_root.parent)
  941     _ensure_private_dir(ledger.parent)
  942     extra = _provider_extra(args)
  943     phase_results: list[dict] = []
  944     failures: list[str] = []
  945     started = time.monotonic()
  946     deadline = started + args.wall_seconds
  947 
  948     def remaining() -> float:
  949         return deadline - time.monotonic()
  950 
  951     def run_phase(mode: str, result_path: Path) -> dict:
  952         budget = remaining()
  953         if budget <= 5.0:
  954             failures.append(f"sample wall budget exhausted before the {mode} phase")
  955             return {"exit_code": 124, "stop_reason": "sample_wall_budget_exhausted"}
  956         try:
  957             completed = _child(
  958                 args,
  959                 mode=mode,
  960                 result_path=result_path,
  961                 state_root=state_root,
  962                 ledger=ledger,
  963                 extra=extra,
  964                 timeout=budget,
  965             )
  966             exit_code = completed.returncode
  967         except subprocess.TimeoutExpired:
  968             failures.append(f"sample wall budget exceeded in the {mode} phase")
  969             exit_code = 124
  970         except Exception as error:  # noqa: BLE001 - 子进程启动失败也必须如实记录
  971             failures.append(
  972                 f"{mode} phase could not start: {type(error).__name__}: {error}"
  973             )
  974             exit_code = 3
  975         if result_path.exists():
  976             phase = json.loads(result_path.read_text(encoding="utf-8"))
  977             # 不覆盖 phase 文件里的产品自身退出码（run_first_agent 返回值）；
  978             # driver 子进程返回码单列，避免同义反复式失败项。
  979             phase["driver_exit_code"] = exit_code
  980             return phase
  981         return {"exit_code": exit_code, "stop_reason": "child_result_missing"}
  982 
  983     if args.mode == "normal":
  984         phase_results.append(run_phase("normal", args.result.with_suffix(".phase.json")))
  985     else:
  986         phase_a = run_phase("inject", args.result.with_suffix(".a.json"))
  987         phase_results.append(phase_a)
  988         if phase_a.get("stop_reason") == "paused_for_resume":
  989             phase_results.append(run_phase("resume", args.result.with_suffix(".b.json")))
  990         else:
  991             failures.append(
  992                 "injection phase did not pause for resume; resume phase skipped"
  993             )
  994     try:
  995         record = _finalize(
  996             args, phase_results, mode=args.mode, wall_seconds=time.monotonic() - started
  997         )
  998     except Exception as error:  # noqa: BLE001 - 判定失败也必须留下如实记录
  999         record = {
 1000             "mode": args.mode,
 1001             "product_status": "incomplete",
 1002             "failures": [f"finalization failed: {type(error).__name__}: {error}"],
 1003             "phase_stop_reasons": [
 1004                 item.get("stop_reason") for item in phase_results
 1005             ],
 1006         }
 1007         args.result.parent.mkdir(parents=True, exist_ok=True)
 1008         args.result.write_text(
 1009             json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
 1010             encoding="utf-8",
 1011         )
 1012         print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
 1013         return 1
 1014     if failures:
 1015         record["failures"] = [*failures, *record["failures"]]
 1016         record["product_status"] = "incomplete"
 1017         args.result.write_text(
 1018             json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
 1019             encoding="utf-8",
 1020         )
 1021     return 0 if record["product_status"] == "completed" else 1
 1022 
 1023 
 1024 def _add_provider_options(parser: argparse.ArgumentParser) -> None:
 1025     parser.add_argument(
 1026         "--provider",
 1027         default="openai_compatible",
 1028         choices=("fake", "openai_compatible"),
 1029     )
 1030     parser.add_argument("--model", default="deepseek-v4-flash")
 1031     parser.add_argument("--base-url", default="https://api.deepseek.com")
 1032     parser.add_argument("--credential-env", default="DEEPSEEK_API_KEY")
 1033     parser.add_argument(
 1034         "--thinking-mode", default="disabled", choices=("enabled", "disabled")
 1035     )
 1036     parser.add_argument("--max-model-attempts", type=int, default=MAX_REQUESTS_PER_SAMPLE)
 1037     parser.add_argument("--max-consents", type=int, default=40)
 1038     parser.add_argument("--max-resumes", type=int, default=2)
 1039     parser.add_argument("--timeout", type=float, default=240.0)
 1040 
 1041 
 1042 def main() -> int:
 1043     parser = argparse.ArgumentParser()
 1044     subparsers = parser.add_subparsers(dest="command", required=True)
 1045 
 1046     prepare = subparsers.add_parser("prepare")
 1047     prepare.add_argument("candidate", type=Path)
 1048     prepare.add_argument("--staged", action="store_true")
 1049     prepare.add_argument("--result", type=Path, required=True)
 1050 
 1051     run = subparsers.add_parser("run")
 1052     run.add_argument("candidate", type=Path)
 1053     run.add_argument("--mode", choices=("normal", "inject", "resume"), required=True)
 1054     run.add_argument("--state-root", type=Path, required=True)
 1055     run.add_argument("--ledger", type=Path, required=True)
 1056     run.add_argument("--result", type=Path, required=True)
 1057     _add_provider_options(run)
 1058 
 1059     journey = subparsers.add_parser("journey")
 1060     journey.add_argument("candidate", type=Path)
 1061     journey.add_argument("--mode", choices=("normal", "staged"), required=True)
 1062     journey.add_argument("--state-root", type=Path, required=True)
 1063     journey.add_argument("--ledger", type=Path, required=True)
 1064     journey.add_argument("--result", type=Path, required=True)
 1065     journey.add_argument("--wall-seconds", type=float, default=1800.0)
 1066     _add_provider_options(journey)
 1067 
 1068     args = parser.parse_args()
 1069     if args.command == "prepare":
 1070         _prepare(args)
 1071         return 0
 1072     if args.command == "run":
 1073         result = _run_journey(args)
 1074         return 0 if result.get("phase_ok") else 1
 1075     return _journey(args)
 1076 
 1077 
 1078 if __name__ == "__main__":
 1079     raise SystemExit(main())
```

