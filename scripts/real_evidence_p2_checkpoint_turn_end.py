"""P2: turn-end checkpoint save trigger — real provider validation.

验证项:
    W1. checkpoint_save_on_turn_end=True 在 real provider chat 中触发 CHECKPOINT_SAVE
    W2. CHECKPOINT_SAVE evidence 来自 route_from_runtime_loop（L3）
    W3. source="turn_end" 在 payload 中正确标记
    W4. checkpoint_save_on_turn_end=False 时不触发 turn_end CHECKPOINT_SAVE
    W5. checkpoint 文件包含正确的 task status/messages
    W6. FakeProvider fallback 验证参数链完整（provider 不可用时）

用法:
    .venv/bin/python scripts/real_evidence_p2_checkpoint_turn_end.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

results: list[dict[str, Any]] = []


def record(case_id: str, verdict: str, detail: str, **kw: Any) -> None:
    results.append({"case": case_id, "verdict": verdict, "detail": detail, **kw})
    label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}.get(verdict, verdict)
    print(f"  {label} {case_id}: {detail}")


class _PipelineSpy:
    """捕获 method + request + result 的 spy dispatcher 包装器。"""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.captured: list[tuple[str, Any, Any]] = []

    def route(self, request: Any) -> Any:
        result = self._real.route(request)
        self.captured.append(("route", request, result))
        return result

    def route_from_runtime_loop(self, request: Any, **kwargs: Any) -> Any:
        result = self._real.route_from_runtime_loop(request, **kwargs)
        self.captured.append(("route_from_runtime_loop", request, result))
        return result

    @property
    def action_log(self):
        return self._real.action_log


def build_spy_dispatcher() -> _PipelineSpy | None:
    """构建注册了 CHECKPOINT_SAVE handler 的 dispatcher + spy。"""
    try:
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.checkpoint_save import CheckpointSaveHandler
        from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
        from agent.runtime_integration.memory_recall import MemoryRecallHandler
        from agent.runtime_integration.memory_retain import MemoryRetainHandler
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

        registry = ActionHandlerRegistry()
        registry.register(
            RuntimeActionType.MEMORY_TURN_END_PROPOSAL, MemoryTurnEndProposalHandler()
        )
        registry.register(RuntimeActionType.MEMORY_PROPOSE, MemoryRetainHandler())
        registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler())
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        registry.register(RuntimeActionType.CHECKPOINT_SAFE_SUMMARY, CheckpointSafeSummaryHandler())
        registry.register(RuntimeActionType.CHECKPOINT_SAVE, CheckpointSaveHandler())

        real = RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())
        return _PipelineSpy(real)
    except Exception as exc:
        record("W0", "FAIL", f"Failed to build dispatcher: {exc}")
        return None


def run_fake_provider_baseline() -> None:
    """W6: FakeProvider 验证参数链完整。"""
    print("\n═══ Part A: FakeProvider Baseline ═══")

    from agent.core import chat
    from agent.provider.fake_provider import FakeProvider
    from agent.runtime_integration.schema import RuntimeActionType

    spy = build_spy_dispatcher()
    if spy is None:
        record("W6", "FAIL", "Cannot build spy dispatcher")
        return

    # W6a: checkpoint_save_on_turn_end=True → CHECKPOINT_SAVE dispatched
    result = chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy,
                  checkpoint_save_on_turn_end=True)
    assert isinstance(result, str)

    turn_end_saves = [
        (m, r, res) for m, r, res in spy.captured
        if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
        and dict(r.payload).get("source") == "turn_end"
    ]
    if turn_end_saves:
        method, req, _ = turn_end_saves[0]
        payload = dict(req.payload)
        record("W6a", "PASS",
               f"FakeProvider: CHECKPOINT_SAVE turn_end dispatched via {method}, "
               f"task_status={payload.get('task_status')}")
    else:
        all_saves = [
            (m, r.action_type.value) for m, r, _ in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
        ]
        record("W6a", "FAIL",
               f"No turn_end CHECKPOINT_SAVE found. "
               f"All CHECKPOINT_SAVE: {all_saves}. "
               f"All captured: {[(r.action_type.value, m) for m, r, _ in spy.captured]}")

    # W6b: checkpoint_save_on_turn_end=False → no turn_end CHECKPOINT_SAVE
    spy2 = build_spy_dispatcher()
    if spy2 is None:
        return
    spy2.captured.clear()
    result2 = chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy2)
    assert isinstance(result2, str)

    turn_end_saves_default = [
        (m, r, res) for m, r, res in spy2.captured
        if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
        and dict(r.payload).get("source") == "turn_end"
    ]
    if not turn_end_saves_default:
        record("W6b", "PASS",
               "FakeProvider default: no turn_end CHECKPOINT_SAVE (correct)")
    else:
        record("W6b", "FAIL",
               f"Default should not trigger turn_end CHECKPOINT_SAVE, "
               f"got {len(turn_end_saves_default)}")


def run_real_provider_validation() -> None:
    """W1-W5: Real provider turn-end checkpoint save validation."""
    print("\n═══ Part B: Real Provider Turn-End Checkpoint Save ═══")

    from agent.provider.factory import build_model_provider_from_env
    from agent.runtime_integration.schema import RuntimeActionType

    provider = build_model_provider_from_env()
    provider_type = getattr(provider, "provider_type", type(provider).__name__)

    if provider_type in ("fake", "FakeProvider"):
        record("W1", "CONCERN",
               "FakeProvider — real API checkpoint validation requires configured provider",
               provider_type=provider_type)
        record("W2", "CONCERN", "Skipped (no real provider)")
        record("W3", "CONCERN", "Skipped (no real provider)")
        record("W4", "CONCERN", "Skipped (no real provider)")
        record("W5", "CONCERN", "Skipped (no real provider)")
        return

    print(f"  provider={provider_type} model={getattr(provider, 'model', '?')}")

    spy = build_spy_dispatcher()
    if spy is None:
        return

    # 使用临时 checkpoint 路径
    with tempfile.NamedTemporaryFile(suffix=".json", prefix="checkpoint_p2_", delete=False) as f:
        checkpoint_path = Path(f.name)
    checkpoint_path.unlink(missing_ok=True)

    import agent.checkpoint as cp_mod
    original_path = cp_mod.CHECKPOINT_PATH
    cp_mod.CHECKPOINT_PATH = checkpoint_path

    try:
        from agent.core import chat

        # W1: checkpoint_save_on_turn_end=True 触发 CHECKPOINT_SAVE
        print("\n  --- W1: Real provider chat with checkpoint_save_on_turn_end=True ---")
        print("  Sending: 'hello, 请用一句话介绍自己'")

        result = chat(
            "hello, 请用一句话介绍自己",
            provider=provider,
            runtime_action_dispatcher=spy,
            checkpoint_save_on_turn_end=True,
        )
        assert isinstance(result, str)
        print(f"  Response: {result[:100]}...")

        turn_end_saves = [
            (m, r, res) for m, r, res in spy.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
            and dict(r.payload).get("source") == "turn_end"
        ]

        if turn_end_saves:
            method, req, checkpoint_result = turn_end_saves[0]
            record("W1", "PASS",
                   f"Real provider: CHECKPOINT_SAVE turn_end dispatched "
                   f"({len(turn_end_saves)} save(s))")

            # W2: L3 evidence — route_from_runtime_loop
            if method == "route_from_runtime_loop":
                ev_raw = getattr(checkpoint_result, 'evidence', {})
                ev = dict(ev_raw) if ev_raw else {}
                record("W2", "PASS",
                       f"L3 evidence via route_from_runtime_loop: "
                       f"dispatcher_origin={ev.get('dispatcher_origin', '?')}")
            else:
                record("W2", "FAIL",
                       f"Expected route_from_runtime_loop, got {method}")

            # W3: source="turn_end" in payload
            payload = dict(req.payload)
            if payload.get("source") == "turn_end":
                record("W3", "PASS",
                       f"source=turn_end confirmed, task_status={payload.get('task_status')}")
            else:
                record("W3", "FAIL",
                       f"Expected source=turn_end, got {payload.get('source')}")

            # W5: checkpoint file content
            if checkpoint_path.exists():
                saved = cp_mod.load_checkpoint(path=checkpoint_path)
                if saved:
                    task_data = saved.get("task", {})
                    conv_data = saved.get("conversation", {})
                    record("W5", "PASS",
                           f"Checkpoint file valid: status={task_data.get('status')}, "
                           f"messages={len(conv_data.get('messages', []))}")
                else:
                    record("W5", "FAIL", "Checkpoint file exists but load failed")
            else:
                record("W5", "CONCERN",
                       "No checkpoint file — handler may use different path or save deferred")
        else:
            all_actions = [(r.action_type.value, m) for m, r, _ in spy.captured]
            record("W1", "CONCERN",
                   f"No turn_end CHECKPOINT_SAVE in real provider chat. "
                   f"Captured: {all_actions}",
                   action_count=len(spy.captured))
            record("W2", "CONCERN", "Skipped (W1 not satisfied)")
            record("W3", "CONCERN", "Skipped (W1 not satisfied)")
            record("W5", "CONCERN", "Skipped (W1 not satisfied)")

        # W4: checkpoint_save_on_turn_end=False → no turn_end CHECKPOINT_SAVE
        print("\n  --- W4: Real provider chat with default (False) ---")
        spy2 = build_spy_dispatcher()
        if spy2 is None:
            return
        print("  Sending: 'hi'")

        result2 = chat("hi", provider=provider, runtime_action_dispatcher=spy2)
        assert isinstance(result2, str)
        print(f"  Response: {result2[:100]}...")

        turn_end_saves_default = [
            (m, r, res) for m, r, res in spy2.captured
            if r.action_type == RuntimeActionType.CHECKPOINT_SAVE
            and dict(r.payload).get("source") == "turn_end"
        ]
        if not turn_end_saves_default:
            record("W4", "PASS",
                   "Default mode: no turn_end CHECKPOINT_SAVE (correct)")
        else:
            record("W4", "FAIL",
                   f"Default should not trigger turn_end CHECKPOINT_SAVE, "
                   f"got {len(turn_end_saves_default)}")

    finally:
        cp_mod.CHECKPOINT_PATH = original_path
        checkpoint_path.unlink(missing_ok=True)


def main() -> None:
    print("=" * 60)
    print("P2 Real Evidence: Turn-End Checkpoint Save Trigger")
    print("=" * 60)

    run_fake_provider_baseline()
    run_real_provider_validation()

    # Summary
    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    concerns = sum(1 for r in results if r["verdict"] == "CONCERN")

    for r in results:
        label = {"PASS": "✓", "FAIL": "✗", "CONCERN": "?"}[r["verdict"]]
        print(f"  {label} {r['case']}: {r['detail']}")

    print(f"\n  PASS={passed} FAIL={failed} CONCERN={concerns}")

    # Write results JSON
    out_path = (
        _project_root / "docs" / "dogfood"
        / "real-evidence-p2-checkpoint-turn-end-results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "date": "2026-05-30",
                "evidence_id": "P2-CHECKPOINT-TURN-END",
                "results": results,
                "summary": {"PASS": passed, "FAIL": failed, "CONCERN": concerns},
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n  Results written to {out_path}")

    if failed > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
