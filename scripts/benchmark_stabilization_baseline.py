#!/usr/bin/env python3
"""v0.9.x stabilization benchmark baseline 的兼容 CLI 入口。

真实实现留在 ``scripts/stabilization_benchmark_baseline.py``，避免复制 runner
逻辑。本文件只为审计命令提供稳定脚本名，不读取 `.env`、不调用真实 LLM、
不引入新的 benchmark 平台能力。
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.stabilization_benchmark_baseline import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
