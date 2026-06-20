"""S4-G03 secret-safe redaction 强制测试（AC-3）。

验证更高保真 evidence（replay chain 的 input/output preview）**绝不**持久化/暴露 raw
secret/api key/完整凭证：注入 fake secret → 断言被 `[REDACTED]` 且原文不出现。

边界（`S4_FIDELITY_CONTRACT.md §1/§4`）：redaction 是硬边界——保真提升绝不以泄露 secret
为代价。本测试只验证 redaction 行为，不读取/打印真实 secret（全 fake 模式）。
"""
from __future__ import annotations

from agent.evidence_redaction import redact_metadata, redact_text
from agent.state import create_agent_state
from agent.task_replay_chain import build_replay_chain

# 一组 fake secret 模式（绝不来自真实凭证；仅用于断言 redaction 覆盖常见形态）。
FAKE_SK = "sk-test-secret-AAAAAAAAAAAAAAAA"  # OpenAI-style
FAKE_GITHUB = "ghp_fakegithubpatAAAAAAAAAAAAAAAA"  # GitHub PAT
FAKE_AWS = "AKIAFAKEAWSKEY1234ABCD"  # AWS access key id
FAKE_BEARER = "Bearer dGhpcyBpcyBhIGZha2UgYmVhcmVyIHRva2Vu"
FAKE_KV = 'api_key="sk-leaked-kv-secret-XYZ"'


# ═══════════════════════════════════════════════════════
# A. redact_text：常见 secret 形态被脱敏
# ═══════════════════════════════════════════════════════


def test_redact_text_masks_openai_style_key():
    out = redact_text(f"call result with key {FAKE_SK}")
    assert FAKE_SK not in out
    assert "[REDACTED]" in out


def test_redact_text_masks_github_pat():
    out = redact_text(f"token={FAKE_GITHUB}")
    assert FAKE_GITHUB not in out
    assert "[REDACTED]" in out


def test_redact_text_masks_aws_key():
    out = redact_text(f"aws_access_key_id={FAKE_AWS}")
    assert FAKE_AWS not in out
    assert "[REDACTED]" in out


def test_redact_text_masks_bearer_token():
    out = redact_text(f"Authorization: {FAKE_BEARER}")
    assert FAKE_BEARER not in out
    assert "[REDACTED]" in out


def test_redact_text_masks_sensitive_kv_assignment():
    """敏感键赋值（api_key=/password=/secret=）的 value 必须被脱敏。"""
    out = redact_text(FAKE_KV)
    assert "sk-leaked-kv-secret-XYZ" not in out
    assert "[REDACTED]" in out


def test_redact_text_preserves_non_secret_content():
    """非 secret 内容不被误伤。"""
    out = redact_text("read fixture-gap-1: gap satisfied")
    assert "fixture-gap-1" in out
    assert "gap satisfied" in out
    assert "[REDACTED]" not in out


def test_redact_text_handles_empty_and_none():
    assert redact_text("") == ""
    # redact_text 只接受 str；None 由调用方处理（build_replay_chain 已保证传入 str）


# ═══════════════════════════════════════════════════════
# B. redact_metadata：递归脱敏 dict 中的字符串值
# ═══════════════════════════════════════════════════════


def test_redact_metadata_masks_nested_string_values():
    metadata = {
        "tool_name": "http_request",
        "headers": f"Authorization: {FAKE_BEARER}",
        "nested": {"token": FAKE_GITHUB},
        "safe": "plain content",
    }
    out = redact_metadata(metadata)
    assert FAKE_BEARER not in str(out)
    assert FAKE_GITHUB not in str(out)
    assert out["tool_name"] == "http_request"
    assert out["safe"] == "plain content"


# ═══════════════════════════════════════════════════════
# C. 强制点：replay chain preview 绝不暴露注入的 fake secret（AC-3 核心）
# ═══════════════════════════════════════════════════════


def test_replay_chain_previews_redact_injected_secret():
    """注入 fake secret 到 tool input/result → chain preview 必须脱敏，原文不出现。

    中文注释：这是 AC-3 的硬断言——replay chain 是 G02 新增的高保真面，提升保真后
    input/output preview 可能携带 secret；G03 必须在投影点强制 redaction，使更高保真
    绝不以泄露 secret 为代价。
    """
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    state.task.tool_execution_log = {
        "toolu_leak": {
            "tool": "http_request",
            "status": "executed",
            "input": {
                "url": "https://example.invalid/api",
                "headers": {"Authorization": FAKE_BEARER},
                "api_key": FAKE_SK,
            },
            "result": f"response included token {FAKE_GITHUB} and aws {FAKE_AWS}",
            "step_index": 0,
        },
    }
    chain = build_replay_chain(state)
    evt = chain.tool_events[0]

    # 所有 fake secret 都不得出现在任何 preview
    for secret in (FAKE_SK, FAKE_GITHUB, FAKE_AWS, FAKE_BEARER):
        assert secret not in evt.input_preview, (
            f"secret 泄漏到 input_preview: {secret}"
        )
        assert secret not in evt.output_preview, (
            f"secret 泄漏到 output_preview: {secret}"
        )
    # 脱敏标记应出现（证明被处理过）
    assert "[REDACTED]" in evt.input_preview or "[REDACTED]" in evt.output_preview


def test_replay_chain_redaction_does_not_strip_normal_fixtures():
    """redaction 不应误伤正常 fixture 内容（与 G02 投影测试协同）。"""
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    state.task.tool_execution_log = {
        "toolu_ok": {
            "tool": "repo_doc_reader",
            "status": "executed",
            "input": {"target": "fixture-gap-1"},
            "result": "gap-1 satisfied",
            "step_index": 0,
        },
    }
    chain = build_replay_chain(state)
    evt = chain.tool_events[0]
    assert "fixture-gap-1" in evt.input_preview
    assert "gap-1 satisfied" in evt.output_preview
