"""G-041: per-tool input/output guardrail primitive tests."""

from __future__ import annotations

from agent.tool_guardrails import (
    GuardrailResult,
    ToolGuardrailRegistry,
    default_input_guardrail,
    default_output_guardrail,
)


def test_input_guardrail_blocks_secret_in_args():
    """Input guardrail detects sk- pattern in tool args."""
    result = default_input_guardrail("write_file", {
        "path": "workspace/test.txt",
        "content": "my key is sk-ant-deadbeef1234567890",
    })
    assert not result.ok
    assert "secret" in result.reason.lower()


def test_input_guardrail_passes_clean_args():
    """Input guardrail passes clean tool args."""
    result = default_input_guardrail("write_file", {
        "path": "workspace/test.txt",
        "content": "hello world",
    })
    assert result.ok


def test_input_guardrail_detects_nested_secret():
    """Input guardrail detects secrets in nested dict values."""
    result = default_input_guardrail("edit_file", {
        "path": "workspace/test.txt",
        "edits": [{"find": "key", "replace": "Bearer xyz1234567890abcdef"}],
    })
    assert not result.ok


def test_output_guardrail_scrubs_secrets():
    """Output guardrail scrubs sk- patterns from results."""
    result = default_output_guardrail(
        "read_file", "the config has key=sk-ant-deadbeef1234567890"
    )
    assert "sk-ant" not in result
    assert "[REDACTED]" in result


def test_output_guardrail_passes_clean_result():
    """Output guardrail passes clean results unchanged."""
    result = default_output_guardrail("read_file", "file content: hello world")
    assert result == "file content: hello world"


def test_registry_check_input_blocks_secret():
    """Registry check_input blocks secrets via default guardrail."""
    reg = ToolGuardrailRegistry()
    result = reg.check_input("write_file", {"content": "sk-test1234567890123"})
    assert not result.ok


def test_registry_check_output_scrubs():
    """Registry check_output scrubs via default guardrail."""
    reg = ToolGuardrailRegistry()
    scrubbed = reg.check_output("read_file", "key: sk-deadbeef1234567890")
    assert "sk-deadbeef" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_registry_custom_per_tool_guardrail():
    """Registry supports custom per-tool guardrails."""
    reg = ToolGuardrailRegistry()

    def block_shell(tool_name: str, tool_input: dict) -> GuardrailResult:
        if "rm -rf" in str(tool_input.values()):
            return GuardrailResult(ok=False, reason="blocked: dangerous command")
        return GuardrailResult(ok=True)

    reg.register_input_guardrail(block_shell, tool_name="run_shell")
    result = reg.check_input("run_shell", {"command": "rm -rf /"})
    assert not result.ok
    assert "dangerous" in result.reason

    # Other tools not affected by the per-tool guardrail.
    result2 = reg.check_input("write_file", {"path": "ok"})
    assert result2.ok
