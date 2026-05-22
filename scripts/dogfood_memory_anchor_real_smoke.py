#!/usr/bin/env python3
"""Memory Proposal Anchor real provider smoke dogfood runner.

中文学习边界：
这个脚本是 Memory Anchor real provider smoke 的端到端狗粮验证——通过 core.chat()
+ 真实 LLM provider 验证全链路，证明 fake/real 共享同一条 core.chat() →
run_main_loop() → turn-end hook 路径。

fake/real 共享检查模块 ``_dogfood_memory_anchor_checks.py``，差异仅在于：
- provider 构造（FakeProvider vs build_model_provider_from_env）
- 授权门控（fake 默认安全，real 需显式 opt-in）
- expected metadata 值（provider_kind=fake vs real 等）

约束：
- 需 MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 显式 opt-in
- --project-dotenv-only / --no-shell-env-fallback 强制仅从 project .env 加载 key
- 不读 .env 内容（到 stdout/stderr/report）
- 不打印 API key 到 stdout/stderr/report
- 不打印实际环境变量名到 report（key_source_kind 只用固定枚举）
- Report 仅含安全字段：auth_status, key_source_kind, project_dotenv_loaded, shell_env_fallback_used
- 不写 human_approved
- 不 auto approve
- 不读取 memory/episodes/*.jsonl
- 不改 Memory governance
- 不新增 real-only loop/dispatcher
- 报告输出到 /private/tmp 的临时目录（tempfile.mkdtemp）

Exit codes:
  0 = PASS
  1 = FAIL
  2 = BLOCKED（未授权、auth 缺失、API key 未配置、shell_env_fallback 被拒绝）

架构依据：docs/plans/2026-05-22-001-feat-memory-anchor-real-smoke-plan.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 共享检查模块
from scripts._dogfood_memory_anchor_checks import (  # noqa: E402
    build_action_detail_lines,
    build_overclaim_prevention_section,
    check_memory_anchor_evidence,
)

# ── 授权门控 ──

_AUTH_ENV = "MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE"

_UNAUTHORIZED_MESSAGE = """\
⚠️  Real Provider Smoke 需要你的明确授权。

这会：
- 调用真实 LLM/API（会消耗 token）
- 不会写 memory episodes
- 不会 auto approve memory
- 不会写 human_approved
- 不会写 checkpoint
- 不会执行工具

授权方式：
  export MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1

推荐使用 project-dotenv-only 模式（仅从项目 .env 加载 key）：
  MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 \\
    .venv/bin/python scripts/dogfood_memory_anchor_real_smoke.py \\
    --project-dotenv-only

可用选项：
  --project-dotenv-only      仅从项目 .env 加载 API key，拒绝 shell env fallback
  --no-shell-env-fallback    同 --project-dotenv-only
  --help                     显示本帮助"""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数——在授权门控前处理 --help。"""
    parser = argparse.ArgumentParser(
        description="Memory Anchor Real Provider Smoke Dogfood",
        add_help=False,
    )
    parser.add_argument(
        "--project-dotenv-only",
        action="store_true",
        default=False,
        help="仅从项目 .env scoped loader 加载 API key，拒绝 shell env fallback",
    )
    parser.add_argument(
        "--no-shell-env-fallback",
        action="store_true",
        default=False,
        help="同 --project-dotenv-only",
    )
    parser.add_argument(
        "--help",
        action="store_true",
        default=False,
        help="显示帮助信息",
    )
    return parser.parse_args(argv)


def _check_auth_gate() -> bool:
    """检查 real provider smoke 授权门控。

    Returns:
        True if authorized, False otherwise
    """
    return os.environ.get(_AUTH_ENV) == "1"


# ── 安全 auth field 派生 ──


def _derive_safe_auth_fields() -> dict[str, Any]:
    """从 scoped loader 派生安全 auth 诊断字段。

    中文学习边界——为什么不用 redacted_summary()：
    - redacted_summary() 包含 api_key_env（实际环境变量名如 "ANTHROPIC_API_KEY"）
      和 provider_type/model/base_url —— 这些不是安全的 report 字段
    - redacted_summary() 的 api_key 字段虽然是 "SET"/"empty" 而非真实 key，
      但 key_source_kind 需要描述的是来源类别（project_dotenv/shell_env），
      不是具体环境变量名
    - Constraint A 明确要求：key_source_kind 只能输出固定枚举，不得输出实际环境变量名

    key_source_kind 固定枚举：
      "project_dotenv" — key 来自项目 .env 文件
      "shell_env"      — key 来自 shell 环境变量
      "missing"        — 未找到 API key
      "unknown"        — 无法确定来源

    Returns:
        dict with safe keys: auth_status, key_source_kind, project_dotenv_loaded,
        shell_env_fallback_used
    """
    import config as legacy_config

    project_root = _PROJECT_ROOT

    # 检查 project .env 是否被加载（通过 _load_project_dotenv_values 读内容，不污染 os.environ）
    project_dotenv_values = legacy_config._load_project_dotenv_values(project_root)
    project_dotenv_loaded = bool(project_dotenv_values)

    # 使用 scoped resolver：优先 project_dotenv，回退 shell_env
    # 返回 (value | None, source_kind: "project_dotenv" | "shell_env" | "missing")
    _key_value, key_source_kind = legacy_config._resolve_scoped_config_value(
        ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"),
        project_root=project_root,
        prefer_project_dotenv=True,
    )

    # auth_status 只从 key 是否存在派生
    auth_status = "authenticated" if _key_value is not None else "unauthenticated"

    # shell_env_fallback_used: project .env 存在但没有 key，退回到 shell env
    shell_env_fallback_used = (
        project_dotenv_loaded
        and key_source_kind == "shell_env"
    )

    return {
        "auth_status": auth_status,
        "key_source_kind": key_source_kind,
        "project_dotenv_loaded": project_dotenv_loaded,
        "shell_env_fallback_used": shell_env_fallback_used,
    }


# ── project-dotenv-only 强制逻辑 ──


def _enforce_project_dotenv_only(
    safe_auth: dict[str, Any],
) -> tuple[bool, str]:
    """检查 project-dotenv-only 约束是否满足。

    中文学习边界——为什么需要 project-dotenv-only 强制：
    - shell env 里的 key 可能是从 shell profile、export、或 external tool 注入的
    - 这些来源不受项目 .env 的 scoped loader 控制，增加了 key 泄露的风险面
    - project-dotenv-only 确保 key 的唯一合法来源是项目 .env 文件
    - 如果 key 来自 shell env（即使值相同），也应当被拒绝

    Returns:
        (ok: bool, reason: str)
    """
    auth_status = safe_auth["auth_status"]
    key_source_kind = safe_auth["key_source_kind"]
    project_dotenv_loaded = safe_auth["project_dotenv_loaded"]
    shell_env_fallback_used = safe_auth["shell_env_fallback_used"]

    # 项目 .env 未找到
    if not project_dotenv_loaded:
        return False, (
            "project .env not found or empty — "
            "project-dotenv-only requires loading API key from project .env"
        )

    # key 来自 shell env 而非 project .env
    if key_source_kind == "shell_env":
        if shell_env_fallback_used:
            return False, (
                "shell_env_fallback detected: project .env loaded but does not "
                "contain ANTHROPIC_API_KEY/OPENAI_API_KEY — key found in shell env instead"
            )
        return False, (
            f"key_source_kind is '{key_source_kind}' — "
            "project-dotenv-only requires key from project .env"
        )

    # key 缺失
    if key_source_kind == "missing":
        return False, (
            "no API key found in project .env — "
            "set ANTHROPIC_API_KEY or OPENAI_API_KEY in project .env"
        )

    # key 来自 project .env——验证通过
    if key_source_kind == "project_dotenv" and auth_status == "authenticated":
        return True, ""

    return False, (
        f"unexpected auth state: auth_status={auth_status}, "
        f"key_source_kind={key_source_kind}"
    )


# ── Provider 构造 ──


def _inject_project_dotenv_into_os_environ() -> None:
    """将 project .env 的值注入 os.environ（仅设置尚未存在的 key）。

    中文学习边界——为什么在 provider 构造前需要这一步：
    - agent/provider/factory.py 的 build_model_provider_from_env() 和
      load_agent_provider_config() 从 os.environ 读取 API key
    - _derive_safe_auth_fields 使用的 _load_project_dotenv_values 只读取内容用于诊断，
      不注入 os.environ——这是刻意隔离，避免诊断路径污染全局环境
    - 因此需要在本函数中显式将 project .env 注入 os.environ，供 provider 工厂使用
    - 只设置尚未在 os.environ 中存在的 key——不覆盖用户显式设置的环境变量
      （但 project-dotenv-only 模式已在外层拒绝 shell env key，所以实际不会冲突）
    """
    import config as legacy_config

    dotenv_vals = legacy_config._load_project_dotenv_values(_PROJECT_ROOT)
    if not dotenv_vals:
        return
    for k, v in dotenv_vals.items():
        if k not in os.environ and v is not None:
            os.environ[k] = v


def _build_real_provider() -> Any:
    """构造真实 LLM provider。

    前置条件：project .env 必须已注入 os.environ（由 main() 中的注入步骤保证）。

    Returns:
        ModelProvider instance

    Raises:
        ProviderConfigurationError: API key 缺失或配置无效
    """
    from agent.provider.factory import build_model_provider, build_model_provider_from_env

    provider = build_model_provider_from_env()
    if provider is not None:
        return provider

    from agent.provider.config import load_agent_provider_config

    config = load_agent_provider_config()
    return build_model_provider(config)


def _build_phase1_dispatcher() -> Any:
    """构建 Phase 1 RuntimeActionDispatcher。"""
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    return build_phase1_dispatcher()


# ── Dogfood 主逻辑 ──


def _run_memory_anchor_real_smoke_dogfood(
    safe_auth: dict[str, Any],
) -> dict[str, Any]:
    """执行一次 Memory Anchor real provider smoke dogfood。

    走 core.chat() + real provider + build_phase1_dispatcher() 路径。
    与 fake dogfood 使用同一套共享检查逻辑。

    Returns:
        dict with: status, chat_result, action_count, actions, errors,
                   pass_checks, fail_checks, safe_auth
    """
    from agent.core import chat

    errors: list[str] = []
    api_error_redacted: str | None = None

    # 构造 real provider
    try:
        provider = _build_real_provider()
    except Exception as exc:
        # 脱敏：exception message 可能包含 API key env var name 等信息
        # 只输出 exception type，不输出 message 内容
        error_type = type(exc).__name__
        # 白名单：只允许已知的 safe error types
        if error_type in (
            "ProviderConfigurationError",
            "ProviderNotImplementedError",
            "ProviderConnectionError",
        ):
            api_error_redacted = f"provider construction failed: {error_type}"
        else:
            api_error_redacted = "provider construction failed: internal error"
        errors.append(api_error_redacted)
        return {
            "status": "BLOCKED",
            "chat_result": "",
            "action_count": 0,
            "actions": [],
            "errors": errors,
            "pass_checks": [],
            "fail_checks": ["provider_construction"],
            "safe_auth": safe_auth,
        }

    dispatcher = _build_phase1_dispatcher()

    # 调用 core.chat()——与 fake 完全相同的入口
    try:
        result = chat(
            "hello",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        # 脱敏：不输出 exception message（可能包含 API key / header / raw env）
        error_type = type(exc).__name__
        api_error_redacted = f"chat() failed: {error_type}"
        errors.append(api_error_redacted)
        return {
            "status": "FAIL",
            "chat_result": "",
            "action_count": 0,
            "actions": [],
            "errors": errors,
            "pass_checks": [],
            "fail_checks": ["chat_completed"],
            "safe_auth": safe_auth,
        }

    # 收集 action_log evidence
    action_log = list(dispatcher.action_log)
    actions = []
    for event in action_log:
        evidence = dict(event.evidence)
        actions.append({
            "action_id": event.action_id,
            "action_type": str(event.action_type),
            "source": event.source,
            "status": event.status,
            "evidence_level": evidence.get("evidence_level", ""),
            "core_loop_invoked": evidence.get("core_loop_invoked"),
            "core_entrypoint": evidence.get("core_entrypoint"),
            "runtime_hook_name": evidence.get("runtime_hook_name"),
            "provider_kind": evidence.get("provider_kind"),
            "provider_external_call": evidence.get("provider_external_call"),
            "external_side_effects": evidence.get("external_side_effects"),
            "target_module": evidence.get("target_module"),
            "target_module_proof_exists": evidence.get("target_module_proof") is not None,
            "disposition": evidence.get("disposition"),
            "pending_review": evidence.get("pending_review"),
            "auto_approved": evidence.get("auto_approved"),
            "not_confirmed": evidence.get("not_confirmed"),
            "real_episodes_read": evidence.get("real_episodes_read"),
            "secret_like_detected": evidence.get("secret_like_detected"),
            "no_silent_retain": evidence.get("no_silent_retain"),
        })

    # ── PASS 标准检查（使用共享检查模块，real smoke expected 值） ──
    check_result = check_memory_anchor_evidence(
        actions,
        expected_provider_kind="real",
        expected_provider_external_call=True,
        expected_external_side_effects=False,
        pre_existing_errors=errors,
    )

    pass_checks = check_result["pass_checks"]
    fail_checks = check_result["fail_checks"]
    errors = check_result["errors"]

    # C1: chat() 正常完成
    pass_checks.insert(0, "chat_completed")

    # C13: no errors
    if not errors:
        pass_checks.append("no_errors")

    # 状态判定：PASS / PARTIAL / FAIL
    if not fail_checks and not errors:
        status = "PASS"
    elif actions and not errors:
        status = "PARTIAL"
    elif api_error_redacted and "provider construction failed" in api_error_redacted:
        status = "BLOCKED"
    else:
        status = "FAIL"

    return {
        "status": status,
        "chat_result": result[:200] if result else "",
        "action_count": len(actions),
        "actions": actions,
        "errors": errors,
        "pass_checks": pass_checks,
        "fail_checks": fail_checks,
        "safe_auth": safe_auth,
    }


# ── 报告生成 ──


def _build_report(report: dict[str, Any]) -> str:
    """生成人类可读 real smoke dogfood 报告。

    安全边界：
    - 不包含 API key
    - 不包含实际环境变量名（key_source_kind 只用固定枚举）
    - safe_auth 块仅含 4 个白名单字段
    """
    safe_auth = report.get("safe_auth", {})

    lines = [
        "=" * 60,
        "Memory Proposal Anchor Real Provider Smoke Dogfood Report",
        "=" * 60,
        "",
        f"Status: {report['status']}",
        f"Chat result preview: {report['chat_result']}",
        f"RuntimeActions triggered: {report['action_count']}",
        "",
        "--- Safe Auth Diagnostics ---",
        f"  auth_status: {safe_auth.get('auth_status', 'unknown')}",
        f"  key_source_kind: {safe_auth.get('key_source_kind', 'unknown')}",
        f"  project_dotenv_loaded: {safe_auth.get('project_dotenv_loaded', 'unknown')}",
        f"  shell_env_fallback_used: {safe_auth.get('shell_env_fallback_used', 'unknown')}",
        "",
    ]

    # PASS/FAIL checks
    if report["pass_checks"]:
        lines.append("PASS CHECKS:")
        for c in report["pass_checks"]:
            lines.append(f"  [x] {c}")
        lines.append("")

    if report["fail_checks"]:
        lines.append("FAIL CHECKS:")
        for c in report["fail_checks"]:
            lines.append(f"  [ ] {c}")
        lines.append("")

    if report["errors"]:
        lines.append("ERRORS:")
        for err in report["errors"]:
            lines.append(f"  - {err}")
        lines.append("")

    # Per-event details
    lines.extend(build_action_detail_lines(report["actions"]))

    # Overclaim prevention
    lines.append(build_overclaim_prevention_section())
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"Result: {report['status']}")
    lines.append("=" * 60)

    return "\n".join(lines)


# ── 入口 ──


def main(argv: list[str] | None = None) -> int:
    """运行 Memory Anchor real provider smoke dogfood。

    Exit codes: 0=PASS, 1=FAIL, 2=BLOCKED
    """

    # 0. 解析参数（在授权门控前支持 --help）
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    project_dotenv_only = args.project_dotenv_only or args.no_shell_env_fallback

    if args.help:
        print(_UNAUTHORIZED_MESSAGE, flush=True)
        return 0

    # 1. 授权门控
    if not _check_auth_gate():
        print(_UNAUTHORIZED_MESSAGE, flush=True)
        return 2

    # 2. 安全 auth 诊断（不读 .env，不打印 secret）
    safe_auth = _derive_safe_auth_fields()

    # 2a. project-dotenv-only 强制逻辑
    if project_dotenv_only:
        ok, reason = _enforce_project_dotenv_only(safe_auth)
        if not ok:
            print(f"BLOCKED: project-dotenv-only enforcement failed — {reason}", flush=True)
            print(f"  auth_status: {safe_auth['auth_status']}", flush=True)
            print(f"  key_source_kind: {safe_auth['key_source_kind']}", flush=True)
            print(f"  project_dotenv_loaded: {safe_auth['project_dotenv_loaded']}", flush=True)
            print(f"  shell_env_fallback_used: {safe_auth['shell_env_fallback_used']}", flush=True)
            return 2

    # 2b. 未认证
    if safe_auth["auth_status"] != "authenticated":
        print("BLOCKED: API key not found in environment.", flush=True)
        print(f"  auth_status: {safe_auth['auth_status']}", flush=True)
        print(f"  key_source_kind: {safe_auth['key_source_kind']}", flush=True)
        print(f"  project_dotenv_loaded: {safe_auth['project_dotenv_loaded']}", flush=True)
        print(f"  shell_env_fallback_used: {safe_auth['shell_env_fallback_used']}", flush=True)
        return 2

    # 3. 输出目录（tempfile.mkdtemp 避免可预测路径）
    output_dir = tempfile.mkdtemp(
        prefix="memory_anchor_real_smoke_",
        dir="/private/tmp",
    )
    report_path = os.path.join(output_dir, "report.txt")

    # 4. 将 project .env 注入 os.environ（供 provider 工厂使用）
    #    安全前提：project-dotenv-only 检查（步骤 2a）已确认 key 来自 project .env
    _inject_project_dotenv_into_os_environ()

    print("Memory Proposal Anchor Real Provider Smoke Dogfood", flush=True)
    print(f"Report dir: {output_dir}", flush=True)
    if project_dotenv_only:
        print("Mode: project-dotenv-only (shell env fallback disabled)", flush=True)
    print(flush=True)

    # 5. 执行 dogfood
    report = _run_memory_anchor_real_smoke_dogfood(safe_auth)

    # 6. 输出报告
    report_text = _build_report(report)
    print(report_text, flush=True)

    with open(report_path, "w") as f:
        f.write(report_text)

    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nJSON report: {json_path}", flush=True)

    # 7. Exit code
    status = report["status"]
    if status == "PASS":
        return 0
    elif status == "BLOCKED":
        return 2
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
