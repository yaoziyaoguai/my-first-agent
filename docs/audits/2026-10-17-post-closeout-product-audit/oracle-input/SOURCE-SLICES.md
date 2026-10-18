
## agent/runtime/state.py:180-330
```text
  180:         r"(?:运行|执行|测试|校验|验证)[^，。；;!?！？]*$",
  181:         re.IGNORECASE,
  182:     ),
  183:     re.compile(
  184:         r"\b(?:explain|explains|explaining|describe|describes|describing)\b\s+"
  185:         r"how\s+to\s+(?:run|execute|build|test|validate|check)\s+"
  186:         r"(?:the\s+)?(?:project\s+)?(?:tests?|validator|command|script|build)\b",
  187:         re.IGNORECASE,
  188:     ),
  189:     re.compile(
  190:         r"\b(?:contain|contains|containing|include|includes|including|mention|"
  191:         r"mentions|mentioning)\b[^,.;!?]{0,24}\b(?:the\s+)?phrase\s+"
  192:         r"(?:call|invoke)\s+(?:the\s+)?local_process\b",
  193:         re.IGNORECASE,
  194:     ),
  195: )
  196: _NEGATED_PUBLIC_WEB_PATTERNS = (
  197:     re.compile(
  198:         r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
  199:         r"[^，。；;,.!?！？]{0,16}"
  200:         r"(?:联网|上网|在线|网上|公开(?:资料|信息|来源|网页|网站)|web)",
  201:         re.IGNORECASE,
  202:     ),
  203:     re.compile(
  204:         r"(?:仅|只)(?:使用|用|在)?[^，。；;,.!?！？]{0,8}本地"
  205:         r"[^，。；;,.!?！？]{0,12}(?:资料|信息|来源|文件|数据)",
  206:         re.IGNORECASE,
  207:     ),
  208:     re.compile(
  209:         r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
  210:         r"[^,.;!?]{0,32}(?:web|online|internet|public\s+source|external\s+source|"
  211:         r"(?:latest|current)[^,.;!?]{0,16}(?:release|package|version|information|"
  212:         r"info|documentation|docs|data|news))",
  213:         re.IGNORECASE,
  214:     ),
  215: )
  216: _NEGATED_LOCAL_PROCESS_PATTERNS = (
  217:     re.compile(
  218:         r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
  219:         r"[^，。；;,.!?！？]{0,16}(?:调用|使用)?\s*local_process\b|"
  220:         r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
  221:         r"[^,.;!?]{0,24}(?:call|invoke)?\s*(?:the\s+)?local_process\b",
  222:         re.IGNORECASE,
  223:     ),
  224:     re.compile(
  225:         r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
  226:         r"[^，。；;,.!?！？]{0,16}"
  227:         r"(?:运行|执行|跑|启动|测试|构建|校验|验证|命令|脚本|校验器)",
  228:         re.IGNORECASE,
  229:     ),
  230:     re.compile(
  231:         r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
  232:         r"[^,.;!?]{0,24}(?:run|execute|build|test|validate|validator|command|script)",
  233:         re.IGNORECASE,
  234:     ),
  235: )
  236: _REQUIREMENT_CLAUSE_BOUNDARY = re.compile(
  237:     r"(?:[，。；;,!?！？]+|\.(?!/)|但是|但|而是|\bbut\b|\bhowever\b)",
  238:     re.IGNORECASE,
  239: )
  240: _PROCESS_OUTPUT_PATH_PATTERN = re.compile(
  241:     r"(?:^|[/_.-])(?:test|tests|testing|result|results|output|outputs|log|logs|"
  242:     r"coverage|junit|check|validator)(?:[/_.-]|$)",
  243:     re.IGNORECASE,
  244: )
  245: _PROCESS_OUTPUT_DESCRIPTION_PATTERN = re.compile(
  246:     r"(?:测试|校验|验证).{0,16}(?:输出|结果|日志|报告|文件)|"
  247:     r"\b(?:test|validation|validator|check).{0,24}(?:output|result|log|report|file)\b",
  248:     re.IGNORECASE,
  249: )
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
  311:             and fact.kind is FactKind.USER_MESSAGE
  312:         ),
  313:         None,
  314:     )
  315:     text = source.content.get("text") if source is not None else None
  316:     return text if isinstance(text, str) else ""
  317: 
  318: 
  319: def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
  320:     return any(pattern.search(text) is not None for pattern in patterns)
  321: 
  322: 
  323: def _without_non_authoritative_spans(
  324:     text: str,
  325:     patterns: tuple[re.Pattern[str], ...],
  326: ) -> str:
  327:     candidate = text
  328:     for pattern in patterns:
  329:         candidate = pattern.sub(" ", candidate)
  330:     return candidate
```

## agent/runtime/state.py:440-553
```text
  440:     return not requested or normalize_process_entrypoint(executable) in requested
  441: 
  442: 
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
  535: 
  536: 
  537: def _looks_like_invented_process_artifact(
  538:     criterion: ProposedCriterion,
  539:     *,
  540:     source_text: str,
  541: ) -> bool:
  542:     path = criterion.artifact_path
  543:     if path is None or path.casefold() in source_text.casefold():
  544:         return False
  545:     return (
  546:         _PROCESS_OUTPUT_PATH_PATTERN.search(path) is not None
  547:         or _PROCESS_OUTPUT_DESCRIPTION_PATTERN.search(criterion.description) is not None
  548:     )
  549: 
  550: 
  551: def _uses_runtime_owned_obligation_id(criterion: ProposedCriterion) -> bool:
  552:     return criterion.criterion_id.startswith(
  553:         (
```

## agent/runtime/state.py:1871-2050
```text
 1871: def verify_goal_completion(state: ConversationState) -> ConversationState:
 1872:     goal = state.goal
 1873:     claim = state.completion_claim
 1874:     if goal is None or claim is None:
 1875:         raise ValueError("completion verification requires a current claim")
 1876:     if _has_unknown_effect(state):
 1877:         raise ValueError("unknown effect recovery has priority over goal verification")
 1878:     if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
 1879:         raise ValueError("goal status is not eligible for completion verification")
 1880:     if claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
 1881:         raise GoalRevisionConflictError("completion claim is stale")
 1882:     if state.browser_takeover_pending is not None:
 1883:         raise ValueError("browser takeover must be resolved before goal verification")
 1884:     active_task_resources(state.facts).require_closed()
 1885:     referenced = {
 1886:         record.evidence_id: record
 1887:         for record in state.evidence_records
 1888:         if record.evidence_id in claim.criterion_evidence_refs
 1889:     }
 1890:     mandatory = tuple(
 1891:         criterion for criterion in goal.admitted_criteria if criterion.mandatory
 1892:     )
 1893:     if not mandatory:
 1894:         raise ValueError("goal has no mandatory criterion")
 1895:     if any(criterion.oracle_kind is None for criterion in goal.proposed_criteria):
 1896:         raise ValueError(
 1897:             "every proposed completion criterion requires a typed evidence oracle"
 1898:         )
 1899:     artifact_requirements = tuple(
 1900:         criterion
 1901:         for criterion in goal.proposed_criteria
 1902:         if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
 1903:     )
 1904:     for requirement in artifact_requirements:
 1905:         if not any(
 1906:             criterion.criterion_id == requirement.criterion_id
 1907:             and criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
 1908:             and criterion.predicate.get("path") == requirement.artifact_path
 1909:             for criterion in mandatory
 1910:         ):
 1911:             raise ValueError(
 1912:                 "artifact criterion must be admitted before completion verification"
 1913:             )
 1914:     process_requirements = tuple(
 1915:         criterion
 1916:         for criterion in goal.proposed_criteria
 1917:         if criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
 1918:     )
 1919:     for requirement in process_requirements:
 1920:         if not any(
 1921:             criterion.criterion_id == requirement.criterion_id
 1922:             and criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
 1923:             for criterion in mandatory
 1924:         ):
 1925:             raise ValueError(
 1926:                 "process criterion must be admitted before completion verification"
 1927:             )
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
 1949:         criterion.criterion_id not in evidence_by_criterion
 1950:         or not evidence_by_criterion[criterion.criterion_id].passed
 1951:         or evidence_by_criterion[criterion.criterion_id].goal_id != goal.goal_id
 1952:         or evidence_by_criterion[criterion.criterion_id].goal_revision != goal.revision
 1953:         or evidence_by_criterion[criterion.criterion_id].oracle_kind
 1954:         is not criterion.oracle_kind
 1955:         or evidence_by_criterion[criterion.criterion_id].predicate_digest
 1956:         != canonical_json_digest(criterion.predicate)
 1957:         for criterion in mandatory
 1958:     ):
 1959:         raise ValueError("current evidence does not prove every mandatory criterion")
 1960:     return replace(
 1961:         state,
 1962:         revision=state.revision + 1,
 1963:         goal=replace(goal, status=GoalStatus.VERIFIED_DONE, next_step=None),
 1964:         goal_authorizations=(),
 1965:         process_leases=(),
 1966:         sandbox_leases=(),
 1967:         browser_leases=(),
 1968:         browser_takeover_pending=None,
 1969:     )
 1970: 
 1971: 
 1972: def _conflict(state: ConversationState, reason: str) -> ActionTransition:
 1973:     return ActionTransition(ActionDisposition.CONFLICT, state, reason=reason)
 1974: 
 1975: 
 1976: def _find_replay(state: ConversationState, action_seq: int):
 1977:     return next(
 1978:         (record for record in state.replay_records if record.action_seq == action_seq),
 1979:         None,
 1980:     )
 1981: 
 1982: 
 1983: def _append_replay_record(
 1984:     state: ConversationState,
 1985:     *,
 1986:     action_seq: int,
 1987:     action_digest: str,
 1988:     max_replay_records: int,
 1989: ) -> ConversationState | None:
 1990:     if max_replay_records < 1:
 1991:         raise ValueError("max_replay_records must be positive")
 1992: 
 1993:     records = list(state.replay_records)
 1994:     replay_floor = state.replay_floor
 1995:     while len(records) >= max_replay_records:
 1996:         # replay_floor 表示连续窗口；不能越过更早的 unfinished action 去删后项。
 1997:         if not records or records[0].result is None:
 1998:             return None
 1999:         evicted = records.pop(0)
 2000:         replay_floor = max(replay_floor, evicted.action_seq + 1)
 2001:     records.append(ReplayRecord(action_seq=action_seq, action_digest=action_digest))
 2002:     # replay record 与 next_action_seq 是同一个接受动作的原子不变量，不能构造半状态。
 2003:     return replace(
 2004:         state,
 2005:         next_action_seq=state.next_action_seq + 1,
 2006:         replay_floor=replay_floor,
 2007:         replay_records=tuple(records),
 2008:     )
 2009: 
 2010: 
 2011: def _goal_target_authorization_scope(
 2012:     state: ConversationState,
 2013:     pending: ApprovalRequest,
 2014:     active: ActiveRun,
 2015:     *,
 2016:     directory: bool,
 2017: ) -> str | None:
 2018:     goal = state.goal
 2019:     call = active.tool_calls[active.batch_cursor]
 2020:     target = call.arguments.get("path")
 2021:     if not (
 2022:         goal is not None
 2023:         and pending.tool_name in {"write_file", "edit_file"}
 2024:         and call.name == pending.tool_name
 2025:         and pending.side_effect == SideEffectClass.WRITE.value
 2026:         and pending.egress in {None, EgressClass.NONE.value}
 2027:         and isinstance(target, str)
 2028:     ):
 2029:         return None
 2030:     if not directory:
 2031:         if target in goal.targets and safe_goal_authorization_target(target):
 2032:             return target
 2033:         # W2：散文 targets 下，当前 Goal 已由 Runtime 准入（真实用户批准来源，
 2034:         # `_admit_approved_file_criterion` 铸造）的精确文件同样可作为复用授权
 2035:         # 候选。只认 durable admitted criterion 的闭合 predicate path，不把
 2036:         # 任意 pending path 或模型自述提升为候选；显示/解析/铸造共用本判断。
 2037:         if safe_goal_authorization_target(target) and any(
 2038:             criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
 2039:             and criterion.predicate.get("path") == target
 2040:             for criterion in goal.admitted_criteria
 2041:         ):
 2042:             return target
 2043:         return None
 2044:     target_parts = target.split("/")
 2045:     candidates = []
 2046:     for goal_target in goal.targets:
 2047:         goal_parts = goal_target.split("/")
 2048:         if (
 2049:             len(target_parts) > len(goal_parts)
 2050:             and safe_goal_authorization_target(target)
```

## agent/runtime/state.py:3510-3590
```text
 3510:     """把已批准的 MCP/SubAgent 调用固化为 Runtime-owned 完成义务。"""
 3511: 
 3512:     goal = state.goal
 3513:     if goal is None or active.batch_cursor >= len(active.tool_calls):
 3514:         return state
 3515:     call = active.tool_calls[active.batch_cursor]
 3516:     if (
 3517:         call.tool_call_id != pending.tool_call_id
 3518:         or not call.name.startswith(("mcp__", "subagent__"))
 3519:     ):
 3520:         return state
 3521:     criterion_id = (
 3522:         f"criterion:required-governed-tool:{goal.goal_id}:{goal.revision}:"
 3523:         f"{call.tool_call_id}"
 3524:     )
 3525:     if any(
 3526:         item.criterion_id == criterion_id
 3527:         for item in (*goal.proposed_criteria, *goal.admitted_criteria)
 3528:     ):
 3529:         return state
 3530:     requirement = ProposedCriterion(
 3531:         criterion_id=criterion_id,
 3532:         description=(
 3533:             f"the approved {call.name} call returns an exact Kernel-governed receipt"
 3534:         ),
 3535:         oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
 3536:     )
 3537:     return replace(
 3538:         state,
 3539:         goal=replace(goal, proposed_criteria=(*goal.proposed_criteria, requirement)),
 3540:         completion_claim=None,
 3541:     )
 3542: 
 3543: 
 3544: def _admit_process_artifact_criterion(
 3545:     state: ConversationState,
 3546:     pending: ApprovalRequest,
 3547:     *,
 3548:     action: ResolveApproval,
 3549: ) -> ConversationState:
 3550:     """ResolveApproval 时铸造 FILESYSTEM_DIGEST criterion（F4：用户确认 digest）。
 3551: 
 3552:     authority 是 **ResolveApproval action 自带的 confirmed_artifact**（用户在批准
 3553:     command 的同一 typed action 里确认 path+sha256）——模型无法自供（schema 回
 3554:     closed 4 字段）。candidate 的 ea 字段是 runtime 内部残留（prepare 路径恒
 3555:     None，保持 checkpoint 兼容），不再作为 authority 来源。malformed fail closed。
 3556:     """
 3557: 
 3558:     goal = state.goal
 3559:     if goal is None:
 3560:         return state
 3561:     ea_path = action.confirmed_artifact_path
 3562:     ea_sha = action.confirmed_artifact_sha256
 3563:     requirement = pending.artifact_confirmation_requirement
 3564:     if requirement is not None and not any(
 3565:         item.criterion_id == requirement.criterion_id
 3566:         and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
 3567:         and item.artifact_path == requirement.artifact_path
 3568:         for item in goal.proposed_criteria
 3569:     ):
 3570:         raise ValueError(
 3571:             "artifact confirmation requirement does not match a current Goal criterion"
 3572:         )
 3573:     if action.defer_artifact_confirmation:
 3574:         if requirement is None:
 3575:             raise ValueError(
 3576:                 "artifact confirmation can be deferred only for a pending requirement"
 3577:             )
 3578:         # 这里只批准生成 effect。未铸造 FILESYSTEM_DIGEST criterion；未来字节必须
 3579:         # 由 confirm_file 重新读取、展示并经独立 approval 后才可成为完成证据。
 3580:         return state
 3581:     if requirement is not None and (
 3582:         ea_path is None
 3583:         or ea_sha is None
 3584:         or ea_path != requirement.artifact_path
 3585:     ):
 3586:         raise ValueError(
 3587:             "artifact confirmation must match the pending path and include sha256"
 3588:         )
 3589:     if ea_path is None and ea_sha is None:
 3590:         return state
```

## agent/runtime/loop.py:2790-2935
```text
 2790:                 # 拒绝重复检索，只是在维护现有 authority，不得据此把已经可证明
 2791:                 # 的 Goal 终化为 blocked（016 J11 真实三连实测）。
 2792:                 if mandatory_refs and not self._rejection_still_blocks_current_goal(
 2793:                     current.state
 2794:                 ):
 2795:                     probe = CompletionClaim(
 2796:                         correlation_id=control.correlation_id,
 2797:                         goal_id=goal_frame.goal_id,
 2798:                         goal_revision=goal_frame.revision,
 2799:                         criterion_evidence_refs=mandatory_refs,
 2800:                     )
 2801:                     try:
 2802:                         self._evidence_registry.derive(
 2803:                             current.state,
 2804:                             probe,
 2805:                             observed_at=self._evidence_time_factory(),
 2806:                         )
 2807:                     except EvidenceVerificationError as error:
 2808:                         evidence_gap = str(error)
 2809:                         gap_repair = self._evidence_registry.assess_gap(
 2810:                             evidence_gap,
 2811:                             available_tools=available_tools,
 2812:                         )
 2813:                         if gap_repair.repairable_tools:
 2814:                             if no_progress.repair_exhausted(
 2815:                                 (
 2816:                                     "blocked_claim_with_repairable_evidence",
 2817:                                     *gap_repair.repairable_tools,
 2818:                                 ),
 2819:                                 allowance=self._limits.max_no_progress_replans,
 2820:                                 observation_id=model_calls,
 2821:                             ):
 2822:                                 return self._finish_no_progress(
 2823:                                     current,
 2824:                                     action,
 2825:                                     warnings,
 2826:                                     message=(
 2827:                                         "Provider repeated blocked claims while an "
 2828:                                         "available tool could close the evidence gap."
 2829:                                     ),
 2830:                                 )
 2831:                             no_progress_since_product_action = True
 2832:                             current = self._save(
 2833:                                 current,
 2834:                                 append_policy_result(
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
 2906:                         # "无安全动作可推进"不成立,受理会把可完成 Goal 终化为
 2907:                         # blocked(false-completion 的对偶)。拒绝并给 completion
 2908:                         # 修复指引;证据不可推导时 blocked 语义照旧成立。
 2909:                         if no_progress.repair_exhausted(
 2910:                             ("blocked_claim_with_derivable_evidence",),
 2911:                             allowance=self._limits.max_no_progress_replans,
 2912:                             observation_id=model_calls,
 2913:                         ):
 2914:                             return self._finish_no_progress(
 2915:                                 current,
 2916:                                 action,
 2917:                                 warnings,
 2918:                                 message=(
 2919:                                     "Provider repeated blocked claims while complete "
 2920:                                     "evidence was derivable."
 2921:                                 ),
 2922:                             )
 2923:                         no_progress_since_product_action = True
 2924:                         current = self._save(
 2925:                             current,
 2926:                             append_policy_result(
 2927:                                 current.state,
 2928:                                 code="completion_evidence_available",
 2929:                                 message=(
 2930:                                     "The blocked_claim was not accepted: every "
 2931:                                     "mandatory criterion already has derivable "
 2932:                                     "evidence from durable facts, so a safe action "
 2933:                                     "can advance this Goal. Resend completion_claim "
 2934:                                     "after reviewing the current authoritative user "
 2935:                                     "input and consumed corrections item by item: "
```

## agent/cli/app.py:152-205
```text
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
```

## agent/cli/app.py:215-279
```text
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
  266:                 state,
  267:                 request_id=approval.request_id,
  268:                 binding_digest=approval.binding_digest,
  269:                 approved=normalized in _AFFIRMATIVE,
  270:                 approved_at=(
  271:                     approval_time_factory() if normalized in _AFFIRMATIVE else None
  272:                 ),
  273:                 defer_artifact_confirmation=(
  274:                     normalized in _AFFIRMATIVE
  275:                     and approval.artifact_confirmation_requirement is not None
  276:                 ),
  277:             ),
  278:             None,
  279:         )
```

## agent/cli/app.py:535-567
```text
  535:         and active.executing_intent is not None
  536:         and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
  537:     )
  538: 
  539: 
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

## agent/cli/render.py:139-185
```text
  139: 
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
```

## agent/cli/render.py:425-440
```text
  425:     def _disclosure_message(*, destination: object, model: object, data_classes: object) -> str:
  426:         data_summary = (
  427:             ", ".join(str(item) for item in data_classes)
  428:             if isinstance(data_classes, (list, tuple))
  429:             else data_classes
  430:         )
  431:         return (
  432:             "Remote provider disclosure required\n"
  433:             f"destination: {terminal_text(destination)}\n"
  434:             f"model: {terminal_text(model)}\n"
  435:             f"data: {terminal_text(data_summary)}\n"
  436:             "Allow this information to be sent? [y/N]"
  437:         )
  438: 
  439:     @staticmethod
  440:     def _result_message_for_limit(error_code: str | None = None) -> str:
```

## agent/tui/render.py:85-200
```text
   85: def project(state: ConversationState, result: RunResult | None = None) -> TuiProjection:
   86:     active = state.active_run
   87:     goal_view = project_goal_view(state)
   88:     pending_takeover = state.browser_takeover_pending
   89:     if pending_takeover is not None and (
   90:         active is None
   91:         or (
   92:             active.status is not ActiveRunStatus.AWAITING_RECOVERY
   93:             and active.phase is not ContinuationPhase.EXECUTING
   94:         )
   95:     ):
   96:         return TuiProjection(
   97:             main_text="Browser takeover — waiting for you",
   98:             form_kind="browser_takeover",
   99:             actions=("browser_done", "browser_cancel"),
  100:             focus="browser_takeover",
  101:             terminal_message=None,
  102:             form_fields=(
  103:                 ("request", pending_takeover.request_id),
  104:                 ("session", pending_takeover.session_ref),
  105:                 ("profile", pending_takeover.profile_ref),
  106:                 ("profile revision", str(pending_takeover.profile_revision)),
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
  151:         if (
  152:             active.executing_intent is not None
  153:             and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
  154:         ):
  155:             return TuiProjection(
  156:                 main_text=(
  157:                     "public observation outcome unknown; record no evidence and continue; "
  158:                     "the request will not retry automatically"
  159:                 ),
  160:                 form_kind="observation_recovery",
  161:                 actions=("record_observation_unknown",),
  162:                 focus="recovery",
  163:                 terminal_message=None,
  164:                 form_fields=_recovery_fields(active.pending_request),
  165:                 goal=goal_view,
  166:                 sources=goal_view.sources,
  167:             )
  168:         return TuiProjection(
  169:             main_text="awaiting recovery",
  170:             form_kind="recovery",
  171:             actions=("mark_succeeded", "mark_failed"),
  172:             focus="recovery",
  173:             terminal_message=None,
  174:             form_fields=_recovery_fields(active.pending_request),
  175:             goal=goal_view,
  176:             sources=goal_view.sources,
  177:         )
  178:     if active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
  179:         request = state.provider_disclosure_request
  180:         fields = ()
  181:         if request is not None:
  182:             fields = (
  183:                 ("destination", request.canonical_destination),
  184:                 ("model", request.model),
  185:                 ("data", ", ".join(request.data_classes)),
  186:                 ("binding", request.request_digest),
  187:             )
  188:         return TuiProjection(
  189:             main_text="remote provider disclosure required",
  190:             form_kind="disclosure",
  191:             actions=("ack_provider",),
  192:             focus="disclosure",
  193:             terminal_message=None,
  194:             form_fields=fields,
  195:             goal=goal_view,
  196:             sources=goal_view.sources,
  197:         )
  198:     if active.phase is ContinuationPhase.EXECUTING:
  199:         # 重开 EXECUTING checkpoint：工具 effect 可能已发生（unknown），只能 Resume
  200:         # 重新进入工具发现真实结果；Cancel 会绕过未知 effect，故不提供。
```

## scripts/run_task_trust_d04.py:87-115
```text
   87: TERMINAL_GOAL_STATUSES = frozenset({"verified_done", "cancelled"})
   88: FILE_EFFECT_TOOLS = frozenset({"write_file", "edit_file", "make_directory"})
   89: MAX_REQUESTS_PER_SAMPLE = 40
   90: BOUND_BUSINESS_KEYS = ("latest_correction", "final_validation")
   91: PROCESS_DECLARED_KEYS = ("resume_without_restatement", "no_effect_replay")
   92: # W3 冻结七项补充检查：evaluator 锁定完整预期集合，缺键/未知键/非 bool 都失败。
   93: SUPPLEMENTAL_KEYS = (
   94:     "transient_new_name",
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
```

## scripts/run_task_trust_d04.py:350-497
```text
  350: 
  351:         # typed 终态优先：完成后不存在合法 pause/注入，文字不能覆盖事实。
  352:         if status in TERMINAL_GOAL_STATUSES:
  353:             return self._stop(
  354:                 obs, "verified_done" if status == "verified_done" else "goal_cancelled"
  355:             )
  356: 
  357:         if self.mode == "inject" and self.injected and not self.pause_sent:
  358:             if self.consumption is not None:
  359:                 self.pause_sent = True
  360:                 self._event("pause", obs)
  361:                 return "/pause"
  362:             if pending == "recovery":
  363:                 return self._stop(obs, "unknown_effect_requires_operator_classification")
  364:             if pending in {"disclosure", "approval"}:
  365:                 return self._consent(obs)
  366:             if pending in {"limit", "retryable"}:
  367:                 # W3：注入后同样不救场，预算暂停如实停等操作者。
  368:                 return self._stop(obs, f"{pending}_pause_requires_user")
  369:             if active is None:
  370:                 # 未消费 correction 前不再追加消息（避免叠出第二条 correction）；
  371:                 # 模型整轮未消费即如实停。
  372:                 return self._stop(obs, "correction_not_consumed_before_idle")
  373:             return self._stop(obs, "unexpected_active_run_without_pending")
  374: 
  375:         if self.mode == "inject" and self.pause_sent:
  376:             if status == "paused" and active is None:
  377:                 return self._stop(obs, "paused_for_resume")
  378:             return self._stop(obs, "pause_not_effective")
  379: 
  380:         if pending == "disclosure":
  381:             return self._consent(obs)
  382:         if pending == "approval":
  383:             if self._should_inject(obs):
  384:                 return self._inject(obs, "approval")
  385:             return self._consent(obs)
  386:         if pending == "recovery":
  387:             return self._stop(obs, "unknown_effect_requires_operator_classification")
  388:         if pending in {"limit", "retryable"}:
  389:             # W3：不自动 /resume 救场；继续推进必须来自用户。
  390:             return self._stop(obs, f"{pending}_pause_requires_user")
  391:         if self._should_inject(obs):
  392:             return self._inject(obs, "idle")
  393:         if active is None:
  394:             # W3：空闲/暂停一律不发「继续」、不自动恢复，如实停等用户。
  395:             reason = (
  396:                 "paused_requires_user"
  397:                 if status in {"paused", "blocked"}
  398:                 else "idle_needs_user_continuation"
  399:             )
  400:             return self._stop(obs, reason)
  401:         return self._stop(obs, "unexpected_idle_before_verified_done")
  402: 
  403:     # -- resume 阶段（新进程）：只恢复与继续，绝不重述业务 -------------------
  404: 
  405:     def _next_resume(self, obs: dict | None) -> str:
  406:         if obs is None:
  407:             return self._stop(obs, "durable_state_unavailable")
  408:         if self.start_observation is None:
  409:             self.start_observation = obs
  410:         self.last_observation = obs
  411:         status = obs["goal_status"]
  412:         pending = obs["pending"]
  413:         active = obs["active_run_status"]
  414:         if status in TERMINAL_GOAL_STATUSES:
  415:             return self._stop(
  416:                 obs, "verified_done" if status == "verified_done" else "goal_cancelled"
  417:             )
  418:         if not self.resume_sent:
  419:             if status in {"paused", "blocked"} and active is None:
  420:                 self.resume_sent = True
  421:                 self._event("resume", obs)
  422:                 return "/resume"
  423:             return self._stop(obs, "resume_expected_paused_goal")
  424:         if pending == "disclosure":
  425:             return self._consent(obs)
  426:         if pending == "approval":
  427:             return self._consent(obs)
  428:         if pending == "recovery":
  429:             return self._stop(obs, "unknown_effect_requires_operator_classification")
  430:         if pending in {"limit", "retryable"}:
  431:             # W3：计划内 /resume 只发一次；再次 limit/retryable 不再救场。
  432:             return self._stop(obs, f"{pending}_pause_requires_user")
  433:         if active is None:
  434:             # W3：恢复后空闲不发「继续」，如实停等用户。
  435:             reason = (
  436:                 "paused_requires_user"
  437:                 if status in {"paused", "blocked"}
  438:                 else "idle_needs_user_continuation"
  439:             )
  440:             return self._stop(obs, reason)
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

## scripts/run_task_trust_d04.py:535-667
```text
  535: 
  536: # ---------------------------------------------------------------------------
  537: # 判定：只依据 typed 终态 + 冻结业务判据 + 过程证据
  538: # ---------------------------------------------------------------------------
  539: 
  540: 
  541: def evaluate_final(
  542:     *,
  543:     mode: str,
  544:     typed_terminal: bool,
  545:     business: dict[str, bool],
  546:     supplemental: dict[str, bool],
  547:     stop_reason: str | None,
  548:     exit_codes: list[int],
  549:     physical_requests: int,
  550:     max_requests: int,
  551:     evidence: dict,
  552:     extra_failures: list[str] | None = None,
  553: ) -> dict:
  554:     """E1 最终判定。任何一项缺失都如实 incomplete，绝不按文字判 PASS。"""
  555: 
  556:     failures: list[str] = list(extra_failures or ())
  557:     if not typed_terminal:
  558:         failures.append("product did not reach typed VERIFIED_DONE in durable state")
  559:     for name in BOUND_BUSINESS_KEYS:
  560:         if not business.get(name, False):
  561:             failures.append(f"business check false: {name}")
  562:     # W3：锁定冻结七项集合——缺键/未知键/非 bool 都失败，七项语义不变。
  563:     for name in SUPPLEMENTAL_KEYS:
  564:         if name not in supplemental:
  565:             failures.append(f"supplemental check missing: {name}")
  566:         elif supplemental[name] is not True:
  567:             failures.append(f"supplemental check false: {name}={supplemental[name]!r}")
  568:     for name in sorted(set(supplemental) - set(SUPPLEMENTAL_KEYS)):
  569:         failures.append(f"supplemental check unknown: {name}")
  570:     if stop_reason != "verified_done":
  571:         failures.append(f"stop reason is not verified_done: {stop_reason!r}")
  572:     for code in exit_codes:
  573:         if code != 0:
  574:             failures.append(f"non-zero process exit code: {code}")
  575:     if physical_requests > max_requests:
  576:         failures.append(
  577:             f"physical requests {physical_requests} exceed the authorized budget {max_requests}"
  578:         )
  579:     for key in REQUIRED_EVIDENCE.get(mode, ()):
  580:         if not evidence.get(key):
  581:             failures.append(f"correction journey evidence missing: {key}")
  582:     return {
  583:         "mode": mode,
  584:         "product_status": "completed" if not failures else "incomplete",
  585:         "failures": failures,
  586:         "typed_terminal": typed_terminal,
  587:         "business_checks": {
  588:             key: bool(business.get(key, False)) for key in BOUND_BUSINESS_KEYS
  589:         },
  590:         "business_declared_false": {
  591:             key: bool(business.get(key, False)) for key in PROCESS_DECLARED_KEYS
  592:         },
  593:         "supplemental_checks": supplemental,
  594:         "stop_reason": stop_reason,
  595:         "exit_codes": exit_codes,
  596:         "physical_requests": physical_requests,
  597:         "max_requests": max_requests,
  598:         "evidence": evidence,
  599:     }
  600: 
  601: 
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
```

## agent/automation/cli.py:1-130
```text
    1: """Thin owner CLI for the portable 019 management and reconcile boundary."""
    2: 
    3: from __future__ import annotations
    4: 
    5: import argparse
    6: import json
    7: from collections.abc import Callable, Sequence
    8: from dataclasses import asdict
    9: 
   10: from agent.automation.composition import AutomationControlCoreV1
   11: from agent.automation.reconcile import ReconcileAutomationsResultV1, ReconcileAutomationsV1
   12: from agent.automation.store import decode_definition_body_json
   13: 
   14: _MAX_TRIGGER_BYTES = 4_096
   15: 
   16: 
   17: def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
   18:     result: dict[str, object] = {}
   19:     for key, value in pairs:
   20:         if key in result:
   21:             raise ValueError(f"duplicate JSON member: {key}")
   22:         result[key] = value
   23:     return result
   24: 
   25: 
   26: def decode_reconcile_request(raw: str) -> ReconcileAutomationsV1:
   27:     if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_TRIGGER_BYTES:
   28:         raise ValueError("reconcile payload must be bounded text")
   29:     try:
   30:         document = json.loads(raw, object_pairs_hook=_strict_object)
   31:     except json.JSONDecodeError as error:
   32:         raise ValueError("reconcile payload is malformed JSON") from error
   33:     if not isinstance(document, dict) or set(document) != {"schema_version", "delivery_id"}:
   34:         raise ValueError("reconcile payload fields must be exact")
   35:     request = ReconcileAutomationsV1(
   36:         schema_version=document["schema_version"],
   37:         delivery_id=document["delivery_id"],
   38:     )
   39:     if _json({"schema_version": request.schema_version, "delivery_id": request.delivery_id}) != raw:
   40:         raise ValueError("reconcile payload must be canonical JSON")
   41:     return request
   42: 
   43: 
   44: def build_parser() -> argparse.ArgumentParser:
   45:     parser = argparse.ArgumentParser(
   46:         prog="first-agent-schedule",
   47:         description=(
   48:             "This installed command does not include a runnable host composition."
   49:         ),
   50:         epilog=(
   51:             "Commands fail closed with needs_019_config until a trusted host injects "
   52:             "the control core. It does not install login items or background jobs."
   53:         ),
   54:     )
   55:     commands = parser.add_subparsers(dest="command", required=True)
   56:     create = commands.add_parser("create")
   57:     _definition_args(create, include_id=False)
   58:     preview = commands.add_parser("preview")
   59:     preview.add_argument("automation_id")
   60:     approve = commands.add_parser("approve")
   61:     approve.add_argument("automation_id")
   62:     approve.add_argument("--preview-digest", required=True)
   63:     _mutation_tokens(approve)
   64:     commands.add_parser("list")
   65:     show = commands.add_parser("show")
   66:     show.add_argument("automation_id")
   67:     open_command = commands.add_parser("open")
   68:     open_command.add_argument("automation_id")
   69:     update = commands.add_parser("update")
   70:     _definition_args(update, include_id=True)
   71:     for name in ("pause", "resume", "cancel"):
   72:         command = commands.add_parser(name)
   73:         command.add_argument("automation_id")
   74:         _mutation_tokens(command)
   75:     purge = commands.add_parser("purge")
   76:     purge.add_argument("automation_id")
   77:     purge.add_argument("--preview-digest")
   78:     purge.add_argument("--expected-token")
   79:     purge.add_argument("--next-token")
   80:     wake = commands.add_parser("wake")
   81:     wake.add_argument("operation", choices=("enable", "disable"))
   82:     reconcile = commands.add_parser("reconcile")
   83:     reconcile.add_argument("--delivery-id")
   84:     return parser
   85: 
   86: 
   87: def _definition_args(parser: argparse.ArgumentParser, *, include_id: bool) -> None:
   88:     if include_id:
   89:         parser.add_argument("automation_id")
   90:     parser.add_argument("--definition-json", required=True)
   91:     _mutation_tokens(parser)
   92: 
   93: 
   94: def _mutation_tokens(parser: argparse.ArgumentParser) -> None:
   95:     parser.add_argument("--expected-token", required=True)
   96:     parser.add_argument("--next-token", required=True)
   97: 
   98: 
   99: def run_cli(
  100:     argv: Sequence[str] | None = None,
  101:     *,
  102:     core: AutomationControlCoreV1 | None,
  103:     write_fn: Callable[[str], None] = print,
  104: ) -> int:
  105:     args = build_parser().parse_args(argv)
  106:     if core is None:
  107:         write_fn(_json({"code": "needs_019_config", "reason": "host_profile_unavailable"}))
  108:         return 2
  109:     try:
  110:         payload = _dispatch(args, core)
  111:     except Exception as error:
  112:         write_fn(_json({"code": "invalid_request", "reason": type(error).__name__}))
  113:         return 2
  114:     write_fn(_json(payload))
  115:     return 0 if payload.get("code") not in {"needs_019_config", "invalid_request"} else 2
  116: 
  117: 
  118: def _dispatch(args: argparse.Namespace, core: AutomationControlCoreV1) -> dict[str, object]:
  119:     management = core.management
  120:     if args.command == "reconcile":
  121:         return _reconcile_payload(
  122:             core.reconcile(ReconcileAutomationsV1(delivery_id=args.delivery_id))
  123:         )
  124:     if args.command == "create":
  125:         result = management.create(
  126:             decode_definition_body_json(args.definition_json),
  127:             expected_snapshot_token=args.expected_token,
  128:             next_snapshot_token=args.next_token,
  129:         )
  130:         return _management_payload(result)
```

## agent/composition.py:330-570
```text
  330:             (Path("/System/Library").resolve(strict=True), Path("/usr/lib").resolve(strict=True)),
  331:             key=str,
  332:         )
  333:     )
  334:     system_digest = canonical_json_digest(
  335:         {"roots": [str(root) for root in system_roots]}
  336:     )
  337:     canonical_temp = Path(_tempfile.gettempdir()).resolve(strict=True)
  338:     base = (
  339:         canonical_temp
  340:         / (
  341:             "first-agent-skill-"
  342:             + hashlib.sha256(str(state_root).encode()).hexdigest()[:12]
  343:         )
  344:     )
  345:     temp_root = base / "temp"
  346:     home_root = base / "home"
  347:     temp_root.mkdir(parents=True, exist_ok=True, mode=0o700)
  348:     home_root.mkdir(parents=True, exist_ok=True, mode=0o700)
  349:     return SkillExecutionConfig(
  350:         runtime=runtime,
  351:         workspace_root=workspace,
  352:         temp_root=temp_root,
  353:         state_root=state_root,
  354:         home_root=home_root,
  355:         system_runtime_roots=system_roots,
  356:         system_runtime_digest=system_digest,
  357:         private_roots=(),
  358:         executor=NativeSandboxExecutor(confiner=confiner),
  359:     )
  360: 
  361: 
  362: @dataclass(frozen=True, slots=True)
  363: class WebResources:
  364:     """固定 Tavily client 的 registrations 与有序 closeables。"""
  365: 
  366:     registrations: tuple[RegisteredTool, ...]
  367:     closeables: tuple[Callable[[], None], ...]
  368:     readiness: WebReadiness
  369:     credential_env: str | None = None
  370: 
  371: 
  372: class WebReadiness(StrEnum):
  373:     """只描述本地配置就绪度；启动时不做网络健康检查。"""
  374: 
  375:     NOT_ENABLED = "not_enabled"
  376:     READY = "ready"
  377:     TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
  378: 
  379: 
  380: def build_web_resources(
  381:     profile: WebProfileV1 | None,
  382:     *,
  383:     credential: str | None,
  384:     http_client: httpx.Client | None = None,
  385:     clock: Callable[[], str] | None = None,
  386:     attempt_recorder: TransportAttemptRecorder | None = None,
  387: ) -> WebResources:
  388:     """未配置时显式关闭；配置后 key 只进入 client 内存。"""
  389:     if profile is None:
  390:         if credential is not None:
  391:             raise ValueError("Web credential cannot be supplied without a profile")
  392:         return WebResources((), (), WebReadiness.NOT_ENABLED)
  393:     if not credential:
  394:         return WebResources(
  395:             (),
  396:             (),
  397:             WebReadiness.TEMPORARILY_UNAVAILABLE,
  398:             credential_env=profile.credential_env,
  399:         )
  400:     client = TavilyClient(
  401:         profile,
  402:         api_key=credential,
  403:         http_client=http_client,
  404:         attempt_recorder=attempt_recorder,
  405:     )
  406:     observed_at = clock or (
  407:         lambda: datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
  408:     )
  409:     return WebResources(
  410:         registrations=build_web_tool_registrations(
  411:             client,
  412:             profile,
  413:             clock=observed_at,
  414:         ),
  415:         closeables=(client.close,) if client.owns_client else (),
  416:         readiness=WebReadiness.READY,
  417:         credential_env=profile.credential_env,
  418:     )
  419: 
  420: 
  421: def build_mcp_resources(
  422:     catalog_config: dict[str, object],
  423:     safety_state: Path,
  424:     *,
  425:     env_provider: Callable[[tuple[str, ...]], dict[str, str]],
  426:     composition_epoch: str | None = None,
  427:     timeouts: SessionTimeouts | None = None,
  428: ) -> McpResources:
  429:     """构建 MCP registrations + bridge/latch。latch 若处于 unresolved ARMED，fail closed。"""
  430:     latch = McpSafetyLatch(safety_state)
  431:     latch.require_clear_for_composition()
  432:     catalog = build_mcp_catalog(catalog_config)
  433:     bridge = McpAsyncBridge(total_timeout_seconds=60.0)
  434:     config = McpExecutorConfig(
  435:         bridge=bridge,
  436:         latch=latch,
  437:         composition_epoch=composition_epoch or secrets.token_hex(8),
  438:         timeouts=timeouts or SessionTimeouts(),
  439:         env_provider=env_provider,
  440:     )
  441:     registrations = build_mcp_tool_registrations(catalog, executor_config=config)
  442:     return McpResources(
  443:         registrations=registrations,
  444:         closeables=(bridge.close,),
  445:         latch=latch,
  446:     )
  447: 
  448: 
  449: def load_mcp_catalog_file(path: Path) -> dict[str, object]:
  450:     """读取显式 MCP catalog JSON。credential value 不会进入运行时；错误不泄露路径。"""
  451:     fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  452:     try:
  453:         raw = b""
  454:         while True:
  455:             chunk = os.read(fd, 65_536)
  456:             if not chunk:
  457:                 break
  458:             raw += chunk
  459:             if len(raw) > 1_000_000:
  460:                 raise McpCatalogError("mcp catalog exceeds the size limit")
  461:     finally:
  462:         os.close(fd)
  463:     try:
  464:         config = json.loads(raw.decode("utf-8"))
  465:     except (UnicodeDecodeError, json.JSONDecodeError) as error:
  466:         raise McpCatalogError("mcp catalog must be valid JSON") from error
  467:     if not isinstance(config, dict):
  468:         raise McpCatalogError("mcp catalog must be a JSON object")
  469:     return config
  470: 
  471: 
  472: def build_composition(
  473:     *,
  474:     provider: ModelProvider,
  475:     checkpoint_store: CheckpointStore,
  476:     tool_registrations: tuple[RegisteredTool, ...],
  477:     event_sink: EventSink,
  478:     progress_event_sink: EventSink | None = None,
  479:     system_policy: str,
  480:     context_limits: ContextLimits,
  481:     invocation_limits: InvocationLimits,
  482:     closeables: tuple[Callable[[], None], ...] = (),
  483:     sources: tuple = (),
  484:     workspace_identity_digest: str = "",
  485:     context_scope_digest: str = "",
  486:     provider_descriptor: ProviderDescriptor | None = None,
  487:     control_inbox: ControlInbox | None = None,
  488:     strict_control_schema: bool = False,
  489:     workspace_binding: ConversationWorkspaceBindingV1 | None = None,
  490:     sandbox_receipt_book=None,
  491:     browser_takeover_complete: Callable[[object], int] | None = None,
  492:     background_claim_verifier: BackgroundClaimVerifier | None = None,
  493:     background_execution_authority: BackgroundExecutionAuthorityV1 | None = None,
  494:     tool_clock: Callable[[], str] | None = None,
  495:     conversation_archive: ConversationArchive | None = None,
  496: ) -> Composition:
  497:     if workspace_binding is not None and (
  498:         workspace_binding.workspace_identity_digest != workspace_identity_digest
  499:         or workspace_binding.workspace_scope_digest != context_scope_digest
  500:     ):
  501:         raise ValueError("composition workspace binding does not match its identity inputs")
  502:     control_inbox = control_inbox or ControlInbox()
  503:     tool_runtime = KernelToolRuntime(
  504:         tool_registrations,
  505:         clock=tool_clock,
  506:         sandbox_receipt_book=sandbox_receipt_book,
  507:         background_claim_verifier=background_claim_verifier,
  508:     )
  509:     definitions = tool_runtime.definitions()
  510:     authority_snapshot = canonical_json_digest(
  511:         {
  512:             "version": "fixed-composition-v1",
  513:             "workspace_identity_digest": workspace_identity_digest,
  514:             "provider_descriptor_digest": (
  515:                 provider_descriptor.identity_digest
  516:                 if provider_descriptor is not None
  517:                 else "local-unbound"
  518:             ),
  519:             "tools": [
  520:                 {
  521:                     "name": definition.name,
  522:                     "input_schema": definition.input_schema,
  523:                     "side_effect": definition.side_effect.value,
  524:                     "egress": definition.egress.value,
  525:                     "execution_authority": definition.execution_authority.value,
  526:                 }
  527:                 for definition in definitions
  528:             ],
  529:         }
  530:     )
  531:     context_manager = KernelContextManager(
  532:         system_policy=system_policy,
  533:         limits=context_limits,
  534:         sources=sources,
  535:         workspace_identity_digest=workspace_identity_digest,
  536:         context_scope_digest=context_scope_digest,
  537:         authority_snapshot=authority_snapshot,
  538:         strict_control_schema=strict_control_schema,
  539:     )
  540:     runtime = AgentRuntime(
  541:         provider=provider,
  542:         context_manager=context_manager,
  543:         tool_runtime=tool_runtime,
  544:         checkpoint_store=checkpoint_store,
  545:         event_sink=event_sink,
  546:         progress_event_sink=progress_event_sink,
  547:         limits=invocation_limits,
  548:         provider_descriptor=provider_descriptor,
  549:         control_inbox=control_inbox,
  550:         workspace_binding=workspace_binding,
  551:         browser_takeover_complete=browser_takeover_complete,
  552:         background_execution_authority=background_execution_authority,
  553:         conversation_archive=conversation_archive,
  554:     )
  555:     return Composition(
  556:         runtime=runtime,
  557:         tool_runtime=tool_runtime,
  558:         context_manager=context_manager,
  559:         control_inbox=control_inbox,
  560:         close_stack=closeables,
  561:         sources=sources,
  562:     )
  563: 
  564: 
  565: def build_memory_resources(
  566:     store: MemoryStore,
  567:     *,
  568:     workspace_scope_digest: str,
  569: ) -> MemoryResources:
  570:     """从已 create/load 的 store 构建 Memory source + governed tool registrations。"""
```

## pyproject.toml:1-65
```text
    1: [build-system]
    2: requires = ["setuptools>=68.0"]
    3: build-backend = "setuptools.build_meta"
    4: 
    5: [project]
    6: name = "first-agent"
    7: version = "1.0.0"
    8: description = "First Agent — local-first agent runtime"
    9: readme = "README.md"
   10: license = {text = "MIT"}
   11: requires-python = ">=3.11"
   12: dependencies = [
   13:     "httpx>=0.27.1",
   14: ]
   15: 
   16: [project.optional-dependencies]
   17: dev = [
   18:     "pytest>=8.0",
   19:     "ruff>=0.15.0",
   20:     "setuptools>=68.0",
   21: ]
   22: browser = [
   23:     "playwright==1.62.0",
   24: ]
   25: skill = [
   26:     "PyYAML>=6,<7",
   27: ]
   28: mcp = [
   29:     "mcp==1.28.1",
   30:     "anyio>=4.14.2",
   31:     "jsonschema>=4.23,<5",
   32: ]
   33: tui = [
   34:     "textual>=8.2,<9",
   35: ]
   36: 
   37: [project.scripts]
   38: first-agent = "main:main"
   39: first-agent-schedule = "agent.automation.cli:main"
   40: 
   41: [tool.setuptools]
   42: py-modules = ["main"]
   43: 
   44: [tool.setuptools.packages.find]
   45: include = ["agent", "agent.*", "first_agent_skill_runner"]
   46: 
   47: [tool.ruff]
   48: target-version = "py311"
   49: line-length = 100
   50: exclude = [".ua", "graphify-out"]
   51: 
   52: [tool.ruff.lint]
   53: select = ["E", "F", "I", "N", "W", "UP", "B", "SIM"]
   54: 
   55: [tool.ruff.lint.isort]
   56: known-first-party = ["agent", "scripts", "tests"]
   57: # pytest 配置以仓库根 pytest.ini 为准（testpaths/markers/filterwarnings/addopts）；
   58: # 此处不再重复定义，避免双份配置互相遮蔽。
   59: 
```
