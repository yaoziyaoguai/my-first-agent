from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_product_tree_contains_only_kernel_packages() -> None:
    expected = {
        "agent/__init__.py",
        "agent/automation/__init__.py",
        "agent/automation/child.py",
        "agent/automation/claim_verifier.py",
        "agent/automation/cli.py",
        "agent/automation/composition.py",
        "agent/automation/contracts.py",
        "agent/automation/controller.py",
        "agent/automation/management.py",
        "agent/automation/reconcile.py",
        "agent/automation/schedule.py",
        "agent/automation/store.py",
        "agent/automation/supervisor.py",
        "agent/automation/wake.py",
        "agent/automation/workspace.py",
        "agent/automation_hosts/__init__.py",
        "agent/automation_hosts/_posix_fs.py",
        "agent/automation_hosts/_posix_workspace_codec.py",
        "agent/automation_hosts/_posix_workspace_files.py",
        "agent/automation_hosts/launchd.py",
        "agent/automation_hosts/macos_cli.py",
        "agent/automation_hosts/macos_profile.py",
        "agent/automation_hosts/macos_runtime.py",
        "agent/automation_hosts/occurrence_child.py",
        "agent/automation_hosts/posix_repository.py",
        "agent/automation_hosts/posix_storage.py",
        "agent/automation_hosts/posix_supervisor.py",
        "agent/automation_hosts/posix_workspace.py",
        "agent/automation_hosts/runtime_executor.py",
        "agent/browser/__init__.py",
        "agent/browser/action_policy.py",
        "agent/browser/contracts.py",
        "agent/browser/observation.py",
        "agent/browser/playwright_adapter.py",
        "agent/browser/ports.py",
        "agent/browser/profile_store.py",
        "agent/browser/quarantine.py",
        "agent/browser/session_store.py",
        "agent/browser/staging.py",
        "agent/browser/takeover.py",
        "agent/browser/tools.py",
        "agent/browser/url_policy.py",
        "agent/cli/__init__.py",
        "agent/cli/actions.py",
        "agent/cli/app.py",
        "agent/cli/render.py",
        "agent/composition.py",
        "agent/continuity/__init__.py",
        "agent/continuity/identity.py",
        "agent/continuity/restart.py",
        "agent/continuity/sessions.py",
        "agent/history/__init__.py",
        "agent/history/catalog.py",
        "agent/history/contracts.py",
        "agent/history/outcomes.py",
        "agent/history/tools.py",
        "agent/memory/__init__.py",
        "agent/memory/contracts.py",
        "agent/memory/preferences.py",
        "agent/memory/source.py",
        "agent/memory/store.py",
        "agent/memory/tools.py",
        "agent/mcp/__init__.py",
        "agent/mcp/bridge.py",
        "agent/mcp/catalog.py",
        "agent/mcp/contracts.py",
        "agent/mcp/safety.py",
        "agent/mcp/tools.py",
        "agent/process/__init__.py",
        "agent/process/admission.py",
        "agent/process/contracts.py",
        "agent/process/preparation.py",
        "agent/process/group.py",
        "agent/process/runner.py",
        "agent/process/tools.py",
        "agent/provider/__init__.py",
        "agent/provider/anthropic_http.py",
        "agent/provider/config.py",
        "agent/provider/factory.py",
        "agent/provider/fake_provider.py",
        "agent/provider/normalize.py",
        "agent/provider/openai_http.py",
        "agent/provider/profile.py",
        "agent/provider/protocol.py",
        "agent/research/__init__.py",
        "agent/research/tools.py",
        "agent/runtime/__init__.py",
            "agent/runtime/checkpoint.py",
            "agent/runtime/context.py",
            "agent/runtime/context_control.py",
            "agent/runtime/context_source.py",
            "agent/runtime/contracts.py",
        "agent/runtime/control.py",
        "agent/runtime/evidence.py",
        "agent/runtime/events.py",
        "agent/runtime/loop.py",
        "agent/runtime/ports.py",
        "agent/runtime/state.py",
        "agent/runtime/tool_governance.py",
        "agent/runtime/tools.py",
        "agent/runtime/views.py",
        "agent/sandbox/__init__.py",
        "agent/sandbox/authority.py",
        "agent/sandbox/contracts.py",
        "agent/sandbox/executor.py",
        "agent/sandbox/hermetic_runtime.py",
        "agent/sandbox/packaged_policy.py",
        "agent/sandbox/policy.py",
        "agent/sandbox/ports.py",
        "agent/sandbox/qualification.py",
        "agent/sandbox/seatbelt.py",
        "agent/sandbox/structured_session.py",
        "agent/sandbox/tools.py",
        "agent/scheduler/__init__.py",
        "agent/scheduler/caller.py",
        "agent/scheduler/contracts.py",
        "agent/skill/__init__.py",
        "agent/skill/catalog.py",
        "agent/skill/execution.py",
        "agent/skill/tools.py",
        "agent/subagent/__init__.py",
        "agent/subagent/child.py",
        "agent/subagent/contracts.py",
        "agent/subagent/process_runner.py",
        "agent/subagent/runner.py",
        "agent/subagent/runtime_factory.py",
        "agent/subagent/tools.py",
        "agent/tools/__init__.py",
        "agent/transport_audit.py",
        "agent/tui/__init__.py",
        "agent/tui/adapter.py",
        "agent/tui/app.py",
        "agent/tui/render.py",
        "agent/tools/edit.py",
        "agent/tools/file_ops.py",
        "agent/tools/path_safety.py",
        "agent/tools/search.py",
        "agent/tools/write.py",
        "agent/web/__init__.py",
        "agent/web/client.py",
        "agent/web/contracts.py",
        "agent/web/profile.py",
        "agent/web/safety.py",
        "agent/web/tools.py",
    }
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "agent").rglob("*.py")
        if "graphify-out" not in path.parts
    }

    assert actual == expected
    packages = {
        path.parent.relative_to(ROOT).as_posix().replace("/", ".")
        for path in (ROOT / "agent").rglob("__init__.py")
        if "graphify-out" not in path.parts
    }
    assert packages == {
        "agent",
        "agent.automation",
        "agent.automation_hosts",
        "agent.browser",
        "agent.cli",
        "agent.continuity",
        "agent.history",
        "agent.mcp",
        "agent.memory",
        "agent.process",
        "agent.provider",
        "agent.research",
        "agent.runtime",
        "agent.sandbox",
        "agent.scheduler",
        "agent.skill",
        "agent.subagent",
        "agent.tools",
        "agent.tui",
        "agent.web",
    }


def test_old_product_entrypoints_and_tracked_frontends_are_absent() -> None:
    for relative in (
        "agent/core.py",
        "agent/loop.py",
        "agent/runtime_integration/__init__.py",
        "agent/confirmation/__init__.py",
        "agent/skill_system/__init__.py",
        "agent/subagent_system/__init__.py",
        "docs/current/PRODUCTIZATION_ROADMAP.md",
        "docs/history/README.md",
        "docs/archive/s-series-runtime-kernel/S_ROADMAP.md",
        "skills/demo-note-maker/SKILL.md",
        "tui/package.json",
    ):
        assert not (ROOT / relative).is_file()


def test_effect_owners_are_unique_in_production_sources() -> None:
    provider_callers: list[str] = []
    tool_callers: list[str] = []
    checkpoint_callers: list[str] = []
    for path in (ROOT / "agent").rglob("*.py"):
        if "graphify-out" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            relative = path.relative_to(ROOT).as_posix()
            if node.func.attr == "generate":
                provider_callers.append(relative)
            elif node.func.attr == "invoke":
                tool_callers.append(relative)
            elif node.func.attr == "compare_and_swap":
                checkpoint_callers.append(relative)

    assert set(provider_callers) == {"agent/runtime/loop.py"}
    assert set(tool_callers) == {"agent/runtime/loop.py"}
    # conversation checkpoint CAS 的唯一 owner 仍是 loop。browser tools 与
    # automation controller 分别只推进自己独立的 session / definition ledger；
    # 都不推进 ConversationState，也不是第二个 model/tool loop。
    assert set(checkpoint_callers) == {
        "agent/automation/controller.py",
        "agent/runtime/loop.py",
        "agent/browser/tools.py",
    }


def test_subagent_package_does_not_import_provider_or_loop() -> None:
    forbidden_prefixes = ("agent.provider", "agent.runtime.loop")
    for path in (ROOT / "agent/subagent").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative == "agent/subagent/runner.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        for name in names:
            if any(name == p or name.startswith(p + ".") for p in forbidden_prefixes):
                raise AssertionError(f"{relative} imports forbidden {name}")


def test_production_sources_never_import_legacy_capability_paths() -> None:
    # agent.skill（单数）是当前唯一允许的 Skill 产品包；下列旧路径必须从未被 import。
    forbidden = (
        "agent.skill_system",
        "agent.skills",
        "agent.skill_lifecycle",
        "agent.subagent_system",
        "agent.runtime_integration",
        "agent.confirmation",
    )
    offenders: list[tuple[str, str]] = []
    for path in (ROOT / "agent").rglob("*.py"):
        if "graphify-out" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            relative = path.relative_to(ROOT).as_posix()
            for name in names:
                for prefix in forbidden:
                    if name == prefix or name.startswith(prefix + "."):
                        offenders.append((relative, name))
    assert not offenders, f"legacy capability imports found: {offenders}"
