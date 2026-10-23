# 审计源码摘录（基线 97f5c58；只读公开文件）

行号是基线一基行号。摘录之外请给需要补看的符号，不猜实现。

## agent/runtime/contracts.py:780–795

```text
780: 
781: 
782: GOAL_TARGET_AUTHORIZATION_MAX_USES = 16
783: GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES = 60
784: _GOAL_AUTHORIZATION_SENSITIVE_COMPONENTS = frozenset(
785:     {
786:         ".aws",
787:         ".claude",
788:         ".codex",
789:         ".git",
790:         ".gnupg",
791:         ".kube",
792:         ".ssh",
793:         ".ua",
794:         "credentials",
795:         "graphify-out",
```

## agent/runtime/contracts.py:815–856

```text
815:     binding_id: str
816:     goal_id: str
817:     goal_revision: int
818:     workspace_identity_digest: str
819:     operation: str
820:     normalized_target: str
821:     source_kind: AuthoritySourceKind
822:     source_id: str
823:     source_digest: str
824:     issued_at: str
825:     expires_at: str
826:     max_uses: int
827:     uses_consumed: int
828:     binding_digest: str
829:     scope: GoalAuthorizationScope = GoalAuthorizationScope.EXACT_FILE
830: 
831:     def __post_init__(self) -> None:
832:         if not isinstance(self.source_kind, AuthoritySourceKind):
833:             raise ValueError("authority source must be authoritative user or durable state")
834:         if not all(
835:             (
836:                 self.binding_id,
837:                 self.goal_id,
838:                 self.workspace_identity_digest,
839:                 self.operation,
840:                 self.normalized_target,
841:                 self.source_id,
842:                 self.source_digest,
843:                 self.issued_at,
844:                 self.expires_at,
845:                 self.binding_digest,
846:             )
847:         ):
848:             raise ValueError("goal authorization binding fields must not be empty")
849:         if self.goal_revision < 1:
850:             raise ValueError("goal authorization revision must be positive")
851:         if not isinstance(self.scope, GoalAuthorizationScope):
852:             raise ValueError("goal authorization scope must be closed")
853:         if self.max_uses != GOAL_TARGET_AUTHORIZATION_MAX_USES:
854:             raise ValueError("goal authorization max_uses must use the fixed bound")
855:         if not 0 <= self.uses_consumed <= self.max_uses:
856:             raise ValueError("goal authorization uses_consumed is outside its bound")
```

## agent/runtime/contracts.py:949–973

```text
949:         *,
950:         goal_id: str,
951:         goal_revision: int,
952:         workspace_identity_digest: str,
953:         operation: str,
954:         normalized_target: str,
955:     ) -> bool:
956:         return (
957:             self.goal_id == goal_id
958:             and self.goal_revision == goal_revision
959:             and self.workspace_identity_digest == workspace_identity_digest
960:             and self.operation == operation
961:             and (
962:                 self.normalized_target == normalized_target
963:                 if self.scope is GoalAuthorizationScope.EXACT_FILE
964:                 else _path_is_within_directory(
965:                     normalized_target,
966:                     self.normalized_target,
967:                 )
968:             )
969:             and self.binding_digest == self._expected_digest()
970:         )
971: 
972: 
973: def _path_is_within_directory(target: str, directory: str) -> bool:
```

## agent/runtime/contracts.py:1317–1402

```text
1317: @dataclass(frozen=True, slots=True)
1318: class ProviderDisclosureReceipt:
1319:     receipt_id: str
1320:     request_digest: str
1321:     acknowledged_action_seq: int
1322:     acknowledged_at: str
1323: 
1324:     def __post_init__(self) -> None:
1325:         if not self.receipt_id or not self.request_digest or not self.acknowledged_at:
1326:             raise ValueError("provider disclosure receipt fields must not be empty")
1327:         if self.acknowledged_action_seq < 1:
1328:             raise ValueError("disclosure acknowledgement action sequence must be positive")
1329: 
1330: 
1331: @dataclass(frozen=True, slots=True)
1332: class ProviderDisclosureRequest:
1333:     disclosure_id: str
1334:     provider_descriptor_digest: str
1335:     canonical_destination: str
1336:     model: str
1337:     data_classes: tuple[str, ...]
1338:     request_digest: str
1339: 
1340:     def __post_init__(self) -> None:
1341:         if not all(
1342:             (
1343:                 self.disclosure_id,
1344:                 self.provider_descriptor_digest,
1345:                 self.canonical_destination,
1346:                 self.model,
1347:                 self.request_digest,
1348:             )
1349:         ):
1350:             raise ValueError("provider disclosure request fields must not be empty")
1351:         if not self.data_classes or any(not item for item in self.data_classes):
1352:             raise ValueError("provider disclosure data classes must not be empty")
1353:         if tuple(sorted(set(self.data_classes))) != self.data_classes:
1354:             raise ValueError("provider disclosure data classes must be sorted and unique")
1355:         if self.request_digest != self._expected_digest():
1356:             raise ValueError("provider disclosure request digest mismatch")
1357: 
1358:     def _expected_digest(self) -> str:
1359:         return canonical_json_digest(
1360:             {
1361:                 "disclosure_id": self.disclosure_id,
1362:                 "provider_descriptor_digest": self.provider_descriptor_digest,
1363:                 "canonical_destination": self.canonical_destination,
1364:                 "model": self.model,
1365:                 "data_classes": self.data_classes,
1366:             }
1367:         )
1368: 
1369:     @classmethod
1370:     def create(
1371:         cls,
1372:         *,
1373:         disclosure_id: str,
1374:         provider_descriptor_digest: str,
1375:         canonical_destination: str,
1376:         model: str,
1377:         data_classes: tuple[str, ...],
1378:     ) -> ProviderDisclosureRequest:
1379:         values = {
1380:             "disclosure_id": disclosure_id,
1381:             "provider_descriptor_digest": provider_descriptor_digest,
1382:             "canonical_destination": canonical_destination,
1383:             "model": model,
1384:             "data_classes": tuple(sorted(set(data_classes))),
1385:         }
1386:         return cls(**values, request_digest=canonical_json_digest(values))
1387: 
1388:     def acknowledge(
1389:         self,
1390:         *,
1391:         receipt_id: str,
1392:         acknowledged_action_seq: int,
1393:         acknowledged_at: str,
1394:     ) -> ProviderDisclosureReceipt:
1395:         return ProviderDisclosureReceipt(
1396:             receipt_id=receipt_id,
1397:             request_digest=self.request_digest,
1398:             acknowledged_action_seq=acknowledged_action_seq,
1399:             acknowledged_at=acknowledged_at,
1400:         )
1401: 
1402: 
```

## agent/runtime/contracts.py:1998–2045

```text
1998: 
1999: 
2000: @dataclass(frozen=True, slots=True)
2001: class ProcessAuthorityLeaseV1:
2002:     """ResolveApproval 铸造的 exact、有限、可过期、可撤销 durable lease（KTD2/KTD4）。
2003: 
2004:     匹配要求所有 binding identity exact equal；不存在 wildcard/prefix/regex。uses_consumed
2005:     在 intent 进入 durable EXECUTING checkpoint 时单调递增。Goal revision/terminal transition
2006:     使其失效。
2007:     """
2008: 
2009:     lease_id: str
2010:     lease_digest: str
2011:     candidate_digest: str
2012:     goal_id: str
2013:     goal_revision: int
2014:     workspace_identity_digest: str
2015:     command_fingerprint: str
2016:     readable_command: str
2017:     executable_digest: str
2018:     argv_digest: str
2019:     cwd_digest: str
2020:     resource_profile: str
2021:     environment_policy_digest: str
2022:     execution_authority: ExecutionAuthorityClass
2023:     approved_request_identity: str
2024:     issued_at: str
2025:     expires_at: str
2026:     max_uses: int = 8
2027:     uses_consumed: int = 0
2028: 
2029:     @classmethod
2030:     def create(
2031:         cls,
2032:         *,
2033:         lease_id: str,
2034:         candidate_digest: str,
2035:         goal_id: str,
2036:         goal_revision: int,
2037:         workspace_identity_digest: str,
2038:         command_fingerprint: str,
2039:         readable_command: str,
2040:         executable_digest: str,
2041:         argv_digest: str,
2042:         cwd_digest: str,
2043:         resource_profile: str,
2044:         environment_policy_digest: str,
2045:         execution_authority: ExecutionAuthorityClass,
```

## agent/runtime/contracts.py:4288–4300

```text
4288:         object.__setattr__(self, "goal_authorizations", tuple(self.goal_authorizations))
4289:         if not isinstance(self.interaction_state, InteractionState):
4290:             raise ValueError("interaction_state must be a closed value")
4291:         if self.provider_disclosure_receipt is not None and (
4292:             self.provider_disclosure_request is None
4293:             or self.provider_disclosure_receipt.request_digest
4294:             != self.provider_disclosure_request.request_digest
4295:         ):
4296:             raise ValueError("provider disclosure receipt must bind the current request")
4297:         correlation_ids = tuple(receipt.correlation_id for receipt in self.control_receipts)
4298:         if len(set(correlation_ids)) != len(correlation_ids):
4299:             raise ValueError("control receipt correlation_id must be unique")
4300:         object.__setattr__(self, "control_receipts", tuple(self.control_receipts))
```

## agent/runtime/contracts.py:4535–4555

```text
4535: 
4536: 
4537: @dataclass(frozen=True, slots=True, kw_only=True)
4538: class AcknowledgeProviderDisclosure(RuntimeAction):
4539:     request_digest: str
4540:     acknowledged_at: str
4541: 
4542:     def __post_init__(self) -> None:
4543:         if not self.request_digest or not self.acknowledged_at:
4544:             raise ValueError("provider disclosure acknowledgement fields must not be empty")
4545: 
4546: 
4547: def _validate_goal_action(goal_id: str, goal_revision: int) -> None:
4548:     if not goal_id:
4549:         raise ValueError("goal action must bind a goal")
4550:     if goal_revision < 1:
4551:         raise ValueError("goal action revision must be positive")
4552: 
4553: 
4554: @dataclass(frozen=True, slots=True, kw_only=True)
4555: class SelectGoal(RuntimeAction):
```

## agent/runtime/contracts.py:5582–5600

```text
5582: def source_data_class(source_kind: SourceKind) -> str:
5583:     if source_kind.value.startswith("history_"):
5584:         return "first_agent_history"
5585:     if source_kind.value.startswith("workspace_"):
5586:         return "workspace_excerpt"
5587:     return "public_web_content"
5588: 
5589: 
5590: @dataclass(frozen=True, slots=True)
5591: class SourceReceiptDraft:
5592:     """Source callable 的无权草稿；Kernel 会重算 digest 并追加执行身份。"""
5593: 
5594:     source_kind: SourceKind
5595:     origin_locator: str
5596:     content: str
5597:     observed_at: str
5598:     snapshot_digest: str | None = None
5599:     request_identity: str | None = None
5600:     origin_request_digest: str | None = None
```

## agent/runtime/state.py:1670–1740

```text
1670: 
1671: def pause_for_provider_disclosure(
1672:     state: ConversationState,
1673:     request: ProviderDisclosureRequest,
1674: ) -> ConversationState:
1675:     active = state.active_run
1676:     if active is None or active.phase is not ContinuationPhase.MODEL:
1677:         raise ValueError("provider disclosure must pause before a model send")
1678:     if _has_unknown_effect(state):
1679:         raise ValueError("unknown effect recovery has priority over disclosure")
1680:     goal = state.goal
1681:     if goal is not None and goal.status not in {
1682:         GoalStatus.CANCELLED,
1683:         GoalStatus.VERIFIED_DONE,
1684:     }:
1685:         goal = replace(goal, status=GoalStatus.NEEDS_AUTHORITY)
1686:     return replace(
1687:         state,
1688:         revision=state.revision + 1,
1689:         goal=goal,
1690:         provider_disclosure_request=request,
1691:         provider_disclosure_receipt=None,
1692:         active_run=replace(
1693:             active,
1694:             status=ActiveRunStatus.AWAITING_DISCLOSURE,
1695:             owner_invocation_id=None,
1696:         ),
1697:     )
1698: 
1699: 
1700: def acknowledge_provider_disclosure(
1701:     state: ConversationState,
1702:     action: AcknowledgeProviderDisclosure,
1703: ) -> ConversationState:
1704:     request = state.provider_disclosure_request
1705:     active = state.active_run
1706:     if request is None or request.request_digest != action.request_digest:
1707:         raise ValueError("provider disclosure acknowledgement does not match")
1708:     goal = state.goal
1709:     if active is None:
1710:         # /pause 允许落在 pending disclosure 上（2026-10-17 E1-B 真实旅程实测）：
1711:         # active run 已安全停止，但披露决定仍 durable。/resume 之后 ack 必须点燃
1712:         # 继续回合——与 SubmitMessage 的点火同型，否则挂起回合被静默丢弃成 idle。
1713:         if (
1714:             state.provider_disclosure_receipt is not None
1715:             or goal is None
1716:             or goal.status is not GoalStatus.GOAL_READY
1717:         ):
1718:             raise ValueError("provider disclosure acknowledgement does not match")
1719:         return replace(
1720:             state,
1721:             provider_disclosure_receipt=request.acknowledge(
1722:                 receipt_id=f"disclosure-receipt:{action.action_seq}",
1723:                 acknowledged_action_seq=action.action_seq,
1724:                 acknowledged_at=action.acknowledged_at,
1725:             ),
1726:             active_run=ActiveRun(run_id=f"resume-{action.action_seq}"),
1727:         )
1728:     if active.status is not ActiveRunStatus.AWAITING_DISCLOSURE:
1729:         raise ValueError("provider disclosure acknowledgement does not match")
1730:     if goal is not None and goal.status is GoalStatus.NEEDS_AUTHORITY:
1731:         goal = replace(goal, status=GoalStatus.GOAL_READY)
1732:     return replace(
1733:         state,
1734:         goal=goal,
1735:         provider_disclosure_receipt=request.acknowledge(
1736:             receipt_id=f"disclosure-receipt:{action.action_seq}",
1737:             acknowledged_action_seq=action.action_seq,
1738:             acknowledged_at=action.acknowledged_at,
1739:         ),
1740:         active_run=replace(active, status=ActiveRunStatus.RUNNABLE),
```

## agent/runtime/state.py:2020–2072

```text
2020:         replay_records=tuple(records),
2021:     )
2022: 
2023: 
2024: def _goal_target_authorization_scope(
2025:     state: ConversationState,
2026:     pending: ApprovalRequest,
2027:     active: ActiveRun,
2028:     *,
2029:     directory: bool,
2030: ) -> str | None:
2031:     goal = state.goal
2032:     call = active.tool_calls[active.batch_cursor]
2033:     target = call.arguments.get("path")
2034:     if not (
2035:         goal is not None
2036:         and pending.tool_name in {"write_file", "edit_file"}
2037:         and call.name == pending.tool_name
2038:         and pending.side_effect == SideEffectClass.WRITE.value
2039:         and pending.egress in {None, EgressClass.NONE.value}
2040:         and isinstance(target, str)
2041:     ):
2042:         return None
2043:     if not directory:
2044:         if target in goal.targets and safe_goal_authorization_target(target):
2045:             return target
2046:         # W2：散文 targets 下，当前 Goal 已由 Runtime 准入（真实用户批准来源，
2047:         # `_admit_approved_file_criterion` 铸造）的精确文件同样可作为复用授权
2048:         # 候选。只认 durable admitted criterion 的闭合 predicate path，不把
2049:         # 任意 pending path 或模型自述提升为候选；显示/解析/铸造共用本判断。
2050:         if safe_goal_authorization_target(target) and any(
2051:             criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
2052:             and criterion.predicate.get("path") == target
2053:             for criterion in goal.admitted_criteria
2054:         ):
2055:             return target
2056:         return None
2057:     target_parts = target.split("/")
2058:     candidates = []
2059:     for goal_target in goal.targets:
2060:         goal_parts = goal_target.split("/")
2061:         if (
2062:             len(target_parts) > len(goal_parts)
2063:             and safe_goal_authorization_target(target)
2064:             and safe_goal_authorization_target(goal_target)
2065:             and all(part not in {"", ".", ".."} for part in (*target_parts, *goal_parts))
2066:             and target_parts[: len(goal_parts)] == goal_parts
2067:         ):
2068:             candidates.append(goal_target)
2069:     return max(candidates, key=lambda item: len(item.split("/")), default=None)
2070: 
2071: 
2072: def _action_is_legal(state: ConversationState, action: Action) -> tuple[bool, str | None]:
```

## agent/runtime/state.py:2635–2685

```text
2635: def _mint_goal_target_authorization(
2636:     state: ConversationState,
2637:     pending: ApprovalRequest,
2638:     action: ResolveApproval,
2639:     *,
2640:     active: ActiveRun,
2641: ) -> ConversationState:
2642:     """把用户 opt-in 绑定为当前 Goal 的文件或明确目录目标。"""
2643: 
2644:     if not (action.authorize_goal_target or action.authorize_goal_directory):
2645:         return state
2646:     directory = action.authorize_goal_directory
2647:     authorized_target = _goal_target_authorization_scope(
2648:         state,
2649:         pending,
2650:         active,
2651:         directory=directory,
2652:     )
2653:     if authorized_target is None:
2654:         raise ValueError("goal authorization requires a current Goal file or directory target")
2655:     goal = state.goal
2656:     assert goal is not None
2657:     if action.approved_at is None:
2658:         raise ValueError("approved_at is required for goal target authorization")
2659:     issued_at = _require_zoned_rfc3339(action.approved_at)
2660:     binding = GoalAuthorizationBinding.create(
2661:         binding_id=f"goal-target-authority:{pending.request_id}",
2662:         goal_id=goal.goal_id,
2663:         goal_revision=goal.revision,
2664:         workspace_identity_digest=goal.workspace_identity_digest,
2665:         operation=pending.tool_name,
2666:         normalized_target=authorized_target,
2667:         scope=(
2668:             GoalAuthorizationScope.DIRECTORY if directory else GoalAuthorizationScope.EXACT_FILE
2669:         ),
2670:         source_kind=AuthoritySourceKind.HUMAN_APPROVAL,
2671:         source_id=pending.request_id,
2672:         source_digest=canonical_action_digest(action),
2673:         issued_at=issued_at,
2674:         expires_at=_add_minutes_rfc3339(
2675:             issued_at,
2676:             GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES,
2677:         ),
2678:     )
2679:     retained = tuple(
2680:         item
2681:         for item in state.goal_authorizations
2682:         if not (
2683:             item.operation == binding.operation
2684:             and item.normalized_target == binding.normalized_target
2685:             and item.scope is binding.scope
```

## agent/cli/app.py:243–302

```text
243:     normalized = raw.strip().casefold()
244: 
245:     disclosure = state.provider_disclosure_request
246:     goal = state.goal
247:     # B（2026-10-18）：活跃与恢复形状共用唯一只读判定（views 谓词）；
248:     # render/yes/no/空白同源，Runtime 仍校验 action 合法性。
249:     disclosure_pending = pending_provider_disclosure_decision(state)
250:     if disclosure_pending and normalized in _AFFIRMATIVE:
251:         assert disclosure is not None
252:         return (
253:             AcknowledgeProviderDisclosure(
254:                 **common,
255:                 request_digest=disclosure.request_digest,
256:                 acknowledged_at="operator-confirmed",
257:             ),
258:             None,
259:         )
260:     if disclosure_pending and (normalized in _NEGATIVE or not normalized):
261:         # REPL 在到达 parse 前已由 contextual exit/空输入路径安全退出；
262:         # 该兜底只约束直接调用方（如 TUI/probe）不把拒绝写成业务 SubmitMessage。
263:         return None, _PENDING_DISCLOSURE_REFUSAL
264:     if (
265:         disclosure is not None
266:         and state.provider_disclosure_receipt is None
267:         and state.active_run is None
268:         and goal is not None
269:         and goal.status is GoalStatus.PAUSED
270:         and normalized in _AFFIRMATIVE | _NEGATIVE
271:     ):
272:         # 窄范围 PAUSED 保护：暂停窗口里的裸 yes/no 不产生业务消息，先 /resume。
273:         return (
274:             None,
275:             "The task is paused; run /resume before answering the pending disclosure.",
276:         )
277: 
278:     approval = _approval_request(state)
279:     if approval is not None and normalized in _AFFIRMATIVE | _NEGATIVE:
280:         approved = normalized in _AFFIRMATIVE
281:         return (
282:             build_resolve_approval(
283:                 state,
284:                 request_id=approval.request_id,
285:                 binding_digest=approval.binding_digest,
286:                 approved=approved,
287:                 approved_at=(approval_time_factory() if normalized in _AFFIRMATIVE else None),
288:                 defer_artifact_confirmation=(
289:                     normalized in _AFFIRMATIVE
290:                     and approval.artifact_confirmation_requirement is not None
291:                 ),
292:                 # P2（对抗审查 2026-10-18）：重绑定只在审批提示已如实披露时
293:                 # 随这次批准授权——用户看到的那条提示就是他的同意范围。
294:                 authorize_obligation_rebind=(
295:                     approved and project_obligation_rebind_disclosure(state) is not None
296:                 ),
297:             ),
298:             None,
299:         )
300: 
301:     recovery = _recovery_request(state)
302:     if recovery is not None:
```

## agent/cli/app.py:377–422

```text
377:         "/approve",
378:         "/approve-goal-target",
379:         "/approve-goal-directory",
380:         "/reject",
381:     }:
382:         request = _approval_request(state)
383:         if request is None:
384:             return None, "No approval request is pending."
385:         if command in {"/approve-goal-target", "/approve-goal-directory"} and (not separator):
386:             # R4：文件审批提示不展示内部 request identity；无参数短命令绑定
387:             # REPL 刚显示的同一 authoritative pending request（显示与解析共用
388:             # 循环内同一 snapshot；输入期间漂移由 expected_revision CAS
389:             # fail closed，不重绑新请求）。适用范围与 Runtime 铸授权共用
390:             # 同一 scope 判定，不适用即拒绝，绝不静默降级为逐笔批准。
391:             file_scope, directory_scope = project_goal_authorization_scopes(state)
392:             applicable = file_scope if command == "/approve-goal-target" else directory_scope
393:             if applicable is None:
394:                 return None, ("The pending approval has no matching Goal scope for this command.")
395:         elif not separator or argument != request.request_id:
396:             return None, "Use the exact pending request ID."
397:         return (
398:             build_resolve_approval(
399:                 state,
400:                 request_id=request.request_id,
401:                 binding_digest=request.binding_digest,
402:                 approved=command != "/reject",
403:                 approved_at=(
404:                     approval_time_factory()
405:                     if command in {"/approve", "/approve-goal-target", "/approve-goal-directory"}
406:                     else None
407:                 ),
408:                 defer_artifact_confirmation=(
409:                     command != "/reject" and request.artifact_confirmation_requirement is not None
410:                 ),
411:                 authorize_goal_target=command == "/approve-goal-target",
412:                 authorize_goal_directory=command == "/approve-goal-directory",
413:                 authorize_obligation_rebind=(
414:                     command == "/approve"
415:                     and project_obligation_rebind_disclosure(state) is not None
416:                 ),
417:             ),
418:             None,
419:         )
420: 
421:     if command in {"/resolve-success", "/resolve-failed"}:
422:         request = _recovery_request(state)
```

## agent/cli/render.py:326–389

```text
326:     def _approval_message(
327:         *,
328:         tool_name: object,
329:         risk: object,
330:         side_effect: object,
331:         preview: object,
332:         artifact_path: str | None = None,
333:         authorization_scopes: tuple[str | None, str | None] = (None, None),
334:         goal_scope_unavailable: bool = False,
335:         obligation_rebind_disclosure: str | None = None,
336:     ) -> str:
337:         lines = [
338:             "Approval required",
339:             f"tool: {terminal_text(tool_name)}",
340:             f"risk/effect: {terminal_text(risk)}/{terminal_text(side_effect)}",
341:             f"preview: {terminal_text(preview, allow_newlines=True)}",
342:         ]
343:         if artifact_path is None:
344:             lines.append("Execute this operation? [y/N]")
345:         else:
346:             lines.append(
347:                 f"This command may generate {terminal_text(artifact_path)}. "
348:                 "Approve generation now? [y/N] The generated file is not confirmed yet; "
349:                 "First Agent must show its current content for a separate confirmation."
350:             )
351:         # R4：适用范围内展示无参数范围授权短命令与准确边界（16 次执行/60 分钟
352:         # 是 Runtime 铸授权的固定 bound）；不适用时完全不出现。
353:         file_scope, directory_scope = authorization_scopes
354:         if file_scope is not None or directory_scope is not None:
355:             lines.append(
356:                 "Scope authorization for the current task only (reusable; "
357:                 "revoke anytime with /revoke-goal-target):"
358:             )
359:             if file_scope is not None:
360:                 lines.append(
361:                     f"/approve-goal-target — approve {terminal_text(tool_name)} for the "
362:                     f"exact file {terminal_text(file_scope)} in this task "
363:                     "(at most 16 executions, expires after 60 minutes, "
364:                     "any goal change ends it)"
365:                 )
366:             if directory_scope is not None:
367:                 lines.append(
368:                     f"/approve-goal-directory — approve {terminal_text(tool_name)} for "
369:                     f"regular files under the Goal directory "
370:                     f"{terminal_text(directory_scope)} in this task "
371:                     "(at most 16 executions, expires after 60 minutes, "
372:                     "any goal change ends it)"
373:                 )
374:             lines.append("yes approves only this one operation.")
375:         elif goal_scope_unavailable:
376:             # E1-A（2026-10-16）：spec 驱动 Goal 的 targets 是散文时，写入复用
377:             # 授权静默不适用（实测 0/17）；如实说明，避免"已授权"误读。
378:             lines.append(
379:                 "No reusable Goal scope for this write: its path is not covered by "
380:                 "the current task targets. Approving here covers only this one "
381:                 "operation; later writes will each require approval again."
382:             )
383:         if obligation_rebind_disclosure is not None:
384:             # P2（对抗审查 2026-10-18）：批准=执行这一笔；若本次批准会同时把
385:             # 一条已失败的验证义务重绑定到这条命令，必须在批准前如实披露。
386:             lines.append(terminal_text(obligation_rebind_disclosure))
387:         return "\n".join(lines)
388: 
389:     @staticmethod
```

## agent/runtime/views.py:178–232

```text
178: def pending_provider_disclosure_decision(state: ConversationState) -> bool:
179:     """B（2026-10-18）：pending provider 外发确认的唯一只读判定。
180: 
181:     活跃 AWAITING_DISCLOSURE 与 /pause→/resume 后的孤儿形状
182:     （active=None、Goal=GOAL_READY）在 request 非空且 receipt=None 时
183:     是同一个 answerable pending 决策；render_pending 与 CLI 的
184:     y/n/空回车路由共用本判定，Runtime 仍独立校验 action 合法性。
185:     只读，不推进状态。
186:     """
187: 
188:     if state.provider_disclosure_request is None:
189:         return False
190:     if state.provider_disclosure_receipt is not None:
191:         return False
192:     active = state.active_run
193:     if active is not None:
194:         return active.status is ActiveRunStatus.AWAITING_DISCLOSURE
195:     goal = state.goal
196:     return goal is not None and goal.status is GoalStatus.GOAL_READY
197: 
198: 
199: def project_goal_authorization_scopes(
200:     state: ConversationState,
201: ) -> tuple[str | None, str | None]:
202:     """R4：当前 pending 文件审批的 (精确文件 scope, 目录 scope) 纯投影。
203: 
204:     与 Runtime 铸授权共用 agent.runtime.state 的同一 scope 判定，None 表示
205:     对应无参数短命令不适用；不得触发 Runtime、Provider、Tool 或持久化。
206:     """
207: 
208:     from agent.runtime.state import _goal_target_authorization_scope
209: 
210:     active = state.active_run
211:     if (
212:         active is None
213:         or active.status is not ActiveRunStatus.AWAITING_APPROVAL
214:         or not isinstance(active.pending_request, ApprovalRequest)
215:         or not active.tool_calls
216:         or active.batch_cursor >= len(active.tool_calls)
217:     ):
218:         return (None, None)
219:     pending = active.pending_request
220:     return (
221:         _goal_target_authorization_scope(state, pending, active, directory=False),
222:         _goal_target_authorization_scope(state, pending, active, directory=True),
223:     )
224: 
225: 
226: def project_goal_target_reuse_unavailable(state: ConversationState) -> bool:
227:     """目标写入审批的复用透明度纯投影（与 R4 共用同一 scope 判定）。
228: 
229:     spec 驱动 Goal 的 targets 常为散文，write_file/edit_file 不在其中时
230:     复用授权静默不适用（E1-A 实测 0/17）；True 表示"Goal 存在、本次是
231:     目标写入、但没有任何可复用 scope"，审批提示据此如实说明，不改语义。
232:     """
```

## agent/runtime/loop.py:1587–1608

```text
1587:                             current, action, warnings, error
1588:                         )
1589:                     # 与普通 provider 分支相同的 disclosure exact-receipt 门禁。
1590:                     disclosure = self._required_disclosure(context)
1591:                     if disclosure is not None and (
1592:                         current.state.provider_disclosure_receipt is None
1593:                         or current.state.provider_disclosure_receipt.request_digest
1594:                         != disclosure.request_digest
1595:                     ):
1596:                         paused = pause_for_provider_disclosure(current.state, disclosure)
1597:                         return self._finish(
1598:                             current,
1599:                             action,
1600:                             status=RunStatus.AWAITING_DISCLOSURE,
1601:                             warnings=warnings,
1602:                             event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
1603:                             message="remote provider disclosure acknowledgement required",
1604:                             outcome_state=paused,
1605:                         )
1606:                     if (
1607:                         self._limits.max_input_tokens is not None
1608:                         and input_tokens + context.budget.estimated_input_tokens
```

## agent/runtime/loop.py:1739–1762

```text
1739:                 return self._finish_context_limit(current, action, warnings, error)
1740:             disclosure = self._required_disclosure(context)
1741:             if disclosure is not None and (
1742:                 current.state.provider_disclosure_receipt is None
1743:                 or current.state.provider_disclosure_receipt.request_digest
1744:                 != disclosure.request_digest
1745:             ):
1746:                 paused = pause_for_provider_disclosure(current.state, disclosure)
1747:                 return self._finish(
1748:                     current,
1749:                     action,
1750:                     status=RunStatus.AWAITING_DISCLOSURE,
1751:                     warnings=warnings,
1752:                     event_kind=RuntimeEventKind.DISCLOSURE_REQUESTED,
1753:                     message="remote provider disclosure acknowledgement required",
1754:                     outcome_state=paused,
1755:                 )
1756:             if (
1757:                 not recovering_persisted_response
1758:                 and background_binding is not None
1759:                 and active.input_tokens_used + context.budget.estimated_input_tokens
1760:                 > background_binding.max_input_tokens
1761:             ):
1762:                 paused = pause_for_limit(current.state)
```

## agent/runtime/loop.py:4341–4381

```text
4341:             for definition in self._tool_runtime.definitions()
4342:         )
4343: 
4344:     def _required_disclosure(
4345:         self,
4346:         context,
4347:     ) -> ProviderDisclosureRequest | None:
4348:         descriptor = self._provider_descriptor
4349:         if descriptor is None or not descriptor.remote:
4350:             return None
4351:         return ProviderDisclosureRequest.create(
4352:             disclosure_id=f"provider:{descriptor.identity_digest[:16]}",
4353:             provider_descriptor_digest=descriptor.identity_digest,
4354:             canonical_destination=descriptor.canonical_destination,
4355:             model=descriptor.model,
4356:             data_classes=context.data_classes,
4357:         )
4358: 
4359:     @staticmethod
4360:     def _goal_authorization_for(state: ConversationState, call: ToolCall):
4361:         goal = state.goal
4362:         target = call.arguments.get("path")
4363:         if goal is None or not isinstance(target, str):
4364:             return None
4365:         return next(
4366:             (
4367:                 binding
4368:                 for binding in state.goal_authorizations
4369:                 if binding.authorizes(
4370:                     goal_id=goal.goal_id,
4371:                     goal_revision=goal.revision,
4372:                     workspace_identity_digest=goal.workspace_identity_digest,
4373:                     operation=call.name,
4374:                     normalized_target=target,
4375:                 )
4376:             ),
4377:             None,
4378:         )
4379: 
4380:     @staticmethod
4381:     def _fact_admission_for(
```

## agent/runtime/context.py:188–207

```text
188: def _fact_disclosure_data_classes(
189:     kind: FactKind,
190:     source_data_classes: tuple[str, ...],
191: ) -> tuple[str, ...]:
192:     """fact kind → consent disclosure data class 的小纯 helper。
193: 
194:     普通 build 的单 fact 投影与 compaction payload 分类共享同一映射，
195:     避免两处语义漂移：USER_MESSAGE→user_messages，CONTEXT_SUMMARY→
196:     conversation_summary，TOOL_RESULT→ receipts 验证出的 source 类别
197:     （generic 时为 tool_results），其余（assistant/tool_calls/policy）→
198:     conversation_history。
199:     """
200: 
201:     if kind is FactKind.TOOL_RESULT:
202:         return source_data_classes
203:     if kind is FactKind.USER_MESSAGE:
204:         return ("user_messages",)
205:     if kind is FactKind.CONTEXT_SUMMARY:
206:         return ("conversation_summary",)
207:     return ("conversation_history",)
```

## agent/runtime/context.py:466–490

```text
466:         state: ConversationState,
467:         action: Action,
468:         tools: tuple[ToolDefinition, ...],
469:     ) -> ContextPack:
470:         plan = self._plan(state, action, tools, collect_sources=True)
471:         messages = tuple(message for group in plan.selected for message in group.messages)
472:         data_classes = {
473:             "system_policy",
474:             *(data_class for group in plan.selected for data_class in group.data_classes),
475:         }
476:         if plan.exposed_tools:
477:             data_classes.add("tool_schemas")
478:         if state.control_receipts:
479:             data_classes.add("control_receipts")
480:         return ContextPack(
481:             system=plan.system_policy,
482:             messages=messages,
483:             tools=plan.exposed_tools,
484:             control_schema=plan.control_schema,
485:             control_receipts=state.control_receipts,
486:             data_classes=tuple(sorted(data_classes)),
487:             goal_bootstrap=plan.goal_bootstrap,
488:             budget=self._budget_report(plan),
489:         )
490: 
```

## agent/runtime/context.py:676–704

```text
676:     def _compaction_disclosure_data_classes(
677:         self,
678:         facts: tuple[ConversationFact, ...],
679:         conversation_id: str,
680:     ) -> tuple[str, ...]:
681:         """F3：由实际进入 compaction payload 的 facts 精确推导 disclosure 类别。
682: 
683:         不复用普通 build 的 active-Goal stale-source omission：compaction
684:         发送 raw historical content，TOOL_RESULT 的类别必须由 receipts 重新
685:         验证得出（与普通 build 同一校验器），metadata 不一致在 provider
686:         调用前 fail closed（ContextLimitError）。
687:         """
688: 
689:         classes: set[str] = {"system_policy"}
690:         for fact in facts:
691:             source_data_classes: tuple[str, ...] = ()
692:             if fact.kind is FactKind.TOOL_RESULT:
693:                 source_data_classes = validate_tool_result_source(
694:                     fact, conversation_id
695:                 ).data_classes
696:             classes.update(
697:                 _fact_disclosure_data_classes(fact.kind, source_data_classes)
698:             )
699:         return tuple(sorted(classes))
700: 
701:     def _budget_report(self, plan: _ContextPlan) -> BudgetReport:
702:         return BudgetReport(
703:             input_limit=self._limits.max_input_tokens,
704:             estimated_input_tokens=plan.estimated_input_tokens,
```

## agent/runtime/context.py:1370–1387

```text
1370:             "text": self._frame_candidate(candidate),
1371:         }
1372:         return _ContextGroup(
1373:             fact_ids=(candidate.candidate_id,),
1374:             messages=(ModelMessage(role="user", content=(block,)),),
1375:             tool_call_ids=(),
1376:             has_tool_result=False,
1377:             pinned=False,
1378:             data_classes=(
1379:                 {
1380:                     "memory": "workspace_memory",
1381:                     "owner_preferences": "owner_preferences",
1382:                 }.get(candidate.source_name, "recalled_context"),
1383:             ),
1384:         )
1385: 
1386:     def _project_candidate(self, candidate: ContextCandidate) -> ContextCandidate:
1387:         original_digest = candidate.content_digest
```

## agent/runtime/context_source.py:156–216

```text
156: def validate_tool_result_source(
157:     fact: ConversationFact,
158:     conversation_id: str,
159: ) -> ToolResultSourceProjection:
160:     """完整校验单个 TOOL_RESULT 的 source receipts，返回具实 data classes。
161: 
162:     普通 build 的 Goal 投影与 compaction 的 disclosure 分类共用这一校验器：
163:     metadata/receipts 不一致一律 ContextLimitError，绝不信任自报的
164:     ``metadata.data_classes``；无 receipts 的 generic 结果类别为
165:     ``tool_results``。本函数不改写 fact，也不做 Goal 绑定过滤。
166:     """
167: 
168:     metadata = fact.content.get("metadata")
169:     if not isinstance(metadata, dict):
170:         return _GENERIC_PROJECTION
171:     if "source_receipts" not in metadata:
172:         if metadata.get("source_refs") not in (None, []):
173:             raise ContextLimitError("citation source mapping is invalid")
174:         return _GENERIC_PROJECTION
175: 
176:     raw_receipts = metadata.get("source_receipts")
177:     if not isinstance(raw_receipts, list):
178:         raise ContextLimitError("source receipt collection is invalid")
179:     if not raw_receipts:
180:         raw_refs = metadata.get("source_refs")
181:         if raw_refs not in (None, []):
182:             raise ContextLimitError("citation source mapping is incomplete")
183:         return _GENERIC_PROJECTION
184: 
185:     try:
186:         receipts = tuple(SourceReceiptV1.from_json(raw) for raw in raw_receipts)
187:     except ValueError as error:
188:         raise ContextLimitError("source receipt is invalid") from error
189:     if any(receipt.conversation_id != conversation_id for receipt in receipts):
190:         raise ContextLimitError("source receipt conversation mismatch")
191: 
192:     projection = _projection_from_receipts(receipts)
193:     if metadata.get("data_classes") != list(projection.data_classes):
194:         raise ContextLimitError("source receipt data classes are inconsistent")
195:     expected_refs = [
196:         {"source_ref": source_ref, "receipt_digest": receipt.receipt_digest}
197:         for source_ref, receipt in zip(
198:             projection.source_refs,
199:             projection.receipts,
200:             strict=True,
201:         )
202:     ]
203:     if metadata.get("source_refs") != expected_refs:
204:         raise ContextLimitError("source ref mapping is inconsistent")
205:     return projection
206: 
207: 
208: def _projection_from_receipts(
209:     receipts: tuple[SourceReceiptV1, ...],
210: ) -> ToolResultSourceProjection:
211:     source_refs = tuple(
212:         f"source-ref:v1:{receipt.receipt_digest}" for receipt in receipts
213:     )
214:     return ToolResultSourceProjection(
215:         receipts=receipts,
216:         data_classes=tuple(sorted({receipt.data_class for receipt in receipts})),
```

## agent/runtime/checkpoint.py:72–84

```text
72: SCHEMA_VERSION = 10
73: # v3 是 process-authority migration source；v4 是旧 strict process schema；v5 加入
74: # artifact confirmation。v6 绑定 candidate/lease 全部 immutable authority 字段，并把
75: # readable command 持久化到 lease。旧版本显式重算收窄后的 digest；v6 漂移 fail closed。
76: PROCESS_MIGRATION_VERSION = 3
77: PREVIOUS_SCHEMA_VERSION = 4
78: ARTIFACT_SCHEMA_VERSION = 5
79: PROCESS_SCHEMA_VERSION = 6
80: BROWSER_SCHEMA_VERSION = 7
81: BACKGROUND_SCHEMA_VERSION = 8
82: ORIGIN_SCHEMA_VERSION = 9
83: LEGACY_SCHEMA_VERSION = 2
84: DEFAULT_MAX_STATE_BYTES = 8 * 1024 * 1024
```

## agent/runtime/checkpoint.py:549–627

```text
549: 
550:     return _decode_state(data)
551: 
552: 
553: def _encode_state(state: ConversationState) -> bytes:
554:     has_structured_proposal = state.goal is not None and any(
555:         criterion.oracle_kind is not None or criterion.artifact_path is not None
556:         for criterion in state.goal.proposed_criteria
557:     )
558:     version = (
559:         SCHEMA_VERSION
560:         if (
561:             state.workspace_binding is not None
562:             or state.active_run is not None
563:             or state.goal_authorizations
564:             or state.process_leases
565:             or state.sandbox_leases
566:             or state.browser_leases
567:             or state.browser_takeover_pending is not None
568:             or state.background_occurrence_binding is not None
569:             or has_structured_proposal
570:         )
571:         else LEGACY_SCHEMA_VERSION
572:     )
573:     document = {
574:         "schema_version": version,
575:         "state": _state_to_dict(
576:             state,
577:             include_workspace_binding=version == SCHEMA_VERSION,
578:             include_proposed_contract=version == SCHEMA_VERSION,
579:             include_background_binding=version == SCHEMA_VERSION,
580:         ),
581:     }
582:     return (
583:         json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
584:         .encode("utf-8")
585:     )
586: 
587: 
588: def _decode_state(data: bytes) -> ConversationState:
589:     try:
590:         document = json.loads(data.decode("utf-8"))
591:     except (UnicodeDecodeError, json.JSONDecodeError) as error:
592:         raise CheckpointMalformedError("checkpoint is not valid UTF-8 JSON") from error
593:     document = _object(document, "document")
594:     _expect_keys(document, {"schema_version", "state"}, "document")
595:     version = document["schema_version"]
596:     if version not in {
597:         LEGACY_SCHEMA_VERSION,
598:         PROCESS_MIGRATION_VERSION,
599:         PREVIOUS_SCHEMA_VERSION,
600:         ARTIFACT_SCHEMA_VERSION,
601:         PROCESS_SCHEMA_VERSION,
602:         BROWSER_SCHEMA_VERSION,
603:         BACKGROUND_SCHEMA_VERSION,
604:         ORIGIN_SCHEMA_VERSION,
605:         SCHEMA_VERSION,
606:     }:
607:         raise CheckpointVersionError(f"unsupported checkpoint schema version: {version}")
608:     try:
609:         return _state_from_dict(
610:             _object(document["state"], "state"),
611:             include_workspace_binding=version != LEGACY_SCHEMA_VERSION,
612:             process_migration=version == PROCESS_MIGRATION_VERSION,
613:             proposed_contract_current=version
614:             in {
615:                 ARTIFACT_SCHEMA_VERSION,
616:                 PROCESS_SCHEMA_VERSION,
617:                 BROWSER_SCHEMA_VERSION,
618:                 BACKGROUND_SCHEMA_VERSION,
619:                 ORIGIN_SCHEMA_VERSION,
620:                 SCHEMA_VERSION,
621:             },
622:             process_contract_current=version
623:             in {
624:                 PROCESS_SCHEMA_VERSION,
625:                 BROWSER_SCHEMA_VERSION,
626:                 BACKGROUND_SCHEMA_VERSION,
627:                 ORIGIN_SCHEMA_VERSION,
```

## agent/runtime/checkpoint.py:1420–1490

```text
1420:         return None
1421:     return {
1422:         "disclosure_id": value.disclosure_id,
1423:         "provider_descriptor_digest": value.provider_descriptor_digest,
1424:         "canonical_destination": value.canonical_destination,
1425:         "model": value.model,
1426:         "data_classes": list(value.data_classes),
1427:         "request_digest": value.request_digest,
1428:     }
1429: 
1430: 
1431: def _disclosure_request_from_dict(value) -> ProviderDisclosureRequest | None:
1432:     if value is None:
1433:         return None
1434:     value = _object(value, "provider_disclosure_request")
1435:     keys = {
1436:         "disclosure_id",
1437:         "provider_descriptor_digest",
1438:         "canonical_destination",
1439:         "model",
1440:         "data_classes",
1441:         "request_digest",
1442:     }
1443:     _expect_keys(value, keys, "provider_disclosure_request")
1444:     return ProviderDisclosureRequest(
1445:         disclosure_id=_string(value["disclosure_id"], "disclosure_id"),
1446:         provider_descriptor_digest=_string(
1447:             value["provider_descriptor_digest"],
1448:             "provider_descriptor_digest",
1449:         ),
1450:         canonical_destination=_string(
1451:             value["canonical_destination"],
1452:             "canonical_destination",
1453:         ),
1454:         model=_string(value["model"], "provider_model"),
1455:         data_classes=tuple(
1456:             _string(item, "data_class")
1457:             for item in _array(value["data_classes"], "data_classes")
1458:         ),
1459:         request_digest=_string(value["request_digest"], "request_digest"),
1460:     )
1461: 
1462: 
1463: def _disclosure_receipt_to_dict(value: ProviderDisclosureReceipt | None) -> dict | None:
1464:     if value is None:
1465:         return None
1466:     return {
1467:         "receipt_id": value.receipt_id,
1468:         "request_digest": value.request_digest,
1469:         "acknowledged_action_seq": value.acknowledged_action_seq,
1470:         "acknowledged_at": value.acknowledged_at,
1471:     }
1472: 
1473: 
1474: def _disclosure_receipt_from_dict(value) -> ProviderDisclosureReceipt | None:
1475:     if value is None:
1476:         return None
1477:     value = _object(value, "provider_disclosure_receipt")
1478:     keys = {"receipt_id", "request_digest", "acknowledged_action_seq", "acknowledged_at"}
1479:     _expect_keys(value, keys, "provider_disclosure_receipt")
1480:     return ProviderDisclosureReceipt(
1481:         receipt_id=_string(value["receipt_id"], "receipt_id"),
1482:         request_digest=_string(value["request_digest"], "request_digest"),
1483:         acknowledged_action_seq=_integer(
1484:             value["acknowledged_action_seq"],
1485:             "acknowledged_action_seq",
1486:         ),
1487:         acknowledged_at=_string(value["acknowledged_at"], "acknowledged_at"),
1488:     )
1489: 
1490: 
```

## agent/process/tools.py:225–255

```text
225: ) -> str:
226:     # F3（review finding）：argv 逐 token JSON-quoting——literal 且无歧义（列表边界
227:     # 可区分、换行/引号被转义、不可伪造披露行）；§12.1 披露项用真实 profile 数值。
228:     # F2（review finding）：cwd 与 executable token 同标准 JSON-quote——模型可控
229:     # 字符串一律不得能伪造 `limits:`/`executable:` 披露行。
230:     resource = ResourceProfileV1.for_profile(ResourceProfile(profile))
231:     rendered_argv = " ".join(json.dumps(token) for token in argv)
232:     lines = [
233:         f"local_process profile={json.dumps(profile)} cwd={json.dumps(cwd)}",
234:         f"  executable: {json.dumps(executable)} -> {json.dumps(resolved)}",
235:         f"  argv: {rendered_argv}",
236:         (
237:             f"  limits: timeout={resource.wall_deadline_seconds}s, "
238:             f"stdout cap={resource.stdout_cap_bytes} bytes, "
239:             f"stderr cap={resource.stderr_cap_bytes} bytes, "
240:             f"combined cap={resource.combined_cap_bytes} bytes"
241:         ),
242:         (
243:             "  environment: closed allowlist "
244:             "(HOME/TMPDIR/PATH/LANG/LC_CTYPE/TZ); no env inheritance"
245:         ),
246:         (
247:             "  lease: up to 8 uses, expires 60 minutes after approval, "
248:             "revocable (RevokeProcessAuthority)"
249:         ),
250:     ]
251:     lines.append(SAME_UID_TRUST_NOTICE)
252:     return "\n".join(lines)
253: 
254: 
255: def _safe_rmtree(path: str) -> None:
```

## agent/cli/actions.py:115–148

```text
115: 
116: def build_resolve_approval(
117:     state: ConversationState,
118:     *,
119:     request_id: str,
120:     binding_digest: str,
121:     approved: bool,
122:     approved_at: str | None = None,
123:     confirmed_artifact_path: str | None = None,
124:     confirmed_artifact_sha256: str | None = None,
125:     defer_artifact_confirmation: bool = False,
126:     authorize_goal_target: bool = False,
127:     authorize_goal_directory: bool = False,
128:     authorize_obligation_rebind: bool = False,
129: ) -> ResolveApproval:
130:     return ResolveApproval(
131:         conversation_id=state.conversation_id,
132:         action_seq=state.next_action_seq,
133:         expected_revision=state.revision,
134:         request_id=request_id,
135:         binding_digest=binding_digest,
136:         approved=approved,
137:         approved_at=approved_at,
138:         confirmed_artifact_path=confirmed_artifact_path,
139:         confirmed_artifact_sha256=confirmed_artifact_sha256,
140:         defer_artifact_confirmation=defer_artifact_confirmation,
141:         authorize_goal_target=authorize_goal_target,
142:         authorize_goal_directory=authorize_goal_directory,
143:         authorize_obligation_rebind=authorize_obligation_rebind,
144:     )
145: 
146: 
147: def utc_now_rfc3339() -> str:
148:     """返回 adapter 写入 typed action 的带时区批准时刻。"""
```

## README.md:178–193

```text
178: 日常安全决定直接在当前提示下回答：Provider disclosure 和文件审批用 `yes/no`（也支持
179: `y/n/是/否/允许/不允许`）；unknown outcome 必须明确回答 `success`、`failed` 或 `stop`。用户无需复制
180: digest/request ID。以下 slash command 只保留为高级精确接口：
181: 
182: - `/ack-provider DIGEST`
183: - `/approve ID`、`/reject ID`
184: - `/approve-goal-target [ID]`（仅对当前 Goal/revision、当前 workspace、同一文件工具与同一精确
185:   Goal target 复用；最多 16 次实际执行、60 分钟后到期，任务修订/终态也立即失效；普通
186:   `yes`、`a`、`/approve` 仍是逐笔批准。文件审批提示在适用范围内直接展示无参数
187:   `/approve-goal-target`，绑定刚显示的待审批请求；范围不适用时拒绝执行，不静默降级）
188: - `/approve-goal-directory [ID]`（仅在 Goal 已明确列出父目录时，授权同一文件工具访问该目录下
189:   的普通项目文件；不会从当前文件自动猜父目录，敏感路径仍拒绝；无参数形式同样绑定刚显示的
190:   待审批请求；TUI 使用 `Shift+D`）
191: - `/revoke-goal-target`（撤销当前任务的全部文件授权；TUI 可用 `Shift+A` 授予精确文件）
192: - `/resolve-success ID`、`/resolve-failed ID`
193: - `/pause`、`/resume`、`/cancel`、`/exit`
```

## README.md:312–324

```text
312: `additionalProperties` 未显式为 `false`）时，OpenAI-compatible strict 投影会在发送请求前以
313: `unsupported_strict_open_object` fail closed；不会静默关闭 strict，也不会改写生产 schema。已知含开放
314: object 的工具 schema 包括 declared Skill entrypoint 的 `arguments`、`browser_act` 的 `fields`，以及取决于
315: server descriptor 的 MCP 工具。触发与模型是否实际调用该工具无关：只要相应工具出现在本次请求的工具
316: 列表中，请求发送前即失败。
317: 
318: 也可使用 `anthropic_compatible`。两个 adapter 都是有限时的一次请求路径（anthropic 侧为 SSE 流式）；
319: 具体 endpoint 可由兼容服务的 base URL 决定。第一次外发以及 destination/model/data-class 变化时，Runtime
320: 会先显示 destination、model 和 data classes；用户在当前提示下确认后才发送，内部 acknowledgement 仍精确
321: 绑定 digest。ack receipt 持久化在 checkpoint，配置或实际数据类别漂移会自动失效。
322: 
323: ## Skills
324: 
```

## AGENTS.md:1–63

```text
1: # AGENTS.md
2: 
3: 本文件是 `/Users/jinkun.wang/work_space/my-first-agent` 的项目级规则。
4: 
5: ## Project identity
6: 
7: - 项目名是 `my-first-agent`；它不是 Coding Agent 的身份。
8: - 默认在 `main` 工作。除非用户明确要求，不 commit、push、tag 或修改 remote。
9: - 本仓库已于 2026-09-09 冻结为学习里程碑（tag `study-freeze-2026-09-09-candidate`）：含七项 v1
10:   capability 与 015–019 候选能力，全部对当前 identity 为 `implemented-candidate`，不再自动开启新的
11:   优化轮次或 promotion 重绑；当前状态权威见
12:   `docs/architecture/CURRENT_CAPABILITY_STATUS.md`。
13: 
14: ## Architecture invariants
15: 
16: - `AgentRuntime.run_turn` 是唯一 production model/tool loop 和状态变更入口。
17: - `ContextManager` 独占模型上下文选择；`ToolRuntime` 独占 tool callable 调用。
18: - CLI/headless 只翻译 typed action 和渲染 event/result。
19: - Provider adapter 只做 `ContextPack → ModelResponse`；不能推进 state 或执行工具。
20: - 所有副作用都走 policy/approval、`EXECUTING` checkpoint 与 result checkpoint。
21: - 不得加入第二套 loop、service locator、compatibility fallback 或 dormant feature flag。
22: - Memory 需要另行批准的 immutable context-source seam；Skill/MCP/SubAgent 只能作为 governed tools；Scheduler 是 external caller；TUI/Evidence 是 event/action adapter。
23: 
24: 架构依据：
25: 
26: - `docs/architecture/KERNEL_ARCHITECTURE.md`
27: - `docs/architecture/EXTENSION_CONTRACTS.md`
28: - `docs/plans/2026-07-18-001-refactor-minimal-runtime-kernel-plan.md`
29: 
30: ## Scope and simplicity
31: 
32: - 只实现用户明确要求或当前合同必需的最小代码。
33: - 优先复用已有 port；不要为单次使用创建抽象。
34: - 修改必须可追溯到请求；不要顺手重构相邻代码。
35: - 新的关键注释/文档默认用中文，解释边界与原因，不逐行复述代码。
36: 
37: ## Safety
38: 
39: - 不读取或输出 `.env`、secret、credential、真实日志、会话、Memory/MCP/Skill/SubAgent 私有目录。
40: - 除非用户明确授权，不做真实 provider/MCP/外部网络调用。
41: - 凭据只在 composition root 注入，不进入 checkpoint、event 或 context。
42: - 文件工具保持 workspace-relative、no-follow、敏感路径拒绝、bounded I/O 和写入审批。
43: - `.ua/`、`graphify-out/` 等 Coding Agent 辅助产物不是产品运行时，不得打包或误当成能力。
44: 
45: ## Development workflow
46: 
47: - 行为或架构变化先写 Red test，再做最小 Green 实现。
48: - 运行 touched-area tests；完成前运行：
49: 
50: ```bash
51: git diff --check
52: .venv/bin/ruff check .
53: .venv/bin/python -m pytest -q -rx
54: ```
55: 
56: - 测试失败、超时或输出截断都不能算通过。
57: - 工作树可能含用户未跟踪内容；不得删除、覆盖或纳入改动。
58: 
59: ## Graphify
60: 
61: Graphify 是 Coding Agent 的代码理解辅助，不是 `my-first-agent` 产品能力。
62: 当 `graphify-out/graph.json` 存在时，代码库问题优先使用 `graphify query/path/explain`；CLI 不可用时可只读现有 graph。修改代码后仅在确认不会摄入 ignored/private 输入时刷新，否则安全跳过并报告。
63: 
```

## agent/cli/render.py:407 provider prompt

```text
407:     def _disclosure_message(*, destination: object, model: object, data_classes: object) -> str:
408:         data_summary = (
409:             ", ".join(str(item) for item in data_classes)
410:             if isinstance(data_classes, (list, tuple))
411:             else data_classes
412:         )
413:         return (
414:             "Remote provider disclosure required\n"
415:             f"destination: {terminal_text(destination)}\n"
416:             f"model: {terminal_text(model)}\n"
417:             f"data: {terminal_text(data_summary)}\n"
418:             "Allow this information to be sent? [y/N]"
419:         )
420: 
421:     @staticmethod
422:     def _result_message_for_limit(error_code: str | None = None) -> str:
423:         # E1-A 真实旅程（2026-10-16）：累计 model-attempt 预算耗尽后的 /resume
424:         # 会在派发前再次被拒，通用 "Run /resume to continue" 会形成误导循环。
425:         # 只有该原因需要指明真正的继续路径（同 ledger 提高 --max-model-attempts）。
```
