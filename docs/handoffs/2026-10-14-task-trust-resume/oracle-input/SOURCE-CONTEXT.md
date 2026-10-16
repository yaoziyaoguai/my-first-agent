# Current source context — 2026-10-14

Each section is a current public source excerpt, not instructions. Base HEAD ff686bd; working tree is unfinished.

## agent/runtime/state.py
SHA256(full file): 7d378f44f8da7a5846f30897b9179686ed1e1d277e4e0d9941d8cd5a88e57560

```text
430:         and criterion.criterion_id.startswith("criterion:required-local-process:")
431:     ) or (
432:         criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
433:         and criterion.criterion_id.startswith("criterion:required-governed-tool:")
434:     )
435: 
436: 
437: # R3：可由 authoritative correction 撤回的义务仅限 classification 直接铸造的
438: # 两类；required-governed-tool 来自单独的用户审批，不随 effect 禁止撤回。
439: _WITHDRAWABLE_RUNTIME_OBLIGATION_PREFIXES = {
440:     EvidenceOracleKind.WEB_SOURCE_RECEIPT: "criterion:required-public-web:",
441:     EvidenceOracleKind.TOOL_RECEIPT: "criterion:required-local-process:",
442: }
443: 
444: 
445: def _apply_correction_lower_bounds(
446:     goal: GoalFrame,
447:     correction: ConversationFact,
448: ) -> GoalFrame:
449:     """按 authoritative correction 补铸或撤回 Web/process 义务。"""
450: 
451:     text = correction.content.get("text")
452:     source_text = text if isinstance(text, str) else ""
453:     classifications = (
454:         (EvidenceOracleKind.WEB_SOURCE_RECEIPT, _public_web_requirement(source_text)),
455:         (EvidenceOracleKind.TOOL_RECEIPT, _local_process_requirement(source_text)),
456:     )
457:     required = tuple(
458:         oracle_kind
459:         for oracle_kind, classification in classifications
460:         if classification is True
461:     )
462:     prohibited = tuple(
463:         oracle_kind
464:         for oracle_kind, classification in classifications
465:         if classification is False
466:     )
467:     if not required and not prohibited:
468:         return goal
469:     identity = canonical_json_digest(
470:         {
471:             "goal_id": goal.goal_id,
472:             "correction_fact_id": correction.fact_id,
473:             "correction_text": source_text,
474:         }
475:     )
476:     criteria = goal.proposed_criteria
477:     # R3 撤回：correction 明确禁止该 effect 时，Runtime 早前为此铸的 proposed
478:     # 义务必须随现行版本失效；残留会让 verify_goal_completion 的 "process
479:     # criterion must be admitted" 检查永久失败，Goal 被 brick。未命中任何
480:     # 现存义务时语义未变化，保持 Goal 原样（noop 判定依赖此相等性）。
481:     for oracle_kind in prohibited:
482:         prefix = _WITHDRAWABLE_RUNTIME_OBLIGATION_PREFIXES[oracle_kind]
483:         criteria = tuple(
484:             item
485:             for item in criteria
486:             if not (
487:                 item.oracle_kind is oracle_kind
488:                 and item.criterion_id.startswith(prefix)
489:             )
490:         )
491:     if not required and criteria == goal.proposed_criteria:
492:         return goal
493:     for oracle_kind in required:
494:         runtime_owned = tuple(
495:             item
496:             for item in criteria
497:             if item.oracle_kind is oracle_kind and _is_runtime_owned_obligation(item)
498:         )
499:         criteria = tuple(
500:             item
501:             for item in criteria
502:             if item.oracle_kind is not oracle_kind or _is_runtime_owned_obligation(item)
503:         )
504:         if runtime_owned:
505:             continue
506:         if oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT:
507:             criterion = ProposedCriterion(
508:                 criterion_id=f"criterion:required-public-web:{identity[:16]}",
509:                 description="the requested public Web source was actually retrieved",
510:                 oracle_kind=oracle_kind,
511:             )
512:         else:
513:             criterion = ProposedCriterion(
514:                 criterion_id=f"criterion:required-local-process:{identity[:16]}",
515:                 description=(
516:                     "the explicitly requested local validation process exits successfully"
517:                 ),
518:                 oracle_kind=oracle_kind,
519:             )
520:         criteria = (*criteria, criterion)
521:     retained_ids = {item.criterion_id for item in criteria}
522:     return replace(
523:         goal,
524:         proposed_criteria=criteria,
525:         admitted_criteria=tuple(
```

```text
1195:     )
1196: 
1197: 
1198: def _require_goal_revision(
1199:     state: ConversationState,
1200:     *,
1201:     goal_id: str,
1202:     expected_revision: int,
1203: ) -> GoalFrame:
1204:     goal = state.goal
1205:     if goal is None or goal.goal_id != goal_id:
1206:         raise GoalRevisionConflictError("goal identity mismatch")
1207:     if goal.revision != expected_revision:
1208:         raise GoalRevisionConflictError("goal revision mismatch")
1209:     return goal
1210: 
1211: 
1212: def _has_unknown_effect(state: ConversationState) -> bool:
1213:     active = state.active_run
1214:     return active is not None and (
1215:         active.phase is ContinuationPhase.EXECUTING
1216:         or active.status is ActiveRunStatus.AWAITING_RECOVERY
1217:     )
1218: 
1219: 
1220: def _stop_safe_active_run(
1221:     state: ConversationState,
1222:     *,
1223:     status: RunStatus,
1224:     message: str,
1225: ) -> tuple[None, RecordedRunResult | None]:
1226:     active = state.active_run
1227:     if active is None:
1228:         return None, state.last_safe_result
1229:     return None, RecordedRunResult(status=status, run_id=active.run_id, message=message)
1230: 
1231: 
1232: def _superseded_tool_result_fact(
1233:     *,
1234:     fact_id: str,
```

```text
1545:         goal = replace(goal, status=GoalStatus.GOAL_READY)
1546:     return replace(
1547:         state,
1548:         goal=goal,
1549:         provider_disclosure_receipt=request.acknowledge(
1550:             receipt_id=f"disclosure-receipt:{action.action_seq}",
1551:             acknowledged_action_seq=action.action_seq,
1552:             acknowledged_at=action.acknowledged_at,
1553:         ),
1554:         active_run=replace(active, status=ActiveRunStatus.RUNNABLE),
1555:     )
1556: 
1557: 
1558: def record_completion_claim(
1559:     state: ConversationState,
1560:     claim: CompletionClaim,
1561: ) -> ConversationState:
1562:     goal = _require_goal_revision(
1563:         state,
1564:         goal_id=claim.goal_id,
1565:         expected_revision=claim.goal_revision,
1566:     )
1567:     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
1568:         raise ValueError("completion claim requires an executable goal")
1569:     if any(
1570:         receipt.correlation_id == claim.correlation_id
1571:         for receipt in state.control_receipts
1572:     ):
1573:         raise ValueError("control correlation_id was already accepted")
1574:     evidence_ids = {record.evidence_id for record in state.evidence_records}
1575:     if not set(claim.criterion_evidence_refs).issubset(evidence_ids):
1576:         raise ValueError("completion claim references unknown evidence")
1577:     accepted_revision = state.revision + 1
1578:     payload_digest = canonical_json_digest(
1579:         {
1580:             "goal_id": claim.goal_id,
1581:             "goal_revision": claim.goal_revision,
1582:             "criterion_evidence_refs": claim.criterion_evidence_refs,
1583:         }
1584:     )
1585:     receipt = ControlReceipt.create(
1586:         correlation_id=claim.correlation_id,
1587:         control_kind="completion_claim",
1588:         goal_id=goal.goal_id,
1589:         goal_revision=goal.revision,
1590:         accepted_state_revision=accepted_revision,
1591:         payload_digest=payload_digest,
1592:     )
1593:     return replace(
1594:         state,
1595:         revision=accepted_revision,
1596:         completion_claim=claim,
1597:         control_receipts=(*state.control_receipts, receipt),
1598:     )
1599: 
1600: 
1601: def record_evidence(
1602:     state: ConversationState,
1603:     records: tuple[EvidenceRecord, ...],
1604: ) -> ConversationState:
1605:     goal = state.goal
1606:     if goal is None or not records:
1607:         raise ValueError("evidence requires a current goal and at least one record")
1608:     known = {record.evidence_id for record in state.evidence_records}
1609:     criteria = {criterion.criterion_id: criterion for criterion in goal.admitted_criteria}
1610:     for record in records:
1611:         criterion = criteria.get(record.criterion_id)
1612:         if (
1613:             record.evidence_id in known
1614:             or record.goal_id != goal.goal_id
1615:             or record.goal_revision != goal.revision
1616:             or criterion is None
1617:             or record.oracle_kind is not criterion.oracle_kind
1618:             or record.predicate_digest != canonical_json_digest(criterion.predicate)
1619:         ):
1620:             raise ValueError("evidence does not bind the current admitted criterion")
1621:         known.add(record.evidence_id)
1622:     return replace(
1623:         state,
1624:         revision=state.revision + 1,
1625:         evidence_records=(*state.evidence_records, *records),
1626:     )
1627: 
1628: 
1629: def _require_requirement_coverage(
1630:     state: ConversationState,
1631:     claim: CompletionClaim,
1632:     *,
1633:     goal: GoalFrame,
1634:     mandatory: tuple[AdmittedCriterion, ...],
1635: ) -> None:
1636:     """R2 完成门：物理证据齐全是必要条件，不是完整业务完成的充分条件。
1637: 
1638:     最终结束必须经过针对当前 Goal revision 与当前权威用户输入/最新 correction
1639:     的逐项覆盖复核（模型提供语义映射，Runtime 校验结构与版本/来源/证据绑定）。
1640:     缺失时拒绝并给出可修复的下一步；不铸造 evidence/permission，不引入第二
1641:     模型裁判。引用整条 fact、空列表或首个文件 digest 的组合不能充当逐项复核。
1642:     """
1643: 
1644:     coverage = claim.requirement_coverage
1645:     if not coverage:
1646:         raise ValueError(
1647:             "completion claim must include per-requirement coverage of the current "
1648:             "authoritative user input and corrections before the goal can be verified"
1649:         )
1650:     source_ids = set(goal.created_from_fact_ids)
1651:     authoritative_ids = {
1652:         fact.fact_id
1653:         for fact in state.facts
1654:         if fact.fact_id in source_ids and fact.kind is FactKind.USER_MESSAGE
1655:     }
1656:     cited: set[str] = set()
1657:     for item in coverage:
1658:         cited.update(item.source_fact_ids)
1659:         if any(fact_id not in source_ids for fact_id in item.source_fact_ids):
1660:             raise ValueError(
1661:                 "requirement coverage must cite the authoritative source facts of "
1662:                 "the current goal"
1663:             )
1664:     uncited = authoritative_ids - cited
1665:     if uncited:
1666:         raise ValueError(
1667:             "requirement coverage does not cite every authoritative user input or "
1668:             f"correction: {sorted(uncited)}"
1669:         )
1670:     mandatory_ids = {criterion.criterion_id for criterion in mandatory}
1671:     pending = tuple(item for item in coverage if item.status == "pending")
1672:     if pending:
1673:         raise ValueError(
1674:             "completion claim lists pending requirements that are not yet satisfied: "
1675:             + ", ".join(item.requirement_id for item in pending)
1676:         )
1677:     for item in coverage:
1678:         unknown = set(item.criterion_ids) - mandatory_ids
1679:         if unknown:
1680:             raise ValueError(
1681:                 "requirement coverage binds criterion ids that are not current "
1682:                 f"admitted mandatory criteria: {sorted(unknown)}"
1683:             )
1684:     covered = {
1685:         criterion_id
1686:         for item in coverage
1687:         for criterion_id in item.criterion_ids
1688:     }
1689:     uncovered = mandatory_ids - covered
1690:     if uncovered:
1691:         raise ValueError(
1692:             "requirement coverage does not bind every mandatory criterion: "
1693:             f"{sorted(uncovered)}"
1694:         )
1695: 
1696: 
1697: def verify_goal_completion(state: ConversationState) -> ConversationState:
1698:     goal = state.goal
1699:     claim = state.completion_claim
1700:     if goal is None or claim is None:
1701:         raise ValueError("completion verification requires a current claim")
1702:     if _has_unknown_effect(state):
1703:         raise ValueError("unknown effect recovery has priority over goal verification")
1704:     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
1705:         raise ValueError("goal status is not eligible for completion verification")
1706:     if claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
1707:         raise GoalRevisionConflictError("completion claim is stale")
1708:     if state.browser_takeover_pending is not None:
1709:         raise ValueError("browser takeover must be resolved before goal verification")
1710:     active_task_resources(state.facts).require_closed()
1711:     referenced = {
1712:         record.evidence_id: record
1713:         for record in state.evidence_records
1714:         if record.evidence_id in claim.criterion_evidence_refs
1715:     }
1716:     mandatory = tuple(
1717:         criterion for criterion in goal.admitted_criteria if criterion.mandatory
1718:     )
1719:     if not mandatory:
1720:         raise ValueError("goal has no mandatory criterion")
1721:     if any(criterion.oracle_kind is None for criterion in goal.proposed_criteria):
1722:         raise ValueError(
1723:             "every proposed completion criterion requires a typed evidence oracle"
1724:         )
1725:     artifact_requirements = tuple(
1726:         criterion
1727:         for criterion in goal.proposed_criteria
1728:         if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
1729:     )
1730:     for requirement in artifact_requirements:
1731:         if not any(
1732:             criterion.criterion_id == requirement.criterion_id
1733:             and criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
1734:             and criterion.predicate.get("path") == requirement.artifact_path
1735:             for criterion in mandatory
1736:         ):
1737:             raise ValueError(
1738:                 "artifact criterion must be admitted before completion verification"
1739:             )
1740:     process_requirements = tuple(
1741:         criterion
1742:         for criterion in goal.proposed_criteria
1743:         if criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
1744:     )
1745:     for requirement in process_requirements:
1746:         if not any(
1747:             criterion.criterion_id == requirement.criterion_id
1748:             and criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
1749:             for criterion in mandatory
1750:         ):
1751:             raise ValueError(
1752:                 "process criterion must be admitted before completion verification"
1753:             )
1754:     _require_requirement_coverage(state, claim, goal=goal, mandatory=mandatory)
1755:     evidence_by_criterion = {
1756:         record.criterion_id: record for record in referenced.values()
1757:     }
1758:     if any(
1759:         criterion.criterion_id not in evidence_by_criterion
1760:         or not evidence_by_criterion[criterion.criterion_id].passed
1761:         or evidence_by_criterion[criterion.criterion_id].goal_id != goal.goal_id
1762:         or evidence_by_criterion[criterion.criterion_id].goal_revision != goal.revision
1763:         or evidence_by_criterion[criterion.criterion_id].oracle_kind
1764:         is not criterion.oracle_kind
1765:         or evidence_by_criterion[criterion.criterion_id].predicate_digest
1766:         != canonical_json_digest(criterion.predicate)
1767:         for criterion in mandatory
1768:     ):
1769:         raise ValueError("current evidence does not prove every mandatory criterion")
1770:     return replace(
1771:         state,
1772:         revision=state.revision + 1,
1773:         goal=replace(goal, status=GoalStatus.VERIFIED_DONE, next_step=None),
1774:         goal_authorizations=(),
1775:         process_leases=(),
1776:         sandbox_leases=(),
1777:         browser_leases=(),
1778:         browser_takeover_pending=None,
1779:     )
1780: 
1781: 
1782: def _conflict(state: ConversationState, reason: str) -> ActionTransition:
1783:     return ActionTransition(ActionDisposition.CONFLICT, state, reason=reason)
1784: 
1785: 
1786: def _find_replay(state: ConversationState, action_seq: int):
1787:     return next(
1788:         (record for record in state.replay_records if record.action_seq == action_seq),
1789:         None,
1790:     )
1791: 
1792: 
1793: def _append_replay_record(
1794:     state: ConversationState,
1795:     *,
1796:     action_seq: int,
1797:     action_digest: str,
1798:     max_replay_records: int,
1799: ) -> ConversationState | None:
1800:     if max_replay_records < 1:
1801:         raise ValueError("max_replay_records must be positive")
1802: 
1803:     records = list(state.replay_records)
1804:     replay_floor = state.replay_floor
1805:     while len(records) >= max_replay_records:
```

```text
3765: def _close_orphaned_tool_batches(
3766:     state: ConversationState,
3767:     *,
3768:     action_seq: int,
3769:     live_call_ids: frozenset[str],
3770: ) -> ConversationState | None:
3771:     """为**可核实**的旧孤儿 tool 批次补记 durable 非执行结果；不可证则拒绝。
3772: 
3773:     V1 修复轮曾在此处无条件为任何缺结果的批次补 ``executed=False``。R1 审计
3774:     证明该推断没有依据：缺 active_run、缺 result、``last_safe_result`` 或旧
3775:     ``superseded`` 文案都不能证明某个 call 未执行（效果可能已发生而结果保存
3776:     失败）。自愈据此收窄为唯一可核实的旧形状：同批**完整连续 prefix**、
3777:     最后一个结果为 Runtime 拒绝审批结果，缺失项全部位于其后——该形状下批次
3778:     在拒绝处停止，suffix 必未开始。其余形状保留原 facts/checkpoint，由
3779:     accept_action 以动作冲突拒绝，不发 provider/tool、不伪造非执行。
3780: 
3781:     新代码的安全停机（pause/cancel/decline/end/complete/CancelRun/控制纠正）
3782:     已在丢 run 的同一 CAS 内闭合各自确定的 suffix，不再依赖本函数。
3783: 
3784:     归属按 call_id 所有权判定（批次是原子单位）：live run 拥有的批次仍会由
3785:     审批/执行或 correction 分支补齐结果，绝不代答；畸形结构保持 parser 的
3786:     fail-closed 判定，不做部分愈合。返回 ``None`` 表示存在不可证孤儿。
3787:     """
3788: 
3789:     facts = state.facts
3790:     total = len(facts)
3791:     reserved_ids = {fact.fact_id for fact in facts}
3792:     insertions: dict[int, tuple[ConversationFact, ...]] = {}
3793:     index = 0
3794:     while index < total:
3795:         fact = facts[index]
3796:         if fact.kind is not FactKind.TOOL_CALLS:
3797:             index += 1
3798:             continue
3799:         raw_calls = fact.content.get("calls")
3800:         expected: list[str] = []
3801:         malformed = not isinstance(raw_calls, list) or not raw_calls
3802:         if not malformed:
3803:             for raw_call in raw_calls:
3804:                 call_id = (
3805:                     raw_call.get("tool_call_id")
3806:                     if isinstance(raw_call, dict)
3807:                     else None
3808:                 )
3809:                 if (
3810:                     not isinstance(call_id, str)
3811:                     or not call_id
3812:                     or call_id in expected
3813:                 ):
3814:                     malformed = True
3815:                     break
3816:                 expected.append(call_id)
3817:         if malformed or any(call_id in live_call_ids for call_id in expected):
3818:             index += 1
3819:             continue
3820:         covered: list[str] = []
3821:         covered_ids: set[str] = set()
3822:         last_result_is_rejection = False
3823:         cursor = index + 1
3824:         while cursor < total and facts[cursor].kind is FactKind.TOOL_RESULT:
3825:             result_call_id = facts[cursor].content.get("tool_call_id")
3826:             if (
3827:                 not isinstance(result_call_id, str)
3828:                 or result_call_id not in expected
3829:                 or result_call_id in covered_ids
3830:             ):
3831:                 break
3832:             covered_ids.add(result_call_id)
3833:             covered.append(result_call_id)
3834:             last_result_is_rejection = (
3835:                 facts[cursor].content.get("rejected") is True
3836:             )
3837:             cursor += 1
3838:         missing = tuple(call_id for call_id in expected if call_id not in covered_ids)
3839:         if not missing:
3840:             index = cursor
3841:             continue
3842:         # 结果段被畸形结果（重复/乱序/异批 call_id）截断时，前缀无法核实：
3843:         # 保持未确定，不做部分愈合（parser 对畸形结构仍是 fail closed）。
3844:         if cursor < total and facts[cursor].kind is FactKind.TOOL_RESULT:
3845:             return None
3846:         # 唯一可核实的旧形状：covered 恰为 expected 的完整连续前缀（按序、
3847:         # 无缺位），且最后一个结果为 Runtime 拒绝审批结果。缺 prefix、乱序、
3848:         # 重复或末结果非拒绝时，调用结果无法证明，保持未确定。
3849:         prefix_is_exact = (
3850:             bool(covered)
3851:             and len(covered) <= len(expected)
3852:             and covered == expected[: len(covered)]
3853:             and last_result_is_rejection
3854:         )
3855:         if not prefix_is_exact:
3856:             return None
3857:         invocation_origin = fact.content.get("invocation_origin")
3858:         healed: list[ConversationFact] = []
3859:         for call_id in missing:
3860:             fact_id = f"action:{action_seq}:superseded-tool:{call_id}"
3861:             if fact_id in reserved_ids:
3862:                 # 跨批次 call_id 撞名（供应商异常形状）：用批次 revision
3863:                 # 后缀确定性去重，不引入随机性，也不静默丢结果。
3864:                 suffix = fact.fact_id.rsplit(":", 1)[-1]
3865:                 fact_id = f"{fact_id}:{suffix}"
3866:             reserved_ids.add(fact_id)
3867:             healed.append(
3868:                 ConversationFact(
3869:                     fact_id=fact_id,
3870:                     kind=FactKind.TOOL_RESULT,
3871:                     content={
3872:                         "tool_call_id": call_id,
3873:                         "text": (
3874:                             "Tool call was not executed; its run was superseded "
3875:                             "before a result was recorded."
3876:                         ),
3877:                         "is_error": True,
3878:                         "executed": False,
3879:                         "superseded": True,
3880:                         **(
3881:                             {"invocation_origin": invocation_origin}
3882:                             if invocation_origin == InvocationOrigin.OPERATOR.value
3883:                             else {}
3884:                         ),
3885:                     },
3886:                 )
3887:             )
3888:         insertions[cursor] = tuple(healed)
3889:         index = cursor
3890:     if not insertions:
3891:         return state
3892:     merged: list[ConversationFact] = []
3893:     for position, fact in enumerate(facts):
3894:         merged.extend(insertions.get(position, ()))
3895:         merged.append(fact)
3896:     # 批次位于 facts 末尾（EOF）时插入点等于 total，循环到不了该位置。
3897:     merged.extend(insertions.get(total, ()))
3898:     return replace(state, facts=tuple(merged))
3899: 
3900: 
3901: def accept_action(
3902:     state: ConversationState | None,
3903:     action: Action,
3904:     *,
3905:     max_replay_records: int = 64,
```

## agent/runtime/loop.py
SHA256(full file): 4bcf36afd6841d7488ee551eba284d0e03cc603d0f53e3d276fb36130bc49e4d

```text
2720:                         event_kind=RuntimeEventKind.COMPLETED,
2721:                         run_id=run_id,
2722:                         message="Goal correction requires user authority before another effect.",
2723:                         outcome_state=completed,
2724:                     )
2725:                 continue
2726:             if isinstance(control, BlockedClaim):
2727:                 available_tools = tuple(sorted(tool.name for tool in context.tools))
2728:                 pending_obligation_tools = (
2729:                     self._evidence_registry.pending_obligation_tools(
2730:                         current.state,
2731:                         available_tools=available_tools,
2732:                     )
2733:                 )
2734:                 if pending_obligation_tools or (
2735:                     available_tools
2736:                     and not self._run_has_product_tool_attempt(current.state)
2737:                 ):
2738:                     required_tools = pending_obligation_tools or available_tools
2739:                     if no_progress.repair_exhausted(
2740:                         ("unverified_blocked_claim", *required_tools),
2741:                         allowance=self._limits.max_no_progress_replans,
2742:                         observation_id=model_calls,
2743:                     ):
2744:                         return self._finish_no_progress(
2745:                             current,
2746:                             action,
2747:                             warnings,
2748:                             message=(
2749:                                 "Provider repeated a blocked claim without attempting an "
2750:                                 "available product tool."
2751:                             ),
2752:                         )
2753:                     no_progress_since_product_action = True
2754:                     current = self._save(
2755:                         current,
2756:                         append_policy_result(
2757:                             current.state,
2758:                             code="blocked_claim_not_verified",
2759:                             message=(
2760:                                 "The blocked_claim was not accepted because no relevant "
2761:                                 "product tool attempt supports a still-pending Runtime-owned "
2762:                                 "Goal obligation. Required next tool: "
2763:                                 f"{', '.join(required_tools)}. Unrelated workspace reads do "
2764:                                 "not establish this blocker. Call the tool that can advance "
2765:                                 "trusted_goal now; claim blocked only after a concrete safe "
2766:                                 "attempt produces a durable blocker."
2767:                                 if pending_obligation_tools
2768:                                 else "The blocked_claim was not accepted because no product "
2769:                                 "tool attempt supports it. Available product tools: "
2770:                                 f"{', '.join(available_tools)}. Call the tool that can "
2771:                                 "advance trusted_goal now; claim blocked only after a "
2772:                                 "concrete safe attempt produces a durable blocker."
2773:                             ),
2774:                         ),
2775:                     )
2776:                     continue
2777:                 goal_frame = current.state.goal
2778:                 mandatory_refs = tuple(
2779:                     ClosedEvidenceRegistry.evidence_id(
2780:                         goal_frame.goal_id,
2781:                         goal_frame.revision,
2782:                         criterion.criterion_id,
2783:                     )
2784:                     for criterion in goal_frame.admitted_criteria
2785:                     if criterion.mandatory
2786:                 )
2787:                 # 用户拒绝当前 Goal 仍需要的 authority 时，blocked 是合法终态；
2788:                 # 但 correction 后拒绝旧 target，或已持有 closed Web receipt 后
2789:                 # 拒绝重复检索，只是在维护现有 authority，不得据此把已经可证明
2790:                 # 的 Goal 终化为 blocked（016 J11 真实三连实测）。
2791:                 if mandatory_refs and not self._rejection_still_blocks_current_goal(
2792:                     current.state
2793:                 ):
2794:                     probe = CompletionClaim(
2795:                         correlation_id=control.correlation_id,
2796:                         goal_id=goal_frame.goal_id,
2797:                         goal_revision=goal_frame.revision,
2798:                         criterion_evidence_refs=mandatory_refs,
2799:                     )
2800:                     try:
2801:                         self._evidence_registry.derive(
2802:                             current.state,
2803:                             probe,
2804:                             observed_at=self._evidence_time_factory(),
2805:                         )
2806:                     except EvidenceVerificationError as error:
2807:                         evidence_gap = str(error)
2808:                         gap_repair = self._evidence_registry.assess_gap(
2809:                             evidence_gap,
2810:                             available_tools=available_tools,
2811:                         )
2812:                         if gap_repair.repairable_tools:
2813:                             if no_progress.repair_exhausted(
2814:                                 (
2815:                                     "blocked_claim_with_repairable_evidence",
2816:                                     *gap_repair.repairable_tools,
2817:                                 ),
2818:                                 allowance=self._limits.max_no_progress_replans,
2819:                                 observation_id=model_calls,
2820:                             ):
2821:                                 return self._finish_no_progress(
2822:                                     current,
2823:                                     action,
2824:                                     warnings,
2825:                                     message=(
2826:                                         "Provider repeated blocked claims while an "
2827:                                         "available tool could close the evidence gap."
2828:                                     ),
2829:                                 )
2830:                             no_progress_since_product_action = True
2831:                             current = self._save(
2832:                                 current,
2833:                                 append_policy_result(
2834:                                     current.state,
2835:                                     code="blocked_claim_not_verified",
2836:                                     message=(
2837:                                         "The blocked_claim was not accepted because the "
2838:                                         "current evidence gap is repairable with an "
2839:                                         "advertised product tool. Required next tool: "
2840:                                         f"{', '.join(gap_repair.repairable_tools)}. "
2841:                                         + gap_repair.repair_instruction
2842:                                     ),
2843:                                 ),
2844:                             )
2845:                             continue
2846:                     else:
2847:                         # 016 第 96 轮 a2 J7:edit+process 均成功(exit 0、durable
2848:                         # receipts)后模型以 blocked 收尾。守卫合同要求 attempt
2849:                         # "produces a durable blocker";完成证据已可推导时
2850:                         # "无安全动作可推进"不成立,受理会把可完成 Goal 终化为
2851:                         # blocked(false-completion 的对偶)。拒绝并给 completion
2852:                         # 修复指引;证据不可推导时 blocked 语义照旧成立。
2853:                         if no_progress.repair_exhausted(
2854:                             ("blocked_claim_with_derivable_evidence",),
2855:                             allowance=self._limits.max_no_progress_replans,
2856:                             observation_id=model_calls,
2857:                         ):
2858:                             return self._finish_no_progress(
2859:                                 current,
2860:                                 action,
2861:                                 warnings,
2862:                                 message=(
2863:                                     "Provider repeated blocked claims while complete "
2864:                                     "evidence was derivable."
2865:                                 ),
2866:                             )
2867:                         no_progress_since_product_action = True
2868:                         current = self._save(
2869:                             current,
2870:                             append_policy_result(
2871:                                 current.state,
2872:                                 code="completion_evidence_available",
2873:                                 message=(
2874:                                     "The blocked_claim was not accepted: every "
2875:                                     "mandatory criterion already has derivable "
2876:                                     "evidence from durable facts, so a safe action "
2877:                                     "can advance this Goal. Resend completion_claim "
2878:                                     "with criterion_evidence_refs copied exactly, "
2879:                                     "element for element and in order, from the "
2880:                                     "CURRENT trusted_goal block's "
2881:                                     "expected_completion_evidence_refs; do not "
2882:                                     "report this Goal as blocked."
2883:                                 ),
2884:                             ),
2885:                         )
2886:                         continue
2887:                 run_id = active.run_id
2888:                 accepted_control = self._ground_rejected_process_blocker(
2889:                     current.state,
2890:                     control,
2891:                 )
2892:                 try:
2893:                     blocked = accept_blocked_claim(current.state, accepted_control)
2894:                 except ValueError as error:
2895:                     # 016 真实 E3 第 87 轮 J10:correlation 复用等可修复控制输入
2896:                     # 不得升级为 runtime_failure;与 CompletionClaim 同型的有界修复
2897:                     # (§18 先例),额度与 fatal 语义不变。
2898:                     if invalid_repairs >= self._limits.max_invalid_repairs:
2899:                         failed = fail_run(
2900:                             current.state,
2901:                             code="invalid_model_control",
2902:                             message="Provider repeated an invalid control after repair allowance.",
2903:                         )
2904:                         return self._finish(
2905:                             current,
2906:                             action,
2907:                             status=RunStatus.FAILED_FATAL,
2908:                             warnings=warnings,
2909:                             event_kind=RuntimeEventKind.FAILED,
2910:                             error_code="invalid_model_control",
2911:                             outcome_state=failed,
2912:                         )
2913:                     invalid_repairs += 1
2914:                     current = self._save(
2915:                         current,
2916:                         append_policy_result(
2917:                             current.state,
2918:                             code="invalid_model_control",
2919:                             message=(
2920:                                 "Control rejected by current trusted state: "
2921:                                 f"{error}. Use trusted_goal values and a new correlation_id."
2922:                             ),
2923:                         ),
2924:                     )
2925:                     continue
2926:                 return self._finish(
2927:                     current,
2928:                     action,
2929:                     status=RunStatus.COMPLETED,
2930:                     warnings=warnings,
2931:                     event_kind=RuntimeEventKind.COMPLETED,
2932:                     run_id=run_id,
2933:                     message=accepted_control.blocker,
2934:                     outcome_state=blocked,
2935:                 )
2936:             if isinstance(control, CompletionClaim):
2937:                 try:
2938:                     records = self._evidence_registry.derive(
2939:                         current.state,
2940:                         control,
2941:                         observed_at=self._evidence_time_factory(),
2942:                     )
2943:                     existing_ids = {record.evidence_id for record in current.state.evidence_records}
2944:                     fresh = tuple(
2945:                         record for record in records if record.evidence_id not in existing_ids
2946:                     )
2947:                     if fresh:
2948:                         current = self._save(
2949:                             current,
2950:                             record_evidence(current.state, fresh),
2951:                         )
2952:                         no_progress.reset()
2953:                     current = self._save(
2954:                         current,
2955:                         record_completion_claim(current.state, control),
2956:                     )
2957:                     current = self._save(
2958:                         current,
2959:                         verify_goal_completion(current.state),
2960:                     )
2961:                 except EvidenceVerificationError as error:
2962:                     if no_progress.repair_exhausted(
2963:                         (
2964:                             "unverified_completion",
2965:                             str(error),
2966:                             canonical_json_digest(list(control.criterion_evidence_refs)),
2967:                         ),
2968:                         allowance=self._limits.max_no_progress_replans,
2969:                         observation_id=model_calls,
2970:                     ):
2971:                         return self._finish_no_progress(
2972:                             current,
2973:                             action,
2974:                             warnings,
2975:                             message=(
2976:                                 "Provider repeated completion claims without adding "
2977:                                 "the required verification evidence."
2978:                             ),
2979:                         )
2980:                     no_progress_since_product_action = True
2981:                     current = self._save(
2982:                         current,
2983:                         append_policy_result(
2984:                             current.state,
2985:                             code="completion_not_verified",
2986:                             message=(
2987:                                 f"{error} "
2988:                                 + self._evidence_registry.assess_gap(
2989:                                     str(error)
2990:                                 ).repair_instruction
2991:                             ),
2992:                         ),
2993:                     )
2994:                     continue
2995:                 except ValueError as error:
2996:                     # 已成功解码但不满足当前 trusted state 的 control（例如复用
2997:                     # correlation_id）属于模型可修复输入，不应把用户任务升级为
2998:                     # runtime_failure。修复次数仍受同一个 hard limit 约束。
2999:                     if invalid_repairs >= self._limits.max_invalid_repairs:
3000:                         failed = fail_run(
3001:                             current.state,
3002:                             code="invalid_model_control",
3003:                             message="Provider repeated an invalid control after repair allowance.",
3004:                         )
3005:                         return self._finish(
3006:                             current,
3007:                             action,
3008:                             status=RunStatus.FAILED_FATAL,
3009:                             warnings=warnings,
3010:                             event_kind=RuntimeEventKind.FAILED,
3011:                             error_code="invalid_model_control",
3012:                             outcome_state=failed,
3013:                         )
3014:                     invalid_repairs += 1
3015:                     current = self._save(
3016:                         current,
3017:                         append_policy_result(
3018:                             current.state,
3019:                             code="invalid_model_control",
3020:                             message=(
3021:                                 "Control rejected by current trusted state: "
3022:                                 f"{error}. Use trusted_goal values and a new correlation_id."
3023:                             ),
3024:                         ),
3025:                     )
3026:                     continue
3027:                 run_id = active.run_id
3028:                 completion_text = "\n".join(
3029:                     block.text
3030:                     for block in response.blocks
3031:                     if isinstance(block, ModelTextBlock)
3032:                 ).strip()
3033:                 completion_message = (
3034:                     completion_text
3035:                     or "Goal completion verified by closed evidence oracles."
3036:                 )
3037:                 completed = complete_run(
3038:                     current.state,
3039:                     message=completion_message,
3040:                     provider_continuation=response.provider_continuation,
3041:                 )
3042:                 return self._finish(
3043:                     current,
3044:                     action,
3045:                     status=RunStatus.COMPLETED,
```

## agent/runtime/context.py
SHA256(full file): a8624913f9e0ef7fdfde7e4ae77209577fffb1a0f01e8ff4c75359ad75bac370

```text
1250:                     raise ContextLimitError("context candidate content digest mismatch")
1251:                 try:
1252:                     provenance_bytes = json.dumps(
1253:                         candidate.provenance,
1254:                         sort_keys=True,
1255:                         separators=(",", ":"),
1256:                         ensure_ascii=False,
1257:                     ).encode("utf-8")
1258:                 except (TypeError, ValueError) as error:
1259:                     raise ContextLimitError("context candidate provenance is invalid") from error
1260:                 if len(provenance_bytes) > self._limits.max_tool_result_chars:
1261:                     raise ContextLimitError("context candidate provenance exceeds the limit")
1262:                 source_tokens += self._estimate(candidate.content)
1263:             if source_tokens > query.source_limits.max_tokens:
1264:                 raise ContextLimitError("context source exceeded the token limit")
1265:             digests.append(f"{snapshot.source_name}:{snapshot.revision}:{snapshot.snapshot_digest}")
1266:             for candidate in snapshot.candidates:
1267:                 groups.append(self._candidate_group(candidate))
1268:         return tuple(groups), tuple(digests)
1269: 
1270:     @staticmethod
1271:     def _goal_group(state: ConversationState) -> _ContextGroup | None:
1272:         goal = state.goal
1273:         if goal is None:
1274:             return None
1275:         admitted_ids = tuple(criterion.criterion_id for criterion in goal.admitted_criteria)
1276:         evidenced_ids = {
1277:             record.criterion_id
1278:             for record in state.evidence_records
1279:             if record.goal_id == goal.goal_id
1280:             and record.goal_revision == goal.revision
1281:             and record.passed
1282:         }
1283:         block: dict[str, JSONValue] = {
1284:             "type": "trusted_goal",
1285:             "trusted": True,
1286:             "goal_id": goal.goal_id,
1287:             "goal_revision": goal.revision,
1288:             "workspace_identity_digest": goal.workspace_identity_digest,
1289:             "user_outcome": goal.user_outcome,
1290:             "beneficiary": goal.beneficiary,
1291:             "targets": list(goal.targets),
1292:             "scope": list(goal.scope),
1293:             "non_goals": list(goal.non_goals),
1294:             "assumptions": list(goal.assumptions),
1295:             "authority_snapshot": goal.authority_snapshot,
1296:             "status": goal.status.value,
1297:             "interaction_state": state.interaction_state.value,
1298:             "progress_summary": goal.progress_summary,
1299:             "next_step": goal.next_step,
1300:             # R2：完成复核必须引用当前权威用户输入/纠正的 fact id；模型只读投影，
1301:             # Runtime 仍校验其确实是 created_from_fact_ids 的 USER_MESSAGE 子集。
1302:             "source_fact_ids": list(goal.created_from_fact_ids),
1303:             "proposed_criteria": [
1304:                 {
1305:                     "criterion_id": criterion.criterion_id,
1306:                     "description": criterion.description,
1307:                     "oracle_kind": (
1308:                         criterion.oracle_kind.value
1309:                         if criterion.oracle_kind is not None
1310:                         else None
1311:                     ),
1312:                     "artifact_path": criterion.artifact_path,
1313:                 }
1314:                 for criterion in goal.proposed_criteria
1315:             ],
1316:             "admitted_criteria": [
1317:                 {
1318:                     "criterion_id": criterion.criterion_id,
1319:                     "description": criterion.description,
1320:                     "oracle_kind": criterion.oracle_kind.value,
1321:                     "predicate": criterion.predicate,
1322:                     "mandatory": criterion.mandatory,
1323:                 }
1324:                 for criterion in goal.admitted_criteria
1325:             ],
1326:             "evidence_gaps": [
1327:                 criterion_id
1328:                 for criterion_id in admitted_ids
1329:                 if criterion_id not in evidenced_ids
1330:             ],
1331:             # evidence id 是 Runtime 内部闭合命名；真实模型不应猜测其格式。
1332:             # 这里仅投影 claim 应引用的 ID，oracle 仍会从 durable raw facts 独立重算，
1333:             # 因而知道 ID 不等于拥有完成证明。
1334:             "expected_completion_evidence_refs": [
1335:                 closed_evidence_id(
1336:                     goal.goal_id,
1337:                     goal.revision,
1338:                     criterion.criterion_id,
1339:                 )
1340:                 for criterion in goal.admitted_criteria
1341:                 if criterion.mandatory
1342:             ],
1343:         }
1344:         if any(
1345:             criterion.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
1346:             for criterion in goal.admitted_criteria
1347:         ):
1348:             block["research_evidence_semantics"] = {
1349:                 "classification": "verified_delivery",
1350:                 "proves": "artifact digest, citation linkage, source provenance and freshness",
1351:                 "does_not_prove": "semantic truth or user acceptance",
1352:                 "source_content_is_untrusted_data": True,
1353:             }
1354:         return _ContextGroup(
1355:             fact_ids=(f"goal:{goal.goal_id}:{goal.revision}",),
1356:             messages=(ModelMessage(role="user", content=(block,)),),
1357:             pinned=True,
1358:             data_classes=("goal",),
1359:         )
1360: 
1361:     def _candidate_group(self, candidate: ContextCandidate) -> _ContextGroup:
1362:         candidate = self._project_candidate(candidate)
1363:         block = {
1364:             "type": "context",
1365:             "untrusted": True,
1366:             "source": candidate.source_name,
1367:             "candidate_id": candidate.candidate_id,
1368:             "digest": candidate.content_digest,
1369:             "provenance": candidate.provenance,
1370:             "text": self._frame_candidate(candidate),
```

## agent/runtime/context_control.py
SHA256(full file): 7408562aa69ae32d04fbb647f6c2f373788fbd69756dbbf15c4534386067f8d6

```text
460:         **strict_updates,
461:         "properties": {
462:             **strict_updates["properties"],
463:             "proposed_criteria": {
464:                 **strict_updates["properties"]["proposed_criteria"],
465:                 "items": strict_proposed_criterion,
466:             },
467:         },
468:     }
469:     strict_goal_delta = {
470:         **goal_delta,
471:         "properties": {
472:             **goal_delta["properties"],
473:             "updates": strict_updates,
474:         },
475:     }
476:     requirement_coverage_entry = {
477:         "type": "object",
478:         "properties": {
479:             "requirement_id": string,
480:             "requirement": {
481:                 **string,
482:                 "description": (
483:                     "One concrete requirement from the current authoritative user "
484:                     "input/corrections, in your own words."
485:                 ),
486:             },
487:             "source_fact_ids": {
488:                 **string_array,
489:                 "description": (
490:                     "Authoritative source fact ids of the current goal that state "
491:                     "this requirement (see trusted_goal.source_fact_ids)."
492:                 ),
493:             },
494:             "status": {
495:                 "type": "string",
496:                 "enum": ["satisfied", "pending"],
497:                 "description": (
498:                     "pending when the requirement is not yet done; a claim with any "
499:                     "pending requirement cannot complete the goal."
500:                 ),
501:             },
502:             "criterion_ids": {
503:                 **string_array,
504:                 "description": (
505:                     "For satisfied: the admitted mandatory criterion ids that prove "
506:                     "it (see trusted_goal.admitted_criteria). Empty for pending."
507:                 ),
508:             },
509:         },
510:         "required": [
511:             "requirement_id",
512:             "requirement",
513:             "source_fact_ids",
514:             "status",
515:             "criterion_ids",
516:         ],
517:         "additionalProperties": False,
518:     }
519:     requirement_coverage = {
520:         "type": "array",
521:         "items": requirement_coverage_entry,
522:         "description": (
523:             "Per-requirement coverage of the current authoritative user input and "
524:             "every correction; every authoritative source fact and every mandatory "
525:             "criterion must be covered before the goal can be verified."
526:         ),
527:     }
528:     strict_fields = {
529:         "direct_response": {"text": string},
530:         "begin_answer": {},
531:         "clarification_request": {
532:             "question": string,
533:             "boundary_code": string,
534:             "missing_fields": string_array,
535:             "safe_assumptions": string_array,
536:         },
537:         "goal_proposal": {
538:             "user_outcome": string,
539:             "beneficiary": string,
540:             "targets": string_array,
541:             "scope": string_array,
542:             "non_goals": string_array,
543:             "assumptions": string_array,
544:             "proposed_criteria": {
545:                 "type": "array",
546:                 "items": strict_proposed_criterion,
547:             },
548:             "requires_public_web": {
549:                 "type": "boolean",
550:                 "description": (
551:                     "True for an explicit public/Web/current/latest/online outcome; Runtime "
552:                     "then requires Web evidence."
553:                 ),
554:             },
555:             "requires_local_process": {
556:                 "type": "boolean",
557:                 "description": (
558:                     "True whenever the user explicitly asks to run, test, build, validate, "
559:                     "check, or execute a local command."
560:                 ),
561:             },
562:         },
563:         "goal_progress": {
564:             "goal_id": trusted_goal_id,
565:             "goal_revision": trusted_goal_revision,
566:             "summary": string,
567:             "next_step": string,
568:         },
569:         "goal_delta_proposal": {"delta": strict_goal_delta},
570:         "completion_claim": {
571:             "goal_id": trusted_goal_id,
572:             "goal_revision": trusted_goal_revision,
573:             "criterion_evidence_refs": trusted_completion_refs,
574:             "requirement_coverage": requirement_coverage,
575:         },
576:         "blocked_claim": {
577:             "goal_id": trusted_goal_id,
578:             "goal_revision": trusted_goal_revision,
579:             "blocker": string,
580:             "safe_attempts": string_array,
581:             "resume_condition": string,
582:         },
583:     }
584:     strict_variants = []
585:     for kind in allowed_kinds:
586:         properties = {
587:             "kind": {"type": "string", "enum": [kind]},
588:             "correlation_id": string,
589:             **strict_fields[kind],
590:         }
591:         strict_variants.append(
592:             {
593:                 "type": "object",
594:                 "properties": properties,
595:                 "required": list(properties),
596:                 "additionalProperties": False,
597:             }
598:         )
599:     portable_fields = {
600:         "direct_response": {"text": string},
601:         "begin_answer": {},
602:         "clarification_request": {
603:             "question": string,
604:             "boundary_code": string,
605:             "missing_fields": {
606:                 **string_array,
607:                 "description": "Must contain at least one missing field.",
608:             },
609:             "safe_assumptions": string_array,
610:         },
611:         "goal_proposal": {**goal_draft_fields, "next_step": string},
612:         "goal_progress": {
613:             "goal_id": trusted_goal_id,
614:             "goal_revision": trusted_goal_revision,
615:             "summary": string,
616:             "next_step": string,
617:         },
618:         "goal_delta_proposal": {"delta": goal_delta},
619:         "completion_claim": {
620:             "goal_id": trusted_goal_id,
621:             "goal_revision": trusted_goal_revision,
622:             "criterion_evidence_refs": trusted_completion_refs,
623:             "requirement_coverage": requirement_coverage,
624:         },
625:         "blocked_claim": {
626:             "goal_id": trusted_goal_id,
627:             "goal_revision": trusted_goal_revision,
628:             "blocker": string,
629:             "safe_attempts": string_array,
630:             "resume_condition": string,
631:         },
632:     }
633:     portable_properties = {
634:         "kind": {"type": "string", "enum": list(allowed_kinds)},
635:         "correlation_id": string,
636:     }
637:     for kind in allowed_kinds:
638:         portable_properties.update(portable_fields[kind])
639:     portable_required = ["kind", "correlation_id"]
640:     if goal_correction_is_pending:
```

## agent/provider/normalize.py
SHA256(full file): a6c30fd1005cd1bc2427cdc151df56b41a271fff0039e4f0e92f07c2502552b2

```text
920:             arguments["proposed_criteria"], _decode_proposed_criterion
921:         ),
922:         next_step=(
923:             _control_str(arguments["next_step"])
924:             if "next_step" in arguments
925:             else None
926:         ),
927:         requires_public_web=_control_bool(arguments["requires_public_web"]),
928:         requires_local_process=_control_bool(arguments["requires_local_process"]),
929:     )
930: 
931: 
932: def _decode_goal_progress(arguments: dict[str, Any]) -> GoalProgress:
933:     return GoalProgress(
934:         correlation_id=_control_str(arguments["correlation_id"]),
935:         goal_id=_control_str(arguments["goal_id"]),
936:         goal_revision=_control_int(arguments["goal_revision"]),
937:         summary=_control_str(arguments["summary"]),
938:         next_step=_control_str(arguments["next_step"]),
939:     )
940: 
941: 
942: def _decode_goal_delta_proposal(arguments: dict[str, Any]) -> GoalDeltaProposal:
943:     return GoalDeltaProposal(
944:         correlation_id=_control_str(arguments["correlation_id"]),
945:         delta=_decode_goal_delta(arguments["delta"]),
946:     )
947: 
948: 
949: def _decode_requirement_coverage(value: Any) -> tuple[RequirementCoverage, ...]:
950:     if not isinstance(value, (list, tuple)):
951:         raise ValueError("requirement_coverage must be an array")
952:     items: list[RequirementCoverage] = []
953:     for raw in value:
954:         if not isinstance(raw, dict):
955:             raise ValueError("requirement_coverage entry must be an object")
956:         items.append(
957:             RequirementCoverage(
958:                 requirement_id=_control_str(raw["requirement_id"]),
959:                 requirement=_control_str(raw["requirement"]),
960:                 source_fact_ids=_control_tuple(
961:                     raw["source_fact_ids"], _control_str
962:                 ),
963:                 status=_control_str(raw["status"]),
964:                 criterion_ids=_control_tuple(raw["criterion_ids"], _control_str),
965:             )
966:         )
967:     return tuple(items)
968: 
969: 
970: def _decode_completion_claim(arguments: dict[str, Any]) -> CompletionClaim:
971:     return CompletionClaim(
972:         correlation_id=_control_str(arguments["correlation_id"]),
973:         goal_id=_control_str(arguments["goal_id"]),
974:         goal_revision=_control_int(arguments["goal_revision"]),
975:         criterion_evidence_refs=_control_tuple(arguments["criterion_evidence_refs"], _control_str),
976:         requirement_coverage=_decode_requirement_coverage(
977:             arguments["requirement_coverage"]
978:         ),
979:     )
980: 
981: 
982: def _decode_blocked_claim(arguments: dict[str, Any]) -> BlockedClaim:
983:     return BlockedClaim(
984:         correlation_id=_control_str(arguments["correlation_id"]),
985:         goal_id=_control_str(arguments["goal_id"]),
986:         goal_revision=_control_int(arguments["goal_revision"]),
987:         blocker=_control_str(arguments["blocker"]),
988:         safe_attempts=_control_tuple(arguments["safe_attempts"], _control_str),
989:         resume_condition=_control_str(arguments["resume_condition"]),
990:     )
```

```text
1020:             "assumptions",
1021:             "proposed_criteria",
1022:             "requires_public_web",
1023:             "requires_local_process",
1024:             "next_step",
1025:         },
1026:         _decode_goal_draft_proposal,
1027:     ),
1028:     "goal_progress": (
1029:         _COMMON_CONTROL_KEYS | {"goal_id", "goal_revision", "summary", "next_step"},
1030:         _decode_goal_progress,
1031:     ),
1032:     "goal_delta_proposal": (_COMMON_CONTROL_KEYS | {"delta"}, _decode_goal_delta_proposal),
1033:     "completion_claim": (
1034:         _COMMON_CONTROL_KEYS
1035:         | {
1036:             "goal_id",
1037:             "goal_revision",
1038:             "criterion_evidence_refs",
1039:             "requirement_coverage",
1040:         },
1041:         _decode_completion_claim,
1042:     ),
1043:     "blocked_claim": (
1044:         _COMMON_CONTROL_KEYS
1045:         | {"goal_id", "goal_revision", "blocker", "safe_attempts", "resume_condition"},
1046:         _decode_blocked_claim,
1047:     ),
1048: }
1049: 
1050: 
```

## agent/runtime/checkpoint.py
SHA256(full file): 2e76e0377acbe4a63aa395ca05da65adf7b5fc6af16bcfff415034b8976b2b4a

```text
1334: 
1335: 
1336: def _completion_claim_to_dict(value: CompletionClaim | None) -> dict | None:
1337:     if value is None:
1338:         return None
1339:     return {
1340:         "correlation_id": value.correlation_id,
1341:         "goal_id": value.goal_id,
1342:         "goal_revision": value.goal_revision,
1343:         "criterion_evidence_refs": list(value.criterion_evidence_refs),
1344:         "requirement_coverage": [
1345:             {
1346:                 "requirement_id": item.requirement_id,
1347:                 "requirement": item.requirement,
1348:                 "source_fact_ids": list(item.source_fact_ids),
1349:                 "status": item.status,
1350:                 "criterion_ids": list(item.criterion_ids),
1351:             }
1352:             for item in value.requirement_coverage
1353:         ],
1354:     }
1355: 
1356: 
1357: def _completion_claim_from_dict(value) -> CompletionClaim | None:
1358:     if value is None:
1359:         return None
1360:     value = _object(value, "completion_claim")
1361:     # R2：旧活动 checkpoint 缺 requirement_coverage 时按空迁移——旧记录不被
1362:     # 默认视为复核已满足，模型在主 loop 正常补复核。
1363:     keys = {
1364:         "correlation_id",
1365:         "goal_id",
1366:         "goal_revision",
1367:         "criterion_evidence_refs",
1368:     }
1369:     if "requirement_coverage" in value:
1370:         keys.add("requirement_coverage")
1371:     _expect_keys(value, keys, "completion_claim")
1372:     raw_coverage = value.get("requirement_coverage") or []
1373:     coverage: list[RequirementCoverage] = []
1374:     for item in _array(raw_coverage, "requirement_coverage"):
1375:         entry = _object(item, "requirement_coverage entry")
1376:         _expect_keys(
1377:             entry,
1378:             {
1379:                 "requirement_id",
1380:                 "requirement",
1381:                 "source_fact_ids",
1382:                 "status",
1383:                 "criterion_ids",
1384:             },
1385:             "requirement_coverage entry",
1386:         )
1387:         coverage.append(
1388:             RequirementCoverage(
1389:                 requirement_id=_string(entry["requirement_id"], "requirement_id"),
1390:                 requirement=_string(entry["requirement"], "requirement"),
1391:                 source_fact_ids=tuple(
1392:                     _string(item, "source_fact_id")
1393:                     for item in _array(entry["source_fact_ids"], "source_fact_ids")
1394:                 ),
1395:                 status=_string(entry["status"], "status"),
1396:                 criterion_ids=tuple(
1397:                     _string(item, "criterion_id")
1398:                     for item in _array(entry["criterion_ids"], "criterion_ids")
1399:                 ),
1400:             )
1401:         )
1402:     return CompletionClaim(
1403:         correlation_id=_string(value["correlation_id"], "correlation_id"),
1404:         goal_id=_string(value["goal_id"], "completion_claim.goal_id"),
1405:         goal_revision=_integer(value["goal_revision"], "completion_claim.goal_revision"),
1406:         criterion_evidence_refs=tuple(
1407:             _string(item, "criterion_evidence_ref")
1408:             for item in _array(
1409:                 value["criterion_evidence_refs"],
1410:                 "criterion_evidence_refs",
1411:             )
1412:         ),
1413:         requirement_coverage=tuple(coverage),
1414:     )
1415: 
1416: 
1417: def _disclosure_request_to_dict(value: ProviderDisclosureRequest | None) -> dict | None:
1418:     if value is None:
1419:         return None
1420:     return {
```

## tests/continuity/test_verified_done.py
SHA256(full file): e10cc10661a6b13bb3607abd39098ae2c2d59ed0987ad76d3dffa634eee43870

```text
1: from __future__ import annotations
2: 
3: import hashlib
4: from dataclasses import replace
5: 
6: import pytest
7: 
8: from agent.runtime.context import ContextLimits, KernelContextManager
9: from agent.runtime.contracts import (
10:     ActiveRun,
11:     AdmittedCriterion,
12:     BlockedClaim,
13:     CompletionClaim,
14:     ContinuationPhase,
15:     ConversationFact,
16:     ConversationState,
17:     EvidenceOracleKind,
18:     ExecutingIntentRecord,
19:     ExecutionAuthorityClass,
20:     FactKind,
21:     GoalBootstrap,
22:     GoalDelta,
23:     GoalDeltaProposal,
24:     GoalDraftProposal,
25:     GoalStatus,
26:     ModelResponse,
27:     ModelTextBlock,
28:     ModelToolCall,
29:     ProposedCriterion,
30:     RequirementCoverage,
31:     Resume,
32:     RunStatus,
33:     SubmitMessage,
34:     ToolCall,
35:     ToolPrepareContext,
36:     closed_evidence_id,
37: )
38: from agent.runtime.evidence import ClosedEvidenceRegistry, EvidenceVerificationError
39: from agent.runtime.loop import AgentRuntime, InvocationLimits
40: from agent.runtime.state import (
41:     accept_goal_delta_proposal,
42:     accept_goal_draft_proposal,
43:     record_completion_claim,
44:     record_evidence,
45:     verify_goal_completion,
46: )
47: from agent.runtime.tools import KernelToolRuntime
48: from agent.tools.file_ops import build_file_tool_runtime
49: from tests.continuity.test_contracts import _goal
50: from tests.kernel.fakes import (
51:     CollectingSink,
52:     InMemoryCheckpointStore,
53:     ScriptedProvider,
54:     goal_noop_response,
55: )
56: 
57: CONTENT = "verified report\n"
58: CONTENT_DIGEST = hashlib.sha256(CONTENT.encode()).hexdigest()
59: EVIDENCE_ID = "evidence:goal:1:1:criterion:report-exists"
60: # _runtime 的 SubmitMessage 被消费为 goal_correction，落为 action:1:user 权威
61: # fact；覆盖率门要求 claim 引用每条权威用户输入，因此两者都必须被覆盖。
62: RUNTIME_SOURCE_FACT_IDS = ("fact:user:1", "action:1:user")
63: 
64: 
65: def _facts(*, fake: bool = False) -> tuple[ConversationFact, ...]:
66:     return (
67:         ConversationFact(
68:             fact_id="fact:user:1",
69:             kind=FactKind.USER_MESSAGE,
70:             content={"text": "write the exact verified report"},
71:         ),
72:         ConversationFact(
73:             fact_id="fact:calls:1",
74:             kind=FactKind.TOOL_CALLS,
75:             content={
76:                 "calls": [
77:                     {
78:                         "tool_call_id": "read-1",
79:                         "name": "read_file",
80:                         "arguments": {"path": "reports/final.md"},
81:                     }
82:                 ]
83:             },
84:         ),
85:         ConversationFact(
86:             fact_id="fact:read-result:1",
87:             kind=FactKind.TOOL_RESULT,
88:             content={
89:                 "tool_call_id": "read-1",
90:                 "text": CONTENT,
91:                 "is_error": False,
92:                 "executed": True,
93:                 "metadata": {"fake": fake},
94:             },
95:         ),
96:     )
97: 
98: 
99: def _state(*, fake: bool = False) -> ConversationState:
100:     goal = _goal()
101:     criterion = goal.admitted_criteria[0]
102:     criterion = replace(
103:         criterion,
104:         predicate={"path": "reports/final.md", "sha256": CONTENT_DIGEST},
105:     )
106:     return ConversationState(
107:         conversation_id="conversation-1",
108:         facts=_facts(fake=fake),
109:         goal=replace(
110:             goal,
111:             admitted_criteria=(criterion,),
112:             status=GoalStatus.GOAL_READY,
113:         ),
114:     )
115: 
116: 
117: def _claim(
118:     *,
119:     correlation_id: str = "claim-1",
120:     source_fact_ids: tuple[str, ...] = ("fact:user:1",),
121: ) -> CompletionClaim:
122:     return CompletionClaim(
123:         correlation_id=correlation_id,
124:         goal_id="goal:1",
125:         goal_revision=1,
126:         criterion_evidence_refs=(EVIDENCE_ID,),
127:         requirement_coverage=(
128:             RequirementCoverage(
129:                 requirement_id="requirement:report",
130:                 requirement="the exact verified report is written",
131:                 source_fact_ids=source_fact_ids,
132:                 status="satisfied",
133:                 criterion_ids=("criterion:report-exists",),
134:             ),
135:         ),
136:     )
137: 
138: 
139: def _runtime(state: ConversationState, *responses: ModelResponse):
140:     store = InMemoryCheckpointStore(state)
141:     provider = ScriptedProvider(
142:         goal_noop_response("verification-user-supplement"),
143:         *responses,
144:     )
145:     runtime = AgentRuntime(
146:         provider=provider,
147:         context_manager=KernelContextManager(
148:             system_policy="policy",
149:             limits=ContextLimits(max_input_tokens=3_000, output_reserve=200),
150:         ),
151:         tool_runtime=KernelToolRuntime(()),
152:         checkpoint_store=store,
153:         event_sink=CollectingSink(),
154:         limits=InvocationLimits(),
155:         invocation_id_factory=lambda: "invocation-evidence",
156:     )
157:     action = SubmitMessage(
158:         conversation_id=state.conversation_id,
159:         action_seq=state.next_action_seq,
160:         expected_revision=state.revision,
161:         run_id="run-verify",
162:         message="verify completion",
163:     )
164:     return runtime, store, action
165: 
166: 
167: def test_text_done_and_model_completion_claim_cannot_self_verify() -> None:
168:     runtime, store, action = _runtime(
169:         _state(),
170:         ModelResponse((ModelTextBlock("done"),)),
171:         ModelResponse((ModelTextBlock("done"),)),
172:     )
173: 
174:     result = runtime.run_turn(action, store.load())
175: 
176:     assert result.status is RunStatus.FAILED_FATAL
177:     assert result.error_code == "invalid_model_control"
178:     assert store.state.goal.status is GoalStatus.GOAL_READY
179:     assert store.state.evidence_records == ()
180: 
181: 
182: def test_deterministic_receipts_bound_to_all_mandatory_criteria_verify_goal() -> None:
183:     from tests.continuity.test_browser_authority import make_lease
184: 
185:     runtime, store, action = _runtime(
186:         replace(_state(), browser_leases=(make_lease(),)),
187:         ModelResponse((), control=_claim(source_fact_ids=RUNTIME_SOURCE_FACT_IDS)),
188:     )
189: 
190:     result = runtime.run_turn(action, store.load())
191: 
192:     assert result.status is RunStatus.COMPLETED
193:     assert store.state.goal.status is GoalStatus.VERIFIED_DONE
194:     assert store.state.evidence_records[0].evidence_id == EVIDENCE_ID
195:     assert store.state.evidence_records[0].source_fact_ids == (
196:         "fact:calls:1",
197:         "fact:read-result:1",
198:     )
199:     assert store.state.browser_leases == ()
200: 
201: 
202: def test_read_back_alone_does_not_auto_complete_goal(tmp_path) -> None:
203:     """R2：read-back 产生闭合证据后，Runtime 不再自行合成复核，回到 model loop。
204: 
205:     修复前：最终 read-back 后 Runtime 自动合成 `runtime-completion:` claim 并
206:     直接 VERIFIED_DONE，模型无需逐项复核权威要求。R2 合同要求自动路径不得
207:     自行合成"已复核所有业务要求"——证据齐全后仍需模型显式提交带
208:     requirement_coverage 的 completion_claim。
209:     """
210: 
211:     workspace = tmp_path / "workspace"
212:     (workspace / "reports").mkdir(parents=True)
213:     (workspace / "reports" / "final.md").write_text(CONTENT, encoding="utf-8")
214:     seed = _state()
215:     state = replace(
216:         seed,
217:         facts=(seed.facts[0],),
218:         active_run=ActiveRun("run-auto-complete"),
219:     )
220:     store = InMemoryCheckpointStore(state)
221:     provider = ScriptedProvider(
222:         ModelResponse(
```

## tests/kernel/test_runtime_compaction.py
SHA256(full file): 0d37c0a10f6bf842e8ee41f2fea52547e12ca796d8d284fa43bf764260a94e81

```text
1190: 
1191:     # 对照组：完整连续 prefix（call-1 拒绝结果）→ 允许补 call-2 尾部。
1192:     rejection = ConversationFact(
1193:         fact_id="run:run-legacy:tool-result:call-1:11",
1194:         kind=FactKind.TOOL_RESULT,
1195:         content={
1196:             "tool_call_id": "call-1",
1197:             "text": "User rejected the requested tool action.",
1198:             "is_error": True,
1199:             "executed": False,
1200:             "rejected": True,
1201:         },
1202:     )
1203:     healed = accept_action(_orphan_state(extra_facts=(rejection,)), action)
1204:     assert healed.disposition is ActionDisposition.ACCEPTED
1205:     closed = [
1206:         fact for fact in healed.state.facts if fact.content.get("superseded") is True
1207:     ]
1208:     assert len(closed) == 1
1209:     assert closed[0].content["tool_call_id"] == "call-2"
1210:     assert closed[0].content["executed"] is False
1211: 
1212: 
1213: def test_legacy_orphan_matrix_multi_batch_and_malformed_fail_closed() -> None:
1214:     """R1-T8：多批次、跨批同 call_id、重复/畸形结果——不跨批借证明，fail closed。"""
1215: 
1216:     def _batch(run: str, calls: tuple[str, ...]) -> ConversationFact:
1217:         return ConversationFact(
1218:             fact_id=f"run:{run}:tool-batch:10",
1219:             kind=FactKind.TOOL_CALLS,
1220:             content={
1221:                 "calls": [
1222:                     {"tool_call_id": call_id, "name": "write_file", "arguments": {}}
1223:                     for call_id in calls
1224:                 ]
1225:             },
1226:         )
1227: 
1228:     def _result(
1229:         fact_id: str, call_id: str, *, rejected: bool = False
1230:     ) -> ConversationFact:
1231:         return ConversationFact(
1232:             fact_id=fact_id,
1233:             kind=FactKind.TOOL_RESULT,
1234:             content={
1235:                 "tool_call_id": call_id,
1236:                 "text": "rejected" if rejected else "ok",
1237:                 "is_error": rejected,
1238:                 "executed": False if rejected else True,
1239:                 **({"rejected": True} if rejected else {}),
1240:             },
1241:         )
1242: 
1243:     def _state(facts: tuple[ConversationFact, ...]) -> ConversationState:
1244:         return ConversationState(
1245:             conversation_id="conversation-1",
1246:             revision=10,
1247:             next_action_seq=8,
1248:             replay_floor=1,
1249:             facts=facts,
1250:         )
1251: 
1252:     action = SubmitMessage(
1253:         conversation_id="conversation-1",
1254:         action_seq=8,
1255:         expected_revision=10,
```

## tests/acceptance/fixtures/d04_resume_correction/SPEC.md
SHA256(full file): 781ed941341a94acd3c9a39e51d221179cfbe652cbe63bc719eb77573c4e086c

```text
1: # Retry feature
2: 
3: Complete the bounded retry behavior for transient `RuntimeError` failures. The
4: new public name is `max_retries`; the command-line adapter must use the same
5: value. Negative limits are invalid, and an operation must never run more than
6: `1 + max_retries` times.
7: 
8: During the task the operator will add one correction: preserve the previous
9: `retry_count` keyword and CLI option as aliases. If both old and new names are
10: provided at once, reject the ambiguous request.
11: 
```

## agent/cli/app.py
SHA256(full file): 63a5df341f901fe2cb5c70effc66507bd231c20f147a3e3991be05c52305e7bc

```text
310:             None,
311:         )
312: 
313:     if command == "/approve-artifact":
314:         request = _approval_request(state)
315:         if request is None:
316:             return None, "No approval request is pending."
317:         requirement = request.artifact_confirmation_requirement
318:         if requirement is None:
319:             return None, "The pending approval has no artifact requirement."
320:         try:
321:             path, sha256 = parse_artifact_confirmation(argument if separator else "")
322:         except ValueError as error:
323:             return None, str(error)
324:         if path != requirement.artifact_path:
325:             return None, "Artifact path must exactly match the pending requirement."
326:         return (
327:             build_resolve_approval(
328:                 state,
329:                 request_id=request.request_id,
330:                 binding_digest=request.binding_digest,
331:                 approved=True,
332:                 approved_at=approval_time_factory(),
333:                 confirmed_artifact_path=path,
334:                 confirmed_artifact_sha256=sha256,
335:             ),
336:             None,
337:         )
338: 
339:     if command in {
340:         "/approve",
341:         "/approve-goal-target",
342:         "/approve-goal-directory",
343:         "/reject",
344:     }:
345:         request = _approval_request(state)
346:         if request is None:
347:             return None, "No approval request is pending."
348:         if not separator or argument != request.request_id:
349:             return None, "Use the exact pending request ID."
350:         return (
351:             build_resolve_approval(
352:                 state,
353:                 request_id=request.request_id,
354:                 binding_digest=request.binding_digest,
355:                 approved=command != "/reject",
356:                 approved_at=(
357:                     approval_time_factory()
358:                     if command
359:                     in {"/approve", "/approve-goal-target", "/approve-goal-directory"}
360:                     else None
361:                 ),
362:                 defer_artifact_confirmation=(
363:                     command != "/reject"
364:                     and request.artifact_confirmation_requirement is not None
365:                 ),
```

## agent/cli/render.py
SHA256(full file): 083e7b7b3b9d0962c6b5e2acaa54115d5524e0dbaaf6e394422a954d947c9298

```text
105:         if sources:
106:             self._write(self._sources_message(sources))
107:         if (
108:             goal_view.status == GoalStatus.VERIFIED_DONE.value
109:             and goal_view.verification_scope
110:         ):
111:             self._write(
112:                 terminal_text(
113:                     self._verification_scope_message(goal_view.verification_scope),
114:                     allow_newlines=True,
115:                 )
116:             )
117:         if (
118:             goal_view.goal_id is not None
119:             and goal_view.goal_revision is not None
120:             and goal_view.status
121:             in {GoalStatus.VERIFIED_DONE.value, GoalStatus.CANCELLED.value}
122:         ):
123:             terminal_key = (
124:                 goal_view.goal_id,
125:                 goal_view.goal_revision,
126:                 goal_view.status,
127:             )
128:             if terminal_key not in self._terminal_hints:
129:                 self._terminal_hints.add(terminal_key)
130:                 self._write(
131:                     "Task is closed. Use /new to start another task in this workspace."
132:                 )
133:         for warning in result.delivery_warnings:
134:             self._write(f"Warning: {terminal_text(warning)}")
135: 
136:     def render_pending(self, state: ConversationState) -> None:
137:         """每次输入前从 authoritative state 只读投影 exact durable decision；
138:         不暴露内部 request identity。
139:         """
140: 
141:         active = state.active_run
142:         if active is None:
143:             return
144:         if (
145:             active.status is ActiveRunStatus.AWAITING_DISCLOSURE
146:             and state.provider_disclosure_request is not None
147:         ):
148:             request = state.provider_disclosure_request
149:             self._write(
150:                 self._disclosure_message(
151:                     destination=request.canonical_destination,
152:                     model=request.model,
153:                     data_classes=request.data_classes,
154:                 )
155:             )
156:             return
157:         if active.status is ActiveRunStatus.AWAITING_APPROVAL and isinstance(
158:             active.pending_request, ApprovalRequest
```

