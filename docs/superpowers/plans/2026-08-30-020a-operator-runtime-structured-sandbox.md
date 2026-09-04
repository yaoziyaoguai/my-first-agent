# 020a Operator Runtime and Structured Sandbox Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加第二个 loop、第二个 tool admission owner 或第二个 process executor 的前提下，为 operator-only governed tools、structured native sandbox session、strict packaged-Skill confinement 与 hermetic child runner 建立可执行基础。

**Architecture:** `ExecuteOperatorTool` 只把一个 synthetic `ToolCall` 注入已有 `ActiveRun`；durable `InvocationOrigin` 随 run checkpoint 跨 approval/restart/recovery 保存，`AgentRuntime.run_turn` 继续独占状态推进，`KernelToolRuntime` 继续独占 exposure admission、policy、approval 与 invoke。`NativeSandboxExecutor.execute(prepared, policy, io_plan=None)` 保持唯一 confinement/process owner；structured 分支只在同一次 invocation 周围建立固定 session、计算外层 digest、做 host readback。strict packaged policy 是现有 workspace allow-default policy 的 closed sibling，不修改其语义；standalone `first_agent_skill_runner` 只在 child 中加载 package script，并在加载前设置 hard rlimits。

**Tech Stack:** Python 3.11、stdlib `dataclasses/enum/hashlib/json/os/pathlib/resource/stat/tempfile`、现有 Runtime/ToolRuntime/Checkpoint、`agent.process` bounded runner、macOS `/usr/bin/sandbox-exec`、pytest、Ruff、setuptools materialized wheel。

**Spec:** `docs/superpowers/specs/2026-08-30-governed-executable-skills-and-artifacts-design.md` §3.1、§5.2、§8.1–§8.2、§12、§13.1。

## Global Constraints

- Scope 只到 020a。不得实现 manifest/package transport、package store、lifecycle mutation、active-set composition、artifact workspace commit 或 PDF/Office/image parser。
- 021 独占 `StoredPackageV1`、`QualificationRecordV1`、`ActiveSkillSetV1` 及 lifecycle gate/store/planner；020a 不定义同义 identity。
- 020b 独占 `build_packaged_skill_registrations(active_set, activation_gate, execution_adapter, *, max_tool_result_chars)` 与 `PackagedSkillExecutionAdapter`；020a 不注册 production executable Skills，不发现 active packages。
- `AgentRuntime.run_turn` 是唯一 production loop 和状态变更入口；operator action 不直接调用 `KernelToolRuntime`，CLI/UI adapter 不执行 tool。
- `KernelToolRuntime` 是唯一 callable admission/policy/approval/invoke owner；MODEL/OPERATOR 都必须走 `prepare → approval → EXECUTING checkpoint → invoke → result checkpoint`。
- `NativeSandboxExecutor` 是唯一 process/confinement owner；不得创建 packaged executor、shell runner、path+command executor、in-process package import、service locator、hot registry、fallback 或 dormant feature flag。
- 当前 `agent.process.preparation.PreparedProcessV1` 就是 frozen spec 中 prepared sandbox invocation 的现有 concrete type；020a 直接复用它，不增加只包一层的 `PreparedSandboxInvocationV1` class/alias。
- `ProcessCommandV1.command_fingerprint` 保持现有 exact executable/argv/cwd/profile/environment identity；随机 session path 只能进入 enforcement profile digest，不能进入 command fingerprint 或外层 authority digest。
- operator arguments 只允许进入 owner-only active checkpoint、`ExecutionIntent.arguments` 与 safety binding；不得进入 conversation/model context、event payload、approval preview自由文本或日志。preview 只能来自 tool binding 的 bounded redacted `effect_preview`。
- structured request/input/output bytes 只在 invoke 内存与 owner-only ephemeral session 中存在；不得进入 checkpoint/event/model context/sandbox receipt。draft 不是 receipt；receipt 仍由 `KernelToolRuntime` 验证后铸造。
- strict packaged profile 必须 `(deny default)`；无法证明 exact runtime/package/session/system allowlist、network denial、fork/exec denial或 hard rlimits时，返回 closed unavailable/known-not-executed。绝不回退到现有 allow-default workspace policy、system Python、user site、`PYTHONPATH`、shell 或 system tool。
- Generic structured I/O 的 product maxima 固定为：request `64 KiB`、inputs `<= 16`、单 input `<= 32 MiB`、全部 inputs `<= 64 MiB`、result `<= 64 MiB`、artifact `<= 64 MiB`、result + artifact `<= 64 MiB`；magic allowlist `<= 16` 项且每项 `<= 64` bytes。caller 只能进一步收窄，不能放宽。
- `runtime-closure-v1.json` 是 closure root 中唯一允许但不进入 file inventory 的 metadata；它的 canonical bytes digest 必须单独进入 closure digest。fresh verifier venv 只运行 verifier/installed product driver，绝不充当 `skill-runtime-v1` 或 ambient fallback。
- `first_agent_skill_runner` 的 request 保持八个 top-level keys，但 `entrypoint_script` 必须是 exact `{path,size,sha256}` descriptor。020b host 可以保留 `ExecutableScriptDescriptorV1(relative_path,size_bytes,sha256)` identity，但只能在唯一 request builder 显式映射 `path=relative_path` 与 `size=size_bytes`；020b Task 5 在开始前必须同步这一 nested shape、从 021 canonical inventory 提供 size/SHA-256，并删除 string/host-shape/union request，这不是 compatibility union。
- source tree 不读取 `.env`、secret、credential、private/runtime data 或未跟踪 `tui/`。测试只使用 synthetic non-sensitive fixtures。
- 每个行为/架构变化先 Red；每个 Task 完成 focused tests、touched Ruff、`git diff --check`。最终才运行 full suite、materialized gate 与真实 Seatbelt gate；timeout、截断、skip 或无 exit code不是 PASS。
- 本计划中的 commit 命令只在实现会话被明确允许 commit 时执行；未获授权时保留工作树并在执行记录中写明 `commit skipped: not authorized`。

## File Responsibility Map

- `agent/runtime/contracts.py`：closed exposure/origin/action contracts；durable run origin；intent origin。不得放 registry 或 lifecycle state。
- `agent/runtime/tools.py`：registration exposure admission、MODEL definitions filtering、origin revalidation、structured draft normalization与现有 sandbox receipt复用。
- `agent/runtime/state.py`：operator action legality、单 synthetic call reduction、operator terminal ownership release；不调用 tool。
- `agent/runtime/checkpoint.py`：checkpoint v9 origin migration；旧 v2–v8 active runs 恢复为 MODEL。
- `agent/runtime/context.py`：在 source projection/grouping 之前移除 OPERATOR-private facts。
- `agent/runtime/loop.py`：复用唯一 drive loop；构造 origin-aware context；operator call结束后不调用 provider。
- `agent/sandbox/contracts.py`：closed structured I/O/draft 与 strict packaged policy/resource contracts。
- `agent/sandbox/structured_session.py`：owner-only fixed session create/freeze/no-follow readback；不 spawn。
- `agent/sandbox/executor.py`：唯一 structured/unstructured execution orchestration、外层 digest、cleanup taxonomy。
- `agent/sandbox/packaged_policy.py`：strict `(deny default)` Seatbelt profile compiler与 canonical root admission。
- `agent/sandbox/seatbelt.py`：同一 confiner 对两个 closed policy types 做显式编译；无 fallback。
- `agent/sandbox/hermetic_runtime.py`：exact runtime closure inventory/digest、固定 child command preparation。
- `scripts/materialize_020a_test_runtime.py`：从显式、已 qualified 的 release runtime root 复制并复验 synthetic non-sensitive test closure；不从 verifier venv、ambient `sys.path` 或网络发现 runtime。
- `first_agent_skill_runner/`：standalone child protocol、preflight、hard rlimits、package script invocation；不 import `agent`。
- `pyproject.toml`：把 standalone runner package收入 wheel；不新增 dependency。
- `tests/kernel/*`、`tests/continuity/*`：origin/exposure/action/checkpoint/privacy/effect-ordering。
- `tests/sandbox/*`：structured contracts/session/readback/strict policy/runner/real Seatbelt probes。
- `tests/fixtures/020a_noop_skill/`：tracked synthetic no-op script；无 package manifest，不能被 production composition发现。
- `tests/reference/test_020a_operator_structured_sandbox.py`：真实 Runtime → approval → ToolRuntime → Seatbelt executor reference path。
- `scripts/verify_020a_materialized.py`：neutral-cwd wheel install与 real Seatbelt E2M gate；不扫描 ignored/private files。
- `scripts/run_020a_e3.py`：三次 fresh synthetic real-Seatbelt journey与 secret-free receipt。

---

### Task 1: Freeze exposure/origin contracts and enforce them in ToolRuntime

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/tools.py`
- Create: `tests/kernel/test_operator_tool_exposure.py`
- Modify: `tests/kernel/test_tool_runtime.py`

**Interfaces:**
- Produces `ToolExposure.MODEL|OPERATOR` and `InvocationOrigin.MODEL|OPERATOR`.
- Extends `RegisteredTool(spec, func, exposure=ToolExposure.MODEL)`; safe default preserves current registrations but every OPERATOR registration must opt in.
- Extends `ToolPrepareContext.invocation_origin` and `ExecutionIntent.invocation_origin`.
- Keeps public `KernelToolRuntime` surface at `definitions/prepare/invoke`; `definitions()` returns MODEL only.

- [ ] **Step 1: Write exposure/origin Reds**

Create `tests/kernel/test_operator_tool_exposure.py` with these complete tests and reuse `_spec` from `tests/kernel/test_tool_runtime.py` only by copying its small fixture, not by importing a test module:

```python
from __future__ import annotations

import pytest

from agent.runtime.contracts import (
    ApprovalPolicy,
    ExecutionAuthorityClass,
    ExecutionIntent,
    InvocationOrigin,
    OutputPolicy,
    SideEffectClass,
    ToolCall,
    ToolExposure,
    ToolPrepareContext,
    ToolRisk,
    ToolSpec,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime, RegisteredTool


def _spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        version="1",
        description="closed fixture",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        risk=ToolRisk.LOW,
        side_effect=SideEffectClass.READ_ONLY,
        output_policy=OutputPolicy.BOUNDED_TEXT,
        approval_policy=ApprovalPolicy.NEVER,
        safety_policy={"enabled": True},
        output_limit_chars=128,
        execution_authority=ExecutionAuthorityClass.IN_PROCESS,
    )


def _context(origin: InvocationOrigin) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-1",
        run_id="run-1",
        state_revision=7,
        invocation_origin=origin,
    )


def test_model_definitions_never_advertise_operator_registration() -> None:
    runtime = KernelToolRuntime(
        (
            RegisteredTool(_spec("visible"), lambda intent: "ok"),
            RegisteredTool(
                _spec("hidden"),
                lambda intent: "ok",
                exposure=ToolExposure.OPERATOR,
            ),
        )
    )
    assert [definition.name for definition in runtime.definitions()] == ["visible"]


def test_guessed_operator_name_is_rejected_before_callable() -> None:
    calls = 0

    def hidden(intent: ExecutionIntent) -> str:
        nonlocal calls
        calls += 1
        return "ran"

    runtime = KernelToolRuntime(
        (RegisteredTool(_spec("hidden"), hidden, exposure=ToolExposure.OPERATOR),)
    )
    result = runtime.prepare(ToolCall("call-1", "hidden", {}), _context(InvocationOrigin.MODEL))
    assert result.executed is False
    assert result.metadata["code"] == "tool_exposure_mismatch"
    assert calls == 0


def test_operator_origin_cannot_invoke_model_registration() -> None:
    runtime = KernelToolRuntime((RegisteredTool(_spec("visible"), lambda intent: "ran"),))
    result = runtime.prepare(
        ToolCall("call-1", "visible", {}),
        _context(InvocationOrigin.OPERATOR),
    )
    assert result.executed is False
    assert result.metadata["code"] == "tool_exposure_mismatch"


def test_invoke_rechecks_origin_against_registration() -> None:
    runtime = KernelToolRuntime(
        (
            RegisteredTool(
                _spec("hidden"),
                lambda intent: "ran",
                exposure=ToolExposure.OPERATOR,
            ),
        )
    )
    intent = runtime.prepare(
        ToolCall("call-1", "hidden", {}),
        _context(InvocationOrigin.OPERATOR),
    )
    assert isinstance(intent, ExecutionIntent)
    forged = object.__new__(ExecutionIntent)
    for field in intent.__dataclass_fields__:
        object.__setattr__(forged, field, getattr(intent, field))
    object.__setattr__(forged, "invocation_origin", InvocationOrigin.MODEL)
    with pytest.raises(IntentConflictError, match="exposure"):
        runtime.invoke(forged)
```

- [ ] **Step 2: Run the Reds**

Run: `.venv/bin/python -m pytest -q tests/kernel/test_operator_tool_exposure.py -rx`

Expected: collection fails because `ToolExposure` and `InvocationOrigin` do not exist.

- [ ] **Step 3: Add the minimal contracts and exact admission**

In `agent/runtime/contracts.py`, add the enums beside existing tool enums and add explicit typed fields:

```python
class ToolExposure(StrEnum):
    MODEL = "model"
    OPERATOR = "operator"


class InvocationOrigin(StrEnum):
    MODEL = "model"
    OPERATOR = "operator"
```

Add to `ToolPrepareContext` and validate:

```python
invocation_origin: InvocationOrigin = InvocationOrigin.MODEL

# in __post_init__
if not isinstance(self.invocation_origin, InvocationOrigin):
    raise TypeError("tool context invocation origin must be closed")
```

Add the required field to `ExecutionIntent` before defaulted fields, include it in `__post_init__`, `_intent_digest`, and `_make_intent`:

```python
invocation_origin: InvocationOrigin

if not isinstance(self.invocation_origin, InvocationOrigin):
    raise TypeError("execution intent invocation origin must be closed")
```

In `agent/runtime/tools.py`, extend registration and enforce exact equality before argument validation:

```python
@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    func: ToolCallable
    prepare_binding: BindingPreparer | None = None
    prepare_authority_binding: AuthorityBindingPreparer | None = None
    policy: ToolPolicy | None = None
    exposure: ToolExposure = ToolExposure.MODEL

    def __post_init__(self) -> None:
        if not isinstance(self.exposure, ToolExposure):
            raise TypeError("registered tool exposure must be closed")
```

```python
def definitions(self) -> tuple[ToolDefinition, ...]:
    return tuple(
        registration.spec.definition()
        for registration in self._tools.values()
        if registration.exposure is ToolExposure.MODEL
    )
```

```python
registration = self._tools.get(call.name)
if registration is None:
    return self._error(call.tool_call_id, "unknown_tool", "Unknown tool requested.")
expected_exposure = ToolExposure(context.invocation_origin.value)
if registration.exposure is not expected_exposure:
    return self._error(
        call.tool_call_id,
        "tool_exposure_mismatch",
        "Tool is not callable from this invocation origin.",
    )
```

At the start of `invoke`, before any lease check or binding revalidation:

```python
expected_exposure = ToolExposure(intent.invocation_origin.value)
if registration.exposure is not expected_exposure:
    raise IntentConflictError("tool exposure changed after preparation")
```

Include `"invocation_origin": intent.invocation_origin.value` in `_intent_digest`. When rebuilding `ToolPrepareContext` inside `invoke`, pass `invocation_origin=intent.invocation_origin`.

- [ ] **Step 4: Run focused Green and existing runtime regression**

Run:

```bash
.venv/bin/python -m pytest -q tests/kernel/test_operator_tool_exposure.py tests/kernel/test_tool_runtime.py tests/kernel/test_tool_registration_composition.py -rx
.venv/bin/ruff check agent/runtime/contracts.py agent/runtime/tools.py tests/kernel/test_operator_tool_exposure.py tests/kernel/test_tool_runtime.py
git diff --check
```

Expected: all commands exit 0; existing registrations remain MODEL-visible without call-site churn.

- [ ] **Step 5: Commit when authorized**

```bash
git add agent/runtime/contracts.py agent/runtime/tools.py tests/kernel/test_operator_tool_exposure.py tests/kernel/test_tool_runtime.py
git commit -m "feat(runtime): enforce operator tool exposure"
```

---

### Task 2: Route ExecuteOperatorTool through the existing run and preserve privacy

**Files:**
- Modify: `agent/runtime/contracts.py`
- Modify: `agent/runtime/state.py`
- Modify: `agent/runtime/checkpoint.py`
- Modify: `agent/runtime/context.py`
- Modify: `agent/runtime/loop.py`
- Create: `tests/kernel/test_operator_tool_action.py`
- Create: `tests/continuity/test_operator_tool_checkpoint.py`
- Create: `tests/continuity/test_operator_tool_context_privacy.py`
- Modify: `tests/kernel/test_effect_ordering.py`
- Modify: `tests/continuity/test_checkpoint_v2.py`
- Modify: `tests/continuity/test_checkpoint_v4.py`
- Modify: `tests/continuity/test_sandbox_checkpoint.py`

**Interfaces:**
- Produces closed `ExecuteOperatorTool(RuntimeAction)`.
- Persists `ActiveRun.invocation_origin`; v2–v8 decode as MODEL, v9 requires the field.
- Produces state reducers `start_operator_tool` and `release_operator_tool`.
- Does not add a new Runtime method; callers continue to call `AgentRuntime.run_turn(action, loaded_snapshot)` with the current mandatory `LoadedSnapshot`.

- [ ] **Step 1: Write action shape and legality Reds**

Create `tests/kernel/test_operator_tool_action.py`:

```python
from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActiveRun,
    ExecuteOperatorTool,
    InvocationOrigin,
)
from agent.runtime.state import accept_action
from tests.kernel.fakes import conversation_with_active_goal


def _action(state, **overrides):
    values = {
        "conversation_id": state.conversation_id,
        "action_seq": state.next_action_seq,
        "expected_revision": state.revision,
        "action_id": "operator-action-1",
        "tool_name": "skill_package_stage",
        "arguments": {"source": {"kind": "local", "path": "private/source.skillpkg"}},
        "submitted_at": "2026-08-30T12:00:00Z",
    }
    values.update(overrides)
    return ExecuteOperatorTool(**values)


def test_action_recursively_freezes_arguments() -> None:
    state = conversation_with_active_goal()
    action = _action(state)
    with pytest.raises(TypeError, match="frozen"):
        action.arguments["source"]["path"] = "changed"


@pytest.mark.parametrize("field,value", [
    ("action_id", ""),
    ("tool_name", "bad name"),
    ("submitted_at", "not-a-time"),
])
def test_action_rejects_open_string_shapes(field, value) -> None:
    state = conversation_with_active_goal()
    with pytest.raises(ValueError):
        _action(state, **{field: value})


def test_operator_action_requires_existing_idle_active_run_and_goal() -> None:
    state = conversation_with_active_goal()
    assert accept_action(state, _action(state)).reason == "operator_tool_requires_active_run"
    ready = replace(state, active_run=ActiveRun(run_id="run-existing"))
    transition = accept_action(ready, _action(ready))
    assert transition.reason is None
    assert transition.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert transition.state.active_run.tool_calls[0].tool_call_id == "operator-action-1"
```

Import `replace` from `dataclasses`; do not add a mutable `__dict__` path to product contracts.

- [ ] **Step 2: Run action Reds**

Run: `.venv/bin/python -m pytest -q tests/kernel/test_operator_tool_action.py -rx`

Expected: import failure for `ExecuteOperatorTool`; after adding only the action type, legality tests still fail.

- [ ] **Step 3: Implement the closed action and durable origin**

In `agent/runtime/contracts.py`, import `re`, add closed validators, and add the action before the `Action` alias:

```python
_OPERATOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RFC3339_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecuteOperatorTool(RuntimeAction):
    action_id: str
    tool_name: str
    arguments: dict[str, JSONValue]
    submitted_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or _OPERATOR_ID.fullmatch(self.action_id) is None:
            raise ValueError("operator action_id has an invalid closed shape")
        if not isinstance(self.tool_name, str) or _TOOL_NAME.fullmatch(self.tool_name) is None:
            raise ValueError("operator tool_name has an invalid closed shape")
        if not isinstance(self.submitted_at, str) or _RFC3339_Z.fullmatch(self.submitted_at) is None:
            raise ValueError("operator submitted_at must be zoned RFC3339")
        _assert_json_compatible(self.arguments, path="operator_tool.arguments")
        object.__setattr__(self, "arguments", _freeze_json_dict(self.arguments))
```

Add `ExecuteOperatorTool` to `Action`. Add to `ActiveRun`:

```python
invocation_origin: InvocationOrigin = InvocationOrigin.MODEL

if not isinstance(self.invocation_origin, InvocationOrigin):
    raise TypeError("active run invocation origin must be closed")
if self.invocation_origin is InvocationOrigin.OPERATOR and len(self.tool_calls) > 1:
    raise ValueError("operator invocation cannot contain more than one tool call")
```

An OPERATOR run has exactly one call while its phase is TOOL/EXECUTING and zero calls after the cursor advances to the terminal MODEL phase; the invariant above deliberately permits that zero-call terminal state.

In `agent/runtime/state.py`, import the new contracts. Add legality before the generic `active is None` branch:

```python
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
```

Add the reducer and call it at the top of `_apply_action`:

```python
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
            "calls": [{
                "tool_call_id": call.tool_call_id,
                "name": call.name,
                "arguments": {},
                "arguments_redacted": True,
            }],
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
```

```python
if isinstance(action, ExecuteOperatorTool):
    return start_operator_tool(state, action)
```

Rerun the Red fixture after the reducer exists.

- [ ] **Step 4: Add checkpoint v9 Reds and migration**

Create `tests/continuity/test_operator_tool_checkpoint.py`:

```python
def test_operator_origin_and_private_arguments_round_trip_owner_checkpoint(tmp_path):
    state = _operator_tool_state()
    store = LocalCheckpointStore.initialize(tmp_path / "checkpoint.json", state)
    restored = store.load()
    assert restored.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert restored.state.active_run.tool_calls[0].arguments["source"]["path"] == "private.skillpkg"
    assert restored.token.startswith("sha256:")


_BACKGROUND_ACTIVE_KEYS = {
    "provider_call_intent",
    "persisted_model_response",
    "model_calls_used",
    "tool_calls_used",
    "sandbox_commands_used",
    "browser_actions_used",
    "input_tokens_used",
    "output_tokens_used",
}


def _historical_active_document(source_version):
    expected = replace(
        ConversationState.new("conversation-historical"),
        active_run=ActiveRun(run_id="run-historical"),
    )
    document = json.loads(_encode_state(expected).decode("utf-8"))
    assert document["schema_version"] == 9
    document["schema_version"] = source_version
    active = document["state"]["active_run"]
    active.pop("invocation_origin")
    if source_version < 8:
        document["state"].pop("background_occurrence_binding")
        for key in _BACKGROUND_ACTIVE_KEYS:
            active.pop(key)
    if source_version < 7:
        document["state"].pop("browser_leases")
        document["state"].pop("browser_takeover_pending")
    if source_version < 6:
        document["state"].pop("sandbox_leases")
    if source_version < 4:
        document["state"].pop("process_leases")
    if source_version == 2:
        document["state"].pop("workspace_binding")
    return document, expected


@pytest.mark.parametrize("source_version", [2, 3, 4, 5, 6, 7, 8])
def test_v2_through_v8_active_run_migrate_to_model_without_losing_state(
    tmp_path,
    source_version,
):
    path = tmp_path / "checkpoint.json"
    document, expected = _historical_active_document(source_version)
    assert "invocation_origin" not in document["state"]["active_run"]
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    restored = LocalCheckpointStore(path).load()
    assert restored.state.active_run.invocation_origin is InvocationOrigin.MODEL
    assert restored.state == expected
```

Run: `.venv/bin/python -m pytest -q tests/continuity/test_operator_tool_checkpoint.py -rx`

Expected: v9 round-trip fails because checkpoint omits origin.

In `agent/runtime/checkpoint.py`, add `SCHEMA_VERSION = 9` and rename only the old current-version role to `BACKGROUND_SCHEMA_VERSION = 8`. Keep `LEGACY_SCHEMA_VERSION = 2`, `PROCESS_MIGRATION_VERSION = 3`, `PREVIOUS_SCHEMA_VERSION = 4`, `ARTIFACT_SCHEMA_VERSION = 5`, `PROCESS_SCHEMA_VERSION = 6`, `BROWSER_SCHEMA_VERSION = 7`, the new `BACKGROUND_SCHEMA_VERSION = 8`, and every corresponding decoder branch. The supported-version set becomes `{2,3,4,5,6,7,8,9}`; it must not collapse to `{8,9}`. Add `origin_contract_current: bool = False` to `_state_from_dict` and `_active_from_dict`, pass it through the existing `_state_from_dict → _active_from_dict` call, and set it only with `version == SCHEMA_VERSION` in `_decode_state`. Encode/decode exactly:

```python
# _active_to_dict
"invocation_origin": active.invocation_origin.value,

# _active_from_dict key set
if origin_contract_current:
    keys.add("invocation_origin")

# ActiveRun constructor
invocation_origin=(
    InvocationOrigin(_string(value["invocation_origin"], "active_run.invocation_origin"))
    if origin_contract_current
    else InvocationOrigin.MODEL
),
```

All former v8 decode feature predicates must use `version in {BACKGROUND_SCHEMA_VERSION, SCHEMA_VERSION}` rather than `version == SCHEMA_VERSION`; only origin strictness is v9-only. Current encoding still passes all existing v8-era fields when `version == SCHEMA_VERSION`. Rename `test_current_state_encodes_as_v8_and_round_trips` and `test_process_leases_alone_use_current_v8_schema` to their v9 equivalents; update current-writer assertions in `tests/continuity/test_checkpoint_v2.py`, `tests/continuity/test_checkpoint_v4.py` and `tests/continuity/test_sandbox_checkpoint.py` from `8` to `9`, change the unknown-version fixture and expectation from `9` to `10`, and keep their existing v2–v8 migration assertions byte-for-byte equivalent apart from the new MODEL origin default.

- [ ] **Step 5: Write privacy and single-loop effect-ordering Reds**

Create `tests/continuity/test_operator_tool_context_privacy.py` and add one full Runtime test to `tests/kernel/test_effect_ordering.py`:

```python
def test_operator_facts_never_project_arguments_or_result_to_model_context():
    private = "owner/private/source.skillpkg"
    state = completed_operator_state(private_argument=private, result_text="private result")
    pack = context_manager().build(state, resume_action(state), ())
    wire = repr(pack.messages)
    assert private not in wire
    assert "private result" not in wire
    assert "operator" not in wire


def test_operator_tool_uses_same_approval_executing_result_order():
    runtime, store, calls, events = operator_runtime_fixture(approval=ApprovalPolicy.ALWAYS)
    initial = store.load()
    first = runtime.run_turn(operator_action(initial.state), initial)
    assert first.status is RunStatus.AWAITING_APPROVAL
    assert calls == []
    pending = store.load()
    assert pending.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    second = runtime.run_turn(approve(first), pending)
    assert second.status is RunStatus.COMPLETED
    assert calls == ["operator-action-1"]
    assert store.saved_phases.index("executing") < store.saved_fact_kinds.index("tool_result")
    assert provider_fixture(runtime).calls == []
    assert "owner/private/source.skillpkg" not in repr(events)
```

Use the existing `RecordingCheckpointStore`, `ScriptedProvider`, `RecordingEventSink`, approval builder and `conversation_with_active_goal` fixtures from their owning test modules by moving any shared fixture smaller than 30 lines into `tests/kernel/fakes.py`; do not make product code test-aware.

Run:

```bash
.venv/bin/python -m pytest -q tests/continuity/test_operator_tool_context_privacy.py tests/kernel/test_effect_ordering.py -rx
```

Expected: private facts appear in context and Runtime attempts provider continuation.

- [ ] **Step 6: Complete loop integration without a second drive path**

In `agent/runtime/context.py`, filter before clipping/source projection:

```python
facts_for_projection = tuple(
    fact
    for fact in state.facts
    if fact.content.get("invocation_origin") != InvocationOrigin.OPERATOR.value
)
```

Apply the existing intent-decision filter to `facts_for_projection`, not `state.facts`. Also make `_runtime_progress_group` and every loop fact inventory skip facts whose `invocation_origin` is OPERATOR. Do not create a second ContextManager.

In `AgentRuntime._drive`, pass:

```python
invocation_origin=active.invocation_origin,
```

to `ToolPrepareContext`. At the top of the existing `while True`, after loading `active` and before provider work, finish a completed operator call:

```python
if (
    active.invocation_origin is InvocationOrigin.OPERATOR
    and active.status is ActiveRunStatus.RUNNABLE
    and active.phase is ContinuationPhase.MODEL
):
    released = release_operator_tool(current.state)
    return self._finish(
        current,
        action,
        status=RunStatus.COMPLETED,
        warnings=warnings,
        event_kind=RuntimeEventKind.COMPLETED,
        run_id=active.run_id,
        message="operator tool action completed",
        outcome_state=released,
    )
```

Guard duplicate/no-progress/provider-evidence logic with `active.invocation_origin is InvocationOrigin.MODEL`; operator non-executed/error results simply advance the existing cursor and reach the terminal branch. Preserve origin only for OPERATOR result facts, so existing MODEL wire blocks remain byte-compatible:

```python
content = {
    "tool_call_id": result.tool_call_id,
    "text": result.content,
    "is_error": result.is_error,
    "executed": result.executed,
    "metadata": result.metadata,
}
if active.invocation_origin is InvocationOrigin.OPERATOR:
    content["invocation_origin"] = InvocationOrigin.OPERATOR.value
```

Use the same conditional tag for state-created approval rejection, `ResolveUnknownToolOutcome`, `RecoverUnknownObservation` and correction-superseded `TOOL_RESULT` facts. Approval and recovery reducers must not reset origin. `ResolveApproval` and `ResolveUnknownToolOutcome` therefore resume the same OPERATOR run and terminate at the same branch. Add rejection/recovery cases to the privacy test and assert neither synthetic text nor private arguments reach a later `ContextPack`.

- [ ] **Step 7: Verify action/replay/restart/recovery Green**

Run:

```bash
.venv/bin/python -m pytest -q tests/kernel/test_operator_tool_action.py tests/kernel/test_operator_tool_exposure.py tests/kernel/test_effect_ordering.py tests/kernel/test_runtime_approval.py tests/kernel/test_runtime_recovery.py tests/continuity/test_operator_tool_checkpoint.py tests/continuity/test_operator_tool_context_privacy.py tests/continuity/test_checkpoint_v2.py tests/continuity/test_checkpoint_v4.py tests/continuity/test_sandbox_checkpoint.py -rx
.venv/bin/ruff check agent/runtime tests/kernel/test_operator_tool_action.py tests/kernel/test_operator_tool_exposure.py tests/continuity/test_operator_tool_checkpoint.py tests/continuity/test_operator_tool_context_privacy.py
git diff --check
```

Expected: all exit 0; assertions prove zero provider calls and one callable invocation across approval/restart.

- [ ] **Step 8: Commit when authorized**

```bash
git add agent/runtime tests/kernel/test_operator_tool_action.py tests/kernel/test_operator_tool_exposure.py tests/kernel/test_effect_ordering.py tests/continuity/test_operator_tool_checkpoint.py tests/continuity/test_operator_tool_context_privacy.py tests/continuity/test_checkpoint_v2.py tests/continuity/test_checkpoint_v4.py tests/continuity/test_sandbox_checkpoint.py
git commit -m "feat(runtime): route operator tools through run turn"
```

---

### Task 3: Add closed structured session contracts and no-follow readback

**Files:**
- Modify: `agent/sandbox/contracts.py`
- Create: `agent/sandbox/structured_session.py`
- Modify: `agent/sandbox/executor.py`
- Modify: `agent/runtime/tools.py`
- Create: `tests/sandbox/test_structured_contracts.py`
- Create: `tests/sandbox/test_structured_session.py`
- Create: `tests/sandbox/test_structured_executor.py`
- Modify: `tests/sandbox/test_executor.py`
- Modify: `tests/sandbox/test_tools.py`

**Interfaces:**
- Produces `StructuredResultKind`, `StructuredReadbackOutcome`, `StructuredSandboxInputV1`, `StructuredSandboxIoPlanV1`, `StructuredSandboxProcessDraftV1`.
- Extends only `NativeSandboxExecutor.execute(prepared, policy, io_plan=None)`.
- Produces pure `structured_invocation_digest(prepared, policy, io_plan)`.
- Keeps `KernelToolRuntime.invoke` as structured draft verifier/receipt minter.

- [ ] **Step 1: Write contract Reds**

Create `tests/sandbox/test_structured_contracts.py`:

```python
def test_outer_digest_excludes_random_session_and_binds_every_authority_input():
    plan = io_plan()
    first = structured_invocation_digest(prepared(), policy(), plan)
    assert first == structured_invocation_digest(prepared(), policy(), plan)
    changed_request = b"{}"
    request_changed = replace(
        plan,
        request_bytes=changed_request,
        request_digest=hashlib.sha256(changed_request).hexdigest(),
    )
    assert first != structured_invocation_digest(prepared(), policy(), request_changed)
    assert first != structured_invocation_digest(prepared(), policy(), replace(plan, entrypoint_digest="f" * 64))
    changed_magic = replace(
        plan,
        inputs=(replace(plan.inputs[0], allowed_magic_hex=("504b0304",)), *plan.inputs[1:]),
    )
    assert first != structured_invocation_digest(prepared(), policy(), changed_magic)


def test_io_plan_rejects_digest_drift_duplicate_slots_and_open_result_kind():
    with pytest.raises(ValueError, match="digest"):
        StructuredSandboxInputV1("source", b"pdf", "0" * 64)
    with pytest.raises(ValueError, match="unique"):
        replace(io_plan(), inputs=(input_one(), input_one()))
    with pytest.raises(ValueError):
        replace(io_plan(), expected_result_kind="future-kind")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: replace(plan, request_bytes=b"x" * (STRUCTURED_REQUEST_MAX_BYTES + 1), request_digest=hashlib.sha256(b"x" * (STRUCTURED_REQUEST_MAX_BYTES + 1)).hexdigest()),
        lambda plan: replace(plan, inputs=tuple(input_one(slot=f"slot_{index}") for index in range(STRUCTURED_INPUT_MAX_ITEMS + 1))),
        lambda plan: replace(plan, inputs=(input_one(content=b"x" * (STRUCTURED_INPUT_MAX_BYTES + 1)),)),
        lambda plan: replace(plan, result_cap_bytes=STRUCTURED_RESULT_MAX_BYTES + 1),
        lambda plan: replace(plan, artifact_cap_bytes=STRUCTURED_ARTIFACT_MAX_BYTES + 1),
        lambda plan: replace(plan, aggregate_output_cap_bytes=STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES + 1),
    ],
)
def test_io_plan_rejects_every_product_maximum_overrun(mutation):
    with pytest.raises(ValueError, match="maximum|aggregate"):
        mutation(io_plan())


def test_magic_allowlist_is_sorted_unique_and_bounded():
    item = input_one(allowed_magic_hex=("89504e47", "25504446", "89504e47"))
    assert item.allowed_magic_hex == ("25504446", "89504e47")
    with pytest.raises(ValueError, match="magic"):
        input_one(allowed_magic_hex=tuple(f"{index:02x}" for index in range(17)))


def test_process_command_fingerprint_is_unchanged_by_io_plan():
    invocation = prepared()
    before = invocation.command.command_fingerprint
    structured_invocation_digest(invocation, policy(), io_plan())
    assert invocation.command.command_fingerprint == before
```

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_structured_contracts.py -rx`

Expected: collection failure for missing structured contracts.

- [ ] **Step 2: Implement immutable contracts and outer digest**

Add these closed shapes to `agent/sandbox/contracts.py`; retain raw bytes only on the transient types:

```python
STRUCTURED_REQUEST_MAX_BYTES = 64 * 1024
STRUCTURED_INPUT_MAX_ITEMS = 16
STRUCTURED_INPUT_MAX_BYTES = 32 * 1024 * 1024
STRUCTURED_INPUT_AGGREGATE_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_RESULT_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_ARTIFACT_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES = 64 * 1024 * 1024
STRUCTURED_MAGIC_MAX_ITEMS = 16
STRUCTURED_MAGIC_MAX_BYTES = 64


class StructuredResultKind(StrEnum):
    OBSERVATION = "observation"
    ARTIFACT = "artifact"


class StructuredReadbackOutcome(StrEnum):
    VALID = "valid"
    NOT_READ = "not_read"
    RESULT_MISSING = "result_missing"
    RESULT_REPLACED = "result_replaced"
    RESULT_TOO_LARGE = "result_too_large"
    RESULT_MALFORMED = "result_malformed"
    ARTIFACT_REPLACED = "artifact_replaced"
    ARTIFACT_TOO_LARGE = "artifact_too_large"
    ARTIFACT_UNEXPECTED = "artifact_unexpected"
    ARTIFACT_MISSING = "artifact_missing"
    EXTRA_OUTPUT = "extra_output"


@dataclass(frozen=True, slots=True)
class StructuredSandboxInputV1:
    slot: str
    content: bytes
    content_digest: str
    allowed_magic_hex: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", self.slot) is None:
            raise ValueError("structured input slot has an invalid shape")
        if not isinstance(self.content, bytes):
            raise TypeError("structured input content must be bytes")
        if hashlib.sha256(self.content).hexdigest() != self.content_digest:
            raise ValueError("structured input digest mismatch")
        if not isinstance(self.allowed_magic_hex, tuple) or any(
            not isinstance(value, str) for value in self.allowed_magic_hex
        ):
            raise TypeError("structured input magic must be a tuple of strings")
        magic = tuple(sorted(set(self.allowed_magic_hex)))
        if len(magic) > STRUCTURED_MAGIC_MAX_ITEMS or any(
            re.fullmatch(r"(?:[0-9a-f]{2})+", value) is None
            or len(value) // 2 > STRUCTURED_MAGIC_MAX_BYTES
            for value in magic
        ):
            raise ValueError("structured input magic must be lowercase even-length hex")
        if len(self.content) > STRUCTURED_INPUT_MAX_BYTES:
            raise ValueError("structured input exceeds product maximum")
        object.__setattr__(self, "allowed_magic_hex", magic)


@dataclass(frozen=True, slots=True)
class StructuredSandboxIoPlanV1:
    package_digest: str
    entrypoint_id: str
    entrypoint_digest: str
    request_bytes: bytes
    request_digest: str
    inputs: tuple[StructuredSandboxInputV1, ...]
    result_cap_bytes: int
    artifact_cap_bytes: int
    aggregate_output_cap_bytes: int
    expected_result_kind: StructuredResultKind

    def __post_init__(self) -> None:
        _require_hex64(self.package_digest, "package_digest")
        _require_hex64(self.entrypoint_digest, "entrypoint_digest")
        if not self.entrypoint_id or len(self.entrypoint_id.encode("utf-8")) > 128:
            raise ValueError("entrypoint_id is invalid")
        if hashlib.sha256(self.request_bytes).hexdigest() != self.request_digest:
            raise ValueError("structured request digest mismatch")
        if len(self.request_bytes) > STRUCTURED_REQUEST_MAX_BYTES:
            raise ValueError("structured request exceeds product maximum")
        if not isinstance(self.inputs, tuple) or any(
            not isinstance(item, StructuredSandboxInputV1) for item in self.inputs
        ):
            raise TypeError("structured inputs must be a closed tuple")
        if len(self.inputs) > STRUCTURED_INPUT_MAX_ITEMS:
            raise ValueError("structured input count exceeds product maximum")
        if sum(len(item.content) for item in self.inputs) > STRUCTURED_INPUT_AGGREGATE_MAX_BYTES:
            raise ValueError("structured input aggregate exceeds product maximum")
        slots = tuple(item.slot for item in self.inputs)
        if len(set(slots)) != len(slots):
            raise ValueError("structured input slots must be unique")
        for name in ("result_cap_bytes", "artifact_cap_bytes", "aggregate_output_cap_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if self.result_cap_bytes + self.artifact_cap_bytes < self.aggregate_output_cap_bytes:
            raise ValueError("aggregate output cap exceeds per-file caps")
        if (
            self.result_cap_bytes > STRUCTURED_RESULT_MAX_BYTES
            or self.artifact_cap_bytes > STRUCTURED_ARTIFACT_MAX_BYTES
            or self.aggregate_output_cap_bytes > STRUCTURED_OUTPUT_AGGREGATE_MAX_BYTES
        ):
            raise ValueError("structured output cap exceeds product maximum")
        if not isinstance(self.expected_result_kind, StructuredResultKind):
            raise TypeError("expected result kind must be closed")


def structured_invocation_digest(prepared, policy, plan: StructuredSandboxIoPlanV1) -> str:
    return canonical_json_digest({
        "domain": "first-agent-structured-invocation-v1",
        "process_command_fingerprint": prepared.command.command_fingerprint,
        "package_digest": plan.package_digest,
        "entrypoint_id": plan.entrypoint_id,
        "entrypoint_digest": plan.entrypoint_digest,
        "request_size": len(plan.request_bytes),
        "request_digest": plan.request_digest,
        "inputs": [
            {
                "slot": item.slot,
                "size": len(item.content),
                "digest": item.content_digest,
                "allowed_magic_hex": list(item.allowed_magic_hex),
            }
            for item in plan.inputs
        ],
        "policy_digest": policy.policy_digest,
        "temp_parent_digest": canonical_json_digest({"temp_root": policy.temp_root}),
        "result_cap_bytes": plan.result_cap_bytes,
        "artifact_cap_bytes": plan.artifact_cap_bytes,
        "aggregate_output_cap_bytes": plan.aggregate_output_cap_bytes,
        "expected_result_kind": plan.expected_result_kind.value,
    })
```

Add the transient draft exactly as a closed dataclass; do not serialize it in checkpoint:

```python
@dataclass(frozen=True, slots=True)
class StructuredSandboxProcessDraftV1:
    process: SandboxExecutionDraftV1
    structured_invocation_digest: str
    readback_outcome: StructuredReadbackOutcome
    request_digest: str
    input_digests: tuple[tuple[str, int, str], ...]
    result_bytes: bytes
    result_digest: str
    artifact_bytes: bytes | None
    artifact_digest: str | None
    draft_digest: str = ""

    def identity_values(self) -> dict[str, object]:
        return {
            "process_draft_digest": self.process.draft_digest,
            "structured_invocation_digest": self.structured_invocation_digest,
            "readback_outcome": self.readback_outcome.value,
            "request_digest": self.request_digest,
            "input_digests": [list(item) for item in self.input_digests],
            "result_size": len(self.result_bytes),
            "result_digest": self.result_digest,
            "artifact_size": (
                len(self.artifact_bytes) if self.artifact_bytes is not None else None
            ),
            "artifact_digest": self.artifact_digest,
        }

    def __post_init__(self) -> None:
        if not isinstance(self.process, SandboxExecutionDraftV1):
            raise TypeError("structured draft requires one sandbox process draft")
        _require_hex64(self.structured_invocation_digest, "structured_invocation_digest")
        _require_hex64(self.request_digest, "request_digest")
        if not isinstance(self.readback_outcome, StructuredReadbackOutcome):
            raise TypeError("structured readback outcome must be closed")
        object.__setattr__(self, "input_digests", tuple(self.input_digests))
        if tuple(sorted(self.input_digests)) != self.input_digests:
            raise ValueError("structured input digests must be canonical")
        for slot, size, digest in self.input_digests:
            if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", slot) is None or size < 0:
                raise ValueError("structured input digest identity is invalid")
            _require_hex64(digest, "structured input digest")
        if hashlib.sha256(self.result_bytes).hexdigest() != self.result_digest:
            raise ValueError("structured result digest mismatch")
        expected_artifact = (
            hashlib.sha256(self.artifact_bytes).hexdigest()
            if self.artifact_bytes is not None
            else None
        )
        if expected_artifact != self.artifact_digest:
            raise ValueError("structured artifact digest mismatch")
        if self.readback_outcome is not StructuredReadbackOutcome.VALID and (
            self.result_bytes or self.artifact_bytes not in {None, b""}
        ):
            raise ValueError("invalid readback cannot expose staged bytes")
        spawn_failed = self.process.outcome is SandboxDraftOutcome.SPAWN_FAILED
        not_read = self.readback_outcome is StructuredReadbackOutcome.NOT_READ
        if spawn_failed != not_read:
            raise ValueError("spawn-failed and not-read must occur together")
        expected = canonical_json_digest(self.identity_values())
        if self.draft_digest and self.draft_digest != expected:
            raise ValueError("structured draft digest mismatch")
        object.__setattr__(self, "draft_digest", expected)
```

Add explicit forged-draft Reds before Green:

```python
@pytest.mark.parametrize(
    ("process_outcome", "readback_outcome"),
    [
        (SandboxDraftOutcome.SPAWN_FAILED, StructuredReadbackOutcome.RESULT_MISSING),
        (SandboxDraftOutcome.EXITED, StructuredReadbackOutcome.NOT_READ),
    ],
)
def test_spawn_failed_is_equivalent_to_not_read(process_outcome, readback_outcome):
    with pytest.raises(ValueError, match="occur together"):
        structured_draft(process_outcome, readback_outcome)
```

- [ ] **Step 3: Write fixed-session safety Reds**

Create `tests/sandbox/test_structured_session.py` with parameterized attacks:

```python
def test_session_has_only_fixed_owner_files_and_read_only_inputs(tmp_path):
    session = create_structured_session(tmp_path, io_plan())
    assert set(os.listdir(session.root_fd)) == {"request.json", "inputs", "result.json", "artifact.bin"}
    assert stat.S_IMODE(os.fstat(session.root_fd).st_mode) == 0o500
    assert stat.S_IMODE(os.stat("request.json", dir_fd=session.root_fd, follow_symlinks=False).st_mode) == 0o400
    assert stat.S_IMODE(os.stat("result.json", dir_fd=session.root_fd, follow_symlinks=False).st_mode) == 0o600
    session.close_and_remove()


@pytest.mark.parametrize("attack,code", [
    (replace_result_with_symlink, "result_replaced"),
    (replace_result_inode, "result_replaced"),
    (unlink_result, "result_missing"),
    (write_oversize_result, "result_too_large"),
    (write_malformed_result, "result_malformed"),
    (create_third_output, "extra_output"),
    (write_artifact_for_observation, "artifact_unexpected"),
])
def test_readback_fails_closed_after_execution(tmp_path, attack, code):
    session = create_structured_session(tmp_path, io_plan())
    attack(session)
    result = read_structured_session(session, io_plan())
    assert result.outcome.value == code
```

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_structured_session.py -rx`

Expected: missing module/functions.

- [ ] **Step 4: Implement descriptor-pinned session creation/readback**

In `agent/sandbox/structured_session.py`, `mkdtemp` followed immediately by the initial no-follow `root_fd` open is the only pathname transition. After that open, use only descriptor-relative operations. The creation sequence is exact:

```python
root = tempfile.mkdtemp(prefix="fa-structured-", dir=temp_parent)
root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
os.fchmod(root_fd, 0o700)
os.mkdir("inputs", 0o700, dir_fd=root_fd)
inputs_fd = os.open("inputs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
_create_exact_file(root_fd, "request.json", plan.request_bytes, 0o400)
for item in plan.inputs:
    _create_exact_file(inputs_fd, item.slot, item.content, 0o400)
result_identity = _create_exact_file(root_fd, "result.json", b"", 0o600)
artifact_identity = _create_exact_file(root_fd, "artifact.bin", b"", 0o600)
os.fchmod(inputs_fd, 0o500)
os.fchmod(root_fd, 0o500)
```

`_create_exact_file` must use `O_CREAT|O_EXCL|O_NOFOLLOW|O_WRONLY`, bounded `_write_all`, `fsync`, `fchmod`, and return `(st_dev, st_ino, st_uid, st_nlink)`. Reject non-regular files, `st_uid != os.getuid()` or `st_nlink != 1`. Keep a pinned `temp_parent_fd` plus the random basename. Cleanup unlinks the four fixed entries and input slots descriptor-relative, removes `inputs` and then the session basename with `os.rmdir(..., dir_fd=temp_parent_fd)`; it never calls path-based `chmod`, `unlink`, `rename` or recursive deletion. If that exact cleanup cannot be proved after spawn, raise `StructuredSessionCleanupError`.

Readback must first compare exact directory entry sets, then open each output with `O_RDONLY|O_NOFOLLOW` relative to `root_fd`, compare original inode/uid/nlink/regular-file facts, and read `cap + 1` bytes. Parse result bytes as UTF-8 JSON and require exactly:

```json
{"kind":"observation","payload":{},"protocol":"first-agent-skill-result-v1"}
```

where `kind` exact-matches the plan and `payload` is JSON-compatible. Require canonical encoding:

```python
canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
if canonical != raw_result:
    return invalid(StructuredReadbackOutcome.RESULT_MALFORMED)
```

For OBSERVATION require zero artifact bytes; for ARTIFACT require one or more bytes. Enforce both per-file caps and `len(result) + len(artifact) <= aggregate_output_cap_bytes`.

- [ ] **Step 5: Extend the one executor and taxonomy**

Change only the existing method signature:

```python
def execute(
    self,
    prepared: PreparedProcessV1,
    policy: SandboxPolicyV1 | PackagedSkillSandboxPolicyV1,
    io_plan: StructuredSandboxIoPlanV1 | None = None,
) -> SandboxExecutionDraftV1 | StructuredSandboxProcessDraftV1 | KnownNotExecuted:
```

Unstructured execution must stay byte-for-byte behavior-compatible. Structured flow:

1. revalidate process before session creation;
2. create/freeze session;
3. set closed `HOME=TMPDIR=session.root`, `PATH=""`, safe locale/TZ;
4. confine and verify enforcement facts against stable policy digest;
5. call the existing injected `run_local_process` exactly once;
6. if `SPAWN_FAILED`, return a structured draft with `readback_outcome=NOT_READ`, empty staged bytes and the same outer digest, then remove session;
7. otherwise readback before cleanup and return one `StructuredSandboxProcessDraftV1`;
8. cleanup uncertainty after a started process raises `StructuredSessionCleanupError`, so the existing Runtime enters `AWAITING_RECOVERY`.

Do not suppress structured cleanup errors. Pre-spawn setup/confine failures return `KnownNotExecuted`. Runner exceptions propagate because spawn status may be unknown.

- [ ] **Step 6: Normalize structured drafts through the existing receipt path**

In `KernelToolRuntime.invoke`, add the structured branch immediately before the ordinary sandbox draft branch:

```python
if isinstance(raw_result, StructuredSandboxProcessDraftV1):
    return self._structured_sandbox_outcome(intent, registration.spec, raw_result)
```

Implement `_structured_sandbox_outcome` by first recomputing `canonical_json_digest(draft.identity_values()) == draft.draft_digest` and verifying `draft.structured_invocation_digest == intent.safety_binding.get("structured_invocation_digest")`, then calling `_sandbox_outcome(intent, spec, draft.process)` exactly once. Preserve its sandbox receipt metadata. `SPAWN_FAILED/NOT_READ` remains `executed=False` but adds the outer digest to metadata. Every post-spawn invalid readback returns `executed=True`, `is_error=True`, code equal to the closed outcome, no result/artifact bytes in content/metadata. Valid readback returns bounded canonical result text and metadata containing only digests/sizes plus:

```python
{
    "structured_invocation_digest": draft.structured_invocation_digest,
    "structured_result_digest": draft.result_digest,
    "structured_artifact_digest": draft.artifact_digest,
    "structured_result_kind": decoded["kind"],
}
```

Never place `draft.artifact_bytes`, request bytes or input bytes in `ToolResult`.

- [ ] **Step 7: Verify structured Green and unchanged unstructured behavior**

Run:

```bash
.venv/bin/python -m pytest -q tests/sandbox/test_structured_contracts.py tests/sandbox/test_structured_session.py tests/sandbox/test_structured_executor.py tests/sandbox/test_executor.py tests/sandbox/test_tools.py tests/kernel/test_tool_outcomes.py tests/kernel/test_runtime_recovery.py -rx
.venv/bin/ruff check agent/sandbox agent/runtime/tools.py tests/sandbox
git diff --check
```

Expected: all exit 0; unstructured executor tests prove optional `io_plan=None` did not change current policy or draft semantics.

- [ ] **Step 8: Commit when authorized**

```bash
git add agent/sandbox agent/runtime/tools.py tests/sandbox tests/kernel/test_tool_outcomes.py
git commit -m "feat(sandbox): add structured session readback"
```

---

### Task 4: Add strict packaged-Skill policy and real denial probes

**Files:**
- Modify: `agent/sandbox/contracts.py`
- Create: `agent/sandbox/packaged_policy.py`
- Modify: `agent/sandbox/seatbelt.py`
- Create: `tests/sandbox/test_packaged_policy.py`
- Create: `tests/sandbox/test_packaged_policy_real.py`
- Modify: `tests/sandbox/test_seatbelt.py`

**Interfaces:**
- Produces `PackagedSkillResourceLimitsV1` and `PackagedSkillSandboxPolicyV1`.
- Produces `build_packaged_skill_policy` and `compile_packaged_skill_profile(policy, environment)`.
- Reuses `SeatbeltConfiner.confine`; no second confiner/executor.

- [ ] **Step 1: Write strict policy Reds**

Create `tests/sandbox/test_packaged_policy.py`:

```python
def test_packaged_profile_is_deny_default_and_exact_allowlist(tmp_path):
    policy, session = fixture_policy_and_session(tmp_path)
    profile = compile_packaged_skill_profile(policy, {"TMPDIR": session})
    lines = profile.splitlines()
    assert lines[:2] == ["(version 1)", "(deny default)"]
    assert "(allow default)" not in profile
    assert policy.workspace_root not in profile
    assert policy.home_root not in profile
    assert '(allow file-read-data (literal "/"))' in profile
    assert '(allow file-read* (subpath "/"))' not in profile
    assert '(deny network*)' in profile
    assert '(deny process-fork)' in profile
    assert f'(allow file-write-data (literal "{session}/result.json"))' in profile
    assert f'(allow file-write-data (literal "{session}/artifact.bin"))' in profile
    assert f'(allow file-write* (subpath "{session}"))' not in profile


def test_policy_rejects_overlapping_runtime_package_or_denied_roots(tmp_path):
    roots = fixture_roots(tmp_path)
    with pytest.raises(ValueError, match="overlap"):
        build_packaged_skill_policy(
            runtime_roots=(roots.package,),
            package_root=roots.package,
            temp_root=roots.temp,
            system_runtime_roots=roots.system,
            workspace_root=roots.workspace,
            home_root=roots.home,
            state_root=roots.state,
            private_roots=(),
            runtime_closure_digest="a" * 64,
            system_runtime_digest="b" * 64,
            resource_limits=PackagedSkillResourceLimitsV1.for_profile("skill-standard-v1"),
        )


@pytest.mark.parametrize("profile", ["skill-standard-v1", "artifact-standard-v1"])
def test_resource_limit_profiles_are_named_exact_and_not_numerically_mutable(profile):
    limits = PackagedSkillResourceLimitsV1.for_profile(profile)
    with pytest.raises(ValueError, match="closed profile"):
        replace(limits, cpu_seconds=limits.cpu_seconds + 1)
    with pytest.raises(ValueError, match="not closed"):
        PackagedSkillResourceLimitsV1.for_profile("future-profile")
```

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_packaged_policy.py -rx`

Expected: missing contracts/module.

- [ ] **Step 2: Implement stable policy identity and compiler**

Add the fixed resource and policy contracts to `agent/sandbox/contracts.py`:

```python
PACKAGED_LIMIT_PROFILE_VALUES = MappingProxyType({
    "skill-standard-v1": MappingProxyType({
        "cpu_seconds": 60,
        "address_space_bytes": 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 64,
        "core_bytes": 0,
    }),
    "artifact-standard-v1": MappingProxyType({
        "cpu_seconds": 120,
        "address_space_bytes": 2 * 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 128,
        "core_bytes": 0,
    }),
})


@dataclass(frozen=True, slots=True)
class PackagedSkillResourceLimitsV1:
    profile: str
    cpu_seconds: int
    address_space_bytes: int
    file_size_bytes: int
    open_files: int
    core_bytes: int
    limits_digest: str = ""

    @classmethod
    def for_profile(cls, profile: str) -> PackagedSkillResourceLimitsV1:
        try:
            values = PACKAGED_LIMIT_PROFILE_VALUES[profile]
        except KeyError as error:
            raise ValueError("packaged resource profile is not closed") from error
        return cls(profile=profile, **values)

    def __post_init__(self) -> None:
        values = {
            "profile": self.profile,
            "cpu_seconds": self.cpu_seconds,
            "address_space_bytes": self.address_space_bytes,
            "file_size_bytes": self.file_size_bytes,
            "open_files": self.open_files,
            "core_bytes": self.core_bytes,
        }
        expected = PACKAGED_LIMIT_PROFILE_VALUES.get(self.profile)
        if expected is None or any(
            not isinstance(getattr(self, name), int)
            or isinstance(getattr(self, name), bool)
            or getattr(self, name) != value
            for name, value in expected.items()
        ):
            raise ValueError("packaged resource limits do not match their closed profile")
        digest = canonical_json_digest(values)
        if self.limits_digest and self.limits_digest != digest:
            raise ValueError("packaged resource limit digest mismatch")
        object.__setattr__(self, "limits_digest", digest)


@dataclass(frozen=True, slots=True)
class PackagedSkillSandboxPolicyV1:
    interpreter_path: str
    runtime_roots: tuple[str, ...]
    package_root: str
    temp_root: str
    system_runtime_roots: tuple[str, ...]
    workspace_root: str
    home_root: str
    state_root: str
    private_roots: tuple[str, ...]
    runtime_closure_digest: str
    system_runtime_digest: str
    resource_limits: PackagedSkillResourceLimitsV1
    policy_digest: str = ""
    mode: SandboxMode = field(init=False, default=SandboxMode.READ_ONLY)
    network: SandboxNetworkMode = field(init=False, default=SandboxNetworkMode.OFF)

    def identity_values(self) -> dict[str, object]:
        return {
            "profile": "packaged-skill-v1",
            "interpreter_path": self.interpreter_path,
            "runtime_roots": list(self.runtime_roots),
            "package_root": self.package_root,
            "temp_root": self.temp_root,
            "system_runtime_roots": list(self.system_runtime_roots),
            "workspace_root": self.workspace_root,
            "home_root": self.home_root,
            "state_root": self.state_root,
            "private_roots": list(self.private_roots),
            "runtime_closure_digest": self.runtime_closure_digest,
            "system_runtime_digest": self.system_runtime_digest,
            "resource_limits_digest": self.resource_limits.limits_digest,
            "mode": self.mode.value,
            "network": self.network.value,
        }

    def __post_init__(self) -> None:
        for name in (
            "interpreter_path",
            "package_root",
            "temp_root",
            "workspace_root",
            "home_root",
            "state_root",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.startswith("/"):
                raise ValueError(f"{name} must be an absolute canonical path")
        object.__setattr__(self, "runtime_roots", tuple(self.runtime_roots))
        object.__setattr__(self, "system_runtime_roots", tuple(self.system_runtime_roots))
        object.__setattr__(self, "private_roots", tuple(self.private_roots))
        _require_hex64(self.runtime_closure_digest, "runtime_closure_digest")
        _require_hex64(self.system_runtime_digest, "system_runtime_digest")
        digest = canonical_json_digest(self.identity_values())
        if self.policy_digest and self.policy_digest != digest:
            raise ValueError("packaged sandbox policy digest mismatch")
        object.__setattr__(self, "policy_digest", digest)
```

`build_packaged_skill_policy` resolves every root with `strict=True`, rejects symlink/noncanonical inputs, duplicate/ancestor overlap among runtime/package/temp/denied roots, package under workspace/home/state, runtime under product tree, writable package/runtime modes, and any network/full/danger option because no such parameter exists. `system_runtime_digest` comes from the exact minimal system-root inventory used by the real probe; 021 may record that digest inside its owned `QualificationRecordV1`, but 020a does not define that lifecycle record.

Only `PackagedSkillResourceLimitsV1.for_profile(...)` constructs a production limits object. Direct construction with altered numerics or an unknown profile fails. The standalone runner owns a stdlib-only copy of the same two exact rows and looks them up by `limits_digest`; `tests/sandbox/test_packaged_runner.py` exact-compares both tables/digests so release drift fails before E2M. 020b maps its already-frozen portable `skill-standard-v1|artifact-standard-v1` value to this factory and puts the resulting digest in the eight-key request.

`compile_packaged_skill_profile` validates `environment["TMPDIR"]` is an existing canonical direct child of `policy.temp_root`, then emits only:

```python
clauses = [
    "(version 1)",
    "(deny default)",
    "(allow process-info*)",
    "(allow signal (target self))",
    "(allow sysctl-read)",
    '(allow file-read-data (literal "/"))',
    f'(allow process-exec (literal "{escape_seatbelt_path(policy.interpreter_path)}"))',
    "(deny process-fork)",
    "(deny network*)",
]
clauses += [
    f'(allow file-read* (subpath "{escape_seatbelt_path(root)}"))'
    for root in (*policy.runtime_roots, policy.package_root, *policy.system_runtime_roots)
]
clauses.append(f'(allow file-read* (subpath "{escape_seatbelt_path(session)}"))')
clauses.append(f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/result.json"))')
clauses.append(f'(allow file-write-data (literal "{escape_seatbelt_path(session)}/artifact.bin"))')
return "\n".join(clauses) + "\n"
```

The literal-root clause is the only Seatbelt bootstrap exception: it permits reading the
root directory object itself so the confined child can start, but it does not admit
`(subpath "/")`, root-directory traversal, or any additional file payload. The Darwin
real probe must demonstrate that this clause makes the allowed controls non-vacuous
while workspace/home/private reads remain denied. Do not hide `/` inside
`system_runtime_roots`.

Do not allow directory write, create, unlink, rename, shell paths or arbitrary executable roots.

In `SeatbeltConfiner.confine`, use a closed type branch:

```python
if isinstance(policy, PackagedSkillSandboxPolicyV1):
    profile = compile_packaged_skill_profile(policy, environment)
elif isinstance(policy, SandboxPolicyV1):
    profile = self._profile_compiler(policy)
else:
    return KnownNotExecuted(
        code="sandbox_policy_type_unknown",
        message="sandbox policy type is not admitted",
    )
```

Existing injected one-argument profile compilers remain unchanged.

- [ ] **Step 3: Add real non-vacuous Seatbelt probes**

Create `tests/sandbox/test_packaged_policy_real.py`. Mark it `pytest.mark.skipif(platform.system() != "Darwin", reason="real Seatbelt is Darwin-only")` for ordinary cross-platform unit runs, but the final E2M gate treats this skip as unavailable, not PASS. Drive each probe through `NativeSandboxExecutor`, not raw `subprocess`:

```python
@pytest.mark.parametrize("probe,expected", [
    ("read_runtime", "allowed"),
    ("read_workspace", "denied"),
    ("read_home", "denied"),
    ("read_private", "denied"),
    ("network_connect", "denied"),
    ("fork", "denied"),
    ("exec_true", "denied"),
    ("create_scratch", "denied"),
    ("unlink_result", "denied"),
    ("write_result", "allowed"),
])
def test_real_packaged_policy_probe(probe, expected, real_fixture):
    result = real_fixture.run(probe)
    assert result.process.outcome is SandboxDraftOutcome.EXITED
    assert decode_probe_verdict(result.result_bytes) == expected
```

The network fixture creates one host loopback listener on an ephemeral port and first performs an unsandboxed successful `AF_INET/SOCK_STREAM connect()` to that exact endpoint. The confined child then calls `connect()` to the same listener/port. Only `OSError.errno in {errno.EPERM, errno.EACCES}` is a policy denial; `ECONNREFUSED`, timeout, DNS failure and every other error fail the test. The other fixture probes return exit 0 with a typed verdict only when they observe the exact expected denial, and each has an allowed control in the same profile. `exec_true` uses `/usr/bin/true`; `fork` calls `os.fork`.

- [ ] **Step 4: Verify policy Green**

Run:

```bash
.venv/bin/python -m pytest -q tests/sandbox/test_packaged_policy.py tests/sandbox/test_seatbelt.py tests/sandbox/test_packaged_policy_real.py -rx
.venv/bin/ruff check agent/sandbox/contracts.py agent/sandbox/packaged_policy.py agent/sandbox/seatbelt.py tests/sandbox/test_packaged_policy.py tests/sandbox/test_packaged_policy_real.py
git diff --check
```

Expected on Darwin with qualified `/usr/bin/sandbox-exec`: all exit 0 and zero skips. On another platform, record `packaged_skill_strict_sandbox_unavailable` and do not proceed to executable registration or promotion.

- [ ] **Step 5: Commit when authorized**

```bash
git add agent/sandbox tests/sandbox/test_packaged_policy.py tests/sandbox/test_packaged_policy_real.py tests/sandbox/test_seatbelt.py
git commit -m "feat(sandbox): add strict packaged skill policy"
```

---

### Task 5: Build the hermetic runtime closure and standalone hard-limited runner

**Files:**
- Create: `agent/sandbox/hermetic_runtime.py`
- Create: `scripts/materialize_020a_test_runtime.py`
- Create: `first_agent_skill_runner/__init__.py`
- Create: `first_agent_skill_runner/__main__.py`
- Modify: `pyproject.toml`
- Create: `tests/sandbox/test_hermetic_runtime.py`
- Create: `tests/sandbox/test_packaged_runner.py`
- Create: `tests/fixtures/020a_noop_skill/scripts/noop.py`
- Create: `tests/fixtures/020a_noop_skill/scripts/report_limits.py`

**Interfaces:**
- Produces `HermeticRuntimeFileV1`, `HermeticRuntimeClosureV1`, `qualify_hermetic_runtime_closure`, `prepare_hermetic_skill_process`.
- Produces `materialize_test_runtime(source_root, destination_root, *, protected_roots)` which accepts only an already-qualified explicit release closure, requires the caller's explicit product/workspace/state protection domains, and requalifies the copy.
- Produces executable module `python -I -m first_agent_skill_runner --package DIGEST --entrypoint ID`.
- Runner protocol is fixed request/result JSON plus optional transient artifact bytes; package script receives bytes, never paths.

**020b Task 5 blocking prerequisite:** before 020b writes `_prepare_components`, update its exact eight-key request fixture and real runner contract so `entrypoint_script` is one nested exact descriptor `{path: str, size: int, sha256: hex64}`. The decoded host value remains `ExecutableScriptDescriptorV1(relative_path, size_bytes, sha256)`; `_prepare_components` is the only owner allowed to map it explicitly to `{path: relative_path, size: size_bytes, sha256: sha256}`. The path comes from the decoded 020b manifest, while size/SHA-256 come from the exact matching 021 canonical `PackageRole.SCRIPT` inventory entry. Missing, duplicate or mismatched inventory entries are pre-spawn rejection. 020b must not accept the prior string or host-field wire shape, add a compatibility union, expose a second wire encoder, or compute the script digest by reopening an unqualified path.

- [ ] **Step 1: Write hermetic closure Reds**

Create `tests/sandbox/test_hermetic_runtime.py`:

```python
def test_fixed_command_contains_no_session_or_model_supplied_process_fields(runtime_fixture, package_root):
    closure = qualify_hermetic_runtime_closure(runtime_fixture.root)
    prepared = prepare_hermetic_skill_process(
        closure,
        package_root=package_root,
        package_digest="a" * 64,
        entrypoint_id="inspect",
    )
    assert prepared.command.argv == (
        "-I", "-m", "first_agent_skill_runner",
        "--package", "a" * 64,
        "--entrypoint", "inspect",
    )
    assert "fa-structured-" not in repr(prepared.command)
    assert prepared.command.executable_identity.resolved_path == closure.interpreter_path


def test_closure_rejects_symlink_unknown_file_and_digest_drift(runtime_fixture):
    for mutation in (runtime_fixture.symlink_file, runtime_fixture.unknown_file, runtime_fixture.replace_file):
        mutated = runtime_fixture.copy()
        mutation(mutated)
        outcome = qualify_hermetic_runtime_closure(mutated.root)
        assert isinstance(outcome, KnownNotExecuted)


def test_manifest_is_excluded_from_inventory_but_bound_to_closure(runtime_fixture):
    closure = qualify_hermetic_runtime_closure(runtime_fixture.root)
    assert "runtime-closure-v1.json" not in {item.path for item in closure.inventory}
    assert closure.manifest_digest == hashlib.sha256(
        runtime_fixture.manifest_path.read_bytes()
    ).hexdigest()
    runtime_fixture.rewrite_manifest_noncanonically()
    assert isinstance(
        qualify_hermetic_runtime_closure(runtime_fixture.root),
        KnownNotExecuted,
    )


def test_materializer_requires_explicit_qualified_source_and_requalifies_copy(
    runtime_fixture,
    tmp_path,
):
    destination = tmp_path / "materialized-runtime"
    protected = tmp_path / "protected"
    protected.mkdir()
    copied = materialize_test_runtime(
        runtime_fixture.root,
        destination,
        protected_roots=(protected,),
    )
    assert copied == qualify_hermetic_runtime_closure(destination)
    assert copied.runtime_root == str(destination.resolve())
    with pytest.raises(ValueError, match="qualified source"):
        materialize_test_runtime(
            tmp_path / "ordinary-venv",
            tmp_path / "rejected",
            protected_roots=(protected,),
        )
```

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_hermetic_runtime.py -rx`

Expected: missing module/contracts.

- [ ] **Step 2: Implement exact closure inventory and fixed preparation**

Implement the leaf contracts in `agent/sandbox/hermetic_runtime.py`:

```python
@dataclass(frozen=True, slots=True)
class HermeticRuntimeFileV1:
    path: str
    role: str
    mode: int
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if self.path.startswith("/") or ".." in self.path.split("/") or "\\" in self.path:
            raise ValueError("runtime inventory path must be canonical relative")
        if self.role not in {"interpreter", "stdlib", "dynload", "runner", "distribution"}:
            raise ValueError("runtime inventory role is not closed")
        if self.mode not in {0o444, 0o555} or self.size < 0:
            raise ValueError("runtime inventory mode or size is invalid")
        _require_hex64(self.sha256, "runtime file digest")


@dataclass(frozen=True, slots=True)
class HermeticRuntimeClosureV1:
    runtime_root: str
    interpreter_path: str
    readable_roots: tuple[str, ...]
    inventory: tuple[HermeticRuntimeFileV1, ...]
    inventory_digest: str
    manifest_digest: str
    closure_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "readable_roots", tuple(self.readable_roots))
        object.__setattr__(self, "inventory", tuple(self.inventory))
        if tuple(sorted(self.inventory, key=lambda item: item.path)) != self.inventory:
            raise ValueError("runtime inventory must be sorted")
        inventory_values = [asdict(item) for item in self.inventory]
        if canonical_json_digest(inventory_values) != self.inventory_digest:
            raise ValueError("runtime inventory digest mismatch")
        _require_hex64(self.manifest_digest, "runtime manifest digest")
        digest = canonical_json_digest({
            "domain": "first-agent-skill-runtime-v1",
            "runtime_root": self.runtime_root,
            "interpreter_path": self.interpreter_path,
            "readable_roots": list(self.readable_roots),
            "inventory_digest": self.inventory_digest,
            "manifest_digest": self.manifest_digest,
        })
        if self.closure_digest and self.closure_digest != digest:
            raise ValueError("runtime closure digest mismatch")
        object.__setattr__(self, "closure_digest", digest)
```

`qualify_hermetic_runtime_closure(root)` opens one root-level `runtime-closure-v1.json` with `O_NOFOLLOW`, regular/owner/nlink/size checks and a `64 KiB` cap. Require exact keys `schema/interpreter/stdlib_roots/dynload_roots/runner_roots/distribution_roots/inventory_digest`, exact schema `first-agent-skill-runtime-closure/v1`, canonical UTF-8 JSON bytes, canonical relative paths, and compute `manifest_digest = sha256(exact_canonical_manifest_bytes)`. The manifest is the one explicit exception to the file inventory: exclude that exact root-level name from `inventory_digest`, but include `manifest_digest` in `closure_digest`. Any other file outside the declared interpreter/stdlib/dynload/runner/distribution inventory is unknown and rejected. The descriptor/no-follow scan hashes every inventoried file with a fixed `512 MiB` per-file cap, rejects symlink/hardlink/non-regular/unknown entries, and compares the byte-sorted inventory digest. This avoids a self-referential manifest hash while keeping manifest changes authority-visible. Return this exact failure on any uncertainty:

```python
return KnownNotExecuted(
    code="hermetic_runtime_closure_invalid",
    message="skill-runtime-v1 closure could not be verified",
)
```

It must prove `first_agent_skill_runner/__main__.py` belongs to a declared runner root and no root points outside the closure. `HermeticRuntimeClosureV1.closure_digest` contains no user/site/product Python fallback.

Implement `scripts/materialize_020a_test_runtime.py` as a tracked stdlib-only helper. It requires explicit `--source-root`, `--destination-root`, and one or more repeated `--protected-root` values; it never defaults or infers any of those paths from cwd, module location, environment or user state. The Python API mirrors this with a required keyword-only non-empty `protected_roots` tuple. `source_root` must first pass `qualify_hermetic_runtime_closure`. Open every explicit locator component-by-component with `O_DIRECTORY|O_NOFOLLOW`; do not call `resolve()` before symlink admission. Before creating the destination, pin the source, destination parent and every protected root, then reject source/destination overlap with each other or with any product/workspace/state protection domain. Copy only the exact manifest plus `closure.inventory` paths with descriptor-relative `O_NOFOLLOW` reads and `O_CREAT|O_EXCL|O_NOFOLLOW` writes, preserving canonical `0444/0555` modes and verifying size/SHA-256 after each write. Write the already-canonical manifest last, fsync files/directories, then require `qualify_hermetic_runtime_closure(destination_root)` to succeed and return that new closure. Unit tests use a synthetic non-sensitive qualified fixture; E2M/E3 pass an explicit application-release `skill-runtime-v1` root plus their verifier-owned product/workspace/state roots and materialize a fresh copy. The fresh wheel-verifier venv is never accepted as `source_root`.

Prepare the fixed command through the existing process seam; do not parse manifest or discover entrypoints:

```python
def prepare_hermetic_skill_process(
    closure: HermeticRuntimeClosureV1,
    *,
    package_root: Path,
    package_digest: str,
    entrypoint_id: str,
):
    _require_hex64(package_digest, "package_digest")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", entrypoint_id) is None:
        raise ValueError("entrypoint_id has an invalid shape")
    return prepare_process(
        {
            "executable": closure.interpreter_path,
            "argv": [
                "-I",
                "-m",
                "first_agent_skill_runner",
                "--package",
                package_digest,
                "--entrypoint",
                entrypoint_id,
            ],
            "cwd": ".",
            "profile": "standard",
        },
        workspace=package_root,
        captured_path="",
    )
```

Before calling it, the caller must reject package-root overlap with closure/product/workspace denied roots. The prepared process pins package cwd identity with the existing `WorkspaceBoundary`; package path never enters argv.

- [ ] **Step 3: Write runner protocol/rlimit/preflight Reds**

Create `tests/sandbox/test_packaged_runner.py`:

```python
@pytest.mark.parametrize("profile", ["skill-standard-v1", "artifact-standard-v1"])
def test_runner_process_applies_limits_or_refuses_before_package_load_when_unavailable(
    profile,
    subprocess_session_fixture,
):
    limits = PackagedSkillResourceLimitsV1.for_profile(profile)
    completed, result = subprocess_session_fixture.run_real_runner(
        resource_limits_digest=limits.limits_digest,
        script="scripts/report_limits.py",
    )
    if completed.returncode:
        assert completed.stdout == ""
        assert "required as limit could not be applied" in completed.stderr
        assert result == {}
        assert subprocess_session_fixture.output_bytes() == (b"", b"")
        return
    assert completed.returncode == 0
    assert result["payload"]["limits"] == {
        "cpu": [limits.cpu_seconds, limits.cpu_seconds],
        "as": [limits.address_space_bytes, limits.address_space_bytes],
        "fsize": [limits.file_size_bytes, limits.file_size_bytes],
        "nofile": [limits.open_files, limits.open_files],
        "core": [limits.core_bytes, limits.core_bytes],
    }


def test_apply_hard_limits_sets_every_soft_and_hard_value_from_the_closed_row(
    monkeypatch,
    fake_resource,
):
    limits = PackagedSkillResourceLimitsV1.for_profile("skill-standard-v1")
    monkeypatch.setattr(skill_runner, "resource", fake_resource)
    skill_runner.apply_hard_limits(limits.limits_digest)
    assert fake_resource.calls == fake_resource.expected_two_phase_calls(limits)


def test_runner_rejects_unknown_limit_digest_before_script_load(session_fixture):
    session_fixture.set_resource_limits_digest("f" * 64)
    loaded = []
    with pytest.raises(RunnerProtocolError, match="not closed"):
        run_request(
            session_fixture.request,
            execute_script=lambda descriptor, content: loaded.append((descriptor, content)),
        )
    assert loaded == []


def test_agent_and_stdlib_runner_limit_tables_have_identical_digests():
    expected = {
        PackagedSkillResourceLimitsV1.for_profile(profile).limits_digest
        for profile in ("skill-standard-v1", "artifact-standard-v1")
    }
    assert set(skill_runner.LIMITS_BY_DIGEST) == expected


@pytest.fixture
def no_limit_syscalls(monkeypatch):
    monkeypatch.setattr(skill_runner, "apply_hard_limits", lambda _digest: None)


def test_header_and_digest_preflight_happen_before_package_load(session_fixture, no_limit_syscalls):
    session_fixture.replace_input(b"not-a-pdf")
    loaded = []
    with pytest.raises(RunnerProtocolError, match="preflight"):
        run_request(
            session_fixture.request,
            execute_script=lambda descriptor, content: loaded.append((descriptor, content)),
        )
    assert loaded == []


def test_package_script_receives_bytes_not_paths(session_fixture, no_limit_syscalls):
    observed = {}
    def run(arguments, inputs):
        observed.update(inputs)
        return {"kind": "observation", "payload": {"size": len(inputs["source"])}, "artifact": None}
    returned = run_request(
        session_fixture.request,
        execute_script=lambda _descriptor, _bytes: {"run": run},
    )
    assert observed == {"source": session_fixture.input_bytes}
    assert all(not isinstance(value, str) for value in observed.values())
    assert returned == {
        "kind": "observation",
        "payload": {"size": len(session_fixture.input_bytes)},
        "artifact": None,
    }
```

Run: `.venv/bin/python -m pytest -q tests/sandbox/test_packaged_runner.py -rx`

Expected: missing runner module.

- [ ] **Step 4: Implement standalone runner with no agent import**

`first_agent_skill_runner/__main__.py` must import only stdlib. Parse exactly four argv tokens after module name, validate package digest as lowercase hex64 and entrypoint ID with the closed shape, then read `TMPDIR/request.json` and `TMPDIR/inputs/<slot>` using `O_NOFOLLOW`. Bound request bytes at `STRUCTURED_REQUEST_MAX_BYTES = 64 * 1024` before JSON decode.

After the bounded host-owned request is decoded and exact keys/identity are validated, map its approved digest through this closed stdlib-only table. Before reading any input or package script, apply every hard limit with soft and hard values equal:

```python
LIMIT_PROFILE_VALUES = {
    "skill-standard-v1": {
        "cpu_seconds": 60,
        "address_space_bytes": 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 64,
        "core_bytes": 0,
    },
    "artifact-standard-v1": {
        "cpu_seconds": 120,
        "address_space_bytes": 2 * 1024 * 1024 * 1024,
        "file_size_bytes": 64 * 1024 * 1024,
        "open_files": 128,
        "core_bytes": 0,
    },
}


def _limit_digest(profile: str, values: dict[str, int]) -> str:
    payload = {"profile": profile, **values}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


LIMITS_BY_DIGEST = {
    _limit_digest(profile, values): values
    for profile, values in LIMIT_PROFILE_VALUES.items()
}


def apply_hard_limits(resource_limits_digest: str) -> None:
    values = LIMITS_BY_DIGEST.get(resource_limits_digest)
    if values is None:
        raise RunnerProtocolError("resource limit digest is not closed")
    limits = (
        (resource.RLIMIT_CPU, values["cpu_seconds"]),
        (resource.RLIMIT_AS, values["address_space_bytes"]),
        (resource.RLIMIT_FSIZE, values["file_size_bytes"]),
        (resource.RLIMIT_NOFILE, values["open_files"]),
        (resource.RLIMIT_CORE, values["core_bytes"]),
    )
    for name, value in limits:
        resource.setrlimit(name, (value, value))
```

If any required limit is unavailable or cannot be set, exit nonzero before script load. The request must have exact keys:

```python
{
    "protocol",
    "package_digest",
    "entrypoint_id",
    "entrypoint_script",
    "arguments",
    "inputs",
    "expected_result_kind",
    "resource_limits_digest",
}
```

Validate the nested script descriptor before limit lookup or package access:

```python
script_descriptor = request["entrypoint_script"]
if not isinstance(script_descriptor, dict) or set(script_descriptor) != {
    "path",
    "size",
    "sha256",
}:
    raise RunnerProtocolError("entrypoint script descriptor keys are not closed")
if (
    not isinstance(script_descriptor["path"], str)
    or not _canonical_script_path(script_descriptor["path"])
    or not isinstance(script_descriptor["size"], int)
    or isinstance(script_descriptor["size"], bool)
    or not 0 <= script_descriptor["size"] <= 32 * 1024 * 1024
    or HEX64.fullmatch(script_descriptor["sha256"]) is None
):
    raise RunnerProtocolError("entrypoint script descriptor is invalid")
```

Each input descriptor has exact `slot/size/sha256/allowed_magic_hex`; verify size and digest and, when the canonical magic tuple is non-empty, require at least one allowed header. `entrypoint_script` has exact nested keys `{path,size,sha256}`. The path must be a canonical `scripts/` relative path without absolute, `..` or backslash; size is `0..32 MiB`; SHA-256 is lowercase hex64. 020b gets all three values from the exact 021 canonical inventory, not from the model or manifest alone.

Open the package root and every script ancestor descriptor-relative with `O_DIRECTORY|O_NOFOLLOW`, open the final script once with `O_RDONLY|O_NOFOLLOW`, and require regular file, current uid, `nlink == 1`, exact size and exact digest with stable before/after `fstat`. Read at most `size + 1` bytes. Never pass the path to `runpy`, never reopen it, and never import it as a module. Compile the verified bytes with the logical canonical path as filename and execute them in one fresh namespace containing only the normal Python builtins plus `__name__="__first_agent_skill_entrypoint__"` and the logical `__file__`; the Seatbelt/read allowlist remains the authority for imports requested by that verified script.

Require exactly one callable named `run`. Call `run(arguments, MappingProxyType(input_bytes))`. Accept only exact return keys `kind/payload/artifact`; validate JSON payload, expected kind, and bytes-or-None artifact. The product runner, not package code, writes canonical `result.json` and optional `artifact.bin` through `O_WRONLY|O_TRUNC|O_NOFOLLOW` to the two precreated inodes.

The core function is concrete and keeps load injection test-only:

```python
def run_request(
    request_path: Path,
    *,
    execute_script=_compile_and_exec_verified_script,
) -> dict[str, object]:
    request = _read_exact_json(request_path, cap=STRUCTURED_REQUEST_MAX_BYTES)
    if set(request) != {
        "protocol",
        "package_digest",
        "entrypoint_id",
        "entrypoint_script",
        "arguments",
        "inputs",
        "expected_result_kind",
        "resource_limits_digest",
    }:
        raise RunnerProtocolError("request keys are not closed")
    _validate_request_identity(request)
    apply_hard_limits(request["resource_limits_digest"])
    session = request_path.parent
    input_values: dict[str, bytes] = {}
    for descriptor in request["inputs"]:
        if set(descriptor) != {"slot", "size", "sha256", "allowed_magic_hex"}:
            raise RunnerProtocolError("input descriptor keys are not closed")
        value = _read_exact_input(session / "inputs", descriptor)
        input_values[descriptor["slot"]] = value
    script_bytes = _read_exact_script(Path.cwd(), request["entrypoint_script"])
    namespace = execute_script(request["entrypoint_script"], script_bytes)
    package_run = namespace.get("run")
    if not callable(package_run):
        raise RunnerProtocolError("entrypoint exports no callable run")
    raw = package_run(request["arguments"], MappingProxyType(input_values))
    if not isinstance(raw, dict) or set(raw) != {"kind", "payload", "artifact"}:
        raise RunnerProtocolError("entrypoint result keys are not closed")
    if raw["kind"] != request["expected_result_kind"]:
        raise RunnerProtocolError("entrypoint result kind mismatch")
    _validate_json(raw["payload"])
    artifact = raw["artifact"]
    if artifact is not None and not isinstance(artifact, bytes):
        raise RunnerProtocolError("artifact must be bytes or null")
    result = {
        "protocol": "first-agent-skill-result-v1",
        "kind": raw["kind"],
        "payload": raw["payload"],
    }
    _replace_precreated(
        session,
        "result.json",
        json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8"),
    )
    if artifact is not None:
        _replace_precreated(session, "artifact.bin", artifact)
    return raw
```

`run_request` returns the exact validated package callable value `{kind,payload,artifact}` only to its child-main/in-process contract-test caller; that return value is not evidence and is never printed. The host-visible result remains the canonical `result.json` document `{protocol,kind,payload}` plus separately read-back `artifact.bin`. `_replace_precreated` is intentionally named for data replacement within the existing inode: it opens the fixed name with `O_WRONLY|O_TRUNC|O_NOFOLLOW` and writes bytes; it never calls rename/unlink/create.

`tests/fixtures/020a_noop_skill/scripts/noop.py` is exact:

```python
import os


def run(arguments, inputs):
    return {
        "kind": "observation",
        "payload": {
            "ambient_canary_present": "FIRST_AGENT_E2M_CANARY" in os.environ,
            "entrypoint": arguments["entrypoint"],
            "input_digests": sorted(inputs),
        },
        "artifact": None,
    }
```

`tests/fixtures/020a_noop_skill/scripts/report_limits.py` is exact and runs only in the independent runner subprocess:

```python
import resource


def _pair(name):
    return list(resource.getrlimit(name))


def run(arguments, inputs):
    del arguments, inputs
    return {
        "kind": "observation",
        "payload": {
            "limits": {
                "cpu": _pair(resource.RLIMIT_CPU),
                "as": _pair(resource.RLIMIT_AS),
                "fsize": _pair(resource.RLIMIT_FSIZE),
                "nofile": _pair(resource.RLIMIT_NOFILE),
                "core": _pair(resource.RLIMIT_CORE),
            },
        },
        "artifact": None,
    }
```

Add `first_agent_skill_runner` to setuptools package discovery:

```toml
[tool.setuptools.packages.find]
include = ["agent", "agent.*", "first_agent_skill_runner"]
```

- [ ] **Step 5: Verify isolated imports, preflight and hard limits**

Run:

```bash
.venv/bin/python -m pytest -q tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py -rx
.venv/bin/python -I -m first_agent_skill_runner --package invalid --entrypoint inspect
.venv/bin/ruff check agent/sandbox/hermetic_runtime.py scripts/materialize_020a_test_runtime.py first_agent_skill_runner tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py tests/fixtures/020a_noop_skill/scripts/noop.py tests/fixtures/020a_noop_skill/scripts/report_limits.py
git diff --check
```

Expected: pytest/Ruff/diff exit 0; invalid direct runner command exits nonzero before package load. Also assert in tests that `"agent" not in sys.modules` in a fresh runner subprocess.

The fresh subprocess may report the closed resource limiter unavailable on a host that
cannot apply every frozen hard limit. In particular, Darwin Python processes can start
with an address-space mapping hundreds of GiB wide, so the closed 1/2 GiB
`RLIMIT_AS` rows may be impossible to lower after interpreter startup. That outcome is
Task-5 evidence only when the child exits nonzero before package script load, writes no
result or artifact bytes, and the fake-resource contract test proves the exact closed
soft/hard calls and digest-table parity. Record
`packaged_skill_resource_limiter_unavailable`; do not change the frozen rows, skip the
limit, or call the runtime qualified. This unavailable result blocks E2M/E3 promotion
until a separately approved resource-profile design is implemented and re-audited
across Task 4, the runner and the real qualified runtime.

- [ ] **Step 6: Commit when authorized**

```bash
git add agent/sandbox/hermetic_runtime.py scripts/materialize_020a_test_runtime.py first_agent_skill_runner pyproject.toml tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py tests/fixtures/020a_noop_skill
git commit -m "feat(sandbox): add hermetic skill runner"
```

---

### Task 6: Implement the real E2/E2M verifier and qualify only when host prerequisites hold

**Files:**
- Create: `tests/reference/test_020a_operator_structured_sandbox.py`
- Create: `scripts/verify_020a_materialized.py`
- Create: `tests/reference/test_020a_materialized_verifier.py`
- Modify: `tests/kernel/fakes.py`

**Interfaces:**
- Consumes Task 1–5 contracts only.
- Test composition manually creates one OPERATOR `RegisteredTool`; this is not a production registration builder.
- Produces no production API.
- Task 6 has two separate completion states. **6A verifier implemented** means the tracked-only build, non-editable install, installed-origin checks, explicit release-runtime admission/materialization, real Runtime driver, and closed evidence decoder are implemented and their contract tests pass. **6B E2/E2M qualified** additionally requires a real application-release `skill-runtime-v1`, real Seatbelt controls, and every frozen hard limit including `RLIMIT_AS` to succeed in the fresh child. 6A may be recorded and committed while 6B is unavailable, but it is not E2, E2M, promotion, or 020a completion.
- On the current Darwin baseline, the frozen 1/2 GiB address-space rows fail in fresh Python with `EINVAL`. The real verifier must therefore exit nonzero with `020A_E2M_UNAVAILABLE(reason=resource_limit_as_unavailable)`. The entrypoint script must remain unloaded, the precreated child `result.json` and `artifact.bin` must remain empty, and no installed-driver success evidence or acceptance artifact may be generated.
- A missing, empty, nonexistent, synthetic-only, or unqualified application-release runtime root cannot be replaced by the current venv, an editable install, ambient `sys.path`, a fake `resource` module, or system Python. A missing/empty/nonexistent locator exits nonzero with `020A_E2M_UNAVAILABLE(reason=release_runtime_root_unavailable)`; an explicit root that fails closure qualification exits nonzero with `020A_E2M_UNAVAILABLE(reason=release_runtime_root_invalid)`. Synthetic release fixtures remain permitted only for verifier contract tests and never count as 6B evidence.
- The verifier owns the exact selected source/build inventory domain:

```python
GENERATED_ACCEPTANCE_PATHS = frozenset({
    "docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3.md",
    "docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3_RECEIPT.json",
})
SOURCE_BUILD_DIGEST_DOMAIN = "020a-source-build-inventory-v1"
```

- [ ] **Step 1: Write the Runtime-path and truthful-unavailability Reds**

Create a reference test with one `ToolSpec` named `fixture_structured_noop`, exposure OPERATOR, HIGH/EXTERNAL/ALWAYS/ISOLATED_SANDBOX. Its deterministic `prepare_binding` returns:

```python
{
    "command_fingerprint": prepared.command.command_fingerprint,
    "policy_digest": policy.policy_digest,
    "sandbox_mode": "read-only",
    "sandbox_network": "off",
    "effect_preview": "Run the packaged structured no-op fixture; no workspace path is disclosed.",
    "trust_notice_id": "strict-packaged-skill-v1",
    "trust_notice_digest": canonical_json_digest({"notice": "strict-packaged-skill-v1"}),
    "structured_invocation_digest": structured_invocation_digest(prepared, policy, io_plan),
}
```

The callable revalidates every binding field and returns `NativeSandboxExecutor.execute(prepared, policy, io_plan)`. Drive:

```python
initial = store.load()
first = runtime.run_turn(
    ExecuteOperatorTool(
        conversation_id=initial.state.conversation_id,
        action_seq=initial.state.next_action_seq,
        expected_revision=initial.state.revision,
        action_id="operator-e2-1",
        tool_name="fixture_structured_noop",
        arguments={},
        submitted_at="2026-08-30T12:00:00Z",
    ),
    initial,
)
assert first.status is RunStatus.AWAITING_APPROVAL
assert spawn_counter.value == 0
pending = store.load()
second = runtime.run_turn(exact_approval(first), pending)
assert second.status is RunStatus.COMPLETED
assert spawn_counter.value == 1
assert provider.calls == []
assert_is_ordered_subsequence(durable_phases, ["tool", "executing", "model"])
result = latest_operator_result(second.state)
assert result.content["metadata"]["structured_invocation_digest"] == expected_outer_digest
assert result.content["metadata"]["sandbox_receipt_kind"] == "native_sandbox_v1"
assert "request_bytes" not in repr(second.state)
assert "input_bytes" not in repr(second.state)
```

The code block above is the positive qualification branch, not an unconditional assertion for every host. Add restart variants after approval pending and after durable EXECUTING. Each variant closes the first Runtime, creates a new Runtime and `LocalCheckpointStore` over the same checkpoint path, calls the new Runtime with `reopened_store.load()`, and never reuses an in-memory state object. Approval-pending restart performs exactly one authorized spawn after the exact grant. EXECUTING restart returns `AWAITING_RECOVERY` with zero automatic spawn.

The real-child case is a qualification test, not an unconditional happy-path assertion. It must use the real `SeatbeltConfiner`, executor and standalone child with no monkeypatched `resource` implementation. If the child can apply the complete frozen row, assert the full completed journey above. If it cannot apply `RLIMIT_AS`, accept only the exact nonzero `resource_limit_as_unavailable` branch and assert all of the following: approval and durable `EXECUTING` preceded the single attempted spawn; no package script was loaded; child stdout, `result.json` and `artifact.bin` are empty; no success evidence was emitted; and no fake/direct-helper result was substituted. No skip, xfail, editable interpreter or conditional weakening is allowed.

Run: `.venv/bin/python -m pytest -q tests/reference/test_020a_operator_structured_sandbox.py -rx`

Expected: fail until every Task 1–5 seam composes and the unavailable branch is as strict as the positive branch.

- [ ] **Step 2: Make the reference verifier Green without production composition**

Use only existing `AgentRuntime`, `KernelToolRuntime`, `LocalCheckpointStore`, `SeatbeltConfiner`, `NativeSandboxExecutor`, hermetic preparation and the tracked fixture. Do not add a helper to `agent/composition.py`. `RegisteredTool` remains a manual OPERATOR registration and is still driven only through `AgentRuntime.run_turn`; the test must not call `KernelToolRuntime.invoke` directly. The contract fixture may receive an explicit synthetic qualified root and materialize a fresh test closure through `materialize_test_runtime`, but its outcome is labelled verifier-structure evidence only. It must never use the pytest/current venv interpreter as the Skill interpreter. On a positive real branch, assert the actual confiner backend is `seatbelt`, enforcement is `confined`, profile starts with deny-default, the child executable identity equals the qualified closure interpreter, and the canonical result reports `ambient_canary_present: false` while the trusted host driver has set `FIRST_AGENT_E2M_CANARY`. On the real unavailable branch, preserve the exact pre-load/empty-output facts from Step 1 and expose only the closed reason.

- [ ] **Step 3: Write materialized verifier Red**

`tests/reference/test_020a_materialized_verifier.py` executes `scripts/verify_020a_materialized.py --source-root <repo> --skill-runtime-root <explicit-qualified-root>` and requires a machine-readable final line plus the real subprocess exit status. The synthetic qualified root supplied by this test proves argument plumbing, materialization, closure identity and the closed unavailable path only; it is never recorded as application-release or promotion evidence. The verifier has no environment/default lookup. Add an invocation with no `--skill-runtime-root` and require nonzero `020A_E2M_UNAVAILABLE(reason=release_runtime_root_unavailable)` before wheel build, installed driver or evidence creation. It must also reject:

- neutral-cwd import resolving to source tree;
- editable install;
- runner origin outside installed wheel;
- missing `/usr/bin/sandbox-exec` or any skipped real denial probe;
- a tracked-input manifest containing `.env`, `tui/`, `.ua/` or `graphify-out/`;
- any wheel/build-context member absent from the exact `git ls-files -z` manifest, including an untracked Python package placed under `agent/` by the Red;
- an installed-driver evidence object with unknown/missing fields, a wrong schema, a recomputed digest mismatch, a wrong checkpoint/receipt join, or a claimed PASS after the child returned unavailable;
- fewer than one complete Runtime journey for a positive verdict.

The current-host real-path Red requires nonzero `020A_E2M_UNAVAILABLE(reason=resource_limit_as_unavailable)`, no entrypoint load, empty child result/artifact files, no `020a-installed-driver-evidence/v1` success object and no generated acceptance path. The tests for the closed evidence decoder may use canonical synthetic objects to cover positive and malformed decoding, but those objects are decoder fixtures, not E2/E2M evidence.

Run: `.venv/bin/python -m pytest -q tests/reference/test_020a_materialized_verifier.py -rx`

Expected: missing verifier.

- [ ] **Step 4: Implement the materialized gate**

`scripts/verify_020a_materialized.py` must:

1. parse `--skill-runtime-root` as an explicit semantic prerequisite without consulting environment, cwd, module origin, the verifier venv or ambient import paths. Missing/empty/nonexistent input returns `release_runtime_root_unavailable`. This locator preflight happens before source build or evidence-directory creation;
2. enumerate only `git ls-files -z` tracked inputs, reject forbidden tracked prefixes, remove exactly the two verifier-owned `GENERATED_ACCEPTANCE_PATHS`, and descriptor-read the remaining selected regular files into a fresh owner-only build context; preserve tracked working-tree bytes, modes and relative paths, but never open or copy an untracked path;
3. exact-compare the temporary context inventory to that selected source/build inventory, then build from that context with `PIP_NO_INDEX=1`, `PIP_DISABLE_PIP_VERSION_CHECK=1`, `pip wheel --no-deps --no-build-isolation` and a closed build environment;
4. create a fresh verifier venv and install the wheel non-editably with `--no-deps --no-index`; assert no editable metadata/source link is present. The current developer venv may launch the verifier but is never an import-origin, closure or promotion fact and is never passed to `prepare_hermetic_skill_process`;
5. validate the explicit root with `qualify_hermetic_runtime_closure`, map closure rejection to `release_runtime_root_invalid`, use `materialize_test_runtime` to create a distinct execution closure, and fail if either root overlaps the verifier venv/source/build/product/workspace/state roots;
6. switch to a neutral temp cwd, remove every inherited variable except a fixed OS-safe subprocess allowlist, and set one host-only `FIRST_AGENT_E2M_CANARY` value; the structured executor's closed environment must omit it;
7. assert `agent`, `first_agent_skill_runner`, the tracked installed driver and console entrypoint origins are inside the non-editable installed prefix, while the Skill interpreter/runner origins are inside the separately materialized release closure. An editable origin, source-tree origin, current-venv origin or origin outside those two admitted roots is a closed failure;
8. invoke the tracked verifier itself under the installed interpreter in `--installed-driver` mode. That stdlib driver creates the manual OPERATOR registration, drives the one real `AgentRuntime.run_turn` path, and writes its durable checkpoint under a verifier-owned directory. It may emit one canonical `020a-installed-driver-evidence/v1` success object only after the real child completed and the checkpoint was reloaded. Normalize `resource_limit_as_unavailable` only when the digest-bound installed runner has the exact Task 5 pre-load failure, the real process exits nonzero, stdout is empty, both fixed output files are zero length and no success object exists; stderr text alone is insufficient. The durable failure checkpoint may remain as the bounded closed diagnostic, but it is not success evidence. The entrypoint remains unloaded and the precreated result/artifact files remain zero length;
9. in the parent verifier, exact-decode the closed success object with an exact key set and closed value types, recompute its canonical digest, exact-join it to the installed origins, selected source/build inventory, wheel, materialized closure, real process receipt and persisted Runtime checkpoint, and require approval-before-spawn, EXECUTING-before-spawn, one spawn, result-after-spawn, `errno in {EPERM,EACCES}`, real loopback-control success and canary absence. Child/package prose, fake `resource`, a synthetic decoder fixture, exit 0, a standalone boolean or a checkpoint without the joined process facts cannot satisfy a claim;
10. emit only digests/counts/backend/profile digest and `020A_E2M_PASS` after every real prerequisite and join succeeds. Any unsupported/skip/timeout/truncation or prerequisite failure exits nonzero with one closed `020A_E2M_UNAVAILABLE(reason=<closed-code>)` line. The `resource_limit_as_unavailable` branch additionally proves zero script load, empty child result/artifact files and absent success evidence. Neither failure branch creates or preserves an acceptance artifact.

- [ ] **Step 5A: Close verifier implementation (6A)**

Run:

```bash
.venv/bin/python -m pytest -q tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py tests/reference/test_020a_operator_structured_sandbox.py tests/reference/test_020a_materialized_verifier.py -rx
.venv/bin/ruff check tests/reference/test_020a_operator_structured_sandbox.py tests/reference/test_020a_materialized_verifier.py tests/kernel/fakes.py scripts/verify_020a_materialized.py
git diff --check
```

Expected: tests/Ruff/diff exit 0 with zero skips. On a host where the frozen limiter is unavailable, the subprocess tests pass by proving the exact nonzero closed branch and its zero-load/zero-success-artifact facts; they do not convert that branch into E2/E2M PASS. This closes only 6A.

- [ ] **Step 5B: Run the real qualification gate (6B)**

Run the missing-prerequisite probe and then the release-harness command:

```bash
.venv/bin/python scripts/verify_020a_materialized.py --source-root .
.venv/bin/python scripts/verify_020a_materialized.py --source-root . --skill-runtime-root "$FIRST_AGENT_020A_RELEASE_RUNTIME_ROOT"
```

The first command must exit nonzero with `020A_E2M_UNAVAILABLE(reason=release_runtime_root_unavailable)` and create no build/evidence/acceptance artifact. `FIRST_AGENT_020A_RELEASE_RUNTIME_ROOT` is a task-specific shell value supplied by the release harness and expanded into the explicit CLI argument; the verifier never reads that environment name and never forwards it to the child.

6B is Green only when the second command has an untruncated exit 0 and final `020A_E2M_PASS`, the decoded facts prove the full real Runtime/Seatbelt/closure/rlimit/evidence join, and the release harness records that the supplied root is its application-release runtime rather than a verifier fixture. The verifier does not mint release authority from a path alone. On the current Darwin baseline the required result is instead nonzero `020A_E2M_UNAVAILABLE(reason=resource_limit_as_unavailable)` with zero script load, zero success-evidence/acceptance-artifact generation and zero-length child result/artifact files. Record `verifier implemented; qualification unavailable`; do not mark Task 6 fully complete, do not create promotion evidence, and do not start Task 7. A fake resource, synthetic closure, editable/current-venv run or decoder fixture cannot satisfy 6B.

- [ ] **Step 6: Commit verifier implementation when authorized**

```bash
git add tests/reference/test_020a_operator_structured_sandbox.py tests/reference/test_020a_materialized_verifier.py tests/kernel/fakes.py scripts/verify_020a_materialized.py
git commit -m "test(020a): add materialized structured sandbox verifier"
```

---

### Task 7: Run three fresh real-Seatbelt journeys and final gates

**Blocking prerequisite:** Do not begin Task 7, create/update either acceptance path, or run an E3 attempt until Task 6B has a fresh real `020A_E2M_PASS` from an explicit application-release runtime root. `verifier implemented; qualification unavailable` is not sufficient. In particular, `resource_limit_as_unavailable`, `release_runtime_root_unavailable`, any other Task 6 unavailable reason, a synthetic closure, fake `resource`, editable/current-venv execution or a source-tree fixture keeps Task 7 and every promotion claim blocked. No later limiter identity, qualification, stage or activation may be minted from those substitutes.

**Files:**
- Create: `scripts/run_020a_e3.py`
- Create: `tests/reference/test_020a_e3_runner.py`
- Create: `docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3.md`
- Create: `docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3_RECEIPT.json`

**Interfaces:**
- Consumes the materialized wheel and tracked synthetic no-op package fixture only; its Skill runtime is the explicit application-release closure retained from Task 6B, never a synthetic runtime fixture.
- Produces one secret-free local OS-bound acceptance receipt; it does not promote 020b/021/PDF capabilities.
- Consumes the Task 6 selected source/build inventory, non-editable wheel, explicit materialized application-release runtime and installed-driver evidence from the same successful 6B run; it cannot rebuild them through a second verifier authority.

- [ ] **Step 1: Freeze E3 runner Reds**

`tests/reference/test_020a_e3_runner.py` requires exactly three fresh attempts. All attempts use the same canonical approved policy `temp_root`, prepared command, request bytes and policy digest, so the outer digest is identical. Each attempt uses a distinct random session child path, action ID and enforcement profile digest; the random child path never enters command/policy/outer identity. Require these claims per attempt:

```python
EXPECTED_CLAIMS = {
    "one_run_turn_owner",
    "one_tool_runtime_owner",
    "approval_before_spawn",
    "executing_before_spawn",
    "result_checkpoint_after_spawn",
    "operator_args_not_projected",
    "model_guess_denied",
    "fixed_session_entries",
    "outer_digest_stable",
    "real_seatbelt_confined",
    "workspace_read_denied",
    "network_connect_denied",
    "fork_denied",
    "descendant_exec_denied",
    "third_output_denied",
    "hard_limits_observed",
    "process_group_reaped",
    "closed_environment_canary_absent",
}
```

Consume the source/build inventory constants owned by the Task 6 verifier; repeat their exact values in the E3 Red so a drift between the two scripts fails:

```python
GENERATED_ACCEPTANCE_PATHS = frozenset({
    "docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3.md",
    "docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3_RECEIPT.json",
})
SOURCE_BUILD_DIGEST_DOMAIN = "020a-source-build-inventory-v1"
```

`source_build_inventory_digest` hashes the byte-sorted `(relative_path, mode, size, sha256)` inventory of exact tracked working-tree files after removing exactly `GENERATED_ACCEPTANCE_PATHS`. The temporary wheel build context uses that same selected inventory; generated acceptance prose/receipt are neither copied nor hashed. Reject any other difference between selected inventory and build context. Receipt schema is exact: `schema`, `source_build_inventory_digest`, `wheel_digest`, `runtime_closure_digest`, `attempts`, `accepted`. Attempts contain only IDs/digests/booleans/counts/closed outcomes. Add a rerun-stability Red: changing either generated acceptance file leaves the inventory digest unchanged, while changing any selected production/test/plan input changes it.

- [ ] **Step 2: Implement bounded three-attempt runner**

`scripts/run_020a_e3.py` requires explicit `--skill-runtime-root`, calls the materialized verifier once while retaining its fresh tracked-only build context, non-editable venv, wheel and separately materialized Skill runtime under one runner-owned temp root, then launches three fresh installed-process journeys from that same materialization. It uses no provider, external network or credential configuration; the only socket is the proven host loopback control. Each attempt has a hard 180-second deadline and reloads durable checkpoints to compute claims; it cannot trust printed success text from the child or package. Exact-compare the canonical policy temp parent across attempts, reject equal session child/profile digests, and require equal outer digests. Write receipt atomically only after all claims are true. Any failed attempt removes a prior accepted receipt and exits nonzero with `020A_E3_BLOCKED(reason=<closed-code>)`.

If the retained Task 6 run is unavailable, the E3 runner must stop before attempt 1, remove any prior accepted receipt, and preserve the specific closed cause such as `020A_E3_BLOCKED(reason=resource_limit_as_unavailable)` or `020A_E3_BLOCKED(reason=release_runtime_root_unavailable)`. It must not turn a Task 6 structural fixture or closed diagnostic into an attempt record.

`docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3.md` states this is local OS-bound foundation acceptance only. It does not claim package lifecycle, active executable Skills or artifact format value.

- [ ] **Step 3: Run focused, full, materialized and E3 gates**

Run in this order and preserve untruncated exit status:

```bash
.venv/bin/python -m pytest -q tests/kernel/test_operator_tool_exposure.py tests/kernel/test_operator_tool_action.py tests/continuity/test_operator_tool_checkpoint.py tests/continuity/test_operator_tool_context_privacy.py tests/sandbox/test_structured_contracts.py tests/sandbox/test_structured_session.py tests/sandbox/test_structured_executor.py tests/sandbox/test_packaged_policy.py tests/sandbox/test_packaged_policy_real.py tests/sandbox/test_hermetic_runtime.py tests/sandbox/test_packaged_runner.py tests/reference/test_020a_operator_structured_sandbox.py tests/reference/test_020a_materialized_verifier.py tests/reference/test_020a_e3_runner.py -rx
git diff --check
.venv/bin/ruff check .
.venv/bin/python -m pytest -q -rx
.venv/bin/python scripts/verify_020a_materialized.py --source-root . --skill-runtime-root "$FIRST_AGENT_020A_RELEASE_RUNTIME_ROOT"
.venv/bin/python scripts/run_020a_e3.py --source-root . --skill-runtime-root "$FIRST_AGENT_020A_RELEASE_RUNTIME_ROOT" --attempts 3
```

Promotion-run expected: every command exits 0; real-policy suite has zero skips; the Task 6 command returns a fresh real `020A_E2M_PASS`; and the receipt has exactly three accepted attempts. Any focused/full failure stops before E2M. Any Task 6 unavailable result stops before E3 and leaves Task 7 incomplete with no accepted receipt. On the current Darwin limiter baseline, the materialized command must exit nonzero with `resource_limit_as_unavailable`; `run_020a_e3.py` must not be used to bypass that gate. Any selected source/build inventory change after E3 invalidates source/wheel digests and requires rerunning affected focused, full, E2M and E3 gates. Re-rendering only the two generated acceptance paths does not change that digest and is covered by the rerun-stability test.

- [ ] **Step 4: Run architectural and secrecy scans**

```bash
rg -n "class .*Runtime|def .*loop|service_locator|fallback|shell=True|subprocess\.(run|Popen)|os\.system" agent/runtime agent/sandbox first_agent_skill_runner
rg -n "request_bytes|artifact_bytes|owner/private|source\.skillpkg" docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3_RECEIPT.json
rg -n "StoredPackageV1|QualificationRecordV1|ActiveSkillSetV1|SkillActivationGate|build_packaged_skill_registrations|PackagedSkillExecutionAdapter" agent/runtime agent/sandbox first_agent_skill_runner
```

Expected: the first scan shows only the existing `AgentRuntime`/process runner and explicitly reviewed safe matches; receipt secrecy scan has no output; lifecycle/020b ownership scan has no output.

- [ ] **Step 5: Commit when authorized**

```bash
git add scripts/run_020a_e3.py tests/reference/test_020a_e3_runner.py docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3.md docs/acceptance/020A_OPERATOR_STRUCTURED_SANDBOX_E3_RECEIPT.json
git commit -m "test(020a): record real structured sandbox acceptance"
```

## Verification Matrix

| Layer | Required evidence | Failure meaning |
| --- | --- | --- |
| E1 contracts | closed enum/action/digest/recursive-freeze/session/rlimit tests | interface is not safe to compose |
| E1 security | no-follow inode attacks, malformed/truncated/extra output, root overlap, runner preflight | structured or strict boundary is incomplete |
| Verifier implementation | tracked-only build, non-editable isolated install, installed origins, explicit release-root admission/materialization, closed evidence decoder and exact unavailable branches | implementation may be complete while qualification remains unavailable |
| E2 Runtime | real `AgentRuntime` + `KernelToolRuntime` + approval + checkpoint + one real Seatbelt child with every frozen hard limit applied | direct helper/fake/synthetic fixture cannot replace this evidence; limiter unavailable means no E2 |
| E2 recovery | restart at approval and EXECUTING, exact replay, zero auto-respawn | unknown outcome semantics are broken |
| E2M | explicit application-release runtime root, tracked-only non-editable wheel, neutral cwd, installed origins, real denial probes and exact evidence/checkpoint/process join | source-tree/current-venv/synthetic success or any unavailable reason cannot be promoted |
| E3 local OS | 3 fresh attempts over the tracked synthetic no-op package, explicit release runtime, real Seatbelt and durable claim recomputation | no 020a acceptance; 020b/021 remain blocked |
| Full regression | Ruff, full pytest, diff check | no completion while any existing kernel capability regresses |

## Explicitly Rejected Designs

- A second `OperatorRuntime`, lifecycle loop, maintenance conversation or direct `KernelToolRuntime.invoke` CLI path: breaks the sole loop/admission owners and splits replay/recovery.
- An `execute(path, command, env)` generic sandbox API: lets manifest/model smuggle process authority and bypasses per-entrypoint `ToolSpec`.
- Adding `profile="packaged"` to current `SandboxPolicyV1` with permissive defaults: changes existing policy/lease digests and risks allow-default fallback.
- A separate `PackagedSkillExecutor`: duplicates confinement/process ownership; structured work belongs around the existing `NativeSandboxExecutor` call.
- Importing package code into the Agent process or using ambient product/system Python: violates hermetic child isolation and makes dependency drift unprovable.
- Passing random session paths in argv or command fingerprint: makes approval/replay authority nondeterministic; session randomness belongs only to profile enforcement facts.
- Letting child create output/scratch names or write a directory subtree: defeats fixed-inode readback and makes archive/parser scratch behavior unqualified.
- Treating malformed/missing/replaced output as `KnownNotExecuted`: process already ran; it must be an executed error with receipt, while cleanup uncertainty remains unknown recovery.
- Serializing structured bytes into checkpoint/event/receipt: violates owner-private/bounded context and makes durable state capacity depend on artifacts.
- Defining 021 identities or 020b registration/adapter seams in 020a: creates competing owners and cyclic plan dependencies.

## v1 Completion Boundary

020a v1 is complete only when operator action governance, structured fixed session, outer digest, strict Seatbelt policy, exact hermetic closure, hard-limited runner, real E2, materialized E2M and three-attempt local E3 all pass. A completed Task 6A verifier with Task 6B `resource_limit_as_unavailable` or `release_runtime_root_unavailable` is an honest implementation checkpoint, not 020a completion. While 6B is unavailable, Task 7/E3, promotion and every downstream limiter-bound qualification/stage/activation remain blocked. 020a still registers zero production executable Skills. Package lifecycle, active snapshot, manifest decoding, per-entrypoint production registrations, typed source receipts, workspace artifact commit and PDF/Office/image capabilities remain owned by 021/020b/later plans.
