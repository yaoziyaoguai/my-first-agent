"""Kernel 的纯状态转换。

这里不调用模型、工具、持久化或事件 sink。所有外部效果由 loop 在状态转换之间排序。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta

from agent.runtime.compaction_rules import validate_compaction_removal
from agent.runtime.contracts import (
    GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES,
    SANDBOX_EXPIRY_MINUTES,
    AbandonUnknownModelOutcome,
    AcknowledgeProviderDisclosure,
    Action,
    ActionDisposition,
    ActionTransition,
    ActiveRun,
    ActiveRunStatus,
    AdmittedCriterion,
    ApprovalGrant,
    ApprovalRequest,
    AuthoritySourceKind,
    BackgroundActionAuthorityV1,
    BeginAnswer,
    BlockedClaim,
    BrowserAuthorityLeaseV1,
    BrowserTakeoverRequestV1,
    CancelBrowserTakeover,
    CancelGoal,
    CancelRun,
    CitationManifestV1,
    ClarificationRequest,
    CompleteBrowserTakeover,
    CompletionClaim,
    ConfirmCriterion,
    ContinuationPhase,
    ControlInboxRequest,
    ControlReceipt,
    ControlRequestKind,
    ConversationFact,
    ConversationState,
    ConversationSummaryV1,
    CriterionAdmissionBinding,
    EgressClass,
    EvidenceOracleKind,
    EvidenceRecord,
    ExecuteOperatorTool,
    ExecutingIntentRecord,
    ExecutionAuthorityClass,
    FactKind,
    GoalAuthorizationBinding,
    GoalAuthorizationScope,
    GoalBootstrap,
    GoalDelta,
    GoalDeltaProposal,
    GoalDraftProposal,
    GoalFrame,
    GoalProgress,
    GoalProposal,
    GoalStatus,
    GrantProviderConsent,
    InteractionState,
    InvocationOrigin,
    PauseGoal,
    PersistedModelResponseV1,
    ProcessAuthorityCandidateV1,
    ProcessAuthorityLeaseV1,
    ProcessReceiptV1,
    ProposedCriterion,
    ProviderCallIntentV1,
    ProviderConsentGrantStatus,
    ProviderConsentScopeV1,
    ProviderContinuationV1,
    ProviderDisclosureRequest,
    ProviderDisclosureRequestV2,
    ProviderFileSourceProofV1,
    ProviderSummarySourceBoundaryV1,
    RecordedRunResult,
    RecoverUnknownObservation,
    RecoveryRequest,
    ReplayRecord,
    ResolveApproval,
    ResolveUnknownToolOutcome,
    Resume,
    ResumeGoal,
    RevokeGoalTargetAuthority,
    RevokeProcessAuthority,
    RevokeProviderConsent,
    RunStatus,
    SandboxAuthorityLeaseV1,
    SideEffectClass,
    SourceKind,
    SourceReceiptV1,
    SubmitMessage,
    ToolCall,
    canonical_action_digest,
    canonical_json_digest,
    safe_goal_authorization_target,
    source_result_since_latest_user,
)
from agent.runtime.provider_consent import (
    mint_provider_consent_grant,
)
from agent.runtime.resource_lifecycle import active_task_resources


class GoalRevisionConflictError(ValueError):
    pass


_EXPLICIT_PUBLIC_WEB_PATTERNS = (
    re.compile(
        r"(?:公开(?:的)?(?:资料|信息|来源|说明|网页|网站|\s*web)|"
        r"(?:联网|在线|网上)(?:资料|信息|来源|搜索|查找)|"
        r"(?:最新|当前).{0,16}(?:公开|网页|网站|web|在线))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:public\s+(?:web|source|sources|information)|"
        r"web\s+(?:research|source|sources|search)|"
        r"online\s+(?:source|sources|research|information)|"
        r"(?:latest|current).{0,24}(?:public|online|web)|"
        r"(?:latest|current)\s+(?:release|package|version|versions|information|"
        r"info|documentation|docs|data|news))\b",
        re.IGNORECASE,
    ),
)
_EXPLICIT_LOCAL_PROCESS_PATTERNS = (
    # R3：中文连接词后的运行/执行动词与句首同权（并/并且、然后/接着/随后/继而、
    # 好后/完后/毕后/以后），明确执行要求不能因连接方式不同而丢义务；
    # (?<!合) 排除"合并运行"这类词内误匹配。
    re.compile(
        r"(?:^|[\n:：]|(?<!合)并(?:且)?|然后|接着|随后|继而|(?:好|完|毕|以)后)\s*"
        r"(?:(?:please\s+)?(?:run|execute)\s+|"
        r"(?:请\s*)?(?:运行|执行)\s*)"
        r"[A-Za-z0-9_.-]+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:调用|使用)\s*local_process\b|"
        r"\b(?:call|invoke)\s+(?:the\s+)?local_process\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:运行|执行|跑|启动).{0,24}(?:测试|校验|验证|检查|构建|命令|脚本|校验器)|"
        r"(?:测试|构建|校验|验证).{0,16}(?:运行|执行|确认|通过)|"
        r"(?:运行|执行)\s+(?:\./|/)[^\s,;，。]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:run|execute|build|test|validate|check)\b.{0,40}"
        r"(?:test|tests|validator|command|script|build|format|project)\b|"
        r"\b(?:make|ensure)\b.{0,24}\btests?\s+pass\b|"
        r"\b(?:run|execute)\s+(?:\./|/)[^\s,;]+",
        re.IGNORECASE,
    ),
)
_NON_AUTHORITATIVE_PUBLIC_WEB_SPANS = (
    re.compile(
        r"\b(?:explain|explains|explaining|describe|describes|describing)\b\s+"
        r"(?:the\s+)?(?:latest|current)\s+(?:release|package|version|versions)"
        r"(?:\s+(?:versioning|information|docs?|data))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:contain|contains|containing|include|includes|including|mention|"
        r"mentions|mentioning)\b[^,.;!?]{0,24}\b(?:the\s+)?phrase\s+"
        r"(?:public\s+web\s+research|web\s+(?:research|search)|"
        r"(?:latest|current)\s+(?:release|package|version|information))\b",
        re.IGNORECASE,
    ),
)
_NON_AUTHORITATIVE_LOCAL_PROCESS_SPANS = (
    re.compile(
        r"^\s*how\s+(?:do|can|should|would)\s+(?:i|we|you)\s+"
        r"(?:run|execute|build|test|validate|check)\b[^?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*what\s+(?:command|script|tool)\b[^?]{0,32}"
        r"(?:run|runs|execute|executes|test|tests|validate|validates)\b[^?]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:如何|怎么|为什么)[^，。；;!?！？]{0,32}"
        r"(?:运行|执行|测试|校验|验证)[^，。；;!?！？]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:explain|explains|explaining|describe|describes|describing)\b\s+"
        r"how\s+to\s+(?:run|execute|build|test|validate|check)\s+"
        r"(?:the\s+)?(?:project\s+)?(?:tests?|validator|command|script|build)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:contain|contains|containing|include|includes|including|mention|"
        r"mentions|mentioning)\b[^,.;!?]{0,24}\b(?:the\s+)?phrase\s+"
        r"(?:call|invoke)\s+(?:the\s+)?local_process\b",
        re.IGNORECASE,
    ),
)
_NEGATED_PUBLIC_WEB_PATTERNS = (
    re.compile(
        r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
        r"[^，。；;,.!?！？]{0,16}"
        r"(?:联网|上网|在线|网上|公开(?:资料|信息|来源|网页|网站)|web)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:仅|只)(?:使用|用|在)?[^，。；;,.!?！？]{0,8}本地"
        r"[^，。；;,.!?！？]{0,12}(?:资料|信息|来源|文件|数据)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
        r"[^,.;!?]{0,32}(?:web|online|internet|public\s+source|external\s+source|"
        r"(?:latest|current)[^,.;!?]{0,16}(?:release|package|version|information|"
        r"info|documentation|docs|data|news))",
        re.IGNORECASE,
    ),
)
_NEGATED_LOCAL_PROCESS_PATTERNS = (
    re.compile(
        r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
        r"[^，。；;,.!?！？]{0,16}(?:调用|使用)?\s*local_process\b|"
        r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
        r"[^,.;!?]{0,24}(?:call|invoke)?\s*(?:the\s+)?local_process\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:不要|别|不得|禁止|无需|不用|不需要|不准)"
        r"[^，。；;,.!?！？]{0,16}"
        r"(?:运行|执行|跑|启动|测试|构建|校验|验证|命令|脚本|校验器)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:do\s+not|don't|must\s+not|never|without|no\s+need\s+to)"
        r"[^,.;!?]{0,24}(?:run|execute|build|test|validate|validator|command|script)",
        re.IGNORECASE,
    ),
)
_REQUIREMENT_CLAUSE_BOUNDARY = re.compile(
    r"(?:[，。；;,!?！？]+|\.(?!/)|但是|但|而是|\bbut\b|\bhowever\b)",
    re.IGNORECASE,
)
_PROCESS_OUTPUT_PATH_PATTERN = re.compile(
    r"(?:^|[/_.-])(?:test|tests|testing|result|results|output|outputs|log|logs|"
    r"coverage|junit|check|validator)(?:[/_.-]|$)",
    re.IGNORECASE,
)
_PROCESS_OUTPUT_DESCRIPTION_PATTERN = re.compile(
    r"(?:测试|校验|验证).{0,16}(?:输出|结果|日志|报告|文件)|"
    r"\b(?:test|validation|validator|check).{0,24}(?:output|result|log|report|file)\b",
    re.IGNORECASE,
)
_PROCESS_ENTRYPOINT_PATTERN = re.compile(
    r"(?:运行|执行|run|execute)\s+((?:\./|/)[^\s，。；;,!?！？]+)",
    re.IGNORECASE,
)
_PROCESS_ENTRYPOINT_CLAUSE_BOUNDARY = re.compile(
    r"(?:[，。；;,!?！？]+|\.(?=\s|$)|但是|但|而是|\bbut\b|\bhowever\b)",
    re.IGNORECASE,
)
# W1：明确文件交付对象的有限识别（与显式 process 要求同型，只认直接正向
# 精确 workspace-relative 路径；阅读/参照/引文/疑问/禁止语境不进下界）。
# 2026-10-18 发布包 A：token 边界改为显式校验（见 _deliverable_token_boundary_ok），
# 允许汉字直接邻接 ASCII 相对路径；单文件形式的扩展名必须字母开头（3.12 这类
# 版本号不是文件）。不再用 `(?<![/\w.])`——它的 Unicode \w 把相邻汉字也当排除。
_DELIVERABLE_PATH_TOKEN = re.compile(
    r"("
    r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?"
    r"(?:/[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?)+"
    r"|[A-Za-z0-9_][A-Za-z0-9_-]*\.[A-Za-z][A-Za-z0-9]{0,11}"
    r")"
)
# 分句级说明型语境：句首疑问词 + 任意位置的 explain；Could/Would you 礼貌
# 请求不再被整句排除（发布包 A 矩阵：礼貌请求仍是交付要求）。
_DELIVERABLE_QUESTION_CLAUSE = re.compile(
    r"^\s*(?:如何|怎么|为什么|是否|请问|\bhow\b|\bwhat\b|\bwhy\b|\bcan\b|\bdo(?:es)?\b)",
    re.IGNORECASE,
)
_DELIVERABLE_EXPLANATION_CLAUSE = re.compile(r"\bexplain\b", re.IGNORECASE)
_DELIVERABLE_VERB_PATTERN = re.compile(
    r"(?:创建|新建|生成|写入|修改|更新|编辑|添加|新增|实现|重构|"
    # 非编码文件交付动词（2026-10-24 P2；审计 D-1 收窄）：必须带目的地
    # 标记（成/到/为，允许短宾语间隔）——裸「总结/整理 failures.log」是
    # 读引用（口头总结），不得铸成强制文件交付义务（会确定性卡死 W1 完成门）。
    r"整理成|整理到|总结到|汇总到|写成|保存为|保存到|输出到|记录到|归档为"
    r"|(?:整理|总结|汇总|保存|输出|记录|归档).{0,24}(?:成|到|为)|"
    r"\b(?:create|generate|write|update|modify|edit|implement|add|refactor)\b|"
    # 英文 save/summarize/organize 同理：必须 into/to/as 指向文件名；
    # 匹配在标记处结束，24 字符窗口只覆盖目的地文件，不覆盖直接宾语。
    r"\b(?:save|summarize|organize)\b.{0,60}\b(?:into|to|as)\b)",
    re.IGNORECASE,
)
_DELIVERABLE_READING_VERB_PATTERN = re.compile(
    r"(?:阅读|读取|查看|参照|参考|打开|"
    r"\b(?:read|review|refer|consult)\b|\blook\s+at\b|\bsee\b)",
    re.IGNORECASE,
)
_DELIVERABLE_SUBJECT_AFTER_PATTERN = re.compile(
    r"^[\s\S]{0,20}?(?:必须|也要|要改|改为|改用|实现|写入|\bmust\b|\bshall\b)",
)
# "实现 SPEC.md 中要求的…" / "按 SPEC.md 的说明实现…"：紧跟路径的规格指称
# 说明该文件是参考输入，不是交付对象（W1.3.3 输出/输入区分）。
# 2026-10-18 发布包 A：扩requirements/实现需求 指称（Implement SPEC.md
# requirements、根据 SPEC.md 实现需求——规格是输入不是输出）。
_DELIVERABLE_REFERENCE_AFTER_PATTERN = re.compile(
    r"^[\s\S]{0,6}?(?:中要求|中描述|中规定|中定义|中说明|的说明|的描述|的规定|的定义"
    r"|实现需求|的需求|\brequirements?\b)"
)
# 「的说明」类属格后缀可被“直接修改 PATH 本身”压过：修改 SPEC.md 的说明
# 中，修改紧邻路径，交付对象就是 SPEC.md；按/根据 引导时路径仍是输入。
_DELIVERABLE_POSSESSIVE_AFTER_PATTERN = re.compile(r"^[\s\S]{0,4}?(?:的说明|的描述|的规定|的定义)")
_DELIVERABLE_DIRECT_EDIT_BEFORE_PATTERN = re.compile(r"(?:修改|更新|编辑|重写|创建|新建|写入)\s*$")
_DELIVERABLE_NEGATION_PATTERN = re.compile(
    r"(?:不要|别|不得|禁止|无需|不用|不需要|不准|"
    r"\bdo\s+not\b|\bdon't\b|\bmust\s+not\b|\bnever\b)",
    re.IGNORECASE,
)
# 日志报告：句首「日志显示」起进入报告语境，跨分号继承；出现明确的
# 「请修改…」类新请求时从该句起恢复权威。只覆盖这一有限语法。
_DELIVERABLE_LOG_REPORT_CLAUSE = re.compile(r"^\s*日志显示")
_DELIVERABLE_LOG_EXIT_REQUEST = re.compile(r"请(?:修改|更新|编辑|重写|创建|新建|写入|生成|添加)")
_NON_AUTHORITATIVE_DELIVERABLE_SPANS = (
    re.compile(r"```[\s\S]*?```"),
    re.compile(r"「[^」]*」"),
    re.compile(r"“[^”]*”"),
)


def _goal_source_text(
    state: ConversationState,
    bootstrap: GoalBootstrap,
) -> str:
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id == bootstrap.source_fact_id and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    text = source.content.get("text") if source is not None else None
    return text if isinstance(text, str) else ""


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _without_non_authoritative_spans(
    text: str,
    patterns: tuple[re.Pattern[str], ...],
) -> str:
    candidate = text
    for pattern in patterns:
        candidate = pattern.sub(" ", candidate)
    return candidate


def _classify_explicit_requirement(
    text: str,
    *,
    positive_patterns: tuple[re.Pattern[str], ...],
    negative_patterns: tuple[re.Pattern[str], ...],
    non_authoritative_spans: tuple[re.Pattern[str], ...] = (),
) -> bool | None:
    """返回 authoritative 文本对一种 effect 的明确要求、禁止或未表态。"""

    classification: bool | None = None
    for clause in _REQUIREMENT_CLAUSE_BOUNDARY.split(text):
        if not clause.strip():
            continue
        candidate = _without_non_authoritative_spans(
            clause,
            non_authoritative_spans,
        )
        negative = _matches_any(candidate, negative_patterns)
        if _matches_any(candidate, positive_patterns) and not negative:
            classification = True
        elif negative:
            classification = False
    return classification


def _public_web_requirement(text: str) -> bool | None:
    return _classify_explicit_requirement(
        text,
        positive_patterns=_EXPLICIT_PUBLIC_WEB_PATTERNS,
        negative_patterns=_NEGATED_PUBLIC_WEB_PATTERNS,
        non_authoritative_spans=_NON_AUTHORITATIVE_PUBLIC_WEB_SPANS,
    )


def _local_process_requirement(text: str) -> bool | None:
    return _classify_explicit_requirement(
        text,
        positive_patterns=_EXPLICIT_LOCAL_PROCESS_PATTERNS,
        negative_patterns=_NEGATED_LOCAL_PROCESS_PATTERNS,
        non_authoritative_spans=_NON_AUTHORITATIVE_LOCAL_PROCESS_SPANS,
    )


def normalize_process_entrypoint(value: str) -> str:
    """规范化 authoritative fact 与 ToolCall 中的同一个 entrypoint token。"""

    return value.strip().rstrip("。；;,.!?！？")


def authoritative_process_entrypoints(state: ConversationState) -> frozenset[str]:
    """提取当前 Goal 中仍生效的显式 process entrypoint。

    这里只读取 Runtime 已接受的 authoritative user facts。否定 clause 会撤销同一
    path，避免 ``不要运行 ./old，只运行 ./check`` 被错误解释成两个必跑入口。
    没有显式 path 时返回空集；该场景仍由 exact process approval 绑定实际命令。
    """

    goal = state.goal
    if goal is None:
        return frozenset()
    source_ids = set(goal.created_from_fact_ids)
    requested: set[str] = set()
    for fact in state.facts:
        if fact.fact_id not in source_ids or fact.kind is not FactKind.USER_MESSAGE:
            continue
        text = fact.content.get("text")
        if not isinstance(text, str):
            continue
        clauses = tuple(
            _without_non_authoritative_spans(
                clause,
                _NON_AUTHORITATIVE_LOCAL_PROCESS_SPANS,
            )
            for clause in _PROCESS_ENTRYPOINT_CLAUSE_BOUNDARY.split(text)
        )
        if fact.content.get("control") == "goal_correction" and any(
            _PROCESS_ENTRYPOINT_PATTERN.search(clause) is not None for clause in clauses
        ):
            # 显式 entrypoint correction 替换旧 command authority；artifact-only
            # correction 没有 process path，因此仍保留原来的 exact binding。
            requested.clear()
        for clause in clauses:
            entrypoints = {
                normalize_process_entrypoint(match.group(1))
                for match in _PROCESS_ENTRYPOINT_PATTERN.finditer(clause)
            }
            if not entrypoints:
                continue
            negative = _matches_any(clause, _NEGATED_LOCAL_PROCESS_PATTERNS)
            if negative:
                requested.difference_update(entrypoints)
            elif _matches_any(clause, _EXPLICIT_LOCAL_PROCESS_PATTERNS):
                requested.update(entrypoints)
    return frozenset(requested)


def process_entrypoint_matches_authority(
    state: ConversationState,
    executable: str,
) -> bool:
    """显式 path 是 evidence admission 下界；无 path 时由 exact approval 绑定。"""

    requested = authoritative_process_entrypoints(state)
    return not requested or normalize_process_entrypoint(executable) in requested


def _last_match_end(text: str, pattern: re.Pattern[str]) -> int:
    return max((match.end() for match in pattern.finditer(text)), default=0)


def _normalize_deliverable_path_token(value: str) -> str:
    """交付路径 token 的安全校验：与 artifact_path 同一 workspace 相对语义。

    额外要求"路径形状"（含 ``/`` 或以扩展名结尾），避免把 ``max_retries`` 这类
    普通标识词当成文件交付对象；绝对路径、父目录逃逸与控制字符一律拒绝。
    """

    if (
        not value
        or len(value) > 1_000
        or value.startswith("/")
        or "\\" in value
        or any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value)
    ):
        return ""
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    if "/" not in value and re.search(r"\.[A-Za-z][A-Za-z0-9]{0,11}$", value) is None:
        return ""
    return value


def _deliverable_token_boundary_ok(clause: str, start: int, end: int) -> bool:
    """token 边界的显式校验（发布包 A）：既允许汉字直接邻接 ASCII 相对
    路径（``命令行适配器retry_app/cli.py``），又拒绝从非法路径形状截取
    合法子串（绝对/盘符/反斜线/URL/遍历续接/查询串/CJK 路径段）。
    """

    if start > 0:
        previous = clause[start - 1]
        if previous in "/.:-\\" or (previous.isascii() and (previous.isalnum() or previous == "_")):
            return False
        if not previous.isascii():
            # 汉字邻接合法，但 CJK 前缀串本身若是路径段（前面还有 `/`、
            # `:` 或 `\`），说明这是含非 ASCII 段的路径，不支持也不截后缀。
            index = start - 1
            while index >= 0 and not clause[index].isascii():
                index -= 1
            if index >= 0 and clause[index] in "/:\\":
                return False
    if end < len(clause):
        following = clause[end]
        if following in "\\:\ue000":
            return False
        if following == "?":
            rest = clause[end + 1 :]
            if rest and not rest[0].isspace():
                return False
        if clause.startswith("/.", end):
            return False
    return True


def authoritative_deliverable_file_paths(
    state: ConversationState,
) -> frozenset[str]:
    """提取当前 Goal 权威来源中仍生效的明确文件交付对象下界（W1）。

    只读 ``created_from_fact_ids`` 绑定的真实 USER_MESSAGE 原文（含已消费
    correction）。每个 clause 内按有限规则判定"直接正向的精确文件交付要求"：
    路径 token 附近的交付动词（就近原则压过阅读动词）、或路径后紧跟的主体
    要求词；疑问句、引文/代码块 span 与近距离禁止词不产生义务。跨 fact 按
    顺序做正/负更新——correction 新增即生效、点名撤回只移除被点名对象、
    沉默或无关 correction 不清空其它交付对象、未消费 correction 不生效。

    这是完成判断的下界，不是工具权限，也不声称覆盖任意自然语言语义：
    有限规则未识别的隐含要求仍由模型与独立验收负责。
    """

    goal = state.goal
    if goal is None:
        return frozenset()
    source_ids = set(goal.created_from_fact_ids)
    requested: set[str] = set()
    for fact in state.facts:
        if fact.fact_id not in source_ids or fact.kind is not FactKind.USER_MESSAGE:
            continue
        text = fact.content.get("text")
        if not isinstance(text, str):
            continue
        # 引文/围栏 span 在整条 authority fact 上先遮蔽再分句，跨分句引文
        # （“创建 a；修改 b”）不得借分句边界漏成权威请求。查询串（``?x=1``）
        # 的半角问号本身是分句边界，先占位保护再分句，避免路径被截出合法子串。
        text = _without_non_authoritative_spans(text, _NON_AUTHORITATIVE_DELIVERABLE_SPANS)
        text = re.sub(r"[?？](?=\S)", "", text)
        log_report = False
        # 逐 clause 判定；沿用 process 的 path-safe 断句（``app/worker.py``
        # 中的点号不当句边界）。
        for raw_clause in _PROCESS_ENTRYPOINT_CLAUSE_BOUNDARY.split(text):
            if not raw_clause.strip():
                continue
            if _DELIVERABLE_LOG_REPORT_CLAUSE.match(raw_clause):
                log_report = True
            if log_report:
                if _DELIVERABLE_LOG_EXIT_REQUEST.search(raw_clause):
                    # 明确新请求从本句起终止日志报告范围。
                    log_report = False
                else:
                    continue
            clause = raw_clause
            if _DELIVERABLE_QUESTION_CLAUSE.match(clause) or _DELIVERABLE_EXPLANATION_CLAUSE.search(
                clause
            ):
                continue
            for match in _DELIVERABLE_PATH_TOKEN.finditer(clause):
                path = _normalize_deliverable_path_token(match.group(1))
                if not path:
                    continue
                start, end = match.span(1)
                if not _deliverable_token_boundary_ok(clause, start, end):
                    continue
                if _DELIVERABLE_NEGATION_PATTERN.search(
                    clause[max(0, start - 16) : start] + " " + clause[end : end + 12]
                ):
                    requested.discard(path)
                    continue
                reference = _DELIVERABLE_REFERENCE_AFTER_PATTERN.match(clause[end : end + 14])
                if reference is not None:
                    # 直接修改 PATH 本身优先于「的说明」类输入后缀：紧邻
                    # 路径的直接编辑动词说明交付对象就是这个文件。
                    direct_edit = _DELIVERABLE_DIRECT_EDIT_BEFORE_PATTERN.search(
                        clause[max(0, start - 8) : start]
                    )
                    possessive = _DELIVERABLE_POSSESSIVE_AFTER_PATTERN.search(
                        clause[end : end + 10]
                    )
                    if not (direct_edit is not None and possessive is not None):
                        continue
                window = clause[max(0, start - 24) : start]
                deliverable_verb = _last_match_end(window, _DELIVERABLE_VERB_PATTERN)
                reading_verb = _last_match_end(window, _DELIVERABLE_READING_VERB_PATTERN)
                if deliverable_verb > reading_verb or (
                    _DELIVERABLE_SUBJECT_AFTER_PATTERN.match(clause[end : end + 24])
                ):
                    requested.add(path)
    return frozenset(requested)


def _looks_like_invented_process_artifact(
    criterion: ProposedCriterion,
    *,
    source_text: str,
) -> bool:
    path = criterion.artifact_path
    if path is None or path.casefold() in source_text.casefold():
        return False
    return (
        _PROCESS_OUTPUT_PATH_PATTERN.search(path) is not None
        or _PROCESS_OUTPUT_DESCRIPTION_PATTERN.search(criterion.description) is not None
    )


def _uses_runtime_owned_obligation_id(criterion: ProposedCriterion) -> bool:
    return criterion.criterion_id.startswith(
        (
            "criterion:required-public-web:",
            "criterion:required-local-process:",
            "criterion:required-governed-tool:",
        )
    )


def _is_runtime_owned_obligation(criterion: ProposedCriterion) -> bool:
    return (
        (
            criterion.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
            and criterion.criterion_id.startswith("criterion:required-public-web:")
        )
        or (
            criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and criterion.criterion_id.startswith("criterion:required-local-process:")
        )
        or (
            criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and criterion.criterion_id.startswith("criterion:required-governed-tool:")
        )
    )


# R3：可由 authoritative correction 撤回的义务仅限 classification 直接铸造的
# 两类；required-governed-tool 来自单独的用户审批，不随 effect 禁止撤回。
_WITHDRAWABLE_RUNTIME_OBLIGATION_PREFIXES = {
    EvidenceOracleKind.WEB_SOURCE_RECEIPT: "criterion:required-public-web:",
    EvidenceOracleKind.TOOL_RECEIPT: "criterion:required-local-process:",
}

# correction 显式要求某 effect 类时，该类去重只认同类前缀：TOOL_RECEIPT 下
# 只认 local-process——governed-tool 是另一类义务（MCP/SubAgent receipt，
# 不受 F1 进程失效约束，与本地验证判据可同时满足）。2026-10-24 F-C：去重
# 此前沿用 _is_runtime_owned_obligation（TOOL_RECEIPT 下同时匹配两个前缀），
# governed-tool pending 时一条用户明示的 process correction 会静默不铸，
# 用户明示的验证要求失去强制（与 E3 过铸死亡螺旋相反的欠铸失败模式）。
_REQUIRED_RUNTIME_OBLIGATION_PREFIXES = {
    EvidenceOracleKind.WEB_SOURCE_RECEIPT: "criterion:required-public-web:",
    EvidenceOracleKind.TOOL_RECEIPT: "criterion:required-local-process:",
}


def _apply_correction_lower_bounds(
    goal: GoalFrame,
    correction: ConversationFact,
) -> GoalFrame:
    """按 authoritative correction 补铸或撤回 Web/process 义务。"""

    text = correction.content.get("text")
    source_text = text if isinstance(text, str) else ""
    classifications = (
        (EvidenceOracleKind.WEB_SOURCE_RECEIPT, _public_web_requirement(source_text)),
        (EvidenceOracleKind.TOOL_RECEIPT, _local_process_requirement(source_text)),
    )
    required = tuple(
        oracle_kind for oracle_kind, classification in classifications if classification is True
    )
    prohibited = tuple(
        oracle_kind for oracle_kind, classification in classifications if classification is False
    )
    if not required and not prohibited:
        return goal
    identity = canonical_json_digest(
        {
            "goal_id": goal.goal_id,
            "correction_fact_id": correction.fact_id,
            "correction_text": source_text,
        }
    )
    criteria = goal.proposed_criteria
    # R3 撤回：correction 明确禁止该 effect 时，Runtime 早前为此铸的 proposed
    # 义务必须随现行版本失效；残留会让 verify_goal_completion 的 "process
    # criterion must be admitted" 检查永久失败，Goal 被 brick。未命中任何
    # 现存义务时语义未变化，保持 Goal 原样（noop 判定依赖此相等性）。
    for oracle_kind in prohibited:
        prefix = _WITHDRAWABLE_RUNTIME_OBLIGATION_PREFIXES[oracle_kind]
        criteria = tuple(
            item
            for item in criteria
            if not (item.oracle_kind is oracle_kind and item.criterion_id.startswith(prefix))
        )
    if not required and criteria == goal.proposed_criteria:
        return goal
    for oracle_kind in required:
        required_prefix = _REQUIRED_RUNTIME_OBLIGATION_PREFIXES[oracle_kind]
        runtime_owned = tuple(
            item
            for item in criteria
            if item.oracle_kind is oracle_kind
            and item.criterion_id.startswith(required_prefix)
        )
        criteria = tuple(
            item
            for item in criteria
            if item.oracle_kind is not oracle_kind or _is_runtime_owned_obligation(item)
        )
        if runtime_owned:
            continue
        if oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT:
            criterion = ProposedCriterion(
                criterion_id=f"criterion:required-public-web:{identity[:16]}",
                description="the requested public Web source was actually retrieved",
                oracle_kind=oracle_kind,
            )
        else:
            criterion = ProposedCriterion(
                criterion_id=f"criterion:required-local-process:{identity[:16]}",
                description=(
                    "the explicitly requested local validation process exits successfully"
                ),
                oracle_kind=oracle_kind,
            )
        criteria = (*criteria, criterion)
    retained_ids = {item.criterion_id for item in criteria}
    return replace(
        goal,
        proposed_criteria=criteria,
        admitted_criteria=tuple(
            item for item in goal.admitted_criteria if item.criterion_id in retained_ids
        ),
    )


def _unconsumed_goal_correction(
    state: ConversationState,
    goal: GoalFrame,
) -> ConversationFact | None:
    return next(
        (
            fact
            for fact in reversed(state.facts)
            if fact.kind is FactKind.USER_MESSAGE
            and fact.content.get("control") == "goal_correction"
            and fact.fact_id not in goal.created_from_fact_ids
        ),
        None,
    )


def goal_correction_adds_runtime_obligation(state: ConversationState) -> bool:
    """判断当前 correction 是否让 Runtime lower-bound 发生真实变化。"""

    goal = state.goal
    if goal is None:
        return False
    correction = _unconsumed_goal_correction(state, goal)
    if correction is None:
        return False
    return _apply_correction_lower_bounds(goal, correction) != goal


def _require_new_goal(state: ConversationState, goal: GoalFrame) -> None:
    if state.goal is not None:
        raise ValueError("conversation already has a goal")
    if goal.status is not GoalStatus.GOAL_READY:
        raise ValueError("new goal must start in GOAL_READY")
    fact_ids = {fact.fact_id for fact in state.facts}
    if not set(goal.created_from_fact_ids).issubset(fact_ids):
        raise ValueError("goal source fact is not authoritative conversation state")


def create_goal(state: ConversationState, goal: GoalFrame) -> ConversationState:
    _require_new_goal(state, goal)
    return replace(state, revision=state.revision + 1, goal=goal)


def _require_unused_correlation(state: ConversationState, correlation_id: str) -> None:
    if any(receipt.correlation_id == correlation_id for receipt in state.control_receipts):
        raise ValueError("control correlation_id was already accepted")


def accept_clarification_request(
    state: ConversationState,
    request: ClarificationRequest,
) -> ConversationState:
    """接受一次澄清控制块:登记 correlation 绑定的 receipt 并进入 durable CLARIFYING。

    问题文本由 loop 作为该 run 唯一 assistant message 落盘,这里不触碰 active_run。
    """
    _require_unused_correlation(state, request.correlation_id)
    accepted_revision = state.revision + 1
    payload_digest = canonical_json_digest(
        {
            "question": request.question,
            "boundary_code": request.boundary_code,
            "missing_fields": request.missing_fields,
            "safe_assumptions": request.safe_assumptions,
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=request.correlation_id,
        control_kind="clarification_request",
        goal_id=None,
        goal_revision=None,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        interaction_state=InteractionState.CLARIFYING,
        control_receipts=(*state.control_receipts, receipt),
    )


def accept_begin_answer(
    state: ConversationState,
    request: BeginAnswer,
) -> ConversationState:
    """持久化本 run 的只读问答选择，不授予 Goal 或 effect authority。"""

    _require_unused_correlation(state, request.correlation_id)
    if state.goal is not None:
        raise ValueError("begin_answer requires no Goal")
    if state.active_run is None:
        raise ValueError("begin_answer requires an active run")
    if state.interaction_state is InteractionState.ANSWERING:
        raise ValueError("begin_answer was already accepted for this run")
    if source_result_since_latest_user(state):
        raise ValueError("begin_answer must precede source retrieval")
    accepted_revision = state.revision + 1
    receipt = ControlReceipt.create(
        correlation_id=request.correlation_id,
        control_kind="begin_answer",
        goal_id=None,
        goal_revision=None,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest({"interaction_state": "answering"}),
    )
    return replace(
        state,
        revision=accepted_revision,
        interaction_state=InteractionState.ANSWERING,
        control_receipts=(*state.control_receipts, receipt),
    )


def accept_goal_proposal(
    state: ConversationState,
    proposal: GoalProposal,
    bootstrap: GoalBootstrap | None,
) -> ConversationState:
    """接受一次 GoalProposal:在同一个 revision 里原子安装 Goal 与其 receipt。

    校验与 create_goal 同源(_require_new_goal),防止两条安装路径漂移;
    active_run 保持不变,由同一 loop 在 CAS 后重建上下文。
    """
    _require_unused_correlation(state, proposal.correlation_id)
    if source_result_since_latest_user(state):
        raise ValueError("GoalProposal requires a fresh user action after source retrieval")
    goal = proposal.goal_frame
    if bootstrap is None:
        raise ValueError("model GoalProposal requires Runtime goal bootstrap")
    if goal.created_from_fact_ids != (bootstrap.source_fact_id,):
        raise ValueError("model GoalProposal source binding does not match Runtime bootstrap")
    if goal.workspace_identity_digest != bootstrap.workspace_identity_digest:
        raise ValueError("model GoalProposal workspace binding does not match Runtime bootstrap")
    if goal.authority_snapshot != bootstrap.authority_snapshot:
        raise ValueError("model GoalProposal authority does not match Runtime bootstrap")
    if goal.admitted_criteria:
        raise ValueError("model GoalProposal cannot mint admitted criteria")
    _require_new_goal(state, goal)
    accepted_revision = state.revision + 1
    receipt = ControlReceipt.create(
        correlation_id=proposal.correlation_id,
        control_kind="goal_proposal",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest(asdict(goal)),
    )
    return replace(
        state,
        revision=accepted_revision,
        goal=goal,
        control_receipts=(*state.control_receipts, receipt),
    )


def accept_goal_draft_proposal(
    state: ConversationState,
    proposal: GoalDraftProposal,
    bootstrap: GoalBootstrap | None,
    *,
    admitted_at: str,
) -> ConversationState:
    """由模型语义草案铸造完整 Goal；Runtime-owned 字段不经过模型 wire。"""

    if bootstrap is None:
        raise ValueError("model GoalDraftProposal requires Runtime goal bootstrap")
    source_text = _goal_source_text(state, bootstrap)
    public_web_requirement = _public_web_requirement(source_text)
    local_process_requirement = _local_process_requirement(source_text)
    # Web/process 义务会抬高 evidence 与 authority 下界；模型可以描述，
    # 但只有 authoritative user fact 可以创建。
    requires_public_web = public_web_requirement is True
    requires_local_process = local_process_requirement is True
    mismatched_artifacts = tuple(
        item.artifact_path
        for item in proposal.proposed_criteria
        if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.artifact_path is not None
        and item.artifact_path not in proposal.targets
    )
    if mismatched_artifacts:
        raise ValueError(
            "filesystem artifact criteria must match targets; use one deferred "
            "filesystem criterion when discovery is required, and represent requested "
            "test success with requires_local_process rather than an invented output file"
        )
    invented_process_artifacts = tuple(
        item.artifact_path
        for item in proposal.proposed_criteria
        if requires_local_process
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and _looks_like_invented_process_artifact(item, source_text=source_text)
    )
    if invented_process_artifacts:
        raise ValueError(
            "filesystem criterion looks like an invented process output that the user "
            "did not request; remove it and represent run/test/validation success only "
            "with requires_local_process=true"
        )
    goal_identity = canonical_json_digest(
        {
            "correlation_id": proposal.correlation_id,
            "source_fact_id": bootstrap.source_fact_id,
            "workspace_identity_digest": bootstrap.workspace_identity_digest,
            "authority_snapshot": bootstrap.authority_snapshot,
            "user_outcome": proposal.user_outcome,
            "targets": proposal.targets,
        }
    )
    if any(_uses_runtime_owned_obligation_id(item) for item in proposal.proposed_criteria):
        raise ValueError(
            "criterion:required-* identifiers are reserved for Runtime-owned obligations"
        )
    proposed_criteria = tuple(
        item
        for item in proposal.proposed_criteria
        if item.oracle_kind
        not in (
            EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            EvidenceOracleKind.TOOL_RECEIPT,
        )
    )
    if requires_public_web:
        proposed_criteria = (
            *(
                item
                for item in proposed_criteria
                if item.oracle_kind is not EvidenceOracleKind.WEB_SOURCE_RECEIPT
            ),
            ProposedCriterion(
                criterion_id=f"criterion:required-public-web:{goal_identity[:16]}",
                description="the requested public Web source was actually retrieved",
                oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            ),
        )
    if requires_local_process:
        proposed_criteria = (
            *(
                item
                for item in proposed_criteria
                if item.oracle_kind is not EvidenceOracleKind.TOOL_RECEIPT
            ),
            ProposedCriterion(
                criterion_id=f"criterion:required-local-process:{goal_identity[:16]}",
                description=(
                    "the explicitly requested local validation process exits successfully"
                ),
                oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
            ),
        )
    goal = GoalFrame(
        goal_id=f"goal-v1-{goal_identity[:24]}",
        revision=1,
        created_from_fact_ids=(bootstrap.source_fact_id,),
        workspace_identity_digest=bootstrap.workspace_identity_digest,
        user_outcome=proposal.user_outcome,
        beneficiary=proposal.beneficiary,
        targets=proposal.targets,
        scope=proposal.scope,
        non_goals=proposal.non_goals,
        assumptions=proposal.assumptions,
        proposed_criteria=proposed_criteria,
        admitted_criteria=(),
        authority_snapshot=bootstrap.authority_snapshot,
        status=GoalStatus.GOAL_READY,
        created_at=admitted_at,
        updated_at=admitted_at,
        progress_summary=None,
        next_step=proposal.next_step,
    )
    return accept_goal_proposal(
        state,
        GoalProposal(proposal.correlation_id, goal),
        bootstrap,
    )


def record_goal_progress(
    state: ConversationState,
    progress: GoalProgress,
) -> ConversationState:
    goal = state.goal
    if goal is None or goal.goal_id != progress.goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != progress.goal_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot accept progress")
    if goal.status is GoalStatus.PAUSED:
        # 进度会把 Goal 翻回 EXECUTING;暂停状态只能被显式 ResumeGoal 解除,
        # 不允许模型上报的 progress 静默恢复任务。
        raise ValueError("paused goal requires an explicit resume before progress")
    if any(receipt.correlation_id == progress.correlation_id for receipt in state.control_receipts):
        raise ValueError("control correlation_id was already accepted")
    accepted_revision = state.revision + 1
    payload_digest = canonical_json_digest(
        {
            "goal_id": progress.goal_id,
            "goal_revision": progress.goal_revision,
            "summary": progress.summary,
            "next_step": progress.next_step,
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=progress.correlation_id,
        control_kind="goal_progress",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        goal=replace(
            goal,
            status=GoalStatus.EXECUTING,
            progress_summary=progress.summary,
            next_step=progress.next_step,
        ),
        control_receipts=(*state.control_receipts, receipt),
    )


def apply_goal_delta(state: ConversationState, delta: GoalDelta) -> ConversationState:
    goal = state.goal
    if goal is None or goal.goal_id != delta.goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != delta.expected_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    updates = dict(delta.updates)
    tuple_fields = {
        "targets",
        "scope",
        "non_goals",
        "assumptions",
        "proposed_criteria",
        "admitted_criteria",
    }
    for field_name in tuple_fields & updates.keys():
        updates[field_name] = tuple(updates[field_name])
    semantic_source_changed = bool({"user_outcome", "scope"} & delta.updates.keys())
    if "proposed_criteria" in updates:
        updates["proposed_criteria"] = tuple(
            _decode_delta_proposed_criterion(item) for item in updates["proposed_criteria"]
        )
        if any(_uses_runtime_owned_obligation_id(item) for item in updates["proposed_criteria"]):
            raise ValueError(
                "criterion:required-* identifiers are reserved for Runtime-owned obligations"
            )
        # 模型可重写文件 criteria，但 Web/process 义务只能由 Runtime 从
        # authoritative user fact 补铸。旧的 Runtime lower-bound 会继续保留；
        # 模型既不能删除它，也不能借 correction 凭空增加同类 authority。
        updates["proposed_criteria"] = tuple(
            item
            for item in updates["proposed_criteria"]
            if item.oracle_kind
            not in (
                EvidenceOracleKind.WEB_SOURCE_RECEIPT,
                EvidenceOracleKind.TOOL_RECEIPT,
            )
        )
        updated_ids = {item.criterion_id for item in updates["proposed_criteria"]}
        admitted_web_ids = {
            item.criterion_id
            for item in goal.admitted_criteria
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        }
        carried = tuple(
            item
            for item in goal.proposed_criteria
            if (
                _is_runtime_owned_obligation(item)
                or (
                    not semantic_source_changed
                    and item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
                    and item.criterion_id in admitted_web_ids
                )
            )
            and item.criterion_id not in updated_ids
        )
        updates["proposed_criteria"] = (*updates["proposed_criteria"], *carried)
    authority_fields = {
        "user_outcome",
        "beneficiary",
        "targets",
        "scope",
        "authority_snapshot",
    }
    updates.update(
        revision=goal.revision + 1,
        updated_at=delta.updated_at or goal.updated_at,
        progress_summary=None,
        next_step=None,
        status=(
            GoalStatus.NEEDS_AUTHORITY
            if authority_fields & delta.updates.keys()
            else GoalStatus.GOAL_READY
        ),
    )
    updated_goal = replace(goal, **updates)
    # process receipt 只证明 correction 前那次具体执行，不能跨任何新意图复用。
    updated_goal = replace(
        updated_goal,
        admitted_criteria=tuple(
            item
            for item in updated_goal.admitted_criteria
            if item.oracle_kind is not EvidenceOracleKind.TOOL_RECEIPT
        ),
    )
    if semantic_source_changed:
        # Web receipt 可随纯 artifact-path 修正复用；outcome/scope 改变后来源
        # 必须重新满足新的语义边界。
        updated_goal = replace(
            updated_goal,
            admitted_criteria=tuple(
                item
                for item in updated_goal.admitted_criteria
                if item.oracle_kind is not EvidenceOracleKind.WEB_SOURCE_RECEIPT
            ),
        )
    if {"user_outcome", "targets", "proposed_criteria"} & delta.updates.keys():
        retained_web_ids = {
            item.criterion_id
            for item in updated_goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
        }
        updated_goal = replace(
            updated_goal,
            admitted_criteria=tuple(
                item
                for item in updated_goal.admitted_criteria
                if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
                and item.criterion_id in retained_web_ids
                and not semantic_source_changed
            ),
        )
    return replace(
        state,
        revision=state.revision + 1,
        goal=updated_goal,
        goal_authorizations=(),
        evidence_records=(),
        completion_claim=None,
        process_leases=(),
        sandbox_leases=(),
    )


def _decode_delta_proposed_criterion(value: object) -> ProposedCriterion:
    if not isinstance(value, Mapping) or set(value) != {
        "criterion_id",
        "description",
        "oracle_kind",
        "artifact_path",
    }:
        raise ValueError("goal delta proposed criterion has an invalid shape")
    criterion_id = value["criterion_id"]
    description = value["description"]
    oracle_kind = value["oracle_kind"]
    artifact_path = value["artifact_path"]
    if not isinstance(criterion_id, str) or not isinstance(description, str):
        raise ValueError("goal delta proposed criterion text fields must be strings")
    if not isinstance(oracle_kind, str):
        raise ValueError("goal delta proposed criterion oracle_kind must be a string")
    if not isinstance(artifact_path, str):
        raise ValueError("goal delta proposed criterion artifact_path must be a string")
    return ProposedCriterion(
        criterion_id=criterion_id,
        description=description,
        oracle_kind=EvidenceOracleKind(oracle_kind),
        artifact_path=artifact_path or None,
    )


def accept_goal_delta_proposal(
    state: ConversationState,
    proposal: GoalDeltaProposal,
) -> ConversationState:
    """受理 revision-bound delta；只有当前用户 correction 能授权其一次变更。"""

    _require_unused_correlation(state, proposal.correlation_id)
    if {"admitted_criteria", "authority_snapshot"} & proposal.delta.updates.keys():
        raise ValueError("model GoalDeltaProposal cannot mint admission or authority")
    current_goal = state.goal
    if current_goal is None:
        raise ValueError("goal delta requires a current goal")
    correction = _unconsumed_goal_correction(state, current_goal)
    if correction is None:
        # 区分"从未有 correction"与"已被此前的 delta 消费":后者说明 Goal 已被
        # 修正,模型应基于修正后的 Goal 继续,而不是反复重发 delta(016 J11 实测)。
        if any(
            fact.kind is FactKind.USER_MESSAGE and fact.content.get("control") == "goal_correction"
            for fact in state.facts
        ):
            raise ValueError(
                "the user correction has already been consumed by an earlier "
                "goal_delta_proposal; proceed with the corrected goal instead"
            )
        raise ValueError("goal delta requires one unconsumed user correction")
    updated = apply_goal_delta(state, proposal.delta)
    goal = updated.goal
    if goal is None:
        raise ValueError("goal delta did not retain a goal")
    goal = _apply_correction_lower_bounds(goal, correction)
    if "targets" in proposal.delta.updates:
        mismatched_artifacts = tuple(
            item.artifact_path
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.artifact_path is not None
            and item.artifact_path not in goal.targets
        )
        if mismatched_artifacts:
            raise ValueError(
                "filesystem artifact criteria must match corrected targets in one atomic delta"
            )
    goal = replace(
        goal,
        created_from_fact_ids=(*goal.created_from_fact_ids, correction.fact_id),
        status=(
            GoalStatus.GOAL_READY if goal.status is GoalStatus.NEEDS_AUTHORITY else goal.status
        ),
    )
    updated = replace(updated, goal=goal)
    receipt = ControlReceipt.create(
        correlation_id=proposal.correlation_id,
        control_kind="goal_delta_proposal",
        goal_id=goal.goal_id,
        goal_revision=proposal.delta.expected_revision,
        accepted_state_revision=updated.revision,
        payload_digest=canonical_json_digest(asdict(proposal.delta)),
    )
    return replace(updated, control_receipts=(*updated.control_receipts, receipt))


def acknowledge_noop_goal_delta(
    state: ConversationState,
    proposal: GoalDeltaProposal,
) -> ConversationState:
    """消费一次用户补充，但不为语义未变化的 Goal 制造新 revision。"""

    _require_unused_correlation(state, proposal.correlation_id)
    goal = state.goal
    if goal is None:
        raise ValueError("goal delta requires a current goal")
    if proposal.delta.goal_id != goal.goal_id or proposal.delta.expected_revision != goal.revision:
        raise GoalRevisionConflictError("goal identity or revision mismatch")
    correction = _unconsumed_goal_correction(state, goal)
    if correction is None:
        if any(
            fact.kind is FactKind.USER_MESSAGE and fact.content.get("control") == "goal_correction"
            for fact in state.facts
        ):
            raise ValueError(
                "the user correction has already been consumed by an earlier "
                "goal_delta_proposal; proceed with the corrected goal instead"
            )
        raise ValueError("goal delta requires one unconsumed user correction")
    accepted_revision = state.revision + 1
    receipt = ControlReceipt.create(
        correlation_id=proposal.correlation_id,
        control_kind="goal_delta_proposal",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest(asdict(proposal.delta)),
    )
    return replace(
        state,
        revision=accepted_revision,
        goal=replace(
            goal,
            created_from_fact_ids=(*goal.created_from_fact_ids, correction.fact_id),
        ),
        control_receipts=(*state.control_receipts, receipt),
    )


def accept_blocked_claim(
    state: ConversationState,
    claim: BlockedClaim,
) -> ConversationState:
    """把准确 blocker 落为 durable fact 后安全结束当前 run。"""

    goal = _require_goal_revision(
        state,
        goal_id=claim.goal_id,
        expected_revision=claim.goal_revision,
    )
    _require_unused_correlation(state, claim.correlation_id)
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over blocked claim")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot become blocked")
    active = state.active_run
    if active is None or active.phase is not ContinuationPhase.MODEL:
        raise ValueError("blocked claim requires an active model phase")
    accepted_revision = state.revision + 1
    fact = ConversationFact(
        fact_id=f"control:{claim.correlation_id}:blocked",
        kind=FactKind.POLICY_RESULT,
        content={
            "code": "blocked_claim",
            "blocker": claim.blocker,
            "safe_attempts": list(claim.safe_attempts),
            "resume_condition": claim.resume_condition,
        },
    )
    receipt = ControlReceipt.create(
        correlation_id=claim.correlation_id,
        control_kind="blocked_claim",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=canonical_json_digest(
            {
                "goal_id": claim.goal_id,
                "goal_revision": claim.goal_revision,
                "blocker": claim.blocker,
                "safe_attempts": claim.safe_attempts,
                "resume_condition": claim.resume_condition,
            }
        ),
    )
    return replace(
        state,
        revision=accepted_revision,
        facts=(*state.facts, fact),
        goal=replace(
            goal,
            status=GoalStatus.BLOCKED,
            next_step=claim.resume_condition,
        ),
        active_run=None,
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id=active.run_id,
            message=claim.blocker,
        ),
        control_receipts=(*state.control_receipts, receipt),
    )


def _require_goal_revision(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> GoalFrame:
    goal = state.goal
    if goal is None or goal.goal_id != goal_id:
        raise GoalRevisionConflictError("goal identity mismatch")
    if goal.revision != expected_revision:
        raise GoalRevisionConflictError("goal revision mismatch")
    return goal


def _has_unknown_effect(state: ConversationState) -> bool:
    active = state.active_run
    return active is not None and (
        active.phase is ContinuationPhase.EXECUTING
        or active.status is ActiveRunStatus.AWAITING_RECOVERY
    )


def _stop_safe_active_run(
    state: ConversationState,
    *,
    status: RunStatus,
    message: str,
) -> tuple[None, RecordedRunResult | None]:
    active = state.active_run
    if active is None:
        return None, state.last_safe_result
    return None, RecordedRunResult(status=status, run_id=active.run_id, message=message)


def _superseded_tool_result_fact(
    *,
    fact_id: str,
    call_id: str,
    text: str,
    invocation_origin: str | None,
) -> ConversationFact:
    return ConversationFact(
        fact_id=fact_id,
        kind=FactKind.TOOL_RESULT,
        content={
            "tool_call_id": call_id,
            "text": text,
            "is_error": True,
            "executed": False,
            "superseded": True,
            **(
                {"invocation_origin": invocation_origin}
                if invocation_origin == InvocationOrigin.OPERATOR.value
                else {}
            ),
        },
    )


def _unstarted_batch_suffix_facts(
    state: ConversationState,
    *,
    text: str,
    already_accounted: int = 0,
) -> tuple[ConversationFact, ...]:
    """为「确定尚未开始」的当前 batch suffix 生成 durable 非执行结果。

    R1：只有转换仍持有当时 active run 的 phase/cursor 时，非执行才可证明——
    TOOL 相（含 AWAITING_APPROVAL）的 cursor 指向尚未 prepare/执行的首个
    call；calls[cursor:] 全部未开始。EXECUTING 相可能已发生效果，由
    unknown-effect 守卫排除在丢 run 入口之外，绝不在此闭合。调用方负责把
    结果与清空/替换 run 落在同一 CAS，并保持结果位于该批次已有结果之后、
    后续 user/assistant fact 之前。``already_accounted`` 用于拒绝审批等
    「cursor call 已有本次转换专属结果」的入口。
    """

    active = state.active_run
    if active is None or active.phase is not ContinuationPhase.TOOL:
        return ()
    missing = active.tool_calls[active.batch_cursor + already_accounted :]
    if not missing:
        return ()
    reserved = {fact.fact_id for fact in state.facts}
    origin = active.invocation_origin.value
    closed: list[ConversationFact] = []
    for call in missing:
        fact_id = f"run:{active.run_id}:superseded-tool:{call.tool_call_id}"
        if fact_id in reserved:
            fact_id = f"{fact_id}:{state.revision}"
        reserved.add(fact_id)
        closed.append(
            _superseded_tool_result_fact(
                fact_id=fact_id,
                call_id=call.tool_call_id,
                text=text,
                invocation_origin=origin,
            )
        )
    return tuple(closed)


def pause_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal pause")
    if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
        raise ValueError("terminal goal cannot be paused")
    if goal.status is GoalStatus.PAUSED:
        raise ValueError("goal is already paused")
    closed_suffix = _unstarted_batch_suffix_facts(
        state,
        text=("Tool call was not executed because the Goal was paused before this call started."),
    )
    active_run, result = _stop_safe_active_run(
        state,
        status=RunStatus.COMPLETED,
        message="goal paused at a safe boundary",
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, *closed_suffix),
        goal=replace(goal, status=GoalStatus.PAUSED),
        active_run=active_run,
        last_safe_result=result,
        goal_authorizations=(),
        process_leases=(),
        sandbox_leases=(),
        browser_leases=(),
        browser_takeover_pending=None,
    )


def resume_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if goal.status not in {GoalStatus.PAUSED, GoalStatus.BLOCKED}:
        raise ValueError("only a paused or blocked goal can resume")
    if state.active_run is not None:
        raise ValueError("paused goal cannot resume over an active run")
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.GOAL_READY),
    )


def cancel_goal(
    state: ConversationState,
    *,
    goal_id: str,
    expected_revision: int,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=goal_id,
        expected_revision=expected_revision,
    )
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal cancellation")
    if goal.status is GoalStatus.VERIFIED_DONE:
        raise ValueError("verified goal cannot be cancelled")
    if goal.status is GoalStatus.CANCELLED:
        raise ValueError("goal is already cancelled")
    closed_suffix = _unstarted_batch_suffix_facts(
        state,
        text=(
            "Tool call was not executed because the Goal was cancelled before this call started."
        ),
    )
    active_run, result = _stop_safe_active_run(
        state,
        status=RunStatus.CANCELLED,
        message="goal cancelled at a safe boundary",
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, *closed_suffix),
        goal=replace(goal, status=GoalStatus.CANCELLED, next_step=None),
        completion_claim=None,
        active_run=active_run,
        last_safe_result=result,
        goal_authorizations=(),
        process_leases=(),
        sandbox_leases=(),
        browser_leases=(),
    )


def apply_control_request(
    state: ConversationState,
    request: ControlInboxRequest,
) -> ConversationState:
    """在 Runtime 的安全轮询点把 process-local 请求变成 durable state。"""

    goal = _require_goal_revision(
        state,
        goal_id=request.goal_id,
        expected_revision=request.goal_revision,
    )
    active = state.active_run
    if (
        request.conversation_id != state.conversation_id
        or active is None
        or active.owner_invocation_id != request.invocation_id
    ):
        raise ValueError("control request does not bind the active invocation")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal control")
    if any(receipt.correlation_id == request.request_id for receipt in state.control_receipts):
        raise ValueError("control request was already accepted")

    if request.kind is ControlRequestKind.PAUSE:
        updated = pause_goal(
            state,
            goal_id=request.goal_id,
            expected_revision=request.goal_revision,
        )
    elif request.kind is ControlRequestKind.CANCEL:
        updated = cancel_goal(
            state,
            goal_id=request.goal_id,
            expected_revision=request.goal_revision,
        )
    else:
        if request.message is None:
            raise ValueError("goal correction message is required")
        correction = ConversationFact(
            fact_id=f"control:{request.request_id}:user",
            kind=FactKind.USER_MESSAGE,
            content={"text": request.message, "control": "goal_correction"},
        )
        # R1：纠正丢弃 run 前，cursor 之后确定未开始的 suffix 与清空落在同一 CAS。
        closed_suffix = _unstarted_batch_suffix_facts(
            state,
            text=(
                "Tool call was not executed because the Goal was corrected before "
                "this call started."
            ),
        )
        updated = replace(
            state,
            revision=state.revision + 1,
            facts=(*state.facts, *closed_suffix, correction),
            goal=replace(
                goal,
                revision=goal.revision + 1,
                status=GoalStatus.NEEDS_AUTHORITY,
                progress_summary=None,
                next_step="Review and admit the user's correction before another effect.",
            ),
            goal_authorizations=(),
            evidence_records=(),
            completion_claim=None,
            interaction_state=InteractionState.CLARIFYING,
            active_run=None,
            # S3-C（DU-24，2026-10-09）：correct 会 bump Goal revision；既有
            # one-shot 租约绑定旧 revision，状态不变量（leases 必须绑定当前
            # revision）会在下一次 checkpoint 校验时 fail closed。与 cancel 的
            # 清理语义对齐：旧租约随纠正作废，新效果需重新批准/租约。
            process_leases=(),
            sandbox_leases=(),
            browser_leases=(),
            last_safe_result=RecordedRunResult(
                status=RunStatus.COMPLETED,
                run_id=active.run_id,
                message="goal correction recorded at a safe boundary",
            ),
        )

    receipt = ControlReceipt.create(
        correlation_id=request.request_id,
        control_kind=f"goal_{request.kind.value}",
        goal_id=request.goal_id,
        goal_revision=request.goal_revision,
        accepted_state_revision=updated.revision,
        payload_digest=request.payload_digest,
    )
    return replace(updated, control_receipts=(*updated.control_receipts, receipt))


def pause_for_provider_disclosure(
    state: ConversationState,
    request: ProviderDisclosureRequest | ProviderDisclosureRequestV2,
) -> ConversationState:
    active = state.active_run
    if active is None or active.phase is not ContinuationPhase.MODEL:
        raise ValueError("provider disclosure must pause before a model send")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over disclosure")
    goal = state.goal
    if goal is not None and goal.status not in {
        GoalStatus.CANCELLED,
        GoalStatus.VERIFIED_DONE,
    }:
        goal = replace(goal, status=GoalStatus.NEEDS_AUTHORITY)
    return replace(
        state,
        revision=state.revision + 1,
        goal=goal,
        provider_disclosure_request=request,
        provider_disclosure_receipt=None,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_DISCLOSURE,
            owner_invocation_id=None,
        ),
    )


def acknowledge_provider_disclosure(
    state: ConversationState,
    action: AcknowledgeProviderDisclosure,
    *,
    now: str | None = None,
) -> ConversationState:
    request = state.provider_disclosure_request
    active = state.active_run
    if request is None or request.request_digest != action.request_digest:
        raise ValueError("provider disclosure acknowledgement does not match")
    acknowledged_at = (
        now
        if isinstance(request, ProviderDisclosureRequestV2) and now is not None
        else action.acknowledged_at
    )
    goal = state.goal
    if active is None:
        # /pause 允许落在 pending disclosure 上（2026-10-17 E1-B 真实旅程实测）：
        # active run 已安全停止，但披露决定仍 durable。/resume 之后 ack 必须点燃
        # 继续回合——与 SubmitMessage 的点火同型，否则挂起回合被静默丢弃成 idle。
        if (
            state.provider_disclosure_receipt is not None
            or goal is None
            or goal.status is not GoalStatus.GOAL_READY
        ):
            raise ValueError("provider disclosure acknowledgement does not match")
        return replace(
            state,
            provider_disclosure_receipt=request.acknowledge(
                receipt_id=f"disclosure-receipt:{action.action_seq}",
                acknowledged_action_seq=action.action_seq,
                acknowledged_at=acknowledged_at,
            ),
            active_run=ActiveRun(run_id=f"resume-{action.action_seq}"),
        )
    if active.status is not ActiveRunStatus.AWAITING_DISCLOSURE:
        raise ValueError("provider disclosure acknowledgement does not match")
    if goal is not None and goal.status is GoalStatus.NEEDS_AUTHORITY:
        goal = replace(goal, status=GoalStatus.GOAL_READY)
    return replace(
        state,
        goal=goal,
        provider_disclosure_receipt=request.acknowledge(
            receipt_id=f"disclosure-receipt:{action.action_seq}",
            acknowledged_action_seq=action.action_seq,
            acknowledged_at=acknowledged_at,
        ),
        active_run=replace(active, status=ActiveRunStatus.RUNNABLE),
    )


def grant_provider_consent(
    state: ConversationState,
    action: GrantProviderConsent,
    *,
    now: str,
) -> ConversationState:
    """把当前已显示的同一条 v2 request 铸造成有限常规许可。"""

    request = state.provider_disclosure_request
    active = state.active_run
    if (
        not isinstance(request, ProviderDisclosureRequestV2)
        or request.request_digest != action.request_digest
        or request.scope_digest != action.scope_digest
        or not request.grant_eligible
        or state.provider_disclosure_receipt is not None
    ):
        raise ValueError("provider consent grant does not match the pending request")
    goal = state.goal
    if active is None:
        if goal is None or goal.status is not GoalStatus.GOAL_READY:
            raise ValueError("provider consent grant does not match the pending request")
        active_run = ActiveRun(run_id=f"resume-{action.action_seq}")
    elif active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
        if goal is not None and goal.status is GoalStatus.NEEDS_AUTHORITY:
            goal = replace(goal, status=GoalStatus.GOAL_READY)
        active_run = replace(active, status=ActiveRunStatus.RUNNABLE)
    else:
        raise ValueError("provider consent grant does not match the pending request")
    grant = mint_provider_consent_grant(
        state=state,
        request=request,
        action_seq=action.action_seq,
        now=now,
    )
    return replace(
        state,
        goal=goal,
        active_run=active_run,
        provider_consent_grant=grant,
        provider_disclosure_request=None,
        provider_disclosure_receipt=None,
    )


def revoke_provider_consent(
    state: ConversationState,
    action: RevokeProviderConsent,
) -> ConversationState:
    del action
    grant = state.provider_consent_grant
    if grant is None:
        raise ValueError("provider consent grant is missing")
    active = state.active_run
    if active is not None and active.status is ActiveRunStatus.AWAITING_DISCLOSURE:
        active = replace(active, status=ActiveRunStatus.RUNNABLE)
    return replace(
        state,
        provider_consent_grant=grant.with_status(
            ProviderConsentGrantStatus.REVOKED
        ),
        provider_disclosure_request=None,
        provider_disclosure_receipt=None,
        active_run=active,
    )


def record_completion_claim(
    state: ConversationState,
    claim: CompletionClaim,
) -> ConversationState:
    goal = _require_goal_revision(
        state,
        goal_id=claim.goal_id,
        expected_revision=claim.goal_revision,
    )
    if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
        raise ValueError("completion claim requires an executable goal")
    if any(receipt.correlation_id == claim.correlation_id for receipt in state.control_receipts):
        raise ValueError("control correlation_id was already accepted")
    evidence_ids = {record.evidence_id for record in state.evidence_records}
    if not set(claim.criterion_evidence_refs).issubset(evidence_ids):
        raise ValueError("completion claim references unknown evidence")
    accepted_revision = state.revision + 1
    # receipt payload 身份绑定全部语义相关字段：R2 的 requirement_coverage 改写
    # （相同其他字段、不同 coverage）不得复用同一 digest。历史 receipt 不重算。
    payload_digest = canonical_json_digest(
        {
            "goal_id": claim.goal_id,
            "goal_revision": claim.goal_revision,
            "criterion_evidence_refs": claim.criterion_evidence_refs,
            "requirement_coverage": [
                {
                    "requirement_id": item.requirement_id,
                    "requirement": item.requirement,
                    "source_fact_ids": item.source_fact_ids,
                    "status": item.status,
                    "criterion_ids": item.criterion_ids,
                }
                for item in claim.requirement_coverage
            ],
        }
    )
    receipt = ControlReceipt.create(
        correlation_id=claim.correlation_id,
        control_kind="completion_claim",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        accepted_state_revision=accepted_revision,
        payload_digest=payload_digest,
    )
    return replace(
        state,
        revision=accepted_revision,
        completion_claim=claim,
        control_receipts=(*state.control_receipts, receipt),
    )


def record_evidence(
    state: ConversationState,
    records: tuple[EvidenceRecord, ...],
) -> ConversationState:
    goal = state.goal
    if goal is None or not records:
        raise ValueError("evidence requires a current goal and at least one record")
    criteria = {criterion.criterion_id: criterion for criterion in goal.admitted_criteria}
    for record in records:
        criterion = criteria.get(record.criterion_id)
        if (
            record.goal_id != goal.goal_id
            or record.goal_revision != goal.revision
            or criterion is None
            or record.oracle_kind is not criterion.oracle_kind
            or record.predicate_digest != canonical_json_digest(criterion.predicate)
        ):
            raise ValueError("evidence does not bind the current admitted criterion")
    # R2-C：同 id 记录按位刷新（derive 对 append-only facts 的当前重导出），
    # 绑定校验不放宽；新记录按提交顺序追加。被后续写入失效的旧证据由此获得
    # 可修复的刷新路径，而不是把 Goal 永久卡在陈旧缓存上。
    merged = {record.evidence_id: record for record in state.evidence_records}
    known_order = [record.evidence_id for record in state.evidence_records]
    for record in records:
        if record.evidence_id not in merged:
            known_order.append(record.evidence_id)
        merged[record.evidence_id] = record
    refreshed = tuple(merged[evidence_id] for evidence_id in known_order)
    if refreshed == state.evidence_records:
        return state
    return replace(
        state,
        revision=state.revision + 1,
        evidence_records=refreshed,
    )


def _require_requirement_coverage(
    state: ConversationState,
    claim: CompletionClaim,
    *,
    goal: GoalFrame,
    mandatory: tuple[AdmittedCriterion, ...],
) -> None:
    """R2 完成门：物理证据齐全是必要条件，不是完整业务完成的充分条件。

    最终结束必须经过针对当前 Goal revision 与当前权威用户输入/最新 correction
    的逐项覆盖复核（模型提供语义映射，Runtime 校验结构与版本/来源/证据绑定）。
    缺失时拒绝并给出可修复的下一步；不铸造 evidence/permission，不引入第二
    模型裁判。引用整条 fact、空列表或首个文件 digest 的组合不能充当逐项复核。
    """

    coverage = claim.requirement_coverage
    if not coverage:
        raise ValueError(
            "completion claim must include per-requirement coverage of the current "
            "authoritative user input and corrections before the goal can be verified"
        )
    source_ids = set(goal.created_from_fact_ids)
    authoritative_ids = {
        fact.fact_id
        for fact in state.facts
        if fact.fact_id in source_ids and fact.kind is FactKind.USER_MESSAGE
    }
    cited: set[str] = set()
    for item in coverage:
        cited.update(item.source_fact_ids)
        if any(fact_id not in source_ids for fact_id in item.source_fact_ids):
            raise ValueError(
                "requirement coverage must cite the authoritative source facts of the current goal"
            )
    uncited = authoritative_ids - cited
    if uncited:
        raise ValueError(
            "requirement coverage does not cite every authoritative user input or "
            f"correction: {sorted(uncited)}"
        )
    mandatory_ids = {criterion.criterion_id for criterion in mandatory}
    pending = tuple(item for item in coverage if item.status == "pending")
    if pending:
        raise ValueError(
            "completion claim lists pending requirements that are not yet satisfied: "
            + ", ".join(item.requirement_id for item in pending)
        )
    for item in coverage:
        unknown = set(item.criterion_ids) - mandatory_ids
        if unknown:
            raise ValueError(
                "requirement coverage binds criterion ids that are not current "
                f"admitted mandatory criteria: {sorted(unknown)}"
            )
    covered = {criterion_id for item in coverage for criterion_id in item.criterion_ids}
    uncovered = mandatory_ids - covered
    if uncovered:
        raise ValueError(
            f"requirement coverage does not bind every mandatory criterion: {sorted(uncovered)}"
        )


def verify_goal_completion(state: ConversationState) -> ConversationState:
    goal = state.goal
    claim = state.completion_claim
    if goal is None or claim is None:
        raise ValueError("completion verification requires a current claim")
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over goal verification")
    if goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
        raise ValueError("goal status is not eligible for completion verification")
    if claim.goal_id != goal.goal_id or claim.goal_revision != goal.revision:
        raise GoalRevisionConflictError("completion claim is stale")
    if state.browser_takeover_pending is not None:
        raise ValueError("browser takeover must be resolved before goal verification")
    active_task_resources(state.facts).require_closed()
    referenced = {
        record.evidence_id: record
        for record in state.evidence_records
        if record.evidence_id in claim.criterion_evidence_refs
    }
    mandatory = tuple(criterion for criterion in goal.admitted_criteria if criterion.mandatory)
    if not mandatory:
        raise ValueError("goal has no mandatory criterion")
    if any(criterion.oracle_kind is None for criterion in goal.proposed_criteria):
        raise ValueError("every proposed completion criterion requires a typed evidence oracle")
    artifact_requirements = tuple(
        criterion
        for criterion in goal.proposed_criteria
        if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
    )
    for requirement in artifact_requirements:
        if not any(
            criterion.criterion_id == requirement.criterion_id
            and criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and criterion.predicate.get("path") == requirement.artifact_path
            for criterion in mandatory
        ):
            raise ValueError("artifact criterion must be admitted before completion verification")
    process_requirements = tuple(
        criterion
        for criterion in goal.proposed_criteria
        if criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
    )
    for requirement in process_requirements:
        if not any(
            criterion.criterion_id == requirement.criterion_id
            and criterion.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            for criterion in mandatory
        ):
            raise ValueError("process criterion must be admitted before completion verification")
    _require_requirement_coverage(state, claim, goal=goal, mandatory=mandatory)
    # W1：权威原文的明确文件交付对象是完成下界；模型缩小后的 admitted 集
    # 合（或一条泛化 coverage）不能替代被草稿遗漏的交付对象。
    deliverable_paths = authoritative_deliverable_file_paths(state)
    if deliverable_paths:
        admitted_paths = {
            criterion.predicate.get("path")
            for criterion in mandatory
            if criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and isinstance(criterion.predicate.get("path"), str)
        }
        missing = sorted(deliverable_paths - admitted_paths)
        if missing:
            raise ValueError(
                "explicit user deliverable files are not covered by current "
                "admitted criteria: " + ", ".join(missing)
            )
    evidence_by_criterion = {record.criterion_id: record for record in referenced.values()}
    if any(
        criterion.criterion_id not in evidence_by_criterion
        or not evidence_by_criterion[criterion.criterion_id].passed
        or evidence_by_criterion[criterion.criterion_id].goal_id != goal.goal_id
        or evidence_by_criterion[criterion.criterion_id].goal_revision != goal.revision
        or evidence_by_criterion[criterion.criterion_id].oracle_kind is not criterion.oracle_kind
        or evidence_by_criterion[criterion.criterion_id].predicate_digest
        != canonical_json_digest(criterion.predicate)
        for criterion in mandatory
    ):
        raise ValueError("current evidence does not prove every mandatory criterion")
    return replace(
        state,
        revision=state.revision + 1,
        goal=replace(goal, status=GoalStatus.VERIFIED_DONE, next_step=None),
        goal_authorizations=(),
        process_leases=(),
        sandbox_leases=(),
        browser_leases=(),
        browser_takeover_pending=None,
    )


def _conflict(state: ConversationState, reason: str) -> ActionTransition:
    return ActionTransition(ActionDisposition.CONFLICT, state, reason=reason)


def _find_replay(state: ConversationState, action_seq: int):
    return next(
        (record for record in state.replay_records if record.action_seq == action_seq),
        None,
    )


def _append_replay_record(
    state: ConversationState,
    *,
    action_seq: int,
    action_digest: str,
    max_replay_records: int,
) -> ConversationState | None:
    if max_replay_records < 1:
        raise ValueError("max_replay_records must be positive")

    records = list(state.replay_records)
    replay_floor = state.replay_floor
    while len(records) >= max_replay_records:
        # replay_floor 表示连续窗口；不能越过更早的 unfinished action 去删后项。
        if not records or records[0].result is None:
            return None
        evicted = records.pop(0)
        replay_floor = max(replay_floor, evicted.action_seq + 1)
    records.append(ReplayRecord(action_seq=action_seq, action_digest=action_digest))
    # replay record 与 next_action_seq 是同一个接受动作的原子不变量，不能构造半状态。
    return replace(
        state,
        next_action_seq=state.next_action_seq + 1,
        replay_floor=replay_floor,
        replay_records=tuple(records),
    )


def _goal_target_authorization_scope(
    state: ConversationState,
    pending: ApprovalRequest,
    active: ActiveRun,
    *,
    directory: bool,
) -> str | None:
    goal = state.goal
    call = active.tool_calls[active.batch_cursor]
    target = call.arguments.get("path")
    if not (
        goal is not None
        and pending.tool_name in {"write_file", "edit_file"}
        and call.name == pending.tool_name
        and pending.side_effect == SideEffectClass.WRITE.value
        and pending.egress in {None, EgressClass.NONE.value}
        and isinstance(target, str)
    ):
        return None
    if not directory:
        if target in goal.targets and safe_goal_authorization_target(target):
            return target
        # W2：散文 targets 下，当前 Goal 已由 Runtime 准入（真实用户批准来源，
        # `_admit_approved_file_criterion` 铸造）的精确文件同样可作为复用授权
        # 候选。只认 durable admitted criterion 的闭合 predicate path，不把
        # 任意 pending path 或模型自述提升为候选；显示/解析/铸造共用本判断。
        if safe_goal_authorization_target(target) and any(
            criterion.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and criterion.predicate.get("path") == target
            for criterion in goal.admitted_criteria
        ):
            return target
        return None
    target_parts = target.split("/")
    candidates = []
    for goal_target in goal.targets:
        goal_parts = goal_target.split("/")
        if (
            len(target_parts) > len(goal_parts)
            and safe_goal_authorization_target(target)
            and safe_goal_authorization_target(goal_target)
            and all(part not in {"", ".", ".."} for part in (*target_parts, *goal_parts))
            and target_parts[: len(goal_parts)] == goal_parts
        ):
            candidates.append(goal_target)
    return max(candidates, key=lambda item: len(item.split("/")), default=None)


def _action_is_legal(state: ConversationState, action: Action) -> tuple[bool, str | None]:
    active = state.active_run
    if isinstance(action, AcknowledgeProviderDisclosure):
        request = state.provider_disclosure_request
        goal = state.goal
        live_match = (
            request is not None
            and request.request_digest == action.request_digest
            and active is not None
            and active.status is ActiveRunStatus.AWAITING_DISCLOSURE
        )
        # 暂停后孤儿披露：run 已停但决定仍 durable；/resume 后必须可应答并点火。
        resumable_orphan = (
            request is not None
            and request.request_digest == action.request_digest
            and state.provider_disclosure_receipt is None
            and active is None
            and goal is not None
            and goal.status is GoalStatus.GOAL_READY
        )
        if not (live_match or resumable_orphan):
            return False, "provider_disclosure_mismatch"
        return True, None
    if isinstance(action, ConfirmCriterion):
        goal = state.goal
        if (
            goal is None
            or goal.goal_id != action.goal_id
            or goal.revision != action.goal_revision
            or active is not None
        ):
            return False, "goal_revision_mismatch"
        criterion = next(
            (item for item in goal.admitted_criteria if item.criterion_id == action.criterion_id),
            None,
        )
        if (
            criterion is None
            or criterion.oracle_kind is not EvidenceOracleKind.USER_CONFIRMATION
            or criterion.admission_digest != action.admission_binding_digest
        ):
            return False, "criterion_confirmation_mismatch"
        return True, None
    if isinstance(action, SubmitMessage):
        if active is not None and active.status is not ActiveRunStatus.AWAITING_APPROVAL:
            return False, "illegal_action_for_state"
        if not action.message.strip() or not action.run_id:
            return False, "invalid_submit_message"
        return True, None

    if isinstance(action, (PauseGoal, ResumeGoal, CancelGoal)):
        goal = state.goal
        if goal is None or goal.goal_id != action.goal_id:
            return False, "goal_identity_mismatch"
        if goal.revision != action.goal_revision:
            return False, "goal_revision_mismatch"
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if isinstance(action, PauseGoal):
            if goal.status in {
                GoalStatus.PAUSED,
                GoalStatus.VERIFIED_DONE,
                GoalStatus.CANCELLED,
            }:
                return False, "illegal_action_for_state"
            return True, None
        if isinstance(action, ResumeGoal):
            if goal.status not in {GoalStatus.PAUSED, GoalStatus.BLOCKED} or active is not None:
                return False, "illegal_action_for_state"
            return True, None
        if goal.status in {GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}:
            return False, "illegal_action_for_state"
        return True, None

    if isinstance(action, (CompleteBrowserTakeover, CancelBrowserTakeover)):
        # 018：takeover controls 是独立 user-only authority action；pending
        # 必须存在且 identity exact 匹配，否则 fail closed。
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        pending_takeover = state.browser_takeover_pending
        if pending_takeover is None:
            return False, "illegal_action_for_state"
        if action.request_id != pending_takeover.request_id:
            return False, "browser_takeover_mismatch"
        if isinstance(action, CompleteBrowserTakeover) and (
            action.session_ref != pending_takeover.session_ref
            or action.expected_profile_revision != pending_takeover.profile_revision
        ):
            return False, "browser_takeover_mismatch"
        return True, None

    if isinstance(action, GrantProviderConsent):
        request = state.provider_disclosure_request
        goal = state.goal
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if (
            not isinstance(request, ProviderDisclosureRequestV2)
            or request.request_digest != action.request_digest
            or request.scope_digest != action.scope_digest
            or not request.grant_eligible
            or state.provider_disclosure_receipt is not None
        ):
            return False, "provider_consent_mismatch"
        live_match = (
            active is not None
            and active.status is ActiveRunStatus.AWAITING_DISCLOSURE
        )
        resumable_orphan = (
            active is None
            and goal is not None
            and goal.status is GoalStatus.GOAL_READY
        )
        if not (live_match or resumable_orphan):
            return False, "provider_consent_mismatch"
        return True, None

    if isinstance(action, RevokeProviderConsent):
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if state.provider_consent_grant is None:
            return False, "provider_consent_missing"
        return True, None

    if isinstance(action, (RevokeProcessAuthority, RevokeGoalTargetAuthority)):
        # revoke 是独立 authority action；expected_revision CAS 由 accept_action 通用处理。
        # unknown-effect recovery 优先，revoke 不假装取消已可能的 in-flight effect。
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if isinstance(action, RevokeGoalTargetAuthority) and not state.goal_authorizations:
            return False, "goal_target_authorization_missing"
        return True, None

    if isinstance(action, AbandonUnknownModelOutcome):
        binding = state.background_occurrence_binding
        intent = active.provider_call_intent if active is not None else None
        if (
            binding is None
            or active is None
            or active.status is not ActiveRunStatus.MODEL_OUTCOME_UNKNOWN
            or intent is None
            or action.occurrence_id != binding.occurrence_id
            or action.background_binding_digest != binding.binding_digest
            or action.provider_call_intent_digest != intent.intent_digest
        ):
            return False, "model_outcome_abandonment_mismatch"
        return True, None

    if isinstance(action, ExecuteOperatorTool):
        goal = state.goal
        if _has_unknown_effect(state):
            return False, "unknown_effect_recovery_required"
        if goal is None or goal.status not in {GoalStatus.GOAL_READY, GoalStatus.EXECUTING}:
            return False, "operator_tool_requires_active_goal"
        if active is None:
            return False, "operator_tool_requires_active_run"
        if (
            active.status is not ActiveRunStatus.RUNNABLE
            or active.phase is not ContinuationPhase.MODEL
            or active.owner_invocation_id is not None
            or active.invocation_origin is not InvocationOrigin.MODEL
        ):
            return False, "operator_tool_requires_idle_run"
        return True, None

    if active is None:
        return False, "illegal_action_for_state"

    if isinstance(action, ResolveApproval):
        pending = active.pending_request
        if active.status is not ActiveRunStatus.AWAITING_APPROVAL or not isinstance(
            pending, ApprovalRequest
        ):
            return False, "illegal_action_for_state"
        if (
            action.request_id != pending.request_id
            or action.binding_digest != pending.binding_digest
        ):
            return False, "pending_request_mismatch"
        if (
            action.authorize_goal_target
            and _goal_target_authorization_scope(state, pending, active, directory=False) is None
        ):
            return False, "goal_target_authorization_mismatch"
        if (
            action.authorize_goal_directory
            and _goal_target_authorization_scope(state, pending, active, directory=True) is None
        ):
            return False, "goal_directory_authorization_mismatch"
        return True, None

    if isinstance(action, ResolveUnknownToolOutcome):
        pending = active.pending_request
        if active.status is not ActiveRunStatus.AWAITING_RECOVERY or not isinstance(
            pending, RecoveryRequest
        ):
            return False, "illegal_action_for_state"
        if (
            action.request_id != pending.request_id
            or action.binding_digest != pending.binding_digest
        ):
            return False, "pending_request_mismatch"
        if (
            active.executing_intent is not None
            and active.executing_intent.egress is EgressClass.PUBLIC_NETWORK
        ):
            return False, "typed_observation_recovery_required"
        return True, None

    if isinstance(action, RecoverUnknownObservation):
        intent = active.executing_intent
        if (
            intent is None
            or active.phase is not ContinuationPhase.EXECUTING
            or intent.egress is not EgressClass.PUBLIC_NETWORK
            or action.tool_call_id != intent.tool_call_id
            or action.intent_digest != intent.intent_digest
        ):
            return False, "observation_recovery_mismatch"
        return True, None

    if isinstance(action, Resume):
        if active.status in {
            ActiveRunStatus.RUNNABLE,
            ActiveRunStatus.AWAITING_APPROVAL,
            ActiveRunStatus.PAUSED_LIMIT,
            ActiveRunStatus.PAUSED_RETRYABLE,
        }:
            return True, None
        return False, "illegal_action_for_state"

    if isinstance(action, CancelRun):
        if active.status is ActiveRunStatus.AWAITING_RECOVERY:
            # 未知 effect 必须由人类 exact 分类，不能被取消绕过。
            return False, "illegal_action_for_state"
        if (
            active.status is ActiveRunStatus.RUNNABLE
            and active.phase is ContinuationPhase.EXECUTING
        ):
            # EXECUTING 的 effect 可能已发生；只能 Resume 进入 unknown-outcome recovery。
            return False, "illegal_action_for_state"
        if active.status in {
            ActiveRunStatus.RUNNABLE,
            ActiveRunStatus.AWAITING_APPROVAL,
            ActiveRunStatus.PAUSED_LIMIT,
            ActiveRunStatus.PAUSED_RETRYABLE,
        }:
            return True, None
        return False, "illegal_action_for_state"
    return False, "illegal_action_for_state"


def _add_minutes_rfc3339(timestamp: str, minutes: int) -> str:
    """对 RFC 3339（含 ``Z``）时间戳加分钟，返回同为 ``Z`` 后缀的 RFC 3339。"""

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _require_zoned_rfc3339(timestamp: str) -> str:
    """F6（review finding）：批准时刻必须是带时区 RFC3339——naive/malformed fail closed。"""

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("approved_at must be a zoned RFC3339 timestamp")
    return timestamp


def _mint_process_authority_lease(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    approved_at: str | None = None,
) -> ConversationState:
    """ResolveApproval(approved=True) 对 process candidate 铸造 durable lease（KTD3/KTD4）。

    lease 时效锚定**批准**时刻。process approval 必须携带带时区的 RFC3339
    ``approved_at``；缺失、malformed 或 naive 时间一律 fail closed，不能退回 candidate
    创建时刻并静默缩短租期。非 process approval（无 candidate）不铸造。lease use 在
    durable EXECUTING checkpoint 时单调消费（U6/U7）。
    """

    candidate = pending.process_authority_candidate
    if candidate is None:
        return state
    if approved_at is None:
        raise ValueError("approved_at is required for process approval")
    lease_issued_at = _require_zoned_rfc3339(approved_at)
    # lease_id 绑定批准请求身份：同一命令的第二次批准（修复后重跑验证的正常
    # 任务路径）铸造新租约而不是撞 state 的 lease_id 唯一性不变量；容量
    # MAX_PROCESS_LEASES 仍 fail closed。
    lease = ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{pending.request_id}:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity=pending.request_id,
        issued_at=lease_issued_at,
        expires_at=_add_minutes_rfc3339(lease_issued_at, candidate.expiry_minutes),
        max_uses=candidate.max_uses,
        uses_consumed=0,
    )
    return replace(state, process_leases=(*state.process_leases, lease))


def _mint_browser_authority_lease(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    approved_at: str | None = None,
) -> ConversationState:
    """ResolveApproval(approved=True) 对 browser candidate 铸造 durable lease。

    lease 的 durable expiry 锚定 candidate 的 RFC3339 ``expires_at``（用户
    在 exact approval 中确认的时限）；approval 等待不静默延长租期。
    """

    candidate = pending.browser_action_candidate
    if candidate is None:
        return state
    if approved_at is None:
        raise ValueError("approved_at is required for browser approval")
    _require_zoned_rfc3339(approved_at)
    lease = BrowserAuthorityLeaseV1.create(
        lease_id=f"browser-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        session_ref=candidate.session_ref,
        browser_identity_digest=candidate.browser_identity_digest,
        profile_ref=candidate.profile_ref,
        profile_revision=candidate.profile_revision,
        allowed_origins=candidate.allowed_origins,
        mode=candidate.mode,
        page_id=candidate.page_id,
        frame_id=candidate.frame_id,
        observation_digest=candidate.observation_digest,
        action_digest=candidate.action_digest,
        consequence=candidate.consequence,
        approved_request_identity=pending.request_id,
        issued_at=approved_at,
        expires_at=candidate.expires_at,
    )
    return replace(state, browser_leases=(*state.browser_leases, lease))


@dataclass(frozen=True, slots=True)
class BrowserTakeoverCompletion:
    """complete takeover 的 closed 结果：期望 revision 递增 + 强制 fresh observe。

    它不是 commit approval——不铸造任何 browser lease。
    """

    expected_profile_revision: int
    requires_observe: bool


def begin_browser_takeover(
    state: ConversationState,
    request: BrowserTakeoverRequestV1,
) -> ConversationState:
    """在 user-facing 暴露之前持久化 pending takeover（spec §7）。

    已有 pending 时 fail closed；期间不产生任何 provider/tool 活动。
    """
    if state.browser_takeover_pending is not None:
        raise ValueError("browser takeover already pending")
    goal = state.goal
    if goal is None or goal.goal_id != request.goal_id or goal.revision != request.goal_revision:
        raise ValueError("browser takeover goal identity mismatch")
    active = state.active_run
    return replace(
        state,
        revision=state.revision + 1,
        # takeover 可能改变页面与 profile；旧 action lease 立即失效。正在
        # 运行的唯一 invocation 同时释放 ownership，typed complete/cancel
        # 才能在后续 run_turn 重新 claim 并恢复同一 run。
        browser_leases=(),
        browser_takeover_pending=request,
        active_run=(replace(active, owner_invocation_id=None) if active is not None else None),
    )


def complete_browser_takeover(
    state: ConversationState,
    *,
    request_id: str,
    session_ref: str,
    expected_profile_revision: int,
) -> tuple[ConversationState, BrowserTakeoverCompletion]:
    """校验 exact request/session/profile 后完成 takeover。

    清 pending、期望 profile revision 递增、要求 fresh browser_observe；
    不铸造任何 commit approval（browser_leases 原样不动）。
    """
    pending = state.browser_takeover_pending
    if pending is None:
        raise ValueError("browser takeover is not pending")
    if (
        request_id != pending.request_id
        or session_ref != pending.session_ref
        or expected_profile_revision != pending.profile_revision
    ):
        raise ValueError("browser takeover identity mismatch")
    completion = BrowserTakeoverCompletion(
        expected_profile_revision=pending.profile_revision + 1,
        requires_observe=True,
    )
    cleared = replace(
        state,
        revision=state.revision + 1,
        browser_takeover_pending=None,
    )
    return cleared, completion


def cancel_browser_takeover(
    state: ConversationState,
    *,
    request_id: str,
) -> ConversationState:
    pending = state.browser_takeover_pending
    if pending is None or pending.request_id != request_id:
        raise ValueError("browser takeover is not pending")
    return replace(
        state,
        revision=state.revision + 1,
        browser_takeover_pending=None,
    )


def _mint_sandbox_authority_lease(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    approved_at: str | None = None,
) -> ConversationState:
    """ResolveApproval(approved=True) 对 sandbox candidate 铸造 durable lease。

    对齐 process lease 语义：时效锚定批准时刻（zoned RFC3339，缺失/malformed/
    naive 一律 fail closed）；非 sandbox approval（无 candidate）不铸造。
    """

    candidate = pending.sandbox_authority_candidate
    if candidate is None:
        return state
    if approved_at is None:
        raise ValueError("approved_at is required for sandbox approval")
    lease_issued_at = _require_zoned_rfc3339(approved_at)
    # 同 _mint_process_authority_lease：lease_id 绑定批准请求身份，二次批准
    # 同一验证命令不再撞唯一性不变量（2026-10-04 真实 D01 运行暴露）。
    lease = SandboxAuthorityLeaseV1.create(
        lease_id=f"sandbox-lease:{pending.request_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        original_command_fingerprint=candidate.original_command_fingerprint,
        policy_digest=candidate.policy_digest,
        mode=candidate.mode,
        network=candidate.network,
        readable_command=candidate.readable_command,
        trust_notice_id=candidate.trust_notice_id,
        trust_notice_digest=candidate.trust_notice_digest,
        approved_request_identity=pending.request_id,
        issued_at=lease_issued_at,
        expires_at=_add_minutes_rfc3339(lease_issued_at, SANDBOX_EXPIRY_MINUTES),
    )
    return replace(state, sandbox_leases=(*state.sandbox_leases, lease))


def _admit_approved_read_only_validation_criterion(
    state: ConversationState,
    pending: ApprovalRequest,
) -> ConversationState:
    """R1（2026-10-03 follow-up）：read-only sandbox 批准时即固化验证义务。

    对齐 process 审批准入（恢复路径不得绕过）：批准 read-only ``sandbox_exec``
    验证命令时，把 Runtime 义务绑定为 native_sandbox_v1 无 digest 谓词（receipt
    尚不存在，candidate 的 fingerprint/policy/mode/network 已可绑定）。多项验证
    的共存路径由此在生产链上成立；旧 process_v1 义务不变造。仅 read-only 准入：
    workspace-write/danger 会失效先前证据，不得充当共存验证。
    """

    candidate = pending.sandbox_authority_candidate
    goal = state.goal
    if candidate is None or goal is None or candidate.mode != "read-only":
        return state
    active = state.active_run
    call = (
        next(
            (item for item in active.tool_calls if item.tool_call_id == pending.tool_call_id),
            None,
        )
        if active is not None
        else None
    )
    if call is None or call.name != "sandbox_exec":
        return state
    if (
        candidate.goal_id != goal.goal_id
        or candidate.goal_revision != goal.revision
        or candidate.workspace_identity_digest != goal.workspace_identity_digest
    ):
        raise ValueError("sandbox candidate does not bind the current Goal")
    admitted_ids = {item.criterion_id for item in goal.admitted_criteria}
    proposed_requirement = next(
        (
            item
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and item.criterion_id not in admitted_ids
        ),
        None,
    )
    if proposed_requirement is not None and _is_runtime_owned_obligation(proposed_requirement):
        executable = call.arguments.get("executable") if isinstance(call.arguments, dict) else None
        if not isinstance(executable, str) or not process_entrypoint_matches_authority(
            state, executable
        ):
            # 与 process 审批同界：approval 不能把另一条命令改写成用户明示
            # validator 的完成证据。
            return state
    criterion_id = (
        proposed_requirement.criterion_id
        if proposed_requirement is not None
        else (f"criterion:sandbox-receipt:{goal.goal_id}:{goal.revision}:{pending.tool_call_id}")
    )
    if any(
        item.criterion_id == criterion_id and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("sandbox validation criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "native_sandbox_v1",
        "command_fingerprint": candidate.original_command_fingerprint,
        "policy_digest": candidate.policy_digest,
        "mode": candidate.mode,
        "network": candidate.network,
        "backend": "seatbelt",
        "enforcement": "confined",
        "outcome": "exited",
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=(
            f"criterion-admission:sandbox-receipt:{pending.request_id}:{pending.tool_call_id}"
        ),
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="native_sandbox_receipt",
    )
    admitted = binding.admit(
        proposed_requirement.description
        if proposed_requirement is not None
        else "approved read-only sandbox_exec must produce the exact Kernel receipt"
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def _mint_goal_target_authorization(
    state: ConversationState,
    pending: ApprovalRequest,
    action: ResolveApproval,
    *,
    active: ActiveRun,
) -> ConversationState:
    """把用户 opt-in 绑定为当前 Goal 的文件或明确目录目标。"""

    if not (action.authorize_goal_target or action.authorize_goal_directory):
        return state
    directory = action.authorize_goal_directory
    authorized_target = _goal_target_authorization_scope(
        state,
        pending,
        active,
        directory=directory,
    )
    if authorized_target is None:
        raise ValueError("goal authorization requires a current Goal file or directory target")
    goal = state.goal
    assert goal is not None
    if action.approved_at is None:
        raise ValueError("approved_at is required for goal target authorization")
    issued_at = _require_zoned_rfc3339(action.approved_at)
    binding = GoalAuthorizationBinding.create(
        binding_id=f"goal-target-authority:{pending.request_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        operation=pending.tool_name,
        normalized_target=authorized_target,
        scope=(
            GoalAuthorizationScope.DIRECTORY if directory else GoalAuthorizationScope.EXACT_FILE
        ),
        source_kind=AuthoritySourceKind.HUMAN_APPROVAL,
        source_id=pending.request_id,
        source_digest=canonical_action_digest(action),
        issued_at=issued_at,
        expires_at=_add_minutes_rfc3339(
            issued_at,
            GOAL_TARGET_AUTHORIZATION_EXPIRY_MINUTES,
        ),
    )
    retained = tuple(
        item
        for item in state.goal_authorizations
        if not (
            item.operation == binding.operation
            and item.normalized_target == binding.normalized_target
            and item.scope is binding.scope
        )
    )
    return replace(state, goal_authorizations=(*retained, binding))


def _apply_action(
    state: ConversationState,
    action: Action,
    *,
    now: str | None = None,
) -> ConversationState:
    if isinstance(action, ExecuteOperatorTool):
        return start_operator_tool(state, action)
    if isinstance(action, AcknowledgeProviderDisclosure):
        return acknowledge_provider_disclosure(state, action, now=now)
    if isinstance(action, GrantProviderConsent):
        return grant_provider_consent(
            state,
            action,
            now=now or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
    if isinstance(action, RevokeProviderConsent):
        return revoke_provider_consent(state, action)
    if isinstance(action, ConfirmCriterion):
        goal = state.goal
        if goal is None:
            raise ValueError("criterion confirmation requires a goal")
        fact = ConversationFact(
            fact_id=f"action:{action.action_seq}:criterion-confirmation",
            kind=FactKind.USER_MESSAGE,
            content={
                "criterion_id": action.criterion_id,
                "confirmed": action.confirmed,
            },
        )
        evidence = state.evidence_records
        if action.confirmed:
            criterion = next(
                item for item in goal.admitted_criteria if item.criterion_id == action.criterion_id
            )
            evidence = (
                *evidence,
                EvidenceRecord(
                    evidence_id=(
                        f"evidence:{goal.goal_id}:{goal.revision}:{criterion.criterion_id}"
                    ),
                    goal_id=goal.goal_id,
                    goal_revision=goal.revision,
                    criterion_id=criterion.criterion_id,
                    oracle_kind=criterion.oracle_kind,
                    predicate_digest=canonical_json_digest(criterion.predicate),
                    source_fact_ids=(fact.fact_id,),
                    source_digest=canonical_json_digest(
                        [
                            {
                                "fact_id": fact.fact_id,
                                "kind": fact.kind,
                                "content": fact.content,
                            }
                        ]
                    ),
                    oracle_identity="user-confirmation:v1",
                    passed=True,
                    observed_at="operator-confirmed",
                ),
            )
        return replace(state, facts=(*state.facts, fact), evidence_records=evidence)
    if isinstance(action, SubmitMessage):
        terminal_goal = state.goal is not None and state.goal.status in {
            GoalStatus.VERIFIED_DONE,
            GoalStatus.CANCELLED,
        }
        correction = (
            state.goal is not None
            and state.goal.status
            not in {GoalStatus.PAUSED, GoalStatus.VERIFIED_DONE, GoalStatus.CANCELLED}
            and (
                state.active_run is None
                or state.active_run.status is ActiveRunStatus.AWAITING_APPROVAL
            )
        )
        facts = state.facts
        content = {"text": action.message}
        if correction:
            # 旧 intent 尚未执行；用户普通文本会撤回它，并成为下一次 GoalDelta
            # 唯一可消费的 authority source。未完成 batch 中的每个 call 都必须先有
            # durable 非执行结果，保持 Anthropic/OpenAI 的 tool continuity 闭合。
            content["control"] = "goal_correction"
            if state.active_run is not None:
                superseded = tuple(
                    ConversationFact(
                        fact_id=(f"action:{action.action_seq}:superseded-tool:{call.tool_call_id}"),
                        kind=FactKind.TOOL_RESULT,
                        content={
                            "tool_call_id": call.tool_call_id,
                            "text": (
                                "Tool call was not executed because the user corrected the Goal."
                            ),
                            "is_error": True,
                            "executed": False,
                            "superseded": True,
                            **(
                                {"invocation_origin": InvocationOrigin.OPERATOR.value}
                                if state.active_run.invocation_origin is InvocationOrigin.OPERATOR
                                else {}
                            ),
                        },
                    )
                    for call in state.active_run.tool_calls[state.active_run.batch_cursor :]
                )
                facts = (*facts, *superseded)
        fact = ConversationFact(
            fact_id=f"action:{action.action_seq}:user",
            kind=FactKind.USER_MESSAGE,
            content=content,
        )
        return replace(
            state,
            facts=(*facts, fact),
            active_run=ActiveRun(run_id=action.run_id),
            # terminal follow-up 只推进 conversation；原 claim 仍证明关闭的 Goal，
            # 不能因新一轮普通讨论被清除。其它路径保持原有 claim invalidation。
            completion_claim=state.completion_claim if terminal_goal else None,
            interaction_state=InteractionState.IDLE,
        )

    if isinstance(action, PauseGoal):
        return pause_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )
    if isinstance(action, ResumeGoal):
        return resume_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )
    if isinstance(action, CancelGoal):
        return cancel_goal(
            state,
            goal_id=action.goal_id,
            expected_revision=action.goal_revision,
        )

    if isinstance(action, CompleteBrowserTakeover):
        completed, _outcome = complete_browser_takeover(
            state,
            request_id=action.request_id,
            session_ref=action.session_ref,
            expected_profile_revision=action.expected_profile_revision,
        )
        return completed
    if isinstance(action, CancelBrowserTakeover):
        return cancel_browser_takeover(state, request_id=action.request_id)
    if isinstance(action, RevokeProcessAuthority):
        if action.lease_id is None:
            retained: tuple[ProcessAuthorityLeaseV1, ...] = ()
        else:
            retained = tuple(
                lease for lease in state.process_leases if lease.lease_id != action.lease_id
            )
        return replace(state, process_leases=retained)
    if isinstance(action, RevokeGoalTargetAuthority):
        return replace(state, goal_authorizations=())
    if isinstance(action, AbandonUnknownModelOutcome):
        return end_run(
            state,
            status=RunStatus.FAILED_FATAL,
            code="model_outcome_abandoned",
            message="Unknown provider outcome was abandoned for this occurrence.",
        )

    active = state.active_run
    if active is None:
        raise ValueError("active run required")

    if isinstance(action, ResolveApproval):
        pending = active.pending_request
        if not isinstance(pending, ApprovalRequest):
            raise ValueError("approval request required")
        if action.approved:
            updated = replace(
                active,
                status=ActiveRunStatus.RUNNABLE,
                phase=ContinuationPhase.TOOL,
                pending_request=None,
                approval_grant=ApprovalGrant(
                    request_id=pending.request_id,
                    binding_digest=pending.binding_digest,
                    approval_basis_revision=pending.approval_basis_revision,
                ),
                approved_request_ids=(*active.approved_request_ids, pending.request_id),
            )
            updated_state = replace(state, active_run=updated)
            updated_state = _mint_process_authority_lease(
                updated_state, pending, approved_at=action.approved_at
            )
            updated_state = _mint_sandbox_authority_lease(
                updated_state, pending, approved_at=action.approved_at
            )
            updated_state = _admit_approved_read_only_validation_criterion(updated_state, pending)
            updated_state = _mint_browser_authority_lease(
                updated_state, pending, approved_at=action.approved_at
            )
            updated_state = _mint_goal_target_authorization(
                updated_state,
                pending,
                action,
                active=active,
            )
            updated_state = _admit_process_artifact_criterion(
                updated_state,
                pending,
                action=action,
            )
            updated_state = _admit_approved_process_receipt_criterion(
                updated_state,
                pending,
                action=action,
            )
            updated_state = _add_approved_governed_tool_requirement(
                updated_state,
                pending,
                active=active,
            )
            updated_state = _admit_approved_file_criterion(
                updated_state,
                action=action,
                active=active,
            )
            return _admit_approved_research_criterion(
                updated_state,
                action=action,
                active=active,
            )
        browser_candidate = pending.browser_action_candidate
        rejection_text = "User rejected the requested tool action."
        if browser_candidate is not None:
            rejection_text = (
                f"The requested browser {browser_candidate.consequence} action was not "
                "run because you declined approval. No browser effect was executed."
            )
        rejection = ConversationFact(
            fact_id=f"action:{action.action_seq}:rejection",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": pending.tool_call_id,
                "text": rejection_text,
                "is_error": True,
                "executed": False,
                "rejected": True,
                **(
                    {"invocation_origin": InvocationOrigin.OPERATOR.value}
                    if active.invocation_origin is InvocationOrigin.OPERATOR
                    else {}
                ),
            },
        )
        # 拒绝是用户的强控制信号：结束当前 run，把控制权交还用户。不能继续
        # 同一 model batch 的剩余工具，也不能再调用 provider 来游说或换命令。
        # Goal 与此前已持久化的结果保留；后续新指令会形成新的 run 和新绑定。
        # R1：cursor 之后的 suffix 确定未开始，与清空 run 落在同一 CAS。
        closed_suffix = _unstarted_batch_suffix_facts(
            state,
            text=(
                "Tool call was not executed because the run stopped at a declined "
                "approval before this call started."
            ),
            already_accounted=1,
        )
        return replace(
            state,
            active_run=None,
            facts=(*state.facts, rejection, *closed_suffix),
            last_safe_result=RecordedRunResult(
                status=RunStatus.CANCELLED,
                run_id=active.run_id,
                message=(
                    "The requested action was declined and this run stopped without "
                    "executing it. The goal remains available for a new instruction."
                ),
                error_code="approval_declined",
            ),
        )

    if isinstance(action, ResolveUnknownToolOutcome):
        pending = active.pending_request
        if not isinstance(pending, RecoveryRequest):
            raise ValueError("recovery request required")
        succeeded = action.resolution.value == "mark_succeeded"
        intent = active.executing_intent
        synthetic = ConversationFact(
            fact_id=f"action:{action.action_seq}:recovery",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": pending.tool_call_id,
                "text": (
                    "Operator classified the previous tool effect as succeeded."
                    if succeeded
                    else "Operator classified the previous tool effect as failed."
                ),
                "is_error": not succeeded,
                "synthetic": True,
                # RC-01（2026-10-11）：UNKNOWN 结果必须保守失效其前的旧验证。
                # 标记失败不等于从未执行；分类来自可信执行意图（不采信模型文本），
                # intent 缺失时不盖章 side_effect，证据/折叠消费者保守视为潜在写入。
                "unknown_outcome": True,
                **({"side_effect": intent.side_effect.value} if intent is not None else {}),
                **(
                    {"invocation_origin": InvocationOrigin.OPERATOR.value}
                    if active.invocation_origin is InvocationOrigin.OPERATOR
                    else {}
                ),
            },
        )
        updated = replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=(
                ContinuationPhase.TOOL
                if active.batch_cursor + 1 < len(active.tool_calls)
                else ContinuationPhase.MODEL
            ),
            pending_request=None,
            executing_intent=None,
            batch_cursor=active.batch_cursor + 1,
            tool_calls=(
                active.tool_calls if active.batch_cursor + 1 < len(active.tool_calls) else ()
            ),
        )
        return replace(state, active_run=updated, facts=(*state.facts, synthetic))

    if isinstance(action, RecoverUnknownObservation):
        intent = active.executing_intent
        if intent is None or intent.egress is not EgressClass.PUBLIC_NETWORK:
            raise ValueError("PUBLIC_NETWORK executing intent required")
        observation = ConversationFact(
            fact_id=f"action:{action.action_seq}:observation-unknown",
            kind=FactKind.TOOL_RESULT,
            content={
                "tool_call_id": intent.tool_call_id,
                "text": (
                    "The public-network observation outcome is unknown; the previous "
                    "request will not be retried automatically."
                ),
                "is_error": True,
                "executed": True,
                "metadata": {
                    "code": "observation_unknown",
                    "observation_outcome": "observation_unknown",
                    "source_receipts": [],
                },
                **(
                    {"invocation_origin": InvocationOrigin.OPERATOR.value}
                    if active.invocation_origin is InvocationOrigin.OPERATOR
                    else {}
                ),
            },
        )
        next_cursor = active.batch_cursor + 1
        has_more = next_cursor < len(active.tool_calls)
        updated = replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            pending_request=None,
            executing_intent=None,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
            approval_grant=None,
            owner_invocation_id=None,
        )
        return replace(state, active_run=updated, facts=(*state.facts, observation))

    if isinstance(action, Resume):
        if active.status in {ActiveRunStatus.AWAITING_APPROVAL, ActiveRunStatus.AWAITING_RECOVERY}:
            return state
        return replace(
            state,
            active_run=replace(
                active,
                status=ActiveRunStatus.RUNNABLE,
                owner_invocation_id=None,
            ),
        )

    if isinstance(action, CancelRun):
        # R1：TOOL 相（含 AWAITING_APPROVAL）的 cursor 之后确定未开始，
        # 与清空 run 落在同一 CAS；EXECUTING/AWAITING_RECOVERY 由合法性
        # 守卫拒绝，不会经此路径丢 UNKNOWN。
        closed_suffix = _unstarted_batch_suffix_facts(
            state,
            text=(
                "Tool call was not executed because the run was cancelled before this call started."
            ),
        )
        return replace(
            state,
            facts=(*state.facts, *closed_suffix),
            active_run=None,
            last_safe_result=RecordedRunResult(
                status=RunStatus.CANCELLED,
                run_id=active.run_id,
            ),
        )
    raise TypeError(f"unsupported action: {type(action).__name__}")


def _admit_approved_file_criterion(
    state: ConversationState,
    *,
    action: ResolveApproval,
    active: ActiveRun,
) -> ConversationState:
    """审批 exact 文件写入时由 Runtime 铸造 deterministic read-back criterion。"""

    goal = state.goal
    if goal is None or active.batch_cursor >= len(active.tool_calls):
        return state
    call = active.tool_calls[active.batch_cursor]
    pending = active.pending_request
    path = call.arguments.get("path")
    if (
        call.name not in {"write_file", "edit_file", "confirm_file"}
        or not isinstance(path, str)
        or not isinstance(pending, ApprovalRequest)
        or pending.new_content_digest is None
    ):
        return state
    matching_proposals = tuple(
        item
        for item in goal.proposed_criteria
        if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST and item.artifact_path == path
    )
    deferred_proposals = tuple(
        item
        for item in goal.proposed_criteria
        if item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST and item.artifact_path is None
    )
    bound_proposal_id: str | None = None
    if not matching_proposals and len(deferred_proposals) == 1:
        matching_proposals = deferred_proposals
        bound_proposal_id = deferred_proposals[0].criterion_id
    if matching_proposals:
        criteria = tuple((item.criterion_id, item.description) for item in matching_proposals)
    else:
        criteria = (
            (
                f"criterion:approved-write:{call.tool_call_id}",
                f"approved file {path} has the exact requested content",
            ),
        )
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("approved write criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "path": path,
        "sha256": pending.new_content_digest,
    }
    criterion_ids = {criterion_id for criterion_id, _description in criteria}
    if all(
        any(
            item.criterion_id == criterion_id
            and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.predicate == predicate
            for item in goal.admitted_criteria
        )
        for criterion_id in criterion_ids
    ):
        return state
    admitted = tuple(
        CriterionAdmissionBinding.create(
            binding_id=(
                f"criterion-admission:approval:{action.action_seq}:"
                f"{call.tool_call_id}:{criterion_id}"
            ),
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            workspace_identity_digest=goal.workspace_identity_digest,
            criterion_id=criterion_id,
            user_outcome_fact_id=source.fact_id,
            user_outcome_digest=source_digest,
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            predicate=predicate,
            required_evidence_class="workspace_file",
        ).admit(description)
        for criterion_id, description in criteria
    )
    superseded_ids = {
        item.criterion_id
        for item in goal.admitted_criteria
        if item.criterion_id in criterion_ids
        or (
            item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
            and item.predicate.get("path") == path
        )
        or (
            item.oracle_kind is EvidenceOracleKind.RESEARCH_PROVENANCE
            and path
            in {
                item.predicate.get("artifact_path"),
                item.predicate.get("manifest_path"),
            }
        )
    }
    retained_criteria = tuple(
        item for item in goal.admitted_criteria if item.criterion_id not in superseded_ids
    )
    retained_evidence = tuple(
        item for item in state.evidence_records if item.criterion_id not in superseded_ids
    )
    proposed_criteria = tuple(
        replace(item, artifact_path=path) if item.criterion_id == bound_proposal_id else item
        for item in goal.proposed_criteria
    )
    return replace(
        state,
        goal=replace(
            goal,
            proposed_criteria=proposed_criteria,
            admitted_criteria=(*retained_criteria, *admitted),
        ),
        evidence_records=retained_evidence,
        completion_claim=None,
    )


def _admit_approved_research_criterion(
    state: ConversationState,
    *,
    action: ResolveApproval,
    active: ActiveRun,
) -> ConversationState:
    """审批 citation sidecar 时铸造额外的 Runtime-owned provenance criterion。"""

    goal = state.goal
    if goal is None or active.batch_cursor >= len(active.tool_calls):
        return state
    call = active.tool_calls[active.batch_cursor]
    pending = active.pending_request
    path = call.arguments.get("path")
    content = call.arguments.get("content")
    if (
        call.name not in {"write_file", "edit_file"}
        or not isinstance(path, str)
        or not path.endswith(".citations.json")
        or not isinstance(content, str)
        or not isinstance(pending, ApprovalRequest)
        or pending.new_content_digest is None
    ):
        return state
    # prepare 已把 transport 追加的单个换行移除并将 canonical digest 放进
    # ApprovalRequest；状态准入必须使用同一份已批准内容，不能重新解释原始参数。
    if hashlib.sha256(content.encode("utf-8")).hexdigest() != pending.new_content_digest:
        if not content.endswith("\n"):
            return state
        canonical_content = content[:-1]
        if (
            hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
            != pending.new_content_digest
        ):
            return state
        content = canonical_content
    try:
        manifest = CitationManifestV1.from_json(content)
    except ValueError:
        return state
    if (
        manifest.goal_id != goal.goal_id
        or manifest.goal_revision != goal.revision
        or path == manifest.artifact_path
        or path not in goal.targets
        or manifest.artifact_path not in goal.targets
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("research criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    criterion_id = (
        "criterion:research-provenance:"
        + canonical_json_digest({"goal_id": goal.goal_id, "artifact_path": manifest.artifact_path})[
            :16
        ]
    )
    predicate = {
        "artifact_path": manifest.artifact_path,
        "artifact_sha256": manifest.artifact_sha256,
        "manifest_path": path,
        "manifest_sha256": pending.new_content_digest,
        "manifest_digest": manifest.manifest_digest,
        "minimum_distinct_sources": len(manifest.citations),
        "required_source_kinds": [],
        "required_source_classes": [],
        "required_receipt_digests": [citation.receipt_digest for citation in manifest.citations],
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:research:{action.action_seq}:{call.tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.RESEARCH_PROVENANCE,
        predicate=predicate,
        required_evidence_class="research_provenance",
    )
    admitted = binding.admit(
        "artifact and citation sidecar are bound to current-Goal source receipts"
    )
    retained_criteria = tuple(
        item for item in goal.admitted_criteria if item.criterion_id != criterion_id
    )
    retained_evidence = tuple(
        item for item in state.evidence_records if item.criterion_id != criterion_id
    )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*retained_criteria, admitted),
        ),
        evidence_records=retained_evidence,
        completion_claim=None,
    )


# 真实层 E1r4（2026-10-18）：裸 pytest 在 pyenv shim 下 exit 2 后，模型用同一
# validator 加「导入/收集环境修复 flag」跑通。这些 flag 不改变选中与执行语义，
# 比较前剥离；值一律是字面常量，避免 flag 变成注入面——``-o addopts=`` 可注入
# ``--collect-only``，``--ignore``/``-k``/``--deselect`` 直接改变选中，均不在此列。
_ENVIRONMENT_REPAIR_FLAG_SEQUENCES: tuple[tuple[str, ...], ...] = (
    ("-p", "no:cacheprovider"),
    ("--import-mode=prepend",),
    ("--import-mode=append",),
    ("--import-mode", "prepend"),
    ("--import-mode", "append"),
    ("--rootdir=.",),
    ("--rootdir", "."),
    ("-o", "pythonpath=."),
)


def _strip_environment_repair_flags(rest: tuple[str, ...]) -> tuple[str, ...]:
    """剥离已知不改变选中/执行语义的环境修复 flag；其余 token 原样保留。"""

    kept: list[str] = []
    index = 0
    while index < len(rest):
        for sequence in _ENVIRONMENT_REPAIR_FLAG_SEQUENCES:
            if rest[index : index + len(sequence)] == sequence:
                index += len(sequence)
                break
        else:
            kept.append(rest[index])
            index += 1
    return tuple(kept)


def _canonical_command_form(executable: object, argv: object) -> tuple[str, tuple[str, ...]] | None:
    """命令的 canonical 等价形式：(entrypoint, rest argv)。

    归一两种**不改变执行语义**的改写：``pythonX -m <module> <rest>`` ⇔
    ``<module> <rest>``（pyenv shim 下模块调用与直接入口等价，这正是真实层
    E1r2/E2 需要的形态），以及已知的环境修复 flag 剥离。其余一切差异（选择类
    flag、不同 rest）都视为不同命令。
    """

    if not isinstance(executable, str):
        return None
    entry = normalize_process_entrypoint(executable)
    if not entry:
        return None
    rest: list[str] = []
    if isinstance(argv, (list, tuple)):
        rest = [item for item in argv if isinstance(item, str)]
    if re.fullmatch(r"python(?:3(?:\.\d+)?)?", entry) and len(rest) >= 2 and rest[0] == "-m":
        module = normalize_process_entrypoint(rest[1])
        if not module:
            return None
        return module, _strip_environment_repair_flags(tuple(rest[2:]))
    return entry, _strip_environment_repair_flags(tuple(rest))


_ENVIRONMENT_CLASS_EXIT_CODES = frozenset({2, 5})


def _environment_class_process_failure(receipt: ProcessReceiptV1) -> bool:
    """区分「环境/调用方式失败」与「被测代码真实失败」。

    P1（对抗审查 2026-10-18）：重绑定资格此前只看「有没有 exited/0」，于是
    ``pytest`` exit 1（测试红了）与 exit 2（用法/导入/中断）同等可重绑定——
    模型可以换一条不验证的命令把红测试掩盖成 VERIFIED_DONE。保守规则：
    只有退出码属于环境类（2 = 用法/中断/收集错误、5 = 无测试被收集）才视为
    「该命令在此环境不可用」，允许用户显式 opt-in 后重绑定；其余非零退出
    （1 测试失败、3 内部错误、4 用法错误以外）一律视为真实验证结果，不可重绑定。
    """

    return receipt.exit_code in _ENVIRONMENT_CLASS_EXIT_CODES


def _rebindable_failed_process_obligation(
    state: ConversationState,
    new_call_arguments: Mapping[str, object],
    *,
    candidate: ProcessAuthorityCandidateV1 | None,
) -> AdmittedCriterion | None:
    """发现 3（2026-10-18 真实层 E1r2/E2）：runtime-owned 验证义务的重绑定候选。

    义务在批准时 pin「首个被批准命令的 fingerprint + exited/0」。当该命令在当前
    Goal 内已执行且从未成功（如裸 ``pytest -q`` 在 pyenv shim 下恒 exit 2）、用户
    又通过 exact approval 批准了一条 **canonical 等价**命令（``python3 -m pytest
    -q``）时，新命令承接该义务；否则旧 fingerprint 永远无法满足，Goal 只能 blocked。

    等价判定必须严格：仅 ``pythonX -m <entry>`` ⇔ ``<entry>`` 归一，entry 与其余
    argv 精确相等。曾成功过（重跑可再满足，由失效型修复知识引导）、从未执行、
    sandbox 型 predicate、跨 Goal receipt、或不等价的命令一律不重绑定（fail
    closed；对抗审查 2026-10-18 实机复现 ``pytest --help``/``--collect-only`` 曾冒领）。
    """

    goal = state.goal
    if (
        goal is None
        or candidate is None
        or candidate.goal_id != goal.goal_id
        or candidate.goal_revision != goal.revision
        or candidate.workspace_identity_digest != goal.workspace_identity_digest
    ):
        return None
    new_form = _canonical_command_form(
        new_call_arguments.get("executable"), new_call_arguments.get("argv")
    )
    if new_form is None:
        return None
    outcomes_by_fingerprint: dict[str, list[tuple[str, int | None]]] = {}
    receipts_by_fingerprint: dict[str, list[ProcessReceiptV1]] = {}
    forms_by_fingerprint: dict[str, tuple[str, tuple[str, ...]] | None] = {}
    arguments_by_call_id: dict[str, tuple[object, object]] = {}
    for fact in state.facts:
        if fact.kind is FactKind.TOOL_CALLS:
            for raw in fact.content.get("calls", ()):
                if not isinstance(raw, dict) or raw.get("name") != "local_process":
                    continue
                arguments = raw.get("arguments")
                call_id = raw.get("tool_call_id")
                if isinstance(arguments, dict) and isinstance(call_id, str):
                    arguments_by_call_id[call_id] = (
                        arguments.get("executable"),
                        arguments.get("argv"),
                    )
        elif fact.kind is FactKind.TOOL_RESULT:
            metadata = fact.content.get("metadata")
            if not isinstance(metadata, dict):
                continue
            try:
                receipt = ProcessReceiptV1.from_json(metadata.get("process_receipt"))
            except ValueError:
                continue
            if receipt.goal_id != goal.goal_id or receipt.goal_revision != goal.revision:
                # P3（对抗审查）：资格必须 Goal 作用域——早前 Goal 的同命令失败
                # 不能让当前 Goal「从未执行」的义务变成可重绑定。
                continue
            fingerprint = receipt.command_fingerprint
            outcomes_by_fingerprint.setdefault(fingerprint, []).append(
                (receipt.outcome.value, receipt.exit_code)
            )
            receipts_by_fingerprint.setdefault(fingerprint, []).append(receipt)
            call_id = fact.content.get("tool_call_id")
            if isinstance(call_id, str) and fingerprint not in forms_by_fingerprint:
                forms_by_fingerprint[fingerprint] = _canonical_command_form(
                    *arguments_by_call_id.get(call_id, (None, None))
                )
    for criterion in goal.admitted_criteria:
        if not criterion.criterion_id.startswith("criterion:required-local-process:"):
            continue
        if criterion.predicate.get("receipt_kind") != "process_v1":
            # sandbox 型 predicate 的 fingerprint 与前台 process 同源，混算会
            # 用另一模态的失败/成功误判（对抗审查 P2）。
            continue
        fingerprint = criterion.predicate.get("command_fingerprint")
        if not isinstance(fingerprint, str):
            continue
        outcomes = outcomes_by_fingerprint.get(fingerprint)
        if not outcomes:
            continue
        if any(outcome == ("exited", 0) for outcome in outcomes):
            continue
        if any(
            receipt.workspace_identity_digest != candidate.workspace_identity_digest
            or receipt.cwd_digest != candidate.cwd_digest
            or receipt.resource_profile != candidate.resource_profile
            or receipt.environment_policy_digest != candidate.environment_policy_digest
            or receipt.execution_authority is not candidate.execution_authority
            for receipt in receipts_by_fingerprint[fingerprint]
        ):
            # 命令文本相同不代表验证范围相同。比较 Kernel 准入/回执中的作用域，
            # 不把子目录的成功、不同环境或权限下的执行替换成原验证；不猜测路径别名。
            continue
        if not all(
            _environment_class_process_failure(receipt)
            for receipt in receipts_by_fingerprint.get(fingerprint, ())
        ):
            # P1：只要有一次失败不是环境类（例如测试真的红了 exit 1），就不
            # 允许重绑定——否则可用不验证的命令掩盖真实失败。
            continue
        if forms_by_fingerprint.get(fingerprint) == new_form:
            return criterion
    return None


def _admit_approved_process_receipt_criterion(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    action: ResolveApproval,
) -> ConversationState:
    """批准 process 时即固化成功 receipt 义务，恢复路径不得绕过。"""

    goal = state.goal
    candidate = pending.process_authority_candidate
    if goal is None or candidate is None:
        return state
    active = state.active_run
    call = (
        next(
            (item for item in active.tool_calls if item.tool_call_id == pending.tool_call_id),
            None,
        )
        if active is not None
        else None
    )
    # 该完成义务只描述 foreground validator 的 exited/0 receipt。受管开发服务
    # 由 browser evidence + managed_web_stop/composition cleanup 闭合，不能伪装成
    # 一次已退出的 local_process，也不能因此留下永远无法满足的 criterion。
    if call is None or call.name != "local_process":
        return state
    if (
        candidate.goal_id != goal.goal_id
        or candidate.goal_revision != goal.revision
        or candidate.workspace_identity_digest != goal.workspace_identity_digest
    ):
        raise ValueError("process candidate does not bind the current Goal")
    admitted_ids = {item.criterion_id for item in goal.admitted_criteria}
    proposed_requirement = next(
        (
            item
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and item.criterion_id not in admitted_ids
        ),
        None,
    )
    if proposed_requirement is not None and _is_runtime_owned_obligation(proposed_requirement):
        executable = call.arguments.get("executable") if call.name == "local_process" else None
        if not isinstance(executable, str):
            raise ValueError(
                "Runtime-owned process criterion requires the pending local_process call"
            )
        if not process_entrypoint_matches_authority(state, executable):
            # approval 只授予这笔 effect 的 lease；它不能把另一个命令改写成用户
            # 明示 validator 的完成证据。
            return state
    rebindable = (
        None
        if proposed_requirement is not None or not action.authorize_obligation_rebind
        else _rebindable_failed_process_obligation(
            state, call.arguments, candidate=candidate
        )
    )
    criterion_id = (
        proposed_requirement.criterion_id
        if proposed_requirement is not None
        else (
            rebindable.criterion_id
            if rebindable is not None
            else (
                f"criterion:process-receipt:{goal.goal_id}:{goal.revision}:{pending.tool_call_id}"
            )
        )
    )
    if rebindable is None and any(
        item.criterion_id == criterion_id and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        # per-call 去重；重绑定路径同 id 属预期（retained 替换），不作早退。
        return state
    if (
        rebindable is None
        and proposed_requirement is None
        and any(
            item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and item.predicate.get("receipt_kind") == "process_v1"
            for item in goal.admitted_criteria
        )
    ):
        # E3r2（2026-10-24 真实层）：F1 保守失效使任意第二次进程执行失效其前
        # 全部 receipt——两条不同指纹的强制 process 判据在构造上永不可同时
        # 满足（任一时刻只有最后执行的进程的 receipt 能存活）。真实层
        # deepseek-flash 的 E3 旅程（已正确文件 + 模型自发辅助验证命令）因此
        # 连续 24 次 completion_not_verified 直到预算耗尽。已有 process 义务
        # 时，per-call fallback 不得再铸第二条；重绑定（替换失败义务）不受
        # 此限，runtime-owned proposed requirement 绑定也不受此限。
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("process receipt criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "process_v1",
        "command_fingerprint": candidate.command_fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=(
            f"criterion-admission:process-receipt:{action.action_seq}:{pending.tool_call_id}"
        ),
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
    )
    admitted = binding.admit(
        proposed_requirement.description
        if proposed_requirement is not None
        else (
            rebindable.description
            if rebindable is not None
            else "approved local_process must produce the exact successful Kernel receipt"
        )
    )
    if rebindable is not None:
        # 重绑定沿用 admit_research_provenance 的 retained 替换模式：同
        # criterion_id 换新 predicate/binding，并作废旧绑定下的证据记录。
        retained_criteria = tuple(
            item for item in goal.admitted_criteria if item.criterion_id != criterion_id
        )
        retained_evidence = tuple(
            item for item in state.evidence_records if item.criterion_id != criterion_id
        )
        return replace(
            state,
            goal=replace(
                goal,
                admitted_criteria=(*retained_criteria, admitted),
            ),
            evidence_records=retained_evidence,
            completion_claim=None,
        )
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def _add_approved_governed_tool_requirement(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    active: ActiveRun,
) -> ConversationState:
    """把已批准的 MCP/SubAgent 调用固化为 Runtime-owned 完成义务。"""

    goal = state.goal
    if goal is None or active.batch_cursor >= len(active.tool_calls):
        return state
    call = active.tool_calls[active.batch_cursor]
    if call.tool_call_id != pending.tool_call_id or not call.name.startswith(
        ("mcp__", "subagent__")
    ):
        return state
    criterion_id = (
        f"criterion:required-governed-tool:{goal.goal_id}:{goal.revision}:{call.tool_call_id}"
    )
    if any(
        item.criterion_id == criterion_id
        for item in (*goal.proposed_criteria, *goal.admitted_criteria)
    ):
        return state
    requirement = ProposedCriterion(
        criterion_id=criterion_id,
        description=(f"the approved {call.name} call returns an exact Kernel-governed receipt"),
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
    )
    return replace(
        state,
        goal=replace(goal, proposed_criteria=(*goal.proposed_criteria, requirement)),
        completion_claim=None,
    )


def _admit_process_artifact_criterion(
    state: ConversationState,
    pending: ApprovalRequest,
    *,
    action: ResolveApproval,
) -> ConversationState:
    """ResolveApproval 时铸造 FILESYSTEM_DIGEST criterion（F4：用户确认 digest）。

    authority 是 **ResolveApproval action 自带的 confirmed_artifact**（用户在批准
    command 的同一 typed action 里确认 path+sha256）——模型无法自供（schema 回
    closed 4 字段）。candidate 的 ea 字段是 runtime 内部残留（prepare 路径恒
    None，保持 checkpoint 兼容），不再作为 authority 来源。malformed fail closed。
    """

    goal = state.goal
    if goal is None:
        return state
    ea_path = action.confirmed_artifact_path
    ea_sha = action.confirmed_artifact_sha256
    requirement = pending.artifact_confirmation_requirement
    if requirement is not None and not any(
        item.criterion_id == requirement.criterion_id
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        and item.artifact_path == requirement.artifact_path
        for item in goal.proposed_criteria
    ):
        raise ValueError(
            "artifact confirmation requirement does not match a current Goal criterion"
        )
    if action.defer_artifact_confirmation:
        if requirement is None:
            raise ValueError("artifact confirmation can be deferred only for a pending requirement")
        # 这里只批准生成 effect。未铸造 FILESYSTEM_DIGEST criterion；未来字节必须
        # 由 confirm_file 重新读取、展示并经独立 approval 后才可成为完成证据。
        return state
    if requirement is not None and (
        ea_path is None or ea_sha is None or ea_path != requirement.artifact_path
    ):
        raise ValueError("artifact confirmation must match the pending path and include sha256")
    if ea_path is None and ea_sha is None:
        return state
    import re as _re

    if (
        not isinstance(ea_path, str)
        or not ea_path
        or "\x00" in ea_path
        or ea_path.startswith("/")
        or ".." in ea_path.split("/")
        or not isinstance(ea_sha, str)
        or not _re.match(r"^[a-f0-9]{64}$", ea_sha)
    ):
        raise ValueError("confirmed_artifact must be workspace-relative path + 64-hex sha256")
    criterion_id = (
        requirement.criterion_id
        if requirement is not None
        else f"criterion:process-artifact:{goal.goal_id}:{goal.revision}:{ea_path}"
    )
    if any(
        item.criterion_id == criterion_id
        and item.oracle_kind is EvidenceOracleKind.FILESYSTEM_DIGEST
        for item in goal.admitted_criteria
    ):
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        raise ValueError("process artifact criterion requires the authoritative user fact")
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {"path": ea_path, "sha256": ea_sha}
    binding = CriterionAdmissionBinding.create(
        binding_id=(
            f"criterion-admission:process-artifact:{action.action_seq}:{pending.tool_call_id}"
        ),
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
        predicate=predicate,
        required_evidence_class="workspace_file",
    )
    admitted = binding.admit(f"process artifact {ea_path} reads back with exact approved sha256")
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def admit_process_receipt_criterion(
    state: ConversationState,
    *,
    tool_call_id: str,
    receipt_digest: str,
    command_fingerprint: str,
    action_seq: int,
) -> ConversationState:
    """兼容路径：成功 process receipt 后补铸 mandatory TOOL_RECEIPT criterion。

    正常路径已在批准时铸造不含未知 digest 的义务，因同 criterion_id
    本函数会保持原义务。它仅为旧的非标准路径保留；不信任 model prose。
    """

    goal = state.goal
    if goal is None:
        return state
    criterion_id = f"criterion:process-receipt:{goal.goal_id}:{goal.revision}:{tool_call_id}"
    if any(
        item.criterion_id == criterion_id and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        return state
    if any(
        item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        and item.predicate.get("receipt_kind") == "process_v1"
        and item.predicate.get("command_fingerprint") == command_fingerprint
        and "receipt_digest" not in item.predicate
        for item in goal.admitted_criteria
    ):
        # 批准路径已铸同指纹的 digest-free 义务（可被任何未失效的同指纹
        # receipt 满足）。此处再铸 digest-pinned per-call criterion 只会在
        # 该 receipt 因后续 workspace 变更失效后留下一条永不可满足的义务，
        # 把"写入后按指引重跑验证"的 Goal 永久卡在完成门外（2026-10-24 P1）。
        return state
    if any(
        item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        and item.predicate.get("receipt_kind") == "process_v1"
        and item.criterion_id != criterion_id
        for item in goal.admitted_criteria
    ):
        # E3r2（2026-10-24 真实层）：F1 保守失效使任意第二次进程执行失效
        # 其前全部 receipt——两条不同指纹的强制 process 判据在构造上永不
        # 可同时满足（任一时刻只有最后执行的进程的 receipt 能存活）。真实
        # 层 deepseek-flash 的 E3 旅程因此连续 24 次 completion_not_verified
        # 直到预算耗尽。已有 process 义务时，兼容路径不得再铸第二条。
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        return state
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "process_v1",
        "receipt_digest": receipt_digest,
        "command_fingerprint": command_fingerprint,
        "outcome": "exited",
        "exit_code": 0,
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:process-receipt:{action_seq}:{tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="process_receipt",
    )
    admitted = binding.admit("local_process command contract satisfied by Kernel receipt")
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def admit_sandbox_receipt_criterion(
    state: ConversationState,
    *,
    tool_call_id: str,
    receipt_digest: str,
    command_fingerprint: str,
    policy_digest: str,
    mode: str,
    network: str,
    action_seq: int,
) -> ConversationState:
    """R1（2026-10-03）：成功 read-only sandbox receipt 的兼容结果时准入。

    正常路径已在批准时铸造无 digest 义务；同 criterion_id 时保持原义务。
    仅 read-only 模式准入（与共存的失效规则一致）。
    """

    goal = state.goal
    if goal is None or mode != "read-only":
        return state
    criterion_id = f"criterion:sandbox-receipt:{goal.goal_id}:{goal.revision}:{tool_call_id}"
    if any(
        item.criterion_id == criterion_id and item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for item in goal.admitted_criteria
    ):
        return state
    if any(
        item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        and item.predicate.get("receipt_kind") == "native_sandbox_v1"
        and item.predicate.get("command_fingerprint") == command_fingerprint
        and "receipt_digest" not in item.predicate
        for item in goal.admitted_criteria
    ):
        # 与 process 路径同一根因（2026-10-24 P1）：批准路径已铸同指纹
        # digest-free 义务时，兼容铸造不得再追加 digest-pinned 副本。
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        return state
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    predicate = {
        "receipt_kind": "native_sandbox_v1",
        "receipt_digest": receipt_digest,
        "command_fingerprint": command_fingerprint,
        "policy_digest": policy_digest,
        "mode": mode,
        "network": network,
        "backend": "seatbelt",
        "enforcement": "confined",
        "outcome": "exited",
    }
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:sandbox-receipt:{action_seq}:{tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate=predicate,
        required_evidence_class="native_sandbox_receipt",
    )
    admitted = binding.admit("read-only sandbox command contract satisfied by Kernel receipt")
    return replace(
        state,
        goal=replace(
            goal,
            admitted_criteria=(*goal.admitted_criteria, admitted),
        ),
        completion_claim=None,
    )


def admit_governed_tool_receipt_criterion(
    state: ConversationState,
    *,
    tool_call_id: str,
    tool_name: str,
    receipt_digest: str,
    action_seq: int,
) -> ConversationState:
    """把 Kernel 铸造的通用 effect receipt 绑定到一个待完成工具 criterion。"""

    goal = state.goal
    if (
        goal is None
        or not tool_call_id
        or not tool_name.startswith(("mcp__", "subagent__"))
        or len(receipt_digest) != 64
        or any(character not in "0123456789abcdef" for character in receipt_digest)
    ):
        return state
    criterion_id = f"criterion:required-governed-tool:{goal.goal_id}:{goal.revision}:{tool_call_id}"
    requirement = next(
        (
            item
            for item in goal.proposed_criteria
            if item.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
            and item.criterion_id == criterion_id
        ),
        None,
    )
    if requirement is None:
        return state
    source = next(
        (
            fact
            for fact in state.facts
            if fact.fact_id in goal.created_from_fact_ids and fact.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        return state
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    binding = CriterionAdmissionBinding.create(
        binding_id=f"criterion-admission:governed-tool:{action_seq}:{tool_call_id}",
        goal_id=goal.goal_id,
        goal_revision=goal.revision,
        workspace_identity_digest=goal.workspace_identity_digest,
        criterion_id=criterion_id,
        user_outcome_fact_id=source.fact_id,
        user_outcome_digest=source_digest,
        oracle_kind=EvidenceOracleKind.TOOL_RECEIPT,
        predicate={"receipt_digest": receipt_digest},
        required_evidence_class="governed_tool_receipt",
    )
    admitted = binding.admit(f"{tool_name} completed with the exact Kernel-governed result receipt")
    return replace(
        state,
        goal=replace(goal, admitted_criteria=(*goal.admitted_criteria, admitted)),
        completion_claim=None,
    )


def admit_web_source_criterion(
    state: ConversationState,
    *,
    tool_call_id: str,
    action_seq: int,
) -> ConversationState:
    """把当前 Goal 的真实 Web source receipt 铸成 mandatory completion 证据。"""

    goal = state.goal
    if goal is None:
        return state
    requirements = tuple(
        item
        for item in goal.proposed_criteria
        if item.oracle_kind is EvidenceOracleKind.WEB_SOURCE_RECEIPT
    )
    if not requirements:
        return state
    fact = next(
        (
            item
            for item in reversed(state.facts)
            if item.kind is FactKind.TOOL_RESULT
            and item.content.get("tool_call_id") == tool_call_id
            and item.content.get("executed") is True
            and item.content.get("is_error") is False
        ),
        None,
    )
    metadata = fact.content.get("metadata") if fact is not None else None
    if (
        fact is None
        or not isinstance(metadata, dict)
        or metadata.get("fake")
        or metadata.get("mock")
    ):
        return state
    raw_receipts = metadata.get("source_receipts")
    if not isinstance(raw_receipts, list):
        return state
    receipts: list[SourceReceiptV1] = []
    for raw in raw_receipts:
        try:
            receipt = SourceReceiptV1.from_json(raw)
        except ValueError:
            continue
        if (
            receipt.conversation_id == state.conversation_id
            and receipt.goal_id == goal.goal_id
            and receipt.goal_revision == goal.revision
            and receipt.source_kind
            in {SourceKind.WEB_SEARCH_SNIPPET, SourceKind.WEB_EXTRACTED_CONTENT}
        ):
            receipts.append(receipt)
    if not receipts:
        return state
    source = next(
        (
            item
            for item in state.facts
            if item.fact_id in goal.created_from_fact_ids and item.kind is FactKind.USER_MESSAGE
        ),
        None,
    )
    if source is None:
        return state
    source_digest = canonical_json_digest(
        {"fact_id": source.fact_id, "kind": source.kind, "content": source.content}
    )
    receipt = receipts[0]
    retained = tuple(
        item
        for item in goal.admitted_criteria
        if item.criterion_id not in {requirement.criterion_id for requirement in requirements}
    )
    admitted = []
    for requirement in requirements:
        predicate = {
            "receipt_digest": receipt.receipt_digest,
            "source_kind": receipt.source_kind.value,
        }
        binding = CriterionAdmissionBinding.create(
            binding_id=(
                f"criterion-admission:web-source:{action_seq}:{tool_call_id}:"
                f"{requirement.criterion_id}"
            ),
            goal_id=goal.goal_id,
            goal_revision=goal.revision,
            workspace_identity_digest=goal.workspace_identity_digest,
            criterion_id=requirement.criterion_id,
            user_outcome_fact_id=source.fact_id,
            user_outcome_digest=source_digest,
            oracle_kind=EvidenceOracleKind.WEB_SOURCE_RECEIPT,
            predicate=predicate,
            required_evidence_class="public_web_source",
        )
        admitted.append(binding.admit(requirement.description))
    return replace(
        state,
        goal=replace(goal, admitted_criteria=(*retained, *admitted)),
        completion_claim=None,
    )


def _close_orphaned_tool_batches(
    state: ConversationState,
    *,
    action_seq: int,
    live_call_ids: frozenset[str],
) -> ConversationState | None:
    """为**可核实**的旧孤儿 tool 批次补记 durable 非执行结果；不可证则拒绝。

    V1 修复轮曾在此处无条件为任何缺结果的批次补 ``executed=False``。R1 审计
    证明该推断没有依据：缺 active_run、缺 result、``last_safe_result`` 或旧
    ``superseded`` 文案都不能证明某个 call 未执行（效果可能已发生而结果保存
    失败）。自愈据此收窄为唯一可核实的旧形状：同批**完整连续 prefix**、
    最后一个结果具有严格审批拒绝语义（``rejected is True``、``executed is
    False``、``is_error is True`` 且无 UNKNOWN 矛盾），缺失项全部位于其后——
    该形状下批次在拒绝处停止，suffix 必未开始。其余形状（含矛盾标记、UNKNOWN、
    缺字段或伪 bool 的损坏历史）保留原 facts/checkpoint，由 accept_action 以
    动作冲突拒绝，不发 provider/tool、不伪造非执行。

    新代码的安全停机（pause/cancel/decline/end/complete/CancelRun/控制纠正）
    已在丢 run 的同一 CAS 内闭合各自确定的 suffix，不再依赖本函数。

    归属按 call_id 所有权判定（批次是原子单位）：live run 拥有的批次仍会由
    审批/执行或 correction 分支补齐结果，绝不代答；畸形结构保持 parser 的
    fail-closed 判定，不做部分愈合。返回 ``None`` 表示存在不可证孤儿。
    """

    facts = state.facts
    total = len(facts)
    reserved_ids = {fact.fact_id for fact in facts}
    insertions: dict[int, tuple[ConversationFact, ...]] = {}
    index = 0
    while index < total:
        fact = facts[index]
        if fact.kind is not FactKind.TOOL_CALLS:
            index += 1
            continue
        raw_calls = fact.content.get("calls")
        expected: list[str] = []
        malformed = not isinstance(raw_calls, list) or not raw_calls
        if not malformed:
            for raw_call in raw_calls:
                call_id = raw_call.get("tool_call_id") if isinstance(raw_call, dict) else None
                if not isinstance(call_id, str) or not call_id or call_id in expected:
                    malformed = True
                    break
                expected.append(call_id)
        if malformed or any(call_id in live_call_ids for call_id in expected):
            index += 1
            continue
        covered: list[str] = []
        covered_ids: set[str] = set()
        last_result: ConversationFact | None = None
        cursor = index + 1
        while cursor < total and facts[cursor].kind is FactKind.TOOL_RESULT:
            result_call_id = facts[cursor].content.get("tool_call_id")
            if (
                not isinstance(result_call_id, str)
                or result_call_id not in expected
                or result_call_id in covered_ids
            ):
                break
            covered_ids.add(result_call_id)
            covered.append(result_call_id)
            last_result = facts[cursor]
            cursor += 1
        missing = tuple(call_id for call_id in expected if call_id not in covered_ids)
        if not missing:
            index = cursor
            continue
        # 结果段被畸形结果（重复/乱序/异批 call_id）截断时，前缀无法核实：
        # 保持未确定，不做部分愈合（parser 对畸形结构仍是 fail closed）。
        if cursor < total and facts[cursor].kind is FactKind.TOOL_RESULT:
            return None
        # 唯一可核实的旧形状：covered 恰为 expected 的完整连续前缀（按序、
        # 无缺位），且最后一个结果具有严格审批拒绝语义——``rejected is True``、
        # ``executed is False``、``is_error is True`` 三个身份级标记同时成立且
        # 无 UNKNOWN 矛盾。仅 ``rejected is True`` 不够：矛盾标记、UNKNOWN、
        # 缺字段或 0/1 伪 bool 都是合成损坏历史，不能证明 suffix 未开始执行。
        # 缺 prefix、乱序、重复或末结果非严格拒绝时同样保持未确定。
        strict_rejection = (
            last_result is not None
            and last_result.content.get("rejected") is True
            and last_result.content.get("executed") is False
            and last_result.content.get("is_error") is True
            and not last_result.content.get("unknown_outcome")
        )
        prefix_is_exact = (
            bool(covered)
            and len(covered) <= len(expected)
            and covered == expected[: len(covered)]
            and strict_rejection
        )
        if not prefix_is_exact:
            return None
        invocation_origin = fact.content.get("invocation_origin")
        healed: list[ConversationFact] = []
        for call_id in missing:
            fact_id = f"action:{action_seq}:superseded-tool:{call_id}"
            if fact_id in reserved_ids:
                # 跨批次 call_id 撞名（供应商异常形状）：用批次 revision
                # 后缀确定性去重，不引入随机性，也不静默丢结果。
                suffix = fact.fact_id.rsplit(":", 1)[-1]
                fact_id = f"{fact_id}:{suffix}"
            reserved_ids.add(fact_id)
            healed.append(
                ConversationFact(
                    fact_id=fact_id,
                    kind=FactKind.TOOL_RESULT,
                    content={
                        "tool_call_id": call_id,
                        "text": (
                            "Tool call was not executed; its run was superseded "
                            "before a result was recorded."
                        ),
                        "is_error": True,
                        "executed": False,
                        "superseded": True,
                        **(
                            {"invocation_origin": invocation_origin}
                            if invocation_origin == InvocationOrigin.OPERATOR.value
                            else {}
                        ),
                    },
                )
            )
        insertions[cursor] = tuple(healed)
        index = cursor
    if not insertions:
        return state
    merged: list[ConversationFact] = []
    for position, fact in enumerate(facts):
        merged.extend(insertions.get(position, ()))
        merged.append(fact)
    # 批次位于 facts 末尾（EOF）时插入点等于 total，循环到不了该位置。
    merged.extend(insertions.get(total, ()))
    return replace(state, facts=tuple(merged))


def accept_action(
    state: ConversationState | None,
    action: Action,
    *,
    max_replay_records: int = 64,
    now: str | None = None,
) -> ActionTransition:
    if state is None:
        state = ConversationState.new(action.conversation_id)
    if action.conversation_id != state.conversation_id:
        return _conflict(state, "conversation_mismatch")
    if action.action_seq < 1:
        return _conflict(state, "invalid_action_sequence")

    digest = canonical_action_digest(action)
    replay = _find_replay(state, action.action_seq)
    if replay is not None:
        if replay.action_digest != digest:
            return _conflict(state, "action_digest_mismatch")
        if replay.result is None:
            return _conflict(state, "action_in_progress")
        return ActionTransition(
            ActionDisposition.REPLAYED,
            state,
            recorded_result=replay.result,
        )
    if action.action_seq < state.replay_floor:
        return _conflict(state, "action_sequence_expired")
    if action.action_seq < state.next_action_seq:
        return _conflict(state, "action_result_unavailable")
    if action.action_seq > state.next_action_seq:
        return _conflict(state, "action_sequence_gap")
    if action.expected_revision != state.revision:
        return _conflict(state, "revision_mismatch")

    legal, reason = _action_is_legal(state, action)
    if not legal:
        return _conflict(state, reason or "illegal_action_for_state")

    # 丢 run 的转换把未完结批次变成孤儿；接受任何新动作前先补记可核实前缀的
    # 非执行结果，否则后续 MODEL 相 compaction 规划在批次覆盖校验上永久
    # fatal（自愈磁盘上已损坏的 checkpoint）。live run 拥有的批次可能仍由
    # 审批/执行或 correction 分支补齐，绝不代答。不可证实的旧孤儿返回 None：
    # 其调用结果无法证明，不能自动继续或伪造非执行，保持原状态并拒绝动作。
    live = state.active_run
    healed_state = _close_orphaned_tool_batches(
        state,
        action_seq=action.action_seq,
        live_call_ids=(
            frozenset(call.tool_call_id for call in live.tool_calls)
            if live is not None
            else frozenset()
        ),
    )
    if healed_state is None:
        return _conflict(state, "unprovable_tool_batch_outcome")
    state = healed_state

    with_replay = _append_replay_record(
        state,
        action_seq=action.action_seq,
        action_digest=digest,
        max_replay_records=max_replay_records,
    )
    if with_replay is None:
        return _conflict(state, "replay_capacity_exhausted")
    applied = _apply_action(with_replay, action, now=now)
    applied = replace(
        applied,
        revision=state.revision + 1,
    )
    return ActionTransition(ActionDisposition.ACCEPTED, applied)


def finalize_action(
    state: ConversationState,
    *,
    action_seq: int,
    result: RecordedRunResult,
    max_replay_records: int = 64,
) -> ConversationState:
    if max_replay_records < 1:
        raise ValueError("max_replay_records must be positive")
    records = list(state.replay_records)
    index = next((i for i, record in enumerate(records) if record.action_seq == action_seq), None)
    if index is None:
        raise ValueError("action replay record not found")
    if records[index].result is not None:
        if records[index].result == result:
            return state
        raise ValueError("action already finalized with a different result")
    records[index] = replace(records[index], result=result)
    replay_floor = state.replay_floor
    while len(records) > max_replay_records:
        evicted = records.pop(0)
        if evicted.result is None:
            raise ValueError("cannot evict an unfinished replay record")
        replay_floor = max(replay_floor, evicted.action_seq + 1)
    return replace(
        state,
        revision=state.revision + 1,
        replay_floor=replay_floor,
        replay_records=tuple(records),
        last_safe_result=result,
    )


def _provider_continuation_payload(
    continuation: ProviderContinuationV1 | None,
) -> dict[str, str] | None:
    if continuation is None:
        return None
    return {
        "provider_identity_digest": continuation.provider_identity_digest,
        "opaque_payload": continuation.opaque_payload,
        "opaque_payload_digest": continuation.opaque_payload_digest,
    }


def complete_run(
    state: ConversationState,
    *,
    message: str | None = None,
    provider_continuation: ProviderContinuationV1 | None = None,
) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    # R1 窄不变量：UNKNOWN 只能经 recovery 分类收尾；正常完成不得抹去它。
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over run completion")
    closed_suffix = _unstarted_batch_suffix_facts(
        state,
        text=("Tool call was not executed because the run completed before this call started."),
    )
    facts = (*state.facts, *closed_suffix)
    if message is not None:
        content = {"text": message}
        continuation_payload = _provider_continuation_payload(provider_continuation)
        if continuation_payload is not None:
            content["provider_continuation"] = continuation_payload
        facts = (
            *facts,
            ConversationFact(
                fact_id=f"run:{active.run_id}:assistant:{state.revision + 1}",
                kind=FactKind.ASSISTANT_MESSAGE,
                content=content,
            ),
        )
    return replace(
        state,
        revision=state.revision + 1,
        facts=facts,
        active_run=None,
        interaction_state=(
            InteractionState.IDLE
            if state.interaction_state is InteractionState.ANSWERING
            else state.interaction_state
        ),
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED,
            run_id=active.run_id,
            message=message,
        ),
    )


def claim_run(state: ConversationState, invocation_id: str) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if active.owner_invocation_id is not None:
        raise ValueError("run is already owned")
    if not invocation_id:
        raise ValueError("invocation_id must not be empty")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(active, owner_invocation_id=invocation_id),
    )


def begin_provider_call(
    state: ConversationState,
    intent: ProviderCallIntentV1,
    *,
    input_tokens: int,
) -> ConversationState:
    active = state.active_run
    binding = state.background_occurrence_binding
    if (
        active is None
        or binding is None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.MODEL
        or active.owner_invocation_id is None
        or intent.occurrence_binding_digest != binding.binding_digest
        or intent.provider_call_index != active.model_calls_used + 1
        or not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or input_tokens < 0
    ):
        raise ValueError("background provider intent does not bind the active run")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.MODEL_EXECUTING,
            provider_call_intent=intent,
            persisted_model_response=None,
            model_calls_used=intent.provider_call_index,
            input_tokens_used=active.input_tokens_used + input_tokens,
        ),
    )


def record_foreground_model_attempt(
    state: ConversationState,
    *,
    input_tokens: int,
) -> ConversationState:
    """发送前持久化前台 run 的累计模型调用；Resume 不重置该预算。"""

    active = state.active_run
    if (
        active is None
        or state.background_occurrence_binding is not None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.MODEL
        or active.owner_invocation_id is None
        or not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or input_tokens < 0
    ):
        raise ValueError("foreground model attempt requires an owned runnable model phase")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            model_calls_used=active.model_calls_used + 1,
            input_tokens_used=active.input_tokens_used + input_tokens,
        ),
    )


def record_provider_response(
    state: ConversationState,
    response: PersistedModelResponseV1,
) -> ConversationState:
    active = state.active_run
    intent = active.provider_call_intent if active is not None else None
    if (
        active is None
        or active.status is not ActiveRunStatus.MODEL_EXECUTING
        or intent is None
        or active.persisted_model_response is not None
        or response.request_digest != intent.request_digest
    ):
        raise ValueError("persisted response does not bind the active provider call")
    return replace(
        state,
        revision=state.revision + 1,
        # normalized response 先 durable，再由 loop 执行任何 control/tool reduction。
        # output usage 同 response 一起入账，restart 不会重新计费或漏计。
        active_run=replace(
            active,
            persisted_model_response=response,
            output_tokens_used=(
                active.output_tokens_used + response.response.bounded_output_tokens
            ),
        ),
    )


def consume_provider_response(state: ConversationState) -> ConversationState:
    """仅构造待 CAS 的逻辑状态；调用者须与首个 response reduction 原子保存。"""

    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.MODEL_EXECUTING
        or active.persisted_model_response is None
    ):
        raise ValueError("durable provider response required")
    return replace(
        state,
        active_run=replace(
            active,
            status=ActiveRunStatus.RUNNABLE,
            provider_call_intent=None,
            persisted_model_response=None,
        ),
    )


def reclaim_background_run(state: ConversationState, invocation_id: str) -> ConversationState:
    active = state.active_run
    if active is None or state.background_occurrence_binding is None:
        raise ValueError("background active run required")
    # TOOL cursor 是 Runtime 已持久化的安全续跑点；EXECUTING 的未知副作用仍由
    # recovery 接管，未落盘 response 的 provider intent 也绝不在这里重发。
    runnable_continuation = active.status is ActiveRunStatus.RUNNABLE and active.phase in {
        ContinuationPhase.MODEL,
        ContinuationPhase.TOOL,
    }
    persisted_provider_response = (
        active.status is ActiveRunStatus.MODEL_EXECUTING
        and active.phase is ContinuationPhase.MODEL
        and active.persisted_model_response is not None
    )
    if not (runnable_continuation or persisted_provider_response):
        raise ValueError("background run is not safely reclaimable")
    if not invocation_id:
        raise ValueError("invocation_id must not be empty")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(active, owner_invocation_id=invocation_id),
    )


def mark_model_outcome_unknown(state: ConversationState) -> ConversationState:
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.MODEL_EXECUTING
        or active.provider_call_intent is None
        or active.persisted_model_response is not None
    ):
        raise ValueError("unresolved provider call intent required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.MODEL_OUTCOME_UNKNOWN,
            owner_invocation_id=None,
        ),
    )


def start_operator_tool(
    state: ConversationState,
    action: ExecuteOperatorTool,
) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("operator tool requires an active run")
    call = ToolCall(action.action_id, action.tool_name, action.arguments)
    fact = ConversationFact(
        fact_id=f"run:{active.run_id}:operator-tool:{state.revision + 1}",
        kind=FactKind.TOOL_CALLS,
        content={
            "invocation_origin": InvocationOrigin.OPERATOR.value,
            "calls": [
                {
                    "tool_call_id": call.tool_call_id,
                    "name": call.name,
                    "arguments": {},
                    "arguments_redacted": True,
                }
            ],
        },
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, fact),
        active_run=replace(
            active,
            invocation_origin=InvocationOrigin.OPERATOR,
            phase=ContinuationPhase.TOOL,
            batch_cursor=0,
            tool_calls=(call,),
            approval_grant=None,
        ),
    )


def release_operator_tool(state: ConversationState) -> ConversationState:
    active = state.active_run
    if (
        active is None
        or active.invocation_origin is not InvocationOrigin.OPERATOR
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.MODEL
        or active.tool_calls
        or active.executing_intent is not None
    ):
        raise ValueError("completed operator tool invocation required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            invocation_origin=InvocationOrigin.MODEL,
            owner_invocation_id=None,
        ),
    )


def start_tool_batch(
    state: ConversationState,
    calls: tuple[ToolCall, ...],
    *,
    preamble: str | None = None,
    provider_continuation: ProviderContinuationV1 | None = None,
) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if active.phase is not ContinuationPhase.MODEL:
        raise ValueError("tool batch can only start from MODEL phase")
    if not calls:
        raise ValueError("tool batch must not be empty")
    call_ids = tuple(call.tool_call_id for call in calls)
    if len(set(call_ids)) != len(call_ids):
        raise ValueError("tool_call_id must be unique within a batch")
    serialized_calls = [
        {
            "tool_call_id": call.tool_call_id,
            "name": call.name,
            "arguments": call.arguments,
        }
        for call in calls
    ]
    content = {"calls": serialized_calls}
    if preamble:
        content["preamble"] = preamble
    continuation_payload = _provider_continuation_payload(provider_continuation)
    if continuation_payload is not None:
        content["provider_continuation"] = continuation_payload
    fact = ConversationFact(
        fact_id=f"run:{active.run_id}:tool-batch:{state.revision + 1}",
        kind=FactKind.TOOL_CALLS,
        content=content,
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, fact),
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL,
            batch_cursor=0,
            tool_calls=calls,
            approval_grant=None,
        ),
    )


def append_policy_result(state: ConversationState, *, code: str, message: str) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    fact = ConversationFact(
        fact_id=f"run:{active.run_id}:policy:{state.revision + 1}",
        kind=FactKind.POLICY_RESULT,
        content={"code": code, "text": message},
    )
    return replace(state, revision=state.revision + 1, facts=(*state.facts, fact))


def pause_for_limit(state: ConversationState) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.PAUSED_LIMIT,
            owner_invocation_id=None,
        ),
    )


def pause_for_retryable(state: ConversationState) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.PAUSED_RETRYABLE,
            owner_invocation_id=None,
        ),
    )


def fail_run(state: ConversationState, *, code: str, message: str) -> ConversationState:
    return end_run(
        state,
        status=RunStatus.FAILED_FATAL,
        code=code,
        message=message,
    )


def end_run(
    state: ConversationState,
    *,
    status: RunStatus,
    code: str,
    message: str,
) -> ConversationState:
    active = state.active_run
    if active is None:
        raise ValueError("active run required")
    # R1 窄不变量：未知 effect 只能经 recovery 分类收尾，普通终态不得抹去它。
    if _has_unknown_effect(state):
        raise ValueError("unknown effect recovery has priority over run termination")
    closed_suffix = _unstarted_batch_suffix_facts(
        state,
        text=("Tool call was not executed because the run ended before this call started."),
    )
    result = RecordedRunResult(
        status=status,
        run_id=active.run_id,
        message=message,
        error_code=code,
    )
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, *closed_suffix),
        active_run=None,
        last_safe_result=result,
    )


def record_nonexecuted_tool_result(
    state: ConversationState,
    result: ConversationFact,
) -> ConversationState:
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.TOOL
        or result.kind is not FactKind.TOOL_RESULT
    ):
        raise ValueError("TOOL phase and Tool Result required")
    expected = active.tool_calls[active.batch_cursor] if active.tool_calls else None
    if expected is None or result.content.get("tool_call_id") != expected.tool_call_id:
        raise ValueError("tool result does not match the current batch cursor")
    next_cursor = active.batch_cursor + 1
    has_more = next_cursor < len(active.tool_calls)
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, result),
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
            approval_grant=None,
        ),
    )


def pause_for_approval(
    state: ConversationState,
    request: ApprovalRequest,
) -> ConversationState:
    active = state.active_run
    if active is None or active.status is not ActiveRunStatus.RUNNABLE:
        raise ValueError("RUNNABLE active run required")
    if request.run_id != active.run_id or active.pending_request is not None:
        raise ValueError("approval request does not match active run")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=request,
            owner_invocation_id=None,
        ),
    )


def mark_executing(
    state: ConversationState,
    *,
    tool_call_id: str,
    intent_digest: str,
    idempotency_key: str,
    side_effect: SideEffectClass,
    egress: EgressClass,
    operation: str,
    request_identity: str,
    execution_authority: ExecutionAuthorityClass,
    process_lease_id: str | None = None,
    sandbox_lease_id: str | None = None,
    browser_lease_id: str | None = None,
    goal_authorization_id: str | None = None,
    background_action_authority: BackgroundActionAuthorityV1 | None = None,
) -> ConversationState:
    if not isinstance(request_identity, str) or not request_identity:
        raise ValueError("executing intent request identity must be a non-empty string")
    active = state.active_run
    if (
        active is None
        or active.status is not ActiveRunStatus.RUNNABLE
        or active.phase is not ContinuationPhase.TOOL
        or active.executing_intent is not None
        or active.pending_request is not None
    ):
        raise ValueError("clean RUNNABLE active run required")
    current_call = active.tool_calls[active.batch_cursor]
    if current_call.tool_call_id != tool_call_id:
        raise ValueError("executing intent must bind the current tool call")
    background_binding = state.background_occurrence_binding
    if background_binding is None:
        if background_action_authority is not None:
            raise ValueError("ordinary run cannot consume background action authority")
    else:
        if active.tool_calls_used >= background_binding.tool_call_limit:
            raise ValueError("background tool-call budget is exhausted")
        class_counter: int | None = None
        class_limit: int | None = None
        expected_class: str | None = None
        if execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX:
            class_counter = active.sandbox_commands_used
            class_limit = background_binding.sandbox_command_limit
            expected_class = "sandbox_confined"
        elif execution_authority is ExecutionAuthorityClass.BROWSER_SESSION:
            class_counter = active.browser_actions_used
            class_limit = background_binding.browser_action_limit
            expected_class = "browser_public_observe"
        if class_counter is not None and class_counter >= class_limit:
            raise ValueError(f"background {expected_class} budget is exhausted")
        if background_action_authority is not None and (
            expected_class is None
            or class_counter is None
            or background_action_authority.occurrence_binding_digest
            != background_binding.binding_digest
            or background_action_authority.action_class != expected_class
            or background_action_authority.budget_ordinal != class_counter + 1
        ):
            raise ValueError("background action authority does not bind this transition")
    record = ExecutingIntentRecord(
        tool_call_id=tool_call_id,
        intent_digest=intent_digest,
        idempotency_key=idempotency_key,
        side_effect=side_effect,
        egress=egress,
        execution_authority=execution_authority,
        operation=operation,
        request_identity=request_identity,
    )
    if (
        execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS
        and process_lease_id is None
    ):
        # F1（P1 review finding 2026-08-16）：LOCAL_SAME_UID_PROCESS 的 EXECUTING
        # checkpoint 必须绑定 exact durable lease（lease use 单调消费的载体）；
        # 无 lease 不得进入 EXECUTING（裸 ApprovalGrant 不能绕过 lease 合同）。
        raise ValueError("process executing intent must consume an exact durable lease")
    process_leases = state.process_leases
    if process_lease_id is not None:
        # lease use 在 durable EXECUTING checkpoint 时单调消费；超过 max_uses 由
        # ProcessAuthorityLeaseV1.__post_init__ fail closed（R9 use exhaustion）。
        incremented: list[ProcessAuthorityLeaseV1] = []
        consumed = False
        for lease in process_leases:
            if lease.lease_id == process_lease_id and not consumed:
                incremented.append(replace(lease, uses_consumed=lease.uses_consumed + 1))
                consumed = True
            else:
                incremented.append(lease)
        if not consumed:
            raise ValueError("process lease use could not bind the executing intent")
        process_leases = tuple(incremented)
    if (
        execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
        and sandbox_lease_id is None
        and (
            background_action_authority is None
            or background_action_authority.action_class != "sandbox_confined"
        )
    ):
        raise ValueError("sandbox executing intent must consume an exact durable lease")
    sandbox_leases = state.sandbox_leases
    if sandbox_lease_id is not None:
        incremented_sandbox: list[SandboxAuthorityLeaseV1] = []
        consumed_sandbox = False
        for lease in sandbox_leases:
            if lease.lease_id == sandbox_lease_id and not consumed_sandbox:
                incremented_sandbox.append(lease.with_use_consumed(lease.uses_consumed + 1))
                consumed_sandbox = True
            else:
                incremented_sandbox.append(lease)
        if not consumed_sandbox:
            raise ValueError("sandbox lease use could not bind the executing intent")
        sandbox_leases = tuple(incremented_sandbox)
    browser_leases = state.browser_leases
    if browser_lease_id is not None:
        incremented_browser: list[BrowserAuthorityLeaseV1] = []
        consumed_browser = False
        for lease in browser_leases:
            if lease.lease_id == browser_lease_id and not consumed_browser:
                incremented_browser.append(lease.with_use_consumed(lease.uses_consumed + 1))
                consumed_browser = True
            else:
                incremented_browser.append(lease)
        if not consumed_browser:
            raise ValueError("browser lease use could not bind the executing intent")
        browser_leases = tuple(incremented_browser)
    goal_authorizations = state.goal_authorizations
    if goal_authorization_id is not None:
        incremented_authorizations: list[GoalAuthorizationBinding] = []
        consumed_authorization = False
        for binding in goal_authorizations:
            if binding.binding_id == goal_authorization_id and not consumed_authorization:
                incremented_authorizations.append(binding.with_use_consumed())
                consumed_authorization = True
            else:
                incremented_authorizations.append(binding)
        if not consumed_authorization:
            raise ValueError("goal authorization use could not bind the executing intent")
        goal_authorizations = tuple(incremented_authorizations)
    return replace(
        state,
        revision=state.revision + 1,
        goal_authorizations=goal_authorizations,
        process_leases=process_leases,
        sandbox_leases=sandbox_leases,
        browser_leases=browser_leases,
        active_run=replace(
            active,
            phase=ContinuationPhase.EXECUTING,
            executing_intent=record,
            approval_grant=None,
            tool_calls_used=(
                active.tool_calls_used + 1
                if background_binding is not None
                else active.tool_calls_used
            ),
            sandbox_commands_used=(
                active.sandbox_commands_used + 1
                if background_binding is not None
                and execution_authority is ExecutionAuthorityClass.ISOLATED_SANDBOX
                else active.sandbox_commands_used
            ),
            browser_actions_used=(
                active.browser_actions_used + 1
                if background_binding is not None
                and execution_authority is ExecutionAuthorityClass.BROWSER_SESSION
                else active.browser_actions_used
            ),
        ),
    )


def _validated_recorded_source_proof(
    *,
    state: ConversationState,
    result: ConversationFact,
    intent,
) -> tuple[ProviderFileSourceProofV1 | None, ConversationFact]:
    raw_proof = result.content.get("runtime_source_proof")
    if raw_proof is None:
        return None, result
    try:
        proof = ProviderFileSourceProofV1.from_dict(raw_proof)
    except (TypeError, ValueError) as error:
        raise ValueError("tool result contains an invalid source proof") from error
    text = result.content.get("text")
    active = state.active_run
    tool_call = (
        active.tool_calls[active.batch_cursor]
        if active is not None
        and 0 <= active.batch_cursor < len(active.tool_calls)
        else None
    )
    # workspace 校验：state 绑定是会话级真相；组合可能只在 Kernel 执行层
    # 携带 workspace 身份（ExecutingIntentRecord 不含该字段），此时信任
    # 铸造端（tools.py 已强制 intent.workspace_identity_digest 非空）。
    # 与 context.py `_valid_file_proof` 的 None-容忍语义保持一致。
    workspace_identity = (
        state.workspace_binding.workspace_identity_digest
        if state.workspace_binding is not None
        else None
    )
    goal = state.goal
    if (
        not isinstance(text, str)
        or result.content.get("is_error") is True
        or result.content.get("executed") is False
        or active is None
        or tool_call is None
        or proof.conversation_id != state.conversation_id
        or proof.run_id != active.run_id
        or proof.tool_call_id != intent.tool_call_id
        or proof.tool_name != tool_call.name
        or proof.operation != (intent.operation or tool_call.name)
        or proof.intent_digest != intent.intent_digest
        or proof.execution_authority != intent.execution_authority.value
        or proof.result_content_digest
        != hashlib.sha256(text.encode("utf-8")).hexdigest()
        or (
            workspace_identity is not None
            and proof.workspace_identity_digest != workspace_identity
        )
        or proof.goal_id != (goal.goal_id if goal is not None else None)
        or proof.goal_revision != (goal.revision if goal is not None else None)
    ):
        raise ValueError("tool result source proof does not bind the executing intent")
    content = dict(result.content)
    content.pop("runtime_source_proof", None)
    return proof, replace(result, content=content)


def record_tool_result(
    state: ConversationState,
    result: ConversationFact,
    *,
    intent_digest: str,
) -> ConversationState:
    active = state.active_run
    intent = active.executing_intent if active else None
    tool_call_id = result.content.get("tool_call_id")
    if (
        active is None
        or active.phase is not ContinuationPhase.EXECUTING
        or intent is None
        or intent.intent_digest != intent_digest
        or intent.tool_call_id != tool_call_id
        or result.kind is not FactKind.TOOL_RESULT
    ):
        raise ValueError("matching EXECUTING intent and Tool Result required")
    proof, recorded_result = _validated_recorded_source_proof(
        state=state,
        result=result,
        intent=intent,
    )
    next_cursor = active.batch_cursor + 1
    has_more = next_cursor < len(active.tool_calls)
    proofs = state.provider_source_proofs
    if proof is not None and all(
        existing.proof_id != proof.proof_id for existing in proofs
    ):
        proofs = (*proofs, proof)
    return replace(
        state,
        revision=state.revision + 1,
        facts=(*state.facts, recorded_result),
        provider_source_proofs=proofs,
        active_run=replace(
            active,
            phase=ContinuationPhase.TOOL if has_more else ContinuationPhase.MODEL,
            executing_intent=None,
            batch_cursor=next_cursor,
            tool_calls=active.tool_calls if has_more else (),
        ),
    )


def _context_summary_fact_id(summary: ConversationSummaryV1) -> str:
    """CONTEXT_SUMMARY fact 的 deterministic identity，只由两个 source digest 派生。

    不含任何模型文本：同一批被归档 facts 的 summary 无论措辞如何变化，
    identity 都指向同一条 replacement fact，方便 archive/CAS 幂等重放。
    """

    return (
        "fact:context-summary:"
        + canonical_json_digest(
            (
                summary.source_checkpoint_digest,
                summary.source_fact_ids_digest,
            )
        )[:16]
    )


def apply_compaction_summary(
    state: ConversationState,
    summary: ConversationSummaryV1,
    removable_fact_ids: tuple[str, ...],
    *,
    source_scope: ProviderConsentScopeV1 | None = None,
) -> ConversationState:
    """020 长会话压缩：把已归档的 summary 应用为唯一的 CONTEXT_SUMMARY fact。

    这是 summary reducer 的全部状态变化：由 ``validate_compaction_removal``
    判定的 selected facts（可非连续）被替换为恰好一个
    ``FactKind.CONTEXT_SUMMARY`` fact——summary 插在最早 selected fact 的
    原位置，每个 selected fact 被跳过，其余 facts 原序保留，revision 恰好
    +1；其余 canonical 字段（Goal/Evidence/Approval/Recovery/control/
    workspace/background/leases）原样携带，永不从 summary 重建。summary
    文本即使形似控制指令也只是 Frozen JSON content。digest 不绑定 state
    原顺序的 selected ids、非法移除或派生 fact_id 与任何 retained fact
    冲突时 fail closed，输入 state 不变。archive 与 CAS 由调用方先行
    在本函数返回后按序完成，本函数不负责。
    """

    removable = validate_compaction_removal(state, removable_fact_ids)
    expected_source_digest = canonical_json_digest([fact.fact_id for fact in removable])
    if summary.source_fact_ids_digest != expected_source_digest:
        raise ValueError("conversation summary does not bind the removable facts in state order")
    # removal 可非连续：用 selected id 集合遍历全量 facts，不能按前缀切片。
    selected_ids = frozenset(fact.fact_id for fact in removable)
    fact_id = _context_summary_fact_id(summary)
    if any(fact.fact_id == fact_id for fact in state.facts if fact.fact_id not in selected_ids):
        raise ValueError("context summary fact_id collides with retained facts")
    summary_fact = ConversationFact(
        fact_id=fact_id,
        kind=FactKind.CONTEXT_SUMMARY,
        content=summary.to_content(),
    )
    if source_scope is None:
        summary_classes = ("conversation_summary",)
        summary_sources = ()
        summary_routine = False
    else:
        summary_classes = tuple(
            sorted(
                {
                    "conversation_summary",
                    *source_scope.data_classes,
                }
            )
        )
        summary_sources = source_scope.sources
        summary_routine = source_scope.routine_compatible
    summary_boundary = ProviderSummarySourceBoundaryV1.create(
        summary_fact_id=fact_id,
        data_classes=summary_classes,
        sources=summary_sources,
        routine_compatible=summary_routine,
    )
    facts: list[ConversationFact] = []
    inserted = False
    for fact in state.facts:
        if fact.fact_id not in selected_ids:
            facts.append(fact)
        elif not inserted:
            # removable 非空由 validate 保证，因此 summary 必然被插入一次。
            facts.append(summary_fact)
            inserted = True
    return replace(
        state,
        revision=state.revision + 1,
        facts=tuple(facts),
        summary_source_boundaries=(
            *tuple(
                boundary
                for boundary in state.summary_source_boundaries
                if boundary.summary_fact_id not in selected_ids
            ),
            summary_boundary,
        ),
    )


def pause_for_recovery(
    state: ConversationState,
    request: RecoveryRequest,
) -> ConversationState:
    active = state.active_run
    intent = active.executing_intent if active else None
    if (
        active is None
        or intent is None
        or active.phase is not ContinuationPhase.EXECUTING
        or request.run_id != active.run_id
        or request.tool_call_id != intent.tool_call_id
        or request.binding_digest != intent.intent_digest
    ):
        raise ValueError("recovery request must bind the EXECUTING intent")
    return replace(
        state,
        revision=state.revision + 1,
        active_run=replace(
            active,
            status=ActiveRunStatus.AWAITING_RECOVERY,
            pending_request=request,
            owner_invocation_id=None,
        ),
    )
