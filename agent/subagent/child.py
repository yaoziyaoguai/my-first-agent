"""Process-isolated child entrypoint（``python -m agent.subagent.child``）。

由 ``ChildProcessRunner`` spawn。读取一个 bounded、owner-only/no-follow JSON config（spec +
profile + objective/handoff/parent idempotency key），用 **同一个** ``AgentRuntime``（经
``build_child_runtime``）跑一次 ``run_turn``，把 bounded 结果（status、message）写到 stdout，
然后 exit 0。这是 SubAgent 真实 hard-deadline 路径：parent 拥有本进程的 process group，可在
``hard_deadline_seconds`` 后 killpg 并确认退出——child 是否“自己报告终态”决定 receipt 是
TERMINATED 还是 UNCONFIRMED。

不创建第二套 loop：本模块只 import 并复用 ``agent.runtime.loop.AgentRuntime.run_turn``。
credential 永不跨进程序列化：http spec 只携带 env name，子进程从自身 env 读取值。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from agent.subagent.contracts import MAX_RESULT_ENVELOPE_BYTES

_RESULT_LIMIT_CHARS = 4_000


def _encode_result_envelope(
    status: str,
    message: str,
    *,
    model_calls: int = 0,
    tool_calls: int = 0,
    sources: tuple[dict, ...] = (),
) -> bytes:
    """输出 seam：在共同 8192-byte 预算内输出完整 UTF-8 JSON 结果 bytes。

    先保留现有 ``_RESULT_LIMIT_CHARS`` 产品字符上限，再按**完整 envelope**（JSON 转义 +
    结构开销，``ensure_ascii=False`` + UTF-8 计字节）验证预算；超预算时二分选择满足
    总字节上限的最大 message 字符前缀（前缀每多一个字符，编码字节单调不减，二分安全）。
    绝不直接截断完整 JSON bytes、不切坏 UTF-8/escape、不引入替换字符；短消息原样保留，
    status 不变、不新增协议字段。返回的 bytes 一定是已验证 ≤ 预算的合法 JSON。
    """
    candidate = message[:_RESULT_LIMIT_CHARS]

    def envelope_bytes(prefix: str) -> bytes:
        payload = {"status": status, "message": prefix}
        # v1 单轮、零工具结果保持原 envelope 形状与精确字节边界；只有真正的
        # 多步 child 才附加计数，旧 parent 仍可忽略未知字段。
        if model_calls > 1 or tool_calls > 0 or sources:
            payload.update({"model_calls": model_calls, "tool_calls": tool_calls})
        if sources:
            payload["sources"] = list(sources)
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    blob = envelope_bytes(candidate)
    if len(blob) <= MAX_RESULT_ENVELOPE_BYTES:
        return blob
    lo, hi = 0, len(candidate)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(envelope_bytes(candidate[:mid])) <= MAX_RESULT_ENVELOPE_BYTES:
            lo = mid
        else:
            hi = mid - 1
    return envelope_bytes(candidate[:lo])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        return _die("usage: python -m agent.subagent.child <config_path>")
    config_path = Path(args[0])

    try:
        from agent.subagent.runner import (
            build_child_provider,
            build_child_runtime,
        )
        from agent.subagent.runtime_factory import compose_child_prompt, derive_child_identity

        config = _load_config(config_path)
        spec = _spec_from_config(config["spec"])
        provider = build_child_provider(spec)
        profile = _profile_from_config(config["profile"])
        objective = str(config["objective"])
        handoff = str(config["handoff"])
        parent_key = str(config["parent_idempotency_key"])
        raw_workspace_root = config.get("workspace_root")
        workspace_root = (
            Path(raw_workspace_root).resolve(strict=True)
            if isinstance(raw_workspace_root, str)
            else None
        )
        raw_protected_paths = config.get("protected_paths", [])
        if not isinstance(raw_protected_paths, list) or any(
            not isinstance(item, str) for item in raw_protected_paths
        ):
            raise ValueError("child protected paths must be a string list")
        protected_paths = tuple(
            Path(item).resolve(strict=False) for item in raw_protected_paths
        )
    except Exception:  # noqa: BLE001 - 任何配置/provider 构建失败：不写结果，exit 非 0 → UNCONFIRMED
        return _die("child config or provider build failed")

    from agent.runtime.contracts import SubmitMessage

    child_conversation_id, child_run_id = derive_child_identity(parent_key)
    runtime, store = build_child_runtime(
        provider,
        profile,
        conversation_id=child_conversation_id,
        strict_control_schema=spec.strict_tools,
        workspace_root=workspace_root,
        protected_paths=protected_paths,
    )
    action = SubmitMessage(
        conversation_id=child_conversation_id,
        action_seq=1,
        expected_revision=0,
        run_id=child_run_id,
        message=compose_child_prompt(objective, handoff),
    )
    # run_turn 内部捕获 provider 异常并分类为终态；它正常返回即表示 child 已 terminally 报告。
    result = runtime.run_turn(action, store.load())
    # 写出已验证的完整 UTF-8 JSON bytes：直接写 buffer，不依赖子进程 locale 的 stdout 编码。
    from agent.runtime.contracts import FactKind

    result_state = getattr(result, "state", None)
    from agent.subagent.evidence import verified_child_sources_from_state

    sources = (
        verified_child_sources_from_state(
            result_state,
            workspace_root=workspace_root,
            protected_paths=protected_paths,
        )
        if result_state is not None
        else ()
    )
    blob = _encode_result_envelope(
        result.status.value,
        result.message or "",
        model_calls=getattr(result, "model_calls_used", 0),
        tool_calls=sum(
            fact.kind is FactKind.TOOL_RESULT
            for fact in (() if result_state is None else result_state.facts)
        ),
        sources=tuple(source.to_json() for source in sources),
    )
    sys.stdout.buffer.write(blob)
    sys.stdout.buffer.flush()
    return 0


def _die(message: str) -> int:
    # 不向 stdout 写可解析结果（parent 只接受 exit 0 + 合法 JSON 为 TERMINATED）。
    sys.stderr.write(message + "\n")
    return 1


def _load_config(config_path: Path) -> dict:
    """bounded、no-follow、owner-only 读取 child config JSON。"""
    import stat

    fd = os.open(config_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("child config must be a regular file")
        if info.st_uid != os.getuid():
            raise ValueError("child config must be owner-only")
        if info.st_size > 200_000:
            raise ValueError("child config too large")
        data = b""
        remaining = info.st_size
        while remaining > 0:
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            data += chunk
            remaining -= len(chunk)
    finally:
        os.close(fd)
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("child config must be a JSON object")
    return parsed


def _profile_from_config(raw: dict):
    from agent.subagent.contracts import ChildProfile

    return ChildProfile(
        runner_version=str(raw["runner_version"]),
        provider_profile_id=str(raw["provider_profile_id"]),
        provider_destination=str(raw["provider_destination"]),
        workspace_scope_digest=str(raw["workspace_scope_digest"]),
        max_input_tokens=int(raw["max_input_tokens"]),
        max_output_tokens=int(raw["max_output_tokens"]),
        limits_digest=str(raw["limits_digest"]),
        hard_deadline_seconds=float(raw["hard_deadline_seconds"]),
    )


def _spec_from_config(raw: dict):
    """把 config dict 中的 spec 还原为 ``ChildProviderSpec``。"""
    from agent.subagent.contracts import ChildProviderSpec

    fake_tool = raw.get("fake_tool")
    return ChildProviderSpec(
        kind=str(raw["kind"]),
        fake_text=raw.get("fake_text"),
        fake_tool=(
            (str(fake_tool[0]), dict(fake_tool[1]))
            if isinstance(fake_tool, list) and len(fake_tool) == 2
            else None
        ),
        sleep_seconds=float(raw.get("sleep_seconds", 0.0) or 0.0),
        stderr_chars=int(raw.get("stderr_chars", 0) or 0),
        provider_type=raw.get("provider_type"),
        model=raw.get("model"),
        base_url=raw.get("base_url"),
        credential_env_name=raw.get("credential_env_name"),
        timeout=raw.get("timeout"),
        thinking_mode=raw.get("thinking_mode"),
        request_path=raw.get("request_path"),
        strict_tools=raw.get("strict_tools", False) is True,
        attempt_ledger_path=raw.get("attempt_ledger_path"),
        max_model_attempts=raw.get("max_model_attempts"),
    )


if __name__ == "__main__":
    sys.exit(main())
