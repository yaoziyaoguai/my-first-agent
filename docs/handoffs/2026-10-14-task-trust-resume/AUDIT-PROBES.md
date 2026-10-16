# 本次独立审计：可重复的离线探针

身份：2026-10-14，base HEAD `ff686bd14642e8ec5041cced6a21daf7c03f8d17`，上一个执行者留下的未提交产品树；对应 `oracle-input/WORKING-TREE.patch`。本文件命令只用公开合成 fixture、内存 reducer/context；不调用模型、不读私人 checkpoint、不产生业务副作用。

以下输出是**审计发现**，不是修复后的 PASS。下一执行者应把安全期望变成正式回归，不照抄当前错误结果作为测试期望。

## A. 恢复前缀、claim身份与解码

从仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from dataclasses import asdict, replace
from agent.provider.normalize import _decode_reserved_control
from agent.runtime.checkpoint import _completion_claim_from_dict, _completion_claim_to_dict
from agent.runtime.contracts import ConversationFact, ConversationState, FactKind, SubmitMessage
from agent.runtime.evidence import ClosedEvidenceRegistry
from agent.runtime.state import accept_action, record_completion_claim, record_evidence, verify_goal_completion
from tests.continuity.test_verified_done import _claim, _state

s = _state()
c = _claim()
records = ClosedEvidenceRegistry().derive(s, c, observed_at='2026-10-14T00:00:00Z')
s = record_evidence(s, records)
a = record_completion_claim(s, c)
changed = replace(c, requirement_coverage=(replace(c.requirement_coverage[0], requirement='every user requirement is satisfied'),))
b = record_completion_claim(s, changed)
print('DIFFERENT_COVERAGE_SAME_RECEIPT_DIGEST', a.control_receipts[-1].payload_digest == b.control_receipts[-1].payload_digest)
print('GENERIC_COVERAGE_ACCEPTED', verify_goal_completion(b).goal.status.value)

raw = _completion_claim_to_dict(c)
for bad in (None, False, 0, '', {}):
    try:
        loaded = _completion_claim_from_dict({**raw, 'requirement_coverage': bad})
        print('CHECKPOINT_ACCEPTS', repr(bad), 'as', len(loaded.requirement_coverage))
    except (ValueError, TypeError) as error:
        print('CHECKPOINT_REJECTS', repr(bad), type(error).__name__)

wire = json.loads(json.dumps({'kind': 'completion_claim', **asdict(c)}))
for extra in (False, True):
    payload = json.loads(json.dumps(wire))
    if extra:
        payload['requirement_coverage'][0]['unrecognized_extra'] = 'audit'
    try:
        result = _decode_reserved_control(payload)
        print('WIRE_ENTRY_EXTRA', extra, 'ACCEPTED', type(result).__name__)
    except Exception as error:
        print('WIRE_ENTRY_EXTRA', extra, 'REJECTED', type(error).__name__)

batch = ConversationFact(fact_id='batch', kind=FactKind.TOOL_CALLS, content={
    'calls': [{'tool_call_id': f'call-{n}', 'name': 'write_file', 'arguments': {}} for n in (1, 2)]
})
for flags in ({'executed': False, 'is_error': True}, {'executed': True, 'is_error': False}, {'executed': False, 'is_error': True, 'unknown_outcome': True}):
    fact = ConversationFact(fact_id='result', kind=FactKind.TOOL_RESULT, content={
        'tool_call_id': 'call-1', 'text': 'audit fixture', 'rejected': True, **flags
    })
    old = ConversationState(conversation_id='audit', revision=10, next_action_seq=8, facts=(batch, fact))
    action = SubmitMessage(conversation_id='audit', action_seq=8, expected_revision=10, run_id='new', message='continue')
    transition = accept_action(old, action)
    print('REJECTION_PREFIX', json.dumps(flags), '->', transition.disposition.value,
          'fabricated_tail', sum(f.content.get('superseded') is True for f in transition.state.facts))
PY
```

本次实测：

```text
DIFFERENT_COVERAGE_SAME_RECEIPT_DIGEST True
GENERIC_COVERAGE_ACCEPTED verified_done
CHECKPOINT_ACCEPTS None as 0
CHECKPOINT_ACCEPTS False as 0
CHECKPOINT_ACCEPTS 0 as 0
CHECKPOINT_ACCEPTS '' as 0
CHECKPOINT_ACCEPTS {} as 0
WIRE_ENTRY_EXTRA False ACCEPTED CompletionClaim
WIRE_ENTRY_EXTRA True ACCEPTED CompletionClaim
REJECTION_PREFIX {"executed": false, "is_error": true} -> accepted fabricated_tail 1
REJECTION_PREFIX {"executed": true, "is_error": false} -> accepted fabricated_tail 1
REJECTION_PREFIX {"executed": false, "is_error": true, "unknown_outcome": true} -> accepted fabricated_tail 1
```

解释边界：

- healer对矛盾/UNKNOWN旧结果缺乏足够核验已被复现；探针是合成损坏历史，**不声称正常审批拒绝会生成这种形状，更不声称已证明远程攻击路径**。
- receipt未绑定新增coverage与两个解码入口不一致属于本次结构扩展的收口缺口。空coverage仍被完成门拒绝，不能把宽松解码夸大成直接获得完成权限。
- 泛化声明可通过仅证明结构校验不等于语义证明；这个探针没有真实D04业务工作区，**不能代替D04 admission→claim→外部grader反例**。
- wire须先JSON roundtrip；直接将Python dataclass的tuple当线上JSON发送会先因数组形状失败，不能拿那个失败证明未知键已被拒绝。

## B. 有需求ID，不等于有需求原文

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from dataclasses import replace
from agent.runtime.context import ContextLimits, KernelContextManager
from agent.runtime.contracts import ActiveRun, ConversationFact, FactKind, Resume
from tests.continuity.test_verified_done import _state

s = _state()
initial = replace(s.facts[0], content={'text': 'ORIGINAL_USER_REQUIREMENT_UNIQUE: fix service AND cli aliases. ' + 'long task detail ' * 1000})
latest = ConversationFact(fact_id='correction-current', kind=FactKind.USER_MESSAGE,
                          content={'text': 'Keep all previous requirements and continue.'})
s = replace(s, facts=(initial, *s.facts[1:], latest), active_run=ActiveRun('audit-context'),
            goal=replace(s.goal, created_from_fact_ids=(initial.fact_id, latest.fact_id)))
action = Resume(conversation_id=s.conversation_id, action_seq=s.next_action_seq, expected_revision=s.revision)
for budget in (4000, 6000):
    context = KernelContextManager(system_policy='policy', limits=ContextLimits(max_input_tokens=budget, output_reserve=200)).build(s, action, ())
    serialized = json.dumps([list(m.content) for m in context.messages])
    print('CONTEXT', budget, 'ORIGINAL_RAW_PRESENT', 'ORIGINAL_USER_REQUIREMENT_UNIQUE' in serialized,
          'ORIGINAL_ID_PRESENT', initial.fact_id in serialized,
          'CORRECTION_PRESENT', 'Keep all previous requirements' in serialized)
PY
```

本次实测：

```text
CONTEXT 4000 ORIGINAL_RAW_PRESENT False ORIGINAL_ID_PRESENT True CORRECTION_PRESENT True
CONTEXT 6000 ORIGINAL_RAW_PRESENT True ORIGINAL_ID_PRESENT True CORRECTION_PRESENT True
```

这是ContextPack选择/裁剪问题，不是说durable事实已经被删除。当前compaction对Goal来源有保护，但`_pin_groups`只固定最新用户消息等内容；durable保护与模型实际可见性要分别验证。修复须有界，不要求无条件把无限历史全部固定到每一轮，也不扩展模型上下文默认预算。
