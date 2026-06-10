#!/usr/bin/env python3
"""First Agent 启动就绪检查（startup readiness check）。

这个脚本是 local trial 的前置检查——在用户按 README 安装依赖后、
第一次交互前，验证 fake/local 默认安全路径能否正常启动。

设计原则：
- 不读取 .env：fake/local 路径明确不依赖真实 API key，加载 .env 反会引入变量干扰
- 使用临时 HOME：避免用户真实 ~/.claude、~/.bashrc 等影响 smoke 结果
- 不调用真实 API：所有检查都是静态 import / CLI 输出验证 / subprocess smoke
- 输出脱敏：不打印任何路径、用户名、环境变量值
- exit code 语义清晰：0=就绪, 1=有告警但可继续, 2=阻塞性错误

为什么 startup readiness 是 local trial 前置能力：
- 用户在本地试用的第一步就是「按 README 安装并启动」
- 如果启动就失败（缺依赖、Python 版本不兼容、import 报错），试用无法推进
- 本脚本让用户在执行 local trial 前先拿到一个 ok/not-ok 的明确信号，降低试错成本

为什么默认 fake/local 是安全路径：
- fake provider 是 deterministic test fixture，不调用真实 LLM
- 不联网、不读 .env、不写用户目录
- 所有输入输出受控，适合首次启动验证
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check_python_version() -> tuple[bool, str]:
    """检查 Python 版本 >= 3.10。（最低要求，推荐 3.12）"""
    vi = sys.version_info
    ok = vi >= (3, 10)
    label = f"{vi.major}.{vi.minor}.{vi.micro}"
    return ok, label


def check_import_main() -> tuple[bool, str]:
    """检查能否 import main 模块（不执行 main()）。

    在 temp HOME 下运行，隔离用户全局配置影响。
    """
    import importlib

    # 确保 PROJECT_ROOT 在 sys.path 最前面——脚本在 scripts/ 子目录下，
    # Python 默认把脚本所在目录加入 sys.path[0]，但 main.py 在项目根目录。
    sys.path.insert(0, str(PROJECT_ROOT))

    orig_home = os.environ.get("HOME")
    with tempfile.TemporaryDirectory(prefix="first_agent_smoke_") as tmp_home:
        os.environ["HOME"] = tmp_home
        # 清除可能干扰 fake provider 判断的环境变量
        for key in list(os.environ):
            if (key.startswith("ANTHROPIC_")
                    or key.startswith("OPENAI_")
                    or key == "MY_FIRST_AGENT_LLM_PROVIDER"):
                del os.environ[key]
        try:
            # 只 import，不执行 main()
            importlib.import_module("main")
            return True, "ok"
        except Exception as e:
            return False, str(e)
        finally:
            if orig_home is not None:
                os.environ["HOME"] = orig_home


def check_provider_mode_default() -> tuple[bool, str]:
    """验证未设置 provider 环境变量时，banner 输出 fake (local only) 模式。

    在隔离环境中运行 main.py，确保不会误触 real provider 路径。
    """
    orig_env = dict(os.environ)
    try:
        # 清除所有可能触发 real provider 的环境变量
        for key in list(os.environ):
            if (
                key.startswith("ANTHROPIC_")
                or key.startswith("OPENAI_")
                or key == "MY_FIRST_AGENT_LLM_PROVIDER"
                or key == "MY_FIRST_AGENT_LLM_MODEL"
                or key == "MODEL_NAME"
            ):
                del os.environ[key]
        # 确保 HOME 是临时目录
        with tempfile.TemporaryDirectory(prefix="first_agent_smoke_") as tmp_home:
            os.environ["HOME"] = tmp_home
            result = subprocess.run(
                [sys.executable, "-c",
                 "from agent.cli_renderer import render_provider_mode_banner; "
                 "print(render_provider_mode_banner())"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(PROJECT_ROOT),
                env={**os.environ},
            )
            output = result.stdout + result.stderr
            if "fake" in output.lower() and "local" in output.lower():
                return True, "fake (local only)"
            return False, output.strip()[:120]
    except Exception as e:
        return False, str(e)
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def check_help_output() -> tuple[bool, str]:
    """检查 --help 输出是否包含关键 onboarding 信息（不调用真实 API）。"""
    orig_env = dict(os.environ)
    try:
        for key in list(os.environ):
            if (
                key.startswith("ANTHROPIC_")
                or key.startswith("OPENAI_")
                or key == "MY_FIRST_AGENT_LLM_PROVIDER"
            ):
                del os.environ[key]
        with tempfile.TemporaryDirectory(prefix="first_agent_smoke_") as tmp_home:
            os.environ["HOME"] = tmp_home
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "main.py"), "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(PROJECT_ROOT),
                env={**os.environ},
            )
            output = result.stdout + result.stderr
            checks = [
                ("First Agent" in output, "title present"),
                ("fake" in output.lower(), "fake mode mentioned"),
                ("当前可用" in output or "Available" in output, "available features"),
            ]
            passed = all(c[0] for c in checks)
            return passed, "; ".join(c[1] for c in checks if c[0])
    except Exception as e:
        return False, str(e)
    finally:
        os.environ.clear()
        os.environ.update(orig_env)


def check_dependencies() -> tuple[bool, str]:
    """检查核心依赖是否可 import。

    只检查 fake/local 路径必需的包，不检查 anthropic（opt-in real provider）。
    """
    required = [
        ("pydantic", "pydantic"),
    ]
    missing = []
    for display_name, import_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing.append(display_name)
    if missing:
        return False, f"missing: {', '.join(missing)}"
    return True, "all core deps ok"


def run_all_checks() -> dict[str, tuple[bool, str]]:
    """运行所有 startup readiness 检查，返回结构化结果。

    不调用 sys.exit()——由调用方决定退出码和输出格式。
    """
    checks: dict[str, tuple[bool, str]] = {}
    checks["python_version"] = check_python_version()
    checks["dependencies"] = check_dependencies()
    checks["import_main"] = check_import_main()
    checks["provider_mode_default"] = check_provider_mode_default()
    checks["help_output"] = check_help_output()
    return checks


def render_readiness_report(results: dict[str, tuple[bool, str]]) -> str:
    """把 check 结果渲染为人类可读报告。"""
    lines = [
        "=" * 60,
        "  First Agent Startup Readiness Check",
        "=" * 60,
        "",
        f"  Python: {sys.version}",
        f"  Project root: {PROJECT_ROOT.name}",
        "",
        "  Checks:",
    ]
    all_ok = True
    for name, (ok, detail) in results.items():
        icon = "PASS" if ok else "FAIL"
        lines.append(f"    [{icon}] {name}: {detail}")
        if not ok:
            all_ok = False

    lines.append("")
    if all_ok:
        lines.append("  结论：startup readiness PASS")
        lines.append("  下一步：python main.py --help 查看 onboarding")
    else:
        lines.append("  结论：startup readiness 存在问题")
        lines.append("  请先修复 FAIL 项再继续 local trial")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    results = run_all_checks()
    print(render_readiness_report(results))
    all_ok = all(ok for ok, _ in results.values())
    if all_ok:
        return 0
    # 检查是否有阻塞性错误（python_version / dependencies / import_main）
    blockers = ["python_version", "dependencies", "import_main"]
    any_blocker_failed = any(not results[k][0] for k in blockers)
    return 2 if any_blocker_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
