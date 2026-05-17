# Test Matrix and Dogfood Guide

这篇文档解决什么问题：集中列出当前最重要的测试、回归和 dogfood 命令，说明哪些默认可跑、哪些 gated。

不解决什么问题：不替代每个测试文件的意图说明，不授权真实 LLM 或真实 MCP。

推荐读者：维护者、Coding Agent、发布前审计者。

## 基础质量门

```bash
git diff --check
ruff check agent tests scripts
python -m pytest tests/ -x -q
```

## Architecture / SubAgent smoke

```bash
python -m pytest tests/test_architecture_boundaries.py tests/test_subagent_local_mvp_contract.py -q
```

## Memory selected tests

```bash
python -m pytest tests/test_memory_interaction.py tests/test_memory_interactive_confirmation.py -q
python -m pytest tests/test_memory_*.py -q
```

## Skill selected tests

```bash
python -m pytest tests/test_skill_schema.py tests/test_skill_registry.py tests/test_skill_progressive_disclosure.py -q
python -m pytest tests/test_skill_selector.py tests/test_skill_invocation.py -q
python -m pytest tests/test_skill_tool_binding.py tests/test_skill_memory_boundary.py tests/test_skill_checkpoint_boundary.py -q
python -m pytest tests/test_skill_dogfood.py -q
```

## SubAgent selected tests

```bash
python -m pytest tests/test_subagent_local_mvp_contract.py tests/test_subagent_descriptor_schema.py tests/test_subagent_registry.py -q
python -m pytest tests/test_subagent_delegation_contract.py tests/test_subagent_context_packaging.py tests/test_subagent_execution_modes.py -q
python -m pytest tests/test_subagent_tool_boundary.py tests/test_subagent_skill_boundary.py tests/test_subagent_memory_boundary.py -q
python -m pytest tests/test_subagent_checkpoint_boundary.py tests/test_subagent_parent_adjudication.py tests/test_subagent_trace.py -q
python -m pytest tests/test_subagent_bounded_execution.py tests/test_subagent_parent_adapter.py tests/test_subagent_cli_tui.py -q
python -m pytest tests/test_subagent_dogfood.py tests/test_architecture_boundaries.py -q
```

## Regression tests

```bash
python -m pytest tests/test_tool_exposure.py tests/test_tool_registry_contract.py tests/test_checkpoint_ownership.py -q
python -m pytest tests/test_memory_interaction.py tests/test_memory_interactive_confirmation.py -q
```

## Synthetic dogfood

Skill System:

```bash
python scripts/dogfood_skill_system.py --tmp-root /tmp/my-first-agent-skill-dogfood --mode synthetic
```

SubAgent System:

```bash
python scripts/dogfood_subagent_system.py --tmp-root /tmp/my-first-agent-subagent-dogfood --mode synthetic
```

Global governance:

```bash
python scripts/dogfood_global_real_api.py --tmp-root /tmp/my-first-agent-global-dogfood --mode synthetic --report-json /tmp/my-first-agent-global-synthetic-dogfood-report.json
```

## Gated real dogfood

Real API dogfood 不是默认检查项。只有同时满足以下条件才允许：

- 文档 phase 明确要求。
- 用户明确允许。
- 使用临时 HOME / tmp root。
- 使用 project `.env` scoped loader 加载 provider config。
- `shell_env_fallback_used` 必须为 `false`；如果只能从 shell env 取 key，必须 blocked。
- 不打印 key / token / secret。
- 结果写入审计摘要，不泄露 provider payload。

全局 Real API dogfood:

```bash
python scripts/dogfood_global_real_api.py --tmp-root /tmp/my-first-agent-global-real-dogfood --mode real-api --report-json /tmp/my-first-agent-global-real-dogfood-report.json
```

## 最近审计基线

- `ruff`: passed。
- full pytest: `2684 passed, 14 skipped`。
- SubAgent synthetic dogfood: `16/16 passed`。
- memory/episodes runtime jsonl 不再被 git tracked。
