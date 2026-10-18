# 当前公开源码切片（只读送审；行号对应 dirty 工作树）

## agent/runtime/state.py:250-310
```text
250: _PROCESS_ENTRYPOINT_PATTERN = re.compile(
251:     r"(?:运行|执行|run|execute)\s+((?:\./|/)[^\s，。；;,!?！？]+)",
252:     re.IGNORECASE,
253: )
254: _PROCESS_ENTRYPOINT_CLAUSE_BOUNDARY = re.compile(
255:     r"(?:[，。；;,!?！？]+|\.(?=\s|$)|但是|但|而是|\bbut\b|\bhowever\b)",
256:     re.IGNORECASE,
257: )
258: # W1：明确文件交付对象的有限识别（与显式 process 要求同型，只认直接正向
259: # 精确 workspace-relative 路径；阅读/参照/引文/疑问/禁止语境不进下界）。
260: _DELIVERABLE_PATH_TOKEN = re.compile(
261:     r"(?<![/\w.])("
262:     r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?"
263:     r"(?:/[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?)+"
264:     r"|[A-Za-z0-9_][A-Za-z0-9_-]*\.[A-Za-z0-9]{1,12}"
265:     r")"
266: )
267: _DELIVERABLE_VERB_PATTERN = re.compile(
268:     r"(?:创建|新建|生成|写入|修改|更新|编辑|添加|新增|实现|重构|"
269:     r"\b(?:create|generate|write|update|modify|edit|implement|add|refactor)\b)",
270:     re.IGNORECASE,
271: )
272: _DELIVERABLE_READING_VERB_PATTERN = re.compile(
273:     r"(?:阅读|读取|查看|参照|参考|打开|"
274:     r"\b(?:read|review|refer|consult)\b|\blook\s+at\b|\bsee\b)",
275:     re.IGNORECASE,
276: )
277: _DELIVERABLE_SUBJECT_AFTER_PATTERN = re.compile(
278:     r"^[\s\S]{0,20}?(?:必须|也要|要改|改为|改用|实现|写入|\bmust\b|\bshall\b)",
279: )
280: # "实现 SPEC.md 中要求的…" / "按 SPEC.md 的说明实现…"：紧跟路径的规格指称
281: # 说明该文件是参考输入，不是交付对象（W1.3.3 输出/输入区分）。
282: _DELIVERABLE_REFERENCE_AFTER_PATTERN = re.compile(
283:     r"^[\s\S]{0,6}?(?:中要求|中描述|中规定|中定义|中说明|的说明|的描述|的规定|的定义)"
284: )
285: _DELIVERABLE_NEGATION_PATTERN = re.compile(
286:     r"(?:不要|别|不得|禁止|无需|不用|不需要|不准|"
287:     r"\bdo\s+not\b|\bdon't\b|\bmust\s+not\b|\bnever\b)",
288:     re.IGNORECASE,
289: )
290: _DELIVERABLE_QUESTION_CLAUSE = re.compile(
291:     r"^\s*(?:如何|怎么|为什么|是否|请问|"
292:     r"\b(?:how|what|why|can|could|would)\b|\bdo(?:es)?\b)",
293:     re.IGNORECASE,
294: )
295: _NON_AUTHORITATIVE_DELIVERABLE_SPANS = (
296:     re.compile(r"```[\s\S]*?```"),
297:     re.compile(r"「[^」]*」"),
298:     re.compile(r"“[^”]*”"),
299: )
300: 
301: 
302: def _goal_source_text(
303:     state: ConversationState,
304:     bootstrap: GoalBootstrap,
305: ) -> str:
306:     source = next(
307:         (
308:             fact
309:             for fact in state.facts
310:             if fact.fact_id == bootstrap.source_fact_id
```

## agent/runtime/state.py:323-333
```text
323: def _without_non_authoritative_spans(
324:     text: str,
325:     patterns: tuple[re.Pattern[str], ...],
326: ) -> str:
327:     candidate = text
328:     for pattern in patterns:
329:         candidate = pattern.sub(" ", candidate)
330:     return candidate
331: 
332: 
333: def _classify_explicit_requirement(
```

## agent/runtime/state.py:443-534
```text
443: def _last_match_end(text: str, pattern: re.Pattern[str]) -> int:
444:     return max((match.end() for match in pattern.finditer(text)), default=0)
445: 
446: 
447: def _normalize_deliverable_path_token(value: str) -> str:
448:     """交付路径 token 的安全校验：与 artifact_path 同一 workspace 相对语义。
449: 
450:     额外要求"路径形状"（含 ``/`` 或以扩展名结尾），避免把 ``max_retries`` 这类
451:     普通标识词当成文件交付对象；绝对路径、父目录逃逸与控制字符一律拒绝。
452:     """
453: 
454:     if (
455:         not value
456:         or len(value) > 1_000
457:         or value.startswith("/")
458:         or "\\" in value
459:         or any(
460:             ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F
461:             for character in value
462:         )
463:     ):
464:         return ""
465:     parts = value.split("/")
466:     if any(part in {"", ".", ".."} for part in parts):
467:         return ""
468:     if "/" not in value and re.search(r"\.[A-Za-z0-9]{1,12}$", value) is None:
469:         return ""
470:     return value
471: 
472: 
473: def authoritative_deliverable_file_paths(
474:     state: ConversationState,
475: ) -> frozenset[str]:
476:     """提取当前 Goal 权威来源中仍生效的明确文件交付对象下界（W1）。
477: 
478:     只读 ``created_from_fact_ids`` 绑定的真实 USER_MESSAGE 原文（含已消费
479:     correction）。每个 clause 内按有限规则判定"直接正向的精确文件交付要求"：
480:     路径 token 附近的交付动词（就近原则压过阅读动词）、或路径后紧跟的主体
481:     要求词；疑问句、引文/代码块 span 与近距离禁止词不产生义务。跨 fact 按
482:     顺序做正/负更新——correction 新增即生效、点名撤回只移除被点名对象、
483:     沉默或无关 correction 不清空其它交付对象、未消费 correction 不生效。
484: 
485:     这是完成判断的下界，不是工具权限，也不声称覆盖任意自然语言语义：
486:     有限规则未识别的隐含要求仍由模型与独立验收负责。
487:     """
488: 
489:     goal = state.goal
490:     if goal is None:
491:         return frozenset()
492:     source_ids = set(goal.created_from_fact_ids)
493:     requested: set[str] = set()
494:     for fact in state.facts:
495:         if fact.fact_id not in source_ids or fact.kind is not FactKind.USER_MESSAGE:
496:             continue
497:         text = fact.content.get("text")
498:         if not isinstance(text, str):
499:             continue
500:         # 逐 clause 判定；沿用 process 的 path-safe 断句（``app/worker.py``
501:         # 中的点号不当句边界）。
502:         for raw_clause in _PROCESS_ENTRYPOINT_CLAUSE_BOUNDARY.split(text):
503:             clause = _without_non_authoritative_spans(
504:                 raw_clause,
505:                 _NON_AUTHORITATIVE_DELIVERABLE_SPANS,
506:             )
507:             if not clause.strip() or _DELIVERABLE_QUESTION_CLAUSE.match(clause):
508:                 continue
509:             for match in _DELIVERABLE_PATH_TOKEN.finditer(clause):
510:                 path = _normalize_deliverable_path_token(match.group(1))
511:                 if not path:
512:                     continue
513:                 start, end = match.span(1)
514:                 if _DELIVERABLE_NEGATION_PATTERN.search(
515:                     clause[max(0, start - 16) : start]
516:                     + " "
517:                     + clause[end : end + 12]
518:                 ):
519:                     requested.discard(path)
520:                     continue
521:                 if _DELIVERABLE_REFERENCE_AFTER_PATTERN.match(
522:                     clause[end : end + 10]
523:                 ):
524:                     continue
525:                 window = clause[max(0, start - 24) : start]
526:                 deliverable_verb = _last_match_end(window, _DELIVERABLE_VERB_PATTERN)
527:                 reading_verb = _last_match_end(
528:                     window, _DELIVERABLE_READING_VERB_PATTERN
529:                 )
530:                 if deliverable_verb > reading_verb or (
531:                     _DELIVERABLE_SUBJECT_AFTER_PATTERN.match(clause[end : end + 24])
532:                 ):
533:                     requested.add(path)
534:     return frozenset(requested)
```

## agent/runtime/state.py:1667-1722
```text
1667: def acknowledge_provider_disclosure(
1668:     state: ConversationState,
1669:     action: AcknowledgeProviderDisclosure,
1670: ) -> ConversationState:
1671:     request = state.provider_disclosure_request
1672:     active = state.active_run
1673:     if request is None or request.request_digest != action.request_digest:
1674:         raise ValueError("provider disclosure acknowledgement does not match")
1675:     goal = state.goal
1676:     if active is None:
1677:         # /pause 允许落在 pending disclosure 上（2026-10-17 E1-B 真实旅程实测）：
1678:         # active run 已安全停止，但披露决定仍 durable。/resume 之后 ack 必须点燃
1679:         # 继续回合——与 SubmitMessage 的点火同型，否则挂起回合被静默丢弃成 idle。
1680:         if (
1681:             state.provider_disclosure_receipt is not None
1682:             or goal is None
1683:             or goal.status is not GoalStatus.GOAL_READY
1684:         ):
1685:             raise ValueError("provider disclosure acknowledgement does not match")
1686:         return replace(
1687:             state,
1688:             provider_disclosure_receipt=request.acknowledge(
1689:                 receipt_id=f"disclosure-receipt:{action.action_seq}",
1690:                 acknowledged_action_seq=action.action_seq,
1691:                 acknowledged_at=action.acknowledged_at,
1692:             ),
1693:             active_run=ActiveRun(run_id=f"resume-{action.action_seq}"),
1694:         )
1695:     if active.status is not ActiveRunStatus.AWAITING_DISCLOSURE:
1696:         raise ValueError("provider disclosure acknowledgement does not match")
1697:     if goal is not None and goal.status is GoalStatus.NEEDS_AUTHORITY:
1698:         goal = replace(goal, status=GoalStatus.GOAL_READY)
1699:     return replace(
1700:         state,
1701:         goal=goal,
1702:         provider_disclosure_receipt=request.acknowledge(
1703:             receipt_id=f"disclosure-receipt:{action.action_seq}",
1704:             acknowledged_action_seq=action.action_seq,
1705:             acknowledged_at=action.acknowledged_at,
1706:         ),
1707:         active_run=replace(active, status=ActiveRunStatus.RUNNABLE),
1708:     )
1709: 
1710: 
1711: def record_completion_claim(
1712:     state: ConversationState,
1713:     claim: CompletionClaim,
1714: ) -> ConversationState:
1715:     goal = _require_goal_revision(
1716:         state,
1717:         goal_id=claim.goal_id,
1718:         expected_revision=claim.goal_revision,
1719:     )
1720:     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
1721:         raise ValueError("completion claim requires an executable goal")
1722:     if any(
```

## agent/runtime/state.py:1928-1948
```text
1928:     _require_requirement_coverage(state, claim, goal=goal, mandatory=mandatory)
1929:     # W1：权威原文的明确文件交付对象是完成下界；模型缩小后的 admitted 集
1930:     # 合（或一条泛化 coverage）不能替代被草稿遗漏的交付对象。
1931:     deliverable_paths = authoritative_deliverable_file_paths(state)
1932:     if deliverable_paths:
1933:         admitted_paths = {
1934:             criterion.predicate.get("path")
1935:             for criterion in mandatory
1936:             if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
1937:             and isinstance(criterion.predicate.get("path"), str)
1938:         }
1939:         missing = sorted(deliverable_paths - admitted_paths)
1940:         if missing:
1941:             raise ValueError(
1942:                 "explicit user deliverable files are not covered by current "
1943:                 "admitted criteria: " + ", ".join(missing)
1944:             )
1945:     evidence_by_criterion = {
1946:         record.criterion_id: record for record in referenced.values()
1947:     }
1948:     if any(
```

## agent/runtime/loop.py:2835-2905
```text
2835:                                     current.state,
2836:                                     code="blocked_claim_not_verified",
2837:                                     message=(
2838:                                         "The blocked_claim was not accepted because the "
2839:                                         "current evidence gap is repairable with an "
2840:                                         "advertised product tool. Required next tool: "
2841:                                         f"{', '.join(gap_repair.repairable_tools)}. "
2842:                                         + gap_repair.repair_instruction
2843:                                     ),
2844:                                 ),
2845:                             )
2846:                             continue
2847:                     else:
2848:                         # W1.5：与完成门复用同一交付缺口判断。admitted 证据全部
2849:                         # 可推导不等于权威原文的明确交付对象已覆盖；缺口未闭合
2850:                         # 时不得断言"证据已完整"并指示重发 completion_claim——
2851:                         # 那会让服从指引的 claim 立即被完成门以同一缺口拒绝。
2852:                         deliverable_gap = sorted(
2853:                             authoritative_deliverable_file_paths(current.state)
2854:                             - {
2855:                                 criterion.predicate.get("path")
2856:                                 for criterion in goal_frame.admitted_criteria
2857:                                 if criterion.mandatory
2858:                                 and criterion.oracle_kind
2859:                                 is EvidenceOracleKind.FILESYSTEM_DIGEST
2860:                                 and isinstance(
2861:                                     criterion.predicate.get("path"), str
2862:                                 )
2863:                             }
2864:                         )
2865:                         if deliverable_gap:
2866:                             if no_progress.repair_exhausted(
2867:                                 (
2868:                                     "blocked_claim_with_deliverable_gap",
2869:                                     *deliverable_gap,
2870:                                 ),
2871:                                 allowance=self._limits.max_no_progress_replans,
2872:                                 observation_id=model_calls,
2873:                             ):
2874:                                 return self._finish_no_progress(
2875:                                     current,
2876:                                     action,
2877:                                     warnings,
2878:                                     message=(
2879:                                         "Provider repeated blocked claims while "
2880:                                         "explicit deliverable files were still "
2881:                                         "missing from admitted criteria."
2882:                                     ),
2883:                                 )
2884:                             no_progress_since_product_action = True
2885:                             current = self._save(
2886:                                 current,
2887:                                 append_policy_result(
2888:                                     current.state,
2889:                                     code="blocked_claim_not_verified",
2890:                                     message=(
2891:                                         "The blocked_claim was not accepted: explicit "
2892:                                         "user deliverable files are still outside the "
2893:                                         "current admitted criteria: "
2894:                                         + ", ".join(deliverable_gap)
2895:                                         + ". Advance them through the normal approval "
2896:                                         "and final read-back path, or produce a "
2897:                                         "durable blocker for them, before reporting "
2898:                                         "this Goal as blocked."
2899:                                     ),
2900:                                 ),
2901:                             )
2902:                             continue
2903:                         # 016 第 96 轮 a2 J7:edit+process 均成功(exit 0、durable
2904:                         # receipts)后模型以 blocked 收尾。守卫合同要求 attempt
2905:                         # "produces a durable blocker";完成证据已可推导时
```

## agent/cli/app.py:65-90
```text
65: /approve-goal-target [request-id] — approve the exact file target for the current
66:   task (without an ID it binds the prompt just shown)
67: /approve-goal-directory [request-id] — approve files under an explicit Goal
68:   directory (without an ID it binds the prompt just shown)
69: /approve-artifact <sha256> <workspace-relative-path> — approve an exact artifact
70: /ack-provider <digest> — acknowledge an exact provider disclosure
71: /resolve-success <request-id>, /resolve-failed <request-id> — resolve an unknown effect
72: /record-observation-unknown — continue after an unknown public observation
73: /revoke <lease-id|all> — revoke process permission
74: /revoke-goal-target — revoke all current-task file permissions
75: /browser-done, /browser-cancel — finish or cancel browser takeover
76: /exit — leave First Agent safely
77: When a prompt offers y/n, success/failed/stop, or continue/stop, you may answer it directly."""
78: 
79: 
80: def run_headless(
81:     runtime: AgentRuntime,
82:     store: CheckpointStore,
83:     action: Action,
84: ) -> RunResult:
85:     """无隐式 I/O 地加载一次 snapshot 并执行一个 typed action。"""
86: 
87:     return runtime.run_turn(action, store.load())
88: 
89: 
90: def load_headless_view(store: CheckpointStore) -> GoalView:
```

## agent/cli/app.py:118-210
```text
118:     store: CheckpointStore,
119:     *,
120:     input_fn: Callable[[str], str] = input,
121:     write_fn: Callable[[str], None] = print,
122:     run_id_factory: Callable[[], str] | None = None,
123:     renderer: TerminalRenderer | None = None,
124:     approval_time_factory: Callable[[], str] = utc_now_rfc3339,
125:     browser_profile_command: Callable[[str], str] | None = None,
126: ) -> int:
127:     make_run_id = run_id_factory or (lambda: str(uuid4()))
128:     renderer = renderer or TerminalRenderer(write_fn)
129:     while True:
130:         # 所见即所批：先取权威 snapshot 并投影 pending 决策，再读输入；
131:         # 该输入解析出的 action 与 run_turn 严格绑定同一 snapshot。
132:         # 若等待输入期间 store 漂移，现有 expected_revision/token CAS 会让
133:         # 该答案零副作用地 fail closed，且不重绑到新请求。
134:         snapshot = store.load()
135:         renderer.render_pending(snapshot.state)
136:         try:
137:             raw = input_fn("> ")
138:         except (EOFError, KeyboardInterrupt, StopIteration):
139:             return 0
140:         if raw == "/exit":
141:             return 0
142:         if raw == "/new":
143:             # r19 小步 2:显式新任务入口。合法性判断与 TUI 共享(new_session_gate);
144:             # 新建动作本身不进 Runtime(零 provider/工具调用),以专用退出码把
145:             # conversation 重建交还装配层,旧 checkpoint 与 evidence 原样保留。
146:             refusal = new_session_gate(snapshot.state)
147:             if refusal is not None:
148:                 write_fn(refusal)
149:                 continue
150:             write_fn("Starting a new task in this workspace (previous task kept).")
151:             return NEW_SESSION_REQUESTED
152:         if raw.strip() == "/help":
153:             write_fn(_HELP_TEXT)
154:             continue
155:         if not raw.strip():
156:             continue
157:         if raw.strip().startswith("/browser-profiles"):
158:             if browser_profile_command is None:
159:                 write_fn("Browser profiles are unavailable in this session.")
160:                 continue
161:             suffix = raw.strip()[len("/browser-profiles"):].strip() or "list"
162:             try:
163:                 write_fn(browser_profile_command(suffix))
164:             except ValueError as error:
165:                 write_fn(str(error))
166:             except OSError:
167:                 write_fn("Browser profile store is unavailable.")
168:             continue
169: 
170:         if raw == "/sources":
171:             renderer.render_sources(snapshot.state)
172:             continue
173:         if raw == "/sources --advanced":
174:             renderer.render_sources(snapshot.state, advanced=True)
175:             continue
176:         if raw == "/leases":
177:             renderer.render_leases(snapshot.state)
178:             continue
179:         if raw == "/leases --advanced":
180:             renderer.render_leases(snapshot.state, advanced=True)
181:             continue
182:         contextual_exit = _contextual_exit_message(raw, snapshot.state)
183:         if contextual_exit is not None:
184:             write_fn(contextual_exit)
185:             return 0
186:         action, error = _parse_action(
187:             raw,
188:             snapshot.state,
189:             make_run_id,
190:             approval_time_factory=approval_time_factory,
191:         )
192:         if error is not None:
193:             write_fn(error)
194:             continue
195:         if action is None:
196:             continue
197: 
198:         renderer.render_working()
199:         try:
200:             result = runtime.run_turn(action, snapshot)
201:         except KeyboardInterrupt:
202:             write_fn(
203:                 "Run interrupted. Saved state was kept; restart First Agent to inspect "
204:                 "or recover the task. A remote request or in-flight effect may still "
205:                 "have completed."
206:             )
207:             return 130
208:         renderer.render_result(result)
209:         if result.status is RunStatus.CONFLICT:
210:             return 2
```

## agent/cli/app.py:213-265
```text
213:         if result.status is RunStatus.CONVERSATION_LIMIT_REACHED:
214:             return 2
215: 
216: 
217: def _parse_action(
218:     raw: str,
219:     state: ConversationState,
220:     make_run_id: Callable[[], str],
221:     *,
222:     approval_time_factory: Callable[[], str] = utc_now_rfc3339,
223: ) -> tuple[Action | None, str | None]:
224:     common = {
225:         "conversation_id": state.conversation_id,
226:         "action_seq": state.next_action_seq,
227:         "expected_revision": state.revision,
228:     }
229:     command, separator, argument = raw.partition(" ")
230:     normalized = raw.strip().casefold()
231: 
232:     disclosure = state.provider_disclosure_request
233:     goal = state.goal
234:     disclosure_answerable = (
235:         disclosure is not None
236:         and state.provider_disclosure_receipt is None
237:         and normalized in _AFFIRMATIVE
238:         and (
239:             (
240:                 state.active_run is not None
241:                 and state.active_run.status is ActiveRunStatus.AWAITING_DISCLOSURE
242:             )
243:             or (
244:                 # /pause 停在 pending disclosure 上后，/resume 完成的 Goal 必须
245:                 # 仍可应答该 durable 决定（2026-10-17 E1-B 缺口）；仍 PAUSED 时
246:                 # 不可——先 /resume。
247:                 goal is not None
248:                 and goal.status is GoalStatus.GOAL_READY
249:             )
250:         )
251:     )
252:     if disclosure_answerable:
253:         return (
254:             AcknowledgeProviderDisclosure(
255:                 **common,
256:                 request_digest=disclosure.request_digest,
257:                 acknowledged_at="operator-confirmed",
258:             ),
259:             None,
260:         )
261: 
262:     approval = _approval_request(state)
263:     if approval is not None and normalized in _AFFIRMATIVE | _NEGATIVE:
264:         return (
265:             build_resolve_approval(
```

## agent/cli/app.py:540-557
```text
540: def _contextual_exit_message(raw: str, state: ConversationState) -> str | None:
541:     """拒绝 disclosure 或停止 unknown-outcome 时安全退出，且不伪造状态变更。"""
542: 
543:     normalized = raw.strip().casefold()
544:     active = state.active_run
545:     if (
546:         state.provider_disclosure_request is not None
547:         and active is not None
548:         and active.status is ActiveRunStatus.AWAITING_DISCLOSURE
549:         and normalized in _NEGATIVE
550:     ):
551:         return "Nothing was sent."
552:     if _recovery_request(state) is not None and normalized in _RECOVERY_STOP:
553:         return "Stopped without classifying or retrying the previous operation."
554:     return None
555: 
```

## agent/cli/render.py:140-187
```text
140:     def render_pending(self, state: ConversationState) -> None:
141:         """每次输入前从 authoritative state 只读投影 exact durable decision；
142:         不暴露内部 request identity。
143:         """
144: 
145:         active = state.active_run
146:         request = state.provider_disclosure_request
147:         goal = state.goal
148:         if (
149:             active is None
150:             and request is not None
151:             and state.provider_disclosure_receipt is None
152:             and goal is not None
153:             and goal.status is GoalStatus.GOAL_READY
154:         ):
155:             # /pause 可以停在 pending disclosure 上（2026-10-17 E1-B 真实缺口）：
156:             # active run 已安全停止，但该 durable 决定在 /resume 完成后必须与
157:             # 审批同等重升，等待 y/拒绝；Goal 仍 PAUSED 时不升。
158:             self._write(
159:                 self._disclosure_message(
160:                     destination=request.canonical_destination,
161:                     model=request.model,
162:                     data_classes=request.data_classes,
163:                 )
164:             )
165:             return
166:         if active is None:
167:             return
168:         if (
169:             active.status is ActiveRunStatus.AWAITING_DISCLOSURE
170:             and state.provider_disclosure_request is not None
171:         ):
172:             request = state.provider_disclosure_request
173:             self._write(
174:                 self._disclosure_message(
175:                     destination=request.canonical_destination,
176:                     model=request.model,
177:                     data_classes=request.data_classes,
178:                 )
179:             )
180:             return
181:         if active.status is ActiveRunStatus.AWAITING_APPROVAL and isinstance(
182:             active.pending_request, ApprovalRequest
183:         ):
184:             request = active.pending_request
185:             requirement = request.artifact_confirmation_requirement
186:             self._write(
187:                 self._approval_message(
```

## agent/tui/render.py:107-150
```text
107:                 (
108:                     "next step",
109:                     "Use Browser done after finishing in the dedicated browser window opened "
110:                     "during this app session. After restarting the app, or when the original "
111:                     "window is unavailable, use Browser cancel. Returning control does not "
112:                     "approve later browser actions.",
113:                 ),
114:             ),
115:             goal=goal_view,
116:             sources=goal_view.sources,
117:         )
118:     if active is None:
119:         terminal = None
120:         if state.last_safe_result is not None:
121:             terminal = state.last_safe_result.message
122:         elif result is not None and result.message is not None:
123:             terminal = result.message
124:         actions = goal_view.legal_actions if goal_view.goal_id is not None else ("submit",)
125:         main_text = terminal or "ready"
126:         if goal_view.status == GoalStatus.VERIFIED_DONE.value:
127:             main_text = f"{main_text}\n{delivery_summary_message(goal_view)}"
128:         if goal_view.verification_scope:
129:             main_text = f"{main_text}\n{verification_scope_message(goal_view.verification_scope)}"
130:         return TuiProjection(
131:             main_text=main_text,
132:             form_kind=None,
133:             actions=actions,
134:             focus="input" if "submit" in actions or "correct_goal" in actions else "goal",
135:             terminal_message=terminal,
136:             goal=goal_view,
137:             sources=goal_view.sources,
138:         )
139:     if active.status is ActiveRunStatus.AWAITING_APPROVAL:
140:         return TuiProjection(
141:             main_text="awaiting approval",
142:             form_kind="approval",
143:             actions=("approve", "reject"),
144:             focus="approval",
145:             terminal_message=None,
146:             form_fields=_approval_fields(active.pending_request),
147:             goal=goal_view,
148:             sources=goal_view.sources,
149:         )
150:     if active.status is ActiveRunStatus.AWAITING_RECOVERY:
```

## scripts/run_task_trust_d04.py:95-120
```text
95:     "legacy_alias",
96:     "default_single_attempt",
97:     "bounded_attempts",
98:     "conflict_rejected",
99:     "negative_invalid",
100:     "cli_both_names",
101: )
102: REQUIRED_EVIDENCE = {
103:     # W3：normal 不注入也不要求 correction 证据；如实记录但不作为判据。
104:     "normal": (),
105:     "staged": (
106:         "correction_injected",
107:         "correction_durable",
108:         "correction_consumed",
109:         "version_changed",
110:         "paused_after_consumption",
111:         "resumed_in_new_process",
112:         "resume_advanced",
113:         "precondition_alias_checks_pending",
114:     ),
115: }
116: 
117: ProbeFn = Callable[[Path], "dict[str, bool]"]
118: 
119: 
120: # ---------------------------------------------------------------------------
```

## scripts/run_task_trust_d04.py:228-260
```text
228:             and isinstance(criterion.predicate.get("path"), str)
229:         }
230:     )
231:     return {
232:         "goal_status": goal.status.value if goal is not None else None,
233:         "goal_id": goal.goal_id if goal is not None else None,
234:         "goal_revision": goal.revision if goal is not None else None,
235:         "user_outcome": goal.user_outcome if goal is not None else None,
236:         "created_from_fact_ids": (
237:             list(goal.created_from_fact_ids) if goal is not None else []
238:         ),
239:         "proposed_criteria": (
240:             [item.criterion_id for item in goal.proposed_criteria]
241:             if goal is not None
242:             else []
243:         ),
244:         "admitted_criteria": (
245:             [item.criterion_id for item in goal.admitted_criteria]
246:             if goal is not None
247:             else []
248:         ),
249:         "active_run_status": status,
250:         "pending": pending,
251:         "pending_request": pending_request,
252:         "admitted_file_paths": admitted_file_paths,
253:         "executed_file_effects": sum(effects.values()),
254:         "effect_tools": effects,
255:         "correction_fact_ids": correction_ids,
256:         "state_revision": state.revision,
257:     }
258: 
259: 
260: def _ledger_lines(path: Path) -> int:
```

## scripts/run_task_trust_d04.py:299-319
```text
299: class JourneyOperator:
300:     mode: str  # normal | inject | resume
301:     candidate: Path | None = None
302:     probe: ProbeFn | None = None
303:     max_consents: int = 40
304:     task: str = INITIAL_PROMPT
305:     correction: str = CORRECTION
306:     task_sent: bool = False
307:     consent_decisions: int = 0
308:     scope_authorizations: int = 0
309:     # W3：不再发送「继续」或救场 /resume；两个计数器恒 0，作为过程证据保留。
310:     resumes: int = 0
311:     continue_decisions: int = 0
312:     injected: bool = False
313:     injection_point: str | None = None
314:     injected_fact_id: str | None = None
315:     pre_injection: dict | None = None
316:     consumption: dict | None = None
317:     pause_sent: bool = False
318:     resume_sent: bool = False
319:     start_observation: dict | None = None
```

## scripts/run_task_trust_d04.py:441-497
```text
441:         return self._stop(obs, "unexpected_idle_before_verified_done")
442: 
443:     # -- 内部决策 ----------------------------------------------------------
444: 
445:     def _should_inject(self, obs: dict) -> bool:
446:         # W3：注入只属于 inject 模式（staged E1-B）；normal 不注入。
447:         return (
448:             self.mode == "inject"
449:             and not self.injected
450:             and obs["goal_status"] is not None
451:             and obs["goal_status"] not in TERMINAL_GOAL_STATUSES
452:             and obs["executed_file_effects"] >= 1
453:         )
454: 
455:     def _inject(self, obs: dict, point: str) -> str:
456:         self.injected = True
457:         self.injection_point = point
458:         self.pre_injection = dict(obs)
459:         if self.probe is not None and self.candidate is not None:
460:             try:
461:                 self.pre_injection["alias_checks"] = self.probe(self.candidate)
462:             except Exception as error:  # noqa: BLE001 - 探针失败必须如实记录
463:                 self.pre_injection["alias_checks"] = {"probe_error": str(error)}
464:         self._event("inject_correction", obs)
465:         return self.correction
466: 
467:     def _consumed(self, obs: dict) -> bool:
468:         fact_id = self.injected_fact_id
469:         if fact_id is None or fact_id not in obs["created_from_fact_ids"]:
470:             return False
471:         if self.consumption is None:
472:             before = self.pre_injection or {}
473:             goal_before = before.get("goal_revision")
474:             state_before = before.get("state_revision")
475:             goal_after = obs["goal_revision"]
476:             state_after = obs["state_revision"]
477:             self.consumption = {
478:                 "fact_id": fact_id,
479:                 "goal_revision_before": goal_before,
480:                 "goal_revision_after": goal_after,
481:                 "state_revision_before": state_before,
482:                 "state_revision_after": state_after,
483:                 "goal_version_changed": bool(
484:                     goal_after is not None
485:                     and goal_before is not None
486:                     and goal_after > goal_before
487:                 ),
488:                 "state_version_changed": bool(
489:                     state_after is not None
490:                     and state_before is not None
491:                     and state_after > state_before
492:                 ),
493:                 "created_from_fact_ids": list(obs["created_from_fact_ids"]),
494:                 "user_outcome": obs["user_outcome"],
495:             }
496:         return True
497: 
```

## scripts/run_task_trust_d04.py:602-670
```text
602: def _consumption_view(phase: dict) -> dict:
603:     consumption = phase.get("consumption") or {}
604:     fact_id = consumption.get("fact_id")
605:     created = consumption.get("created_from_fact_ids") or []
606:     return {
607:         "fact_id": fact_id,
608:         "consumed": bool(fact_id and fact_id in created),
609:         "version_changed": bool(
610:             consumption.get("goal_version_changed")
611:             or consumption.get("state_version_changed")
612:         ),
613:         "goal_version_changed": bool(consumption.get("goal_version_changed")),
614:         "state_version_changed": bool(consumption.get("state_version_changed")),
615:         "user_outcome": consumption.get("user_outcome"),
616:     }
617: 
618: 
619: def _staged_evidence(phase_a: dict, phase_b: dict, final_obs: dict | None) -> dict:
620:     a_final = phase_a.get("final_observation") or {}
621:     checks = (phase_a.get("pre_injection") or {}).get("alias_checks") or {}
622:     consumption = _consumption_view(phase_a)
623:     b_start = phase_b.get("start_observation") or {}
624:     effects_after = (final_obs or {}).get("executed_file_effects", 0)
625:     revision_after = (final_obs or {}).get("goal_revision")
626:     typed_terminal = bool(final_obs and final_obs.get("goal_status") == "verified_done")
627:     return {
628:         "correction_injected": bool(
629:             phase_a.get("injected") and phase_a.get("injection_point")
630:         ),
631:         "correction_durable": bool(
632:             phase_a.get("injected_fact_id")
633:             and phase_a.get("injected_fact_id") in a_final.get("correction_fact_ids", [])
634:         ),
635:         "correction_consumed": consumption["consumed"],
636:         "version_changed": consumption["version_changed"],
637:         "paused_after_consumption": bool(
638:             phase_a.get("pause_sent")
639:             and phase_a.get("stop_reason") == "paused_for_resume"
640:             and a_final.get("goal_status") == "paused"
641:         ),
642:         "resumed_in_new_process": bool(
643:             phase_b.get("pid")
644:             and phase_a.get("pid")
645:             and phase_b["pid"] != phase_a["pid"]
646:             and phase_b.get("resume_sent")
647:         ),
648:         "resume_advanced": bool(
649:             typed_terminal
650:             and (
651:                 effects_after > (b_start.get("executed_file_effects") or 0)
652:                 or (
653:                     revision_after is not None
654:                     and revision_after > (b_start.get("goal_revision") or 0)
655:                 )
656:             )
657:         ),
658:         "precondition_alias_checks_pending": bool(
659:             checks
660:             and "probe_error" not in checks
661:             and not (checks.get("legacy_alias") and checks.get("cli_both_names"))
662:         ),
663:         "phase_a_pid": phase_a.get("pid"),
664:         "phase_b_pid": phase_b.get("pid"),
665:         "injection_point": phase_a.get("injection_point"),
666:         "consumption": consumption if consumption["fact_id"] else None,
667:         "alias_checks_at_injection": checks or None,
668:     }
669: 
670: 
```

## scripts/run_task_trust_d04.py:737-750
```text
737: def _run_journey(args) -> dict:
738:     from main import main as run_first_agent
739: 
740:     offline = args.provider == "fake"
741:     if not offline:
742:         from scripts.run_real_coding_scenario import _require_dispatch_authorized
743: 
744:         manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
745:         _require_dispatch_authorized(manifest, args)
746: 
747:     candidate = args.candidate.resolve(strict=True)
748:     state_root = args.state_root.resolve()
749:     _ensure_private_dir(state_root.parent)
750:     ledger = args.ledger.resolve()
```

## scripts/run_task_trust_d04.py:1039-1057
```text
1039: def _journey(args) -> int:
1040:     state_root = args.state_root.resolve()
1041:     ledger = args.ledger.resolve()
1042:     _ensure_private_dir(state_root.parent)
1043:     _ensure_private_dir(ledger.parent)
1044:     extra = _provider_extra(args)
1045:     phase_results: list[dict] = []
1046:     failures: list[str] = []
1047:     started = time.monotonic()
1048:     deadline = started + args.wall_seconds
1049: 
1050:     def remaining() -> float:
1051:         return deadline - time.monotonic()
1052: 
1053:     def run_phase(mode: str, result_path: Path) -> dict:
1054:         budget = remaining()
1055:         if budget <= 5.0:
1056:             failures.append(f"sample wall budget exhausted before the {mode} phase")
1057:             return {"exit_code": 124, "stop_reason": "sample_wall_budget_exhausted"}
```

## scripts/run_task_trust_d04.py:1126-1177
```text
1126: def _add_provider_options(parser: argparse.ArgumentParser) -> None:
1127:     parser.add_argument(
1128:         "--provider",
1129:         default="openai_compatible",
1130:         choices=("fake", "openai_compatible"),
1131:     )
1132:     parser.add_argument("--model", default="deepseek-v4-flash")
1133:     parser.add_argument("--base-url", default="https://api.deepseek.com")
1134:     parser.add_argument("--credential-env", default="DEEPSEEK_API_KEY")
1135:     parser.add_argument(
1136:         "--thinking-mode", default="disabled", choices=("enabled", "disabled")
1137:     )
1138:     parser.add_argument("--max-model-attempts", type=int, default=MAX_REQUESTS_PER_SAMPLE)
1139:     parser.add_argument("--max-consents", type=int, default=40)
1140:     parser.add_argument("--max-resumes", type=int, default=2)
1141:     parser.add_argument("--timeout", type=float, default=240.0)
1142: 
1143: 
1144: def main() -> int:
1145:     parser = argparse.ArgumentParser()
1146:     subparsers = parser.add_subparsers(dest="command", required=True)
1147: 
1148:     prepare = subparsers.add_parser("prepare")
1149:     prepare.add_argument("candidate", type=Path)
1150:     prepare.add_argument("--staged", action="store_true")
1151:     prepare.add_argument("--result", type=Path, required=True)
1152: 
1153:     run = subparsers.add_parser("run")
1154:     run.add_argument("candidate", type=Path)
1155:     run.add_argument("--mode", choices=("normal", "inject", "resume"), required=True)
1156:     run.add_argument("--state-root", type=Path, required=True)
1157:     run.add_argument("--ledger", type=Path, required=True)
1158:     run.add_argument("--result", type=Path, required=True)
1159:     _add_provider_options(run)
1160: 
1161:     journey = subparsers.add_parser("journey")
1162:     journey.add_argument("candidate", type=Path)
1163:     journey.add_argument("--mode", choices=("normal", "staged"), required=True)
1164:     journey.add_argument("--state-root", type=Path, required=True)
1165:     journey.add_argument("--ledger", type=Path, required=True)
1166:     journey.add_argument("--result", type=Path, required=True)
1167:     journey.add_argument("--wall-seconds", type=float, default=1800.0)
1168:     _add_provider_options(journey)
1169: 
1170:     args = parser.parse_args()
1171:     if args.command == "prepare":
1172:         _prepare(args)
1173:         return 0
1174:     if args.command == "run":
1175:         result = _run_journey(args)
1176:         return 0 if result.get("phase_ok") else 1
1177:     return _journey(args)
```


