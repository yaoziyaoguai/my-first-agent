"""无凭据、无网络模型的 installed CLI 复现；退出 1 表示验收行为仍失败。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def run(entry: Path, args: list[str], input_text: str) -> dict[str, object]:
    # 故意不继承 ambient credential、profile 或 PYTHONPATH。
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "en_US.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [str(entry), *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/private/tmp",
        env=env,
        check=False,
    )
    output = result.stdout + result.stderr
    if len(output) > 20_000:
        raise RuntimeError("probe output exceeds bound; no PASS can be inferred")
    return {"exit_code": result.returncode, "output": output}


def manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-agent", type=Path, required=True)
    args = parser.parse_args()
    # 不 resolve executable symlink，以保留安装 venv 的启动语义。
    entry = args.first_agent.absolute()
    if not entry.is_file():
        parser.error("--first-agent must name an installed executable")
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="first-agent-qa-v2-", dir="/private/tmp") as tmp:
        root = Path(tmp)
        for choice in (1, 2):
            workspace = root / f"workspace-{choice}"
            workspace.mkdir()
            state = root / f"state-{choice}"
            common = ["--workspace", str(workspace), "--state-root", str(state)]
            initial = run(entry, [*common, "--provider", "fake"], "/new\n/exit\n")
            before = manifest(state)
            reopened = run(entry, [*common, "--provider", "fake"], f"{choice}\n/exit\n")
            after = manifest(state)
            passed = (
                initial["exit_code"] == 0
                and reopened["exit_code"] == 0
                and "First Agent is ready" in str(reopened["output"])
                and before == after
            )
            cases.append({
                "id": f"R1-select-{choice}",
                "pass": passed,
                "initial": initial,
                "reopen": reopened,
                "state_bytes_unchanged": before == after,
            })
        workspace = root / "help-workspace"
        workspace.mkdir()
        common = ["--workspace", str(workspace), "--state-root", str(root / "help-state")]
        help_result = run(entry, [*common, "--provider", "fake"], "/help\n/exit\n")
        output = str(help_result["output"])
        cases.append({
            "id": "R3-interactive-help",
            "pass": help_result["exit_code"] == 0
            and "Unknown command" not in output
            and all(name in output for name in ("/new", "/sources", "/exit")),
            **help_result,
        })
    print(json.dumps({"cases": cases}, ensure_ascii=False, indent=2))
    return 0 if all(case["pass"] for case in cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
