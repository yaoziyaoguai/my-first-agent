"""Dogfood harness 共享 helpers（de-stateful consolidation）。

本模块提供统一的、轻量的 dogfood script 基础设施：
- StepResult frozen dataclass — 所有 dogfood step 使用统一 schema
- write_dogfood_report() — 统一报告写入（tmp-root-first，默认不覆盖）
- redact_secrets() — 不可逆脱敏 helper
- temp_workspace() — 临时 workspace context manager

为什么需要这个模块：
- 当前 scripts/dogfood* 各自硬编码报告路径、各自定义 pass/fail 格式
- 各自处理 secret redaction，容易遗漏
- 无统一 temp workspace 约定，公开文档中的路径依赖不确定

设计原则：
- 不执行 dogfood，不调用真实 API，不读取真实 sessions/runs/memory
- 不删除历史报告，不强制全量迁移所有 scripts
- StepResult 的 detail 字段只放脱敏后的补充信息
"""
from __future__ import annotations

import json
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class StepResult:
    """统一 dogfood step 结果 schema。

    所有 dogfood step 使用此 dataclass 记录结果，确保跨脚本
    的 pass/fail/skip 记录格式一致，方便后续聚合和审计。
    """

    step_id: str
    """步骤标识符，如 'BL1-P2-01'"""

    description: str
    """人类可读的步骤描述"""

    status: str
    """'pass' | 'concern' | 'fail' | 'skipped'"""

    actual_summary: str
    """观察到的实际行为摘要"""

    expected: str
    """期望行为描述"""

    provider_mode: str
    """'fake' | 'real' | 'none'"""

    detail: dict | None = None
    """补充信息（脱敏后），可选"""

    def to_dict(self) -> dict:
        """转为可序列化的 dict（用于 JSON 输出）。"""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "status": self.status,
            "actual_summary": self.actual_summary,
            "expected": self.expected,
            "provider_mode": self.provider_mode,
            "detail": self.detail,
        }


def write_dogfood_report(
    results: list[StepResult],
    output_path: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """将 StepResult 列表写入统一的 dogfood 报告文件。

    默认不覆盖已有 active report。输出到 tmp-root-first
    （workspace/dogfood/ 或用户指定路径），不直接写 docs/dogfood/
    以避免覆盖人工报告。

    返回实际写入的 Path。
    """
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"报告已存在: {output_path}。设置 overwrite=True 覆盖，或指定新路径。"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": timestamp,
        "total_steps": len(results),
        "pass_count": sum(1 for r in results if r.status == "pass"),
        "concern_count": sum(1 for r in results if r.status == "concern"),
        "fail_count": sum(1 for r in results if r.status == "fail"),
        "skipped_count": sum(1 for r in results if r.status == "skipped"),
        "results": [r.to_dict() for r in results],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return output_path


def redact_secrets(text: str) -> str:
    """不可逆脱敏 secret pattern。

    脱敏范围：
    - sk-ant-* (Anthropic API key)
    - sk-* (OpenAI/其他 API key)
    - Bearer * (Bearer token)

    不可逆——不会在 log 中出现 raw secret。
    不脱敏非 secret 内容。
    """
    # Bearer token（先处理，避免被 sk-* 规则误匹配）
    text = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED]", text)
    # Anthropic API key: sk-ant-...
    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]+", "sk-ant-[REDACTED]", text)
    # OpenAI / 其他 API key: sk-...（不匹配已脱敏的 sk-ant-）
    text = re.sub(r"(?<!\[REDACTED\]\s)sk-[A-Za-z0-9_\-]{20,}", "sk-[REDACTED]", text)
    return text


@contextmanager
def temp_workspace(prefix: str = "dogfood_"):
    """创建临时 workspace 目录，yield Path，自动清理。

    用法:
        with temp_workspace("dogfood_") as ws:
            report = ws / "report.json"
            write_dogfood_report(results, report)
        # ws 目录已在 context manager exit 时自动删除
    """
    tmp_dir: str | None = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix=prefix)
        yield Path(tmp_dir)
    finally:
        if tmp_dir is not None:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)
