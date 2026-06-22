# FirstAgent Provider Abstraction Audit (protocol-centric)

Date: 2026-06-22

Status: independent audit of the provider layer's abstraction. **Finding: the
code is already protocol-based; the documentation/maturity framing was
vendor-centric and is corrected here.** This doc reframes provider maturity from
"vendor L6" to **protocol-adapter maturity + endpoint-profile maturity +
capability matrix**, per the user's directive.

## 1. Thesis

A vendor-centric framing ("Provider L6 = DeepSeek verified; Kimi/GLM not
released") is wrong for this codebase. The correct unit of abstraction is:

- **Protocol adapter** (`provider_type`): decides the request/response shape —
  `openai_native` / `openai_compatible` / `anthropic_native` /
  `anthropic_compatible` / `fake`.
- **Endpoint profile** (vendor/endpoint identity): `name` + `base_url` + `model`
  + credential ref + known quirks. A vendor may expose MULTIPLE protocols
  (DeepSeek exposes both OpenAI-compatible and Anthropic-compatible endpoints).
- **Capability matrix**: per (protocol, endpoint, model) — tool calling,
  streaming, token usage, structured/JSON output, vision, reasoning,
  fail-closed behavior.

L6 must first rate the **protocol path** (is the adapter real-verified?), then
the **endpoint profile** (is a specific endpoint smoke-validated?). One endpoint
profile's validation MUST NOT generalize to all vendors.

## 2. Industry multi-provider config patterns (research)

- **DeepSeek** exposes TWO protocols: OpenAI-compatible
  (`https://api.deepseek.com/v1`, `/chat/completions`, recommended) and
  Anthropic-compatible (`https://api.deepseek.com/anthropic`, `/v1/messages`, for
  Anthropic-ecosystem tooling). Same vendor, two protocol paths.
  ([api-docs.deepseek.com](https://api-docs.deepseek.com/),
  [anthropic_api guide](https://api-docs.deepseek.com/guides/anthropic_api))
- **LiteLLM** = unified gateway for 100+ providers; config keys `model` +
  `api_key`(env) + `api_base`/`base_url`; the OpenAI-compatible-endpoint pattern
  is the canonical protocol-angle config. LiteLLM treats providers as
  protocol-typed endpoints, not vendor adapters.
  ([docs.litellm.ai/providers/openrouter](https://docs.litellm.ai/docs/providers/openrouter),
  [openai_compatible](https://docs.litellm.ai/docs/providers/openai_compatible),
  [github/BerriAI/litellm](https://github.com/BerriAI/litellm))
- **OpenRouter** = managed aggregator exposing one OpenAI-compatible API over
  many providers. ([openrouter.ai/blog/insights/openrouter-vs-litellm](https://openrouter.ai/blog/insights/openrouter-vs-litellm))
- **Kimi (Moonshot) K2.5, Qwen (Alibaba DashScope), GLM (Zhipu), vLLM, Ollama,
  Azure OpenAI** ALL expose OpenAI-compatible `/v1/chat/completions`; migration =
  change `api_key` + `base_url` + `model`. Kimi K2.5 also exposes an
  Anthropic-compatible endpoint. NO per-vendor adapter is needed for these — the
  OpenAI-compatible protocol path covers them.
  ([platform.kimi.com migrating-from-openai](https://platform.kimi.com/docs/guide/migrating-from-openai-to-kimi),
  [help.aliyun.com DashScope OpenAI compat](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope),
  [open.bigmodel.cn](https://open.bigmodel.cn/dev/api))
- **SDK base_url override**: OpenAI SDK and Anthropic SDK both select the endpoint
  via `base_url`; the SDK is protocol-typed (openai vs anthropic), the endpoint is
  a config value. This is exactly FirstAgent's `provider_type` + `base_url` model.

**Industry de-facto standard**: protocol determines the SDK/adapter; base_url +
api_key + model determine the endpoint/vendor; capability differences are a
matrix, not a per-vendor adapter.

## 3. FirstAgent current abstraction audit

The CODE is already protocol-based (good):

- `provider_type` IS the protocol dimension
  (`config/config.example.yaml:21`:
  `fake | anthropic_native | anthropic_compatible | openai_native | openai_compatible`).
- `agent/provider/factory.py:build_model_provider(config)` dispatches by
  `provider_type` (protocol) → the right adapter; it does NOT branch on vendor.
- Config decouples protocol (`type`) from endpoint (`base_url`, `model`,
  `api_key`/`api_key_env`). `request_path` and `auth_scheme` are
  protocol-determined inside the adapter (config.example.yaml:27).
- `config/config.local.example.yaml` shows the SAME `anthropic_compatible`
  protocol reused across endpoints: DeepSeek
  (`api.deepseek.com/anthropic`, `deepseek-v4-flash`) and Kimi
  (`coding.dashscope.aliyuncs.com/apps/anthropic`, `kimi-k2.5`) — both via one
  protocol adapter, different endpoint profiles.

The PROBLEM is documentation/maturity framing (vendor-centric), now corrected:

- Prior: "Provider/model boundary L6 ... DeepSeek ONLY; Kimi/GLM config-exists."
- Corrected: "**anthropic_compatible protocol path: L6** (real-verified, R-series
  Run 12 + reproducible G-010/G-015/G-019/G-022 dogfood). **DeepSeek endpoint
  profile: smoke-validated.** Kimi/GLM **endpoint profiles** lack
  credential + smoke + capability validation — they use SUPPORTED protocols
  (anthropic_compatible / openai_compatible), so there is NO adapter gap, only an
  endpoint-profile validation gap."

This is the precise correction: validating one endpoint profile (DeepSeek) proves
the `anthropic_compatible` protocol path; it does NOT prove every vendor, and it
does NOT mean Kimi/GLM need new adapters.

## 4. New abstraction: protocol adapter + endpoint profile + capability matrix

```
config.provider:
  protocol (provider_type): openai_native | openai_compatible |
                            anthropic_native | anthropic_compatible | fake
  name      (endpoint/vendor id): deepseek | kimi | glm | openrouter |
                                  vllm | ollama | azure_openai | custom
  base_url  (protocol endpoint)
  model
  credential_ref (api_key_env | api_key)   # secret-by-reference preferred
  extra_headers / headers_ref              # optional
  capabilities: {tool_calling, streaming, usage, structured, vision, reasoning}
  tool_name_policy                         # sanitize rules (e.g. ae94f26)
  streaming_mode                           # native | fail_closed | disabled
  timeout / retry
  fail_closed_flags                        # e.g. openai_compatible streaming
```

- **Protocol adapter** = the request/response code path selected by `protocol`.
  FirstAgent already has 4 real adapters + fake. Maturity is rated PER PROTOCOL
  PATH.
- **Endpoint profile** = a named (name + base_url + model + credential)
  instantiation of a protocol. Maturity is "smoke-validated" or
  "config-exists-only" PER PROFILE.
- **Capability matrix** = per (protocol, profile, model): tool calling supported?
  streaming? token usage? structured output? vision? reasoning? — these are
  capability flags, not vendor identity. Example: FirstAgent's `openai_compatible`
  adapter has `streaming_mode = fail_closed` (`openai_http.py:420`) — a capability
  gap in that PROTOCOL PATH, not a Kimi/GLM-specific bug.

## 5. Config schema recommendation

FirstAgent's current schema (`enabled, type, model, base_url, api_key[_env]`) is
already protocol-centric and aligns with the LiteLLM/SDK pattern. Recommended
formalization (docs-level; code already supports the core):

1. Rename `type` → `protocol` in docs (keep `type` as config alias for back-compat)
   to make the protocol dimension explicit.
2. Add an optional **endpoint profile `name`** field (default: derived from
   base_url/model) so maturity/audit can cite "DeepSeek endpoint profile"
   explicitly.
3. Document the **capability matrix** fields (capabilities, streaming_mode,
   tool_name_policy, fail_closed_flags) as optional profile metadata the operator
   sets/inspects — the operator must be able to SEE that `openai_compatible`
   streaming is fail-closed before choosing a profile.
4. Keep secret-by-reference (`api_key_env`) as the recommended pattern; inline
   `api_key` only for local uncommitted config.

## 6. Maturity / L6 reframing

Old (vendor-centric, overclaim-prone): "Provider L6 = DeepSeek; Kimi/GLM not
released."

New (protocol-centric):

| Layer | Level | Evidence |
|---|---|---|
| `anthropic_compatible` protocol path | **L6** | R-series Run 12 + reproducible G-010/G-015/G-019/G-022 real dogfood (governed tool_use, memory, skill all via this path). |
| `openai_compatible` protocol path | **L4** | adapter exists + offline contract-proven (test_provider_contract.py); streaming is fail-closed (capability gap G-047); no real smoke yet. |
| `anthropic_native` / `openai_native` | **L2** | factory-wired + contract-proven; no real smoke (no official OpenAI/Anthropic credential configured). |
| `fake` protocol path | **L3** | deterministic test support; not a real ceiling. |
| DeepSeek endpoint profile (anthropic_compatible) | **validated** | smoke-validated (the basis of the L6 protocol-path claim). |
| Kimi endpoint profile (anthropic_compatible) | **config-exists** | no credential + no smoke; uses the L6 protocol path, so NO adapter gap — only a profile-validation gap (G-046). |
| GLM endpoint profile (openai_compatible) | **config-exists** | no credential + no smoke; additionally limited by the openai_compatible streaming fail-closed capability gap (G-047). |

## 7. Provider gaps (cross-reference ledger)

- **G-046 (reframed)**: endpoint-profile smoke plan — validate at least one MORE
  endpoint profile on an ALREADY-L6 protocol path (e.g. DeepSeek via
  `openai_compatible`, or Kimi via `anthropic_compatible` once a key is
  configured) to prove the protocol path generalizes beyond a single profile.
- **G-047 (new)**: `openai_compatible` capability gap — streaming is fail-closed
  (`openai_http.py:420`); either implement streaming or document it as a permanent
  capability boundary. This is a PROTOCOL-PATH capability, not a vendor issue.
- **G-048 (new)**: config schema normalization — formalize `protocol`/`name`/
  `capabilities`/`streaming_mode`/`tool_name_policy`/`fail_closed_flags` as
  documented profile metadata (docs-level; operator-visible capability matrix).
- **G-049 (new)**: provider capability matrix surface — expose per-protocol-path
  capabilities (tool_calling/streaming/usage/structured) in `capability-status` /
  `status` so an operator sees protocol-path limits BEFORE choosing an endpoint.

## 8. Boundaries (no overclaim)

- The `anthropic_compatible` L6 is a **protocol path** claim, validated by ONE
  endpoint profile (DeepSeek). It does NOT claim Kimi/GLM are released.
- Kimi/GLM are NOT missing adapters — they use supported protocols; they lack
  endpoint-profile validation (credential + smoke + capability). This is a
  concrete config/validation gap, NOT "缺授权" hand-waving and NOT an architecture
  gap.
- `openai_compatible` is L4 (not L6): the adapter works but streaming is
  fail-closed and no real smoke exists. Do not generalize the anthropic_compatible
  L6 to openai_compatible.
- `*_native` paths are L2: factory-wired, no credential/smoke. Do not claim
  official OpenAI/Anthropic endpoint support.
