# 基线证据与离线复现

绑定 `ff686bd14642e8ec5041cced6a21daf7c03f8d17`。以下探针只消费公开源码/测试与合成内存状态，不调用模型，不读凭据，不写产品代码。探针中的“断言旧缺陷存在”不是最终回归测试：实施者应改写为期望安全行为的 Red test。

## R1：已发生的效果被自愈成未执行

在仓库根运行：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from tests.kernel.test_effect_ordering import _runtime, _action
from tests.kernel.fakes import (
    InMemoryCheckpointStore, conversation_with_active_goal,
    ScriptedProvider, goal_noop_response,
)
from agent.runtime.checkpoint import CheckpointError
from agent.runtime.contracts import (
    ModelResponse, ModelToolCall, FactKind, Resume, SubmitMessage,
)
from agent.runtime.state import accept_action

class Store(InMemoryCheckpointStore):
    attempts = 0
    def compare_and_swap(self, snapshot, new_state):
        self.attempts += 1
        if self.attempts in (9, 10, 11):
            active = new_state.active_run
            print('FAILED_CAS', self.attempts, active.phase.value, active.status.value)
            raise CheckpointError('injected pre-commit write failure')
        return super().compare_and_swap(snapshot, new_state)

store = Store(conversation_with_active_goal())
effects = []
def effect(intent):
    active = store.load().state.active_run
    assert active.phase.value == 'executing'
    assert active.executing_intent.tool_call_id == 'call-1'
    effects.append('X')
    print('EFFECT_AFTER_DURABLE_EXECUTING', len(effects))
    return 'done'

provider = ScriptedProvider(
    goal_noop_response('supplement'),
    ModelResponse((ModelToolCall('call-1', 'write_fixture', {}),)),
)
result = _runtime(store, provider, effect).run_turn(_action(store.state), store.load())
state = store.load().state
print('RESULT', result.status.value, 'EFFECTS', len(effects), 'DURABLE_ACTIVE', state.active_run)
recovery = accept_action(state, Resume(
    conversation_id=state.conversation_id, action_seq=state.next_action_seq,
    expected_revision=state.revision,
))
print('RESUME', recovery.disposition.value, recovery.reason)
transition = accept_action(state, SubmitMessage(
    conversation_id=state.conversation_id, action_seq=state.next_action_seq,
    expected_revision=state.revision, run_id='next-run', message='continue',
))
print('NEXT', transition.disposition.value)
print('HEALED', [dict(f.content) for f in transition.state.facts if f.kind is FactKind.TOOL_RESULT])
PY
```

基线观察：效果计数 1；第9次 result 保存失败，第10/11次 recovery 保存失败；之后 fatal 保存成功且 `active_run=None`；Resume 非法；新 SubmitMessage 被接受并补 `executed=False`。

这是合法端口故障注入，不是已发生的真实磁盘损坏。真实 LocalCheckpointStore 允许写入在 replace 前失败、旧快照仍有效。新回归优先按 attempted state 的语义/阶段注入，不永久绑定第9/10/11次调用；断言 `EXECUTING` 先持久化，避免把“效果根本没执行”的路径测绿。

## R3：等义中文产生不同必做义务

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from agent.runtime.contracts import (
    ConversationFact, ConversationState, FactKind, GoalBootstrap,
    GoalDraftProposal, ProposedCriterion, EvidenceOracleKind,
)
from agent.runtime.state import accept_goal_draft_proposal

for text in ('修复功能，运行 pytest -q', '修复功能并运行 pytest -q',
             '不要运行测试，只修改 app.py'):
    user = ConversationFact('audit:user', FactKind.USER_MESSAGE, {'text': text})
    state = ConversationState(conversation_id='audit:offline', facts=(user,))
    bootstrap = GoalBootstrap(
        source_fact_id=user.fact_id,
        workspace_identity_digest='workspace:v1:' + 'c' * 64,
        authority_snapshot='authority:v1:' + 'd' * 64,
    )
    draft = GoalDraftProposal(
        correlation_id='audit:proposal', user_outcome=text, beneficiary='owner',
        targets=('app.py',), scope=('workspace',), non_goals=(), assumptions=(),
        proposed_criteria=(ProposedCriterion(
            criterion_id='criterion:app', description='功能修复并验证',
            oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
            artifact_path='app.py',
        ),), requires_local_process=True,
    )
    accepted = accept_goal_draft_proposal(
        state, draft, bootstrap, admitted_at='2026-10-13T00:00:00Z',
    )
    print(text, any(
        c.oracle_kind is EvidenceOracleKind.TOOL_RECEIPT
        for c in accepted.goal.proposed_criteria
    ))
PY
```

基线输出依次 `True / False / False`；修复后的前两项必须相同且为 True，禁止项仍 False。`requires_local_process=True` 是模型草案，不是执行授权；不能直接把该字段变成权限来源。

## R2：真实报告的失败，不预设成已证明的代码根因

公开证据：[旧 RESULTS 的 V1 真实层复跑](../2026-10-11-product-reliability-closure/RESULTS.md)（基线第411–418行）。

- 产品终态 `verified_done`，输出“Goal completion verified…”和“Task is closed”。
- 独立 D04 业务判据 `latest_correction=false`、`final_validation=false`：service 改了，CLI 旧别名没加。
- 这是业务失败证据，不证明它由 R3 文字匹配或 auto-readback 单独造成。先建确定性复现并区分原因。
- `resume_without_restatement`、`no_effect_replay` 是 grader 中按设计固定 false 的过程项；它们与上述两个业务失败字段分开，不能混用。
- 不读取旧 `.local` 现场来补推断。只使用公开 fixture、新的合成过程；真实新运行需要当前授权。

公开入口：`tests/acceptance/fixtures/d04_resume_correction/SPEC.md`、`scripts/materialize_coding_scenario.py`、`scripts/coding_scenario_grader.py::grade_d04`、`tests/acceptance/test_coding_autonomy_grader.py` 中 reference corrected behavior。

冻结输入（SHA-256）：

| 路径 | 摘要 |
| --- | --- |
| `scripts/coding_scenario_grader.py` | `a857d4cd748f152753a9c0ca1c8e08790aa77281f45db1ac8d630fe952a504db` |
| `tests/acceptance/fixtures/d04_resume_correction/SPEC.md` | `781ed941341a94acd3c9a39e51d221179cfbe652cbe63bc719eb77573c4e086c` |
| `docs/handoffs/2026-09-13-coding-autonomy-repair/TASK-MANIFEST.json` | `dc2bfec8c17ce578586412ddf44e63c95f52eb581155bf89ccfd66118a8bbd0e` |

新增 fixture 可以另建本次测试副本；不改原要求、grader 或历史 manifest 的授权值来获得 PASS。模型不得访问 workspace 外的 grader；实施者可读它理解验收。

## R4：默认提示与授权命令断开

- `agent/cli/app.py::_parse_action` 要求 `/approve-goal-target <exact-id>` 和 `/approve-goal-directory <exact-id>`。
- `agent/cli/render.py::render_pending` 明确不显示内部 request identity；正常提示仅 y/N。
- `yes` 映射一次 `ResolveApproval`，两个范围授权 flag 都是 False；CLI 内 `/status`、`/goal` 不是可补出 ID 的命令。
- 复用 `tests/cli/test_commands.py::test_approval_commands_require_the_exact_pending_id` 的合成请求，串联 renderer、无参数命令和 Runtime；不要用测试偷偷供应界面没有给用户的信息。
- `/approve-artifact` 帮助当前写 `<path> <sha256>`，实际 `parse_artifact_confirmation` 解析 `<sha256> <workspace-relative-path>`。

## 最终身份缺口（交付门，不是新修复项）

本次审计读取旧公开构建产物，确认最新记录 wheel SHA `2e70b7dc9ea35e0920ac67455248580853f6a7c98d943a735df37e7658daee39` 内：

- `agent/runtime/state.py` SHA `834bb972679a1e73f908b81aa2e9ac3e5a525c65926cd562ccfcb27d59e88fc3`，而 main 为 `9f3ce4553c3fb0b0e9978489031f2bcf14701c42335cff3656915a71fabde764`。
- `agent/runtime/loop.py` SHA `4f5928067dc326aa19b7f37d6422f36b36c7eb1ead5236dd9bce8f5f7f4ed5f7`，而 main 为 `e2f13f12d8d3e82729037b423fb48d689a02661256004423f8b6be18114184ab`。

所以旧 installed 13项不能覆盖最终合并修复。这里只要求新修复版本的增量 installed，不要求复跑历史全部 E3 或安装态全库。
