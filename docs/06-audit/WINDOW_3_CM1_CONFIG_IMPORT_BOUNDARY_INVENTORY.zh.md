# Window 3 CM-1 Config / Provider Import-Boundary Inventory

> 日期：2026-06-13
> 范围：CM-1 config/provider import-boundary spike
> 状态：implementation evidence document

本文件只记录真实 config/provider 入口的 owner、用途和保留/收敛结论。
它不是广义 capability model，也不定义跨 Tool / Skill / MCP / SubAgent /
Scheduler / Provider 的共享 contract。Window 3 不新增 production symbol，
不改 provider selection，不接入 action_scheduler。

## 1. CM-1 Config Surface Inventory

| Surface | Path | Owner | Runtime-facing | Classification | Keep/Converge |
|---|---|---|---|---|---|
| provider_config | agent/provider/config.py | AgentProviderConfig owns provider API env config and SUPPORTED_PROVIDER_TYPES | yes | owner | Keep. This is the real provider API/env config authority. |
| provider_simple_config | agent/provider/simple_config.py | UnifiedProviderConfig owns config/config.yaml loading | yes | preferred local project entry | Keep. It is the recommended project config source today. |
| provider_profiles | agent/provider/profiles.py | ProviderProfile owns named profile loading from config/provider_profiles.yaml | yes, through provider factory legacy step | compatibility / alternate entry | Keep and mark as legacy/profile entry. Do not merge in Window 3. |
| local_config | agent/local_config.py | local/dev customization and display metadata loader | no direct provider factory owner | local/dev support surface | Keep. It is not a duplicate provider API source. |
| mcp_config | agent/mcp_config.py | MCPConfig parser, validation model, path policy, and load_mcp_config | MCP-specific only | MCP config owner | Keep. Separate from provider config by protocol boundary. |
| mcp_config_cli | agent/mcp_config_cli.py | Thin CLI adapter for mcp config commands | CLI-only | wrapper | Keep thin. It must call service/presenter, not own policy. |
| mcp_config_presenter | agent/mcp_config_presenter.py | Presenter render boundary for MCP config output | CLI/output only | presenter | Keep. It renders redacted service models only. |
| mcp_config_service | agent/mcp_config_service.py | MCP config service/use-case safe apply and plan preview | MCP-specific only | service/use-case | Keep. It owns workflow semantics, not provider selection. |

Source consistency rule: the Roadmap text historically mentioned config.py /
simple_config.py / profiles.py under the agent root. The source of truth is the
real code path under agent/provider/ for those three files.

## 2. Per-Surface Owner Snapshot

| Path | Owner | Purpose | Boundary |
|---|---|---|---|
| agent/provider/config.py | AgentProviderConfig provider API owner | Validates provider_type, API auth metadata, model, base_url, max tokens, timeout, and streaming support | Runtime-facing provider adapter config; not local customization metadata. |
| agent/provider/simple_config.py | UnifiedProviderConfig config/config.yaml owner | Loads the recommended project config file and converts it to AgentProviderConfig | Compatibility-safe local file entry; no env expansion for provider.api_key. |
| agent/provider/profiles.py | ProviderProfile profile owner | Loads named profile source and resolves active profile | Legacy/profile source kept for compatibility; not a runtime flow. |
| agent/local_config.py | local/dev display config owner | Loads local/dev customization and display-facing metadata | Separate from provider API config; no provider factory ownership. |
| agent/mcp_config.py | MCPConfig parser owner | Parses and validates MCP server config, SecretValueRef, path policy, and load_mcp_config | MCP-specific config model; no server execution or endpoint reachability check. |
| agent/mcp_config_cli.py | CLI adapter thin owner | Parses mcp config command arguments and delegates to service/presenter | Adapter stays thin; no business policy ownership. |
| agent/mcp_config_presenter.py | Presenter render owner | Renders MCP config validation, inspection, plan, and apply results | Output formatting only; uses already-redacted models. |
| agent/mcp_config_service.py | service/use-case safe apply owner | Owns list/inspect/validate, plan preview, backup, diff, and safe apply manifest | Workflow semantics stay here; no MCP command execution or network connection. |

## 3. Provider Factory / Provider Selection

agent/provider/factory.py is the provider selection boundary. It consumes
AgentProviderConfig and returns a concrete ModelProvider.

Current precedence in build_model_provider_from_env:

1. config/config.yaml via load_unified_provider_config
2. FIRST_AGENT_PROVIDER_PROFILE via provider_profiles.yaml
3. MY_FIRST_AGENT_LLM_PROVIDER and related provider env vars
4. default fake provider

This is not a provider registry. Selection is an explicit factory branch over
AgentProviderConfig.provider_type. Window 3 keeps that shape unchanged.

## 4. Import-Boundary Findings

Graphify and source inspection found these load-bearing edges:

| Boundary | Source evidence | Finding |
|---|---|---|
| profiles -> provider config | agent/provider/profiles.py imports AgentProviderConfig and SUPPORTED_PROVIDER_TYPES from agent/provider/config.py | profiles is a compatibility/profile source layered on the provider config owner. |
| simple_config -> provider config | agent/provider/simple_config.py imports AgentProviderConfig and SUPPORTED_PROVIDER_TYPES | config/config.yaml converts into the same provider config object. |
| factory -> simple_config/profiles/env config | agent/provider/factory.py calls load_unified_provider_config, then profile loaders, then load_agent_provider_config | provider selection already has ordered fallback; no new registry needed. |
| mcp_config_service/presenter -> mcp_config | mcp_config_service.py and mcp_config_presenter.py import MCPConfig models and load_mcp_config | MCP config has its own parser/service/presenter boundary. |
| local_config -> display_events | agent/local_config.py imports display masking helpers | local_config is local metadata/display support, not provider factory input. |

## 5. Keep / Future Convergence

Keep now:

- agent/provider/config.py remains the provider API/env config owner.
- agent/provider/simple_config.py remains the recommended config/config.yaml entry.
- agent/provider/profiles.py remains compatibility/profile entry.
- agent/local_config.py remains local/dev support.
- agent/mcp_config*.py remains MCP-specific config workflow.
- agent/provider/factory.py remains explicit provider selection.

Future convergence candidates, outside Window 3:

- Decide whether profiles/env fallback should remain after config/config.yaml is mature.
- Decide whether Roadmap wording should consistently use agent/provider/ paths.
- Decide whether provider diagnostics should present the precedence stack in one place.

Do not do in Window 3:

- no provider registry
- no provider system rewrite
- no shared capability contract
- no unified capability status type
- no RuntimeAction refactor
- no action_scheduler wiring

## 6. Why This Is Not CM-2

CM-1 answers a narrow import-boundary question: which config surfaces exist,
who owns each one, and whether they are duplicate sources or deliberate wrappers.

CM-2 would define a shared cross-surface capability abstraction. That has no
current consumer in this window and would cross the Roadmap deferred decision.
Window 3 therefore stays descriptive: markdown inventory plus boundary tests
reading existing source facts.

## 7. Scheduler Boundary Note

ActionSchedulerHandler is registered for scheduler RuntimeActionTypes, and
ActionScheduler can be manually injected in tests through the existing
chat(action_scheduler=...) seam. Production entrypoints do not inject it by
default. The precise label is:

- dormant-by-default
- registered-not-routed in production
- injectable seam exists
- manually injectable in tests

This document deliberately avoids describing the scheduler as impossible to
route while the injection seam remains present and tested.
