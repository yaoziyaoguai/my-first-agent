"""v0.3 M2 · 健康报告渲染（纯函数）。

为什么单独成模块：
- 和 cli_renderer 一样属于「输出层」，不持有运行时状态、不写日志、不读
  checkpoint，只把 health_check.collect_health_results 返回的 dict 渲染
  成人类可读 / 机器可读两种格式。
- M2 的「可视化」**仅指 CLI 下结构化健康报告**，不引入 Textual / 图形面板。
- 不会自动归档 / 删除任何文件；所有 action 字段是给用户复制粘贴用的命令。
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# 整体状态优先级：error > warn > pass / skip。
_STATUS_RANK = {"error": 3, "warn": 2, "pass": 1, "skip": 0}
_STATUS_ICON = {"pass": "✅", "warn": "⚠️", "error": "❌", "skip": "⏭️"}
_BAR = "─" * 60


def overall_status(results: Mapping[str, Mapping[str, Any]] | None) -> str:
    """从所有 check 结果聚合出整体状态：error > warn > pass。"""
    if not results:
        return "skip"
    worst = "pass"
    for r in results.values():
        if not isinstance(r, Mapping):
            continue
        s = r.get("status", "skip")
        if _STATUS_RANK.get(s, 0) > _STATUS_RANK.get(worst, 0):
            worst = s
    return worst


def _render_check_block(name: str, result: Mapping[str, Any]) -> list[str]:
    status = result.get("status", "skip")
    icon = _STATUS_ICON.get(status, "?")
    lines = [
        f"{icon} {name} [{status}]",
        f"   当前值 : {result.get('current_value', '—')}",
        f"   位置   : {result.get('path', '—')}",
    ]
    if status in {"warn", "error"}:
        risk = result.get("risk")
        action = result.get("action")
        if risk:
            lines.append(f"   风险   : {risk}")
        if action:
            # action 可能是多行（含示例命令），缩进对齐
            for i, action_line in enumerate(str(action).splitlines()):
                prefix = "   建议   : " if i == 0 else "            "
                lines.append(prefix + action_line)
    return lines


def format_health_report(results: Mapping[str, Mapping[str, Any]] | None) -> str:
    """完整人类可读健康报告。

    刻意把每个 warn/error 的 risk + action 都展开，不再像 v0.2 那样只说
    「有告警」。pass / skip 项保持极简一行。
    """
    if not results:
        return "(no health results)"

    lines: list[str] = [
        _BAR,
        "🏥 项目健康检查报告（v0.3 M2）",
        _BAR,
    ]
    overall = overall_status(results)
    overall_icon = _STATUS_ICON.get(overall, "?")
    lines.append(f"整体状态：{overall_icon} {overall}")
    lines.append(_BAR)

    for name, result in results.items():
        if not isinstance(result, Mapping):
            continue
        lines.extend(_render_check_block(name, result))
        lines.append("")

    lines.append(_BAR)
    lines.append(
        "提示：所有「建议」都是给你复制粘贴的命令，本程序**不会**自动执行清理。"
    )
    lines.append("      详细维护指南：docs/V0_3_HEALTH_MAINTENANCE.md")
    lines.append(_BAR)
    return "\n".join(lines)


def format_health_report_json(
    results: Mapping[str, Mapping[str, Any]] | None,
) -> str:
    """机器可读 JSON 输出（schema 稳定）。

    输出 schema：
    {
      "overall": "pass" | "warn" | "error" | "skip",
      "checks": {
        "<check_name>": {
          "status": "pass" | "warn" | "error" | "skip",
          "current_value": <str>,
          "path": <str>,
          "risk": <str>,
          "action": <str>,
          "message": <str>,
          ...   # 兼容 v0.2 的 size_mb / count / file_count 等数值字段
        }
      }
    }

    任何对 schema 的破坏都应该在测试里被守护，避免下游脚本断裂。
    """
    payload = {
        "overall": overall_status(results),
        "checks": dict(results) if results else {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
