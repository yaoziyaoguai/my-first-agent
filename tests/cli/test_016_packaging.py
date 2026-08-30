from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import main as entrypoint

ROOT = Path(__file__).resolve().parents[2]


def _current_first_agent_distribution() -> tuple[str, str] | None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlib import metadata\n"
            "import json\n"
            "try:\n"
            "    item = metadata.distribution('first-agent')\n"
            "except metadata.PackageNotFoundError:\n"
            "    print('null')\n"
            "else:\n"
            "    print(json.dumps([item.version, str(item.locate_file(''))]))\n",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=ROOT.parent,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
    value = json.loads(probe.stdout)
    if value is None:
        return None
    assert isinstance(value, list) and len(value) == 2
    assert all(isinstance(item, str) for item in value)
    return value[0], value[1]


def test_candidate_metadata_and_console_entry_are_1_0() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert document["project"]["version"] == "1.0.0"
    assert document["project"]["scripts"]["first-agent"] == "main:main"
    assert "setuptools>=68.0" in document["project"]["optional-dependencies"]["dev"]


def test_help_prioritizes_everyday_start_and_setup() -> None:
    help_text = entrypoint.build_parser().format_help()

    assert "Run in the current directory" in help_text
    assert "setup" in help_text and "setup-web" in help_text
    assert "Advanced options" in help_text


def test_built_wheel_exposes_installed_entry_point_from_neutral_directory(
    tmp_path: Path,
) -> None:
    current_distribution = _current_first_agent_distribution()
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheel = next(wheel_dir.glob("first_agent-1.0.0-*.whl"))

    prefix = tmp_path / "prefix"
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--ignore-installed",
            "--prefix",
            str(prefix),
            str(wheel),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert _current_first_agent_distribution() == current_distribution

    neutral = tmp_path / "neutral"
    neutral.mkdir()
    command = prefix / "bin" / "first-agent"
    site_packages = (
        prefix
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    clean_env = {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(site_packages),
    }
    version_result = subprocess.run(
        [str(command), "--version"],
        cwd=neutral,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    help_result = subprocess.run(
        [str(command), "--help"],
        cwd=neutral,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert version_result.returncode == 0
    assert version_result.stdout.strip() == "first-agent 1.0.0"
    assert help_result.returncode == 0
    assert "Run in the current directory" in help_result.stdout
    assert str(ROOT) not in version_result.stdout + help_result.stdout
    origin = subprocess.run(
        [sys.executable, "-c", "import main; print(main.__file__)"],
        cwd=neutral,
        env=clean_env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert origin.returncode == 0
    assert str(site_packages) in origin.stdout
    assert str(ROOT) not in origin.stdout
