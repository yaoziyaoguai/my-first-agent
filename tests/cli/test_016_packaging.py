"""016 packaging 回归：wheel-origin、native wrapper 与 base-vs-extra 边界。

从当前 tree 构建一次 non-editable wheel，装入 include-system-site-packages=false 的
临时 venv（venv 自带 pip --no-index --no-deps 安装），native console wrapper 不设
PYTHONPATH/PYTHONHOME 直接执行；httpx 运行时闭包由控制器按 pyproject 声明在当前
dev 环境解析后精确物化到候选 venv site（不含 extras/pytest/ruff/editable，复制
dist-info），以支撑离线 native 执行。

本回归不证明 pip 在线依赖解析与 extras 的正向安装矩阵，那由独立的真实
wheelhouse 验收负责。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
import venv
from collections.abc import Sequence
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement

import main as entrypoint

ROOT = Path(__file__).resolve().parents[2]
EXTRA_MODULES = ("yaml", "mcp", "textual", "playwright")


def _run(
    command: Sequence[str | Path],
    *,
    home: Path,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(part) for part in command],
        cwd=None if cwd is None else str(cwd),
        env=env if env is not None else {"HOME": str(home), "PATH": os.environ.get("PATH", "")},
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _native_env(home: Path) -> dict[str, str]:
    """native wrapper 环境：刻意不含 PYTHONPATH/PYTHONHOME，不暴露 host site。"""

    return {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def _origin_is_from_installed_site(origin: str, site: Path) -> bool:
    """正向 origin 断言与负向污染 oracle 共用同一谓词。"""

    return Path(origin).is_relative_to(site)


def _resolve_base_runtime_closure(declared: Sequence[str]) -> dict[str, str]:
    """在当前 dev 环境按 pyproject 声明 BFS 解析 base 闭包，逐边校验已安装 version。

    只跟随无 extra marker 的 Requires-Dist 边（extras、pytest/ruff 永远不会被
    httpx 闭包触达）。
    """

    resolved: dict[str, str] = {}
    visited: set[str] = set()
    pending = list(declared)
    while pending:
        raw = pending.pop(0)
        if raw in visited:
            continue
        visited.add(raw)
        requirement = Requirement(raw)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        dist = metadata.distribution(requirement.name)
        if requirement.specifier and not requirement.specifier.contains(dist.version):
            raise AssertionError(f"dev environment {requirement.name} violates {raw}")
        resolved[dist.metadata["Name"].replace("-", "_").lower()] = dist.version
        pending.extend(dist.requires or [])
    assert resolved, "base dependency closure must not be empty"
    return resolved


def _materialize_base_runtime_closure(site: Path, closure: dict[str, str]) -> None:
    """按 RECORD 把 wheel 安装的闭包精确复制进候选 venv site（含 dist-info）。

    拒绝 editable/direct 来源；复制目标是临时 venv site，不经 PYTHONPATH 暴露 host。
    越出 site 的 entry（如 httpx 的 ../../../bin/httpx）是依赖自身的 console
    script，不属于本测试所需，跳过而不复制。
    """

    for canonical, expected_version in closure.items():
        dist = metadata.distribution(canonical)
        assert dist.version == expected_version, canonical
        assert dist.read_text("direct_url.json") is None, f"{canonical} must be index-installed"
        files = dist.files
        assert files is not None, f"{canonical} must carry a wheel RECORD"
        for item in files:
            parts = item.parts
            if "__pycache__" in parts or parts[-1].endswith(".pyc"):
                continue
            # 只物化到 site：含 '..' 的 entry 是越出 site-packages 的依赖 console script。
            if ".." in parts:
                continue
            source = Path(dist.locate_file(item))
            assert source.is_file(), source
            destination = site.joinpath(*parts)
            assert destination.is_relative_to(site), destination
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


@pytest.fixture(scope="module")
def installed_candidate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """整个模块共享一次 wheel 构建、一个隔离 venv 与一次闭包物化。"""

    work_root = tmp_path_factory.mktemp("installed-candidate")
    home = work_root / "controller-home"
    home.mkdir()

    wheel_dir = work_root / "wheel"
    wheel_dir.mkdir()
    build = _run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", str(wheel_dir), str(ROOT)],
        home=home,
        timeout=300,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    (wheel,) = wheel_dir.glob("first_agent-1.0.0-*.whl")

    venv_root = work_root / "candidate-venv"
    venv.create(str(venv_root), system_site_packages=False, with_pip=True)
    venv_python = venv_root / "bin" / "python"
    python_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
    venv_site = venv_root / "lib" / python_dir / "site-packages"
    assert "include-system-site-packages = false" in (venv_root / "pyvenv.cfg").read_text()

    # 安装器解释器即候选 venv python，wrapper shebang 因此指向候选 venv。
    install = _run(
        [venv_python, "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        home=home,
        timeout=180,
    )
    assert install.returncode == 0, install.stdout + install.stderr

    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    _materialize_base_runtime_closure(venv_site, _resolve_base_runtime_closure(declared))

    return venv_root, venv_python, venv_site


def test_candidate_metadata_and_console_entry_are_1_0() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert document["project"]["version"] == "1.0.0"
    assert document["project"]["scripts"]["first-agent"] == "main:main"
    assert document["project"]["scripts"]["first-agent-schedule"] == "agent.automation.cli:main"
    assert "setuptools>=68.0" in document["project"]["optional-dependencies"]["dev"]


def test_help_prioritizes_everyday_start_and_setup() -> None:
    help_text = entrypoint.build_parser().format_help()

    assert "Run in the current directory" in help_text
    assert "setup" in help_text and "setup-web" in help_text
    assert "Advanced options" in help_text


def test_installed_candidate_wheel_runs_natively_in_isolated_venv(
    installed_candidate: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    venv_root, venv_python, venv_site = installed_candidate
    agent_wrapper = venv_root / "bin" / "first-agent"
    schedule_wrapper = venv_root / "bin" / "first-agent-schedule"

    # 旧 harness 的 host pip --prefix 安装会把 host 解释器写进 shebang，故必须核对。
    for wrapper in (agent_wrapper, schedule_wrapper):
        interpreter = Path(wrapper.read_text().splitlines()[0][2:].split()[0])
        assert interpreter == venv_python, (wrapper.name, interpreter)

    neutral = tmp_path / "neutral"
    neutral.mkdir()
    home = tmp_path / "native-home"
    home.mkdir()
    native = _native_env(home)

    version_result = _run([agent_wrapper, "--version"], home=home, cwd=neutral, env=native)
    help_result = _run([agent_wrapper, "--help"], home=home, cwd=neutral, env=native)
    assert version_result.returncode == 0
    assert version_result.stdout.strip() == "first-agent 1.0.0"
    assert help_result.returncode == 0
    assert "Run in the current directory" in help_result.stdout

    schedule_help = _run([schedule_wrapper, "--help"], home=home, cwd=neutral, env=native)
    assert schedule_help.returncode == 0, schedule_help.stdout + schedule_help.stderr
    assert "first-agent-schedule" in schedule_help.stdout
    # 无 019 配置时 reconcile（含完整 --delivery-id）必须闭合为 needs_019_config。
    reconcile_command = [schedule_wrapper, "reconcile", "--delivery-id", "candidate:probe"]
    reconcile = _run(reconcile_command, home=home, cwd=neutral, env=native)
    assert reconcile.returncode == 2, reconcile.stdout + reconcile.stderr
    assert '"code":"needs_019_config"' in reconcile.stdout

    # 一次 probe 同时取 sys.path 与四个关键 origin：唯一 site 是候选 venv site，
    # entrypoint / schedule target / skill runner / base runtime 都来自安装产物。
    origin_probe = _run(
        [
            venv_python,
            "-c",
            "import importlib, json, sys\n"
            "names = ['main', 'agent.automation.cli', 'first_agent_skill_runner', 'httpx']\n"
            "print(json.dumps({'sys_path': sys.path,\n"
            " 'origins': {name: importlib.import_module(name).__file__ for name in names}}))\n",
        ],
        home=home,
        cwd=neutral,
        env=native,
    )
    assert origin_probe.returncode == 0, origin_probe.stdout + origin_probe.stderr
    origin_data = json.loads(origin_probe.stdout)
    assert [entry for entry in origin_data["sys_path"] if entry.endswith("site-packages")] == [
        str(venv_site)
    ]
    for label, origin in origin_data["origins"].items():
        assert _origin_is_from_installed_site(origin, venv_site), (label, origin)
        assert str(ROOT) not in origin, (label, origin)

    # skill runner 保持零依赖可用：-S 下从安装 origin 导入，且不连坐 import agent。
    runner_probe = _run(
        [
            venv_python,
            "-S",
            "-c",
            "import json, sys\n"
            "import first_agent_skill_runner.__main__ as runner\n"
            "print(json.dumps({'origin': runner.__file__, 'agent': 'agent' in sys.modules}))\n",
        ],
        home=home,
        cwd=neutral,
        env={**native, "PYTHONPATH": str(venv_site)},
    )
    assert runner_probe.returncode == 0, runner_probe.stdout + runner_probe.stderr
    runner_data = json.loads(runner_probe.stdout)
    assert _origin_is_from_installed_site(runner_data["origin"], venv_site)
    assert str(ROOT) not in runner_data["origin"]
    assert runner_data["agent"] is False

    # installed first-agent + FakeProvider 走一次真实 AgentRuntime turn 再退出。
    repl_workspace = tmp_path / "repl-workspace"
    repl_workspace.mkdir()
    repl = _run(
        [agent_wrapper, "--provider", "fake", "--state-root", str(tmp_path / "repl-state")],
        home=home,
        cwd=repl_workspace,
        env=native,
        stdin="installed candidate wheel says hello\n/exit\n",
        timeout=120,
    )
    assert repl.returncode == 0, repl.stdout + repl.stderr
    assert "First Agent is ready in:" in repl.stdout
    # FakeProvider echo 最新一条 user 文本：回显出现即证明一次完整 AgentRuntime turn。
    assert "installed candidate wheel says hello" in repl.stdout
    assert str(ROOT) not in repl.stdout + repl.stderr

    # base 安装不含四个 extras；httpx 作为正向对照可导入。
    for module in EXTRA_MODULES:
        missing = _run(
            [venv_python, "-c", f"import {module}"], home=home, cwd=neutral, env=native
        )
        assert missing.returncode != 0, module
        assert "ModuleNotFoundError" in missing.stderr, (module, missing.stderr)
    httpx_control = _run([venv_python, "-c", "import httpx"], home=home, cwd=neutral, env=native)
    assert httpx_control.returncode == 0, httpx_control.stderr

    # 产品级 missing-extra 诊断（TUI）：错误指向缺依赖本身，而非缺配置。
    tui_run = _run(
        [agent_wrapper, "--provider", "fake", "--tui",
         "--state-root", str(tmp_path / "tui-state")],
        home=home,
        cwd=repl_workspace,
        env=native,
        stdin="",
        timeout=120,
    )
    assert tui_run.returncode == 2, tui_run.stdout + tui_run.stderr
    assert "the TUI requires the optional 'tui' extra" in tui_run.stdout
    assert "install it or use the plain CLI" in tui_run.stdout


def test_origin_detector_rejects_source_contamination(
    installed_candidate: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """负向 oracle：同一 origin 谓词必须拒绝 source 污染，否则正向断言无意义。"""

    _, venv_python, venv_site = installed_candidate
    home = tmp_path / "oracle-home"
    home.mkdir()

    # 故意从 ROOT cwd 解析 main 制造真实污染，同一谓词必须判为未安装来源。
    contaminated = _run(
        [venv_python, "-c", "import main; print(main.__file__)"],
        home=home,
        cwd=ROOT,
        env=_native_env(home),
    )
    assert contaminated.returncode == 0, contaminated.stdout + contaminated.stderr
    origin = contaminated.stdout.strip()
    assert origin == str(ROOT / "main.py"), origin
    assert not _origin_is_from_installed_site(origin, venv_site)
