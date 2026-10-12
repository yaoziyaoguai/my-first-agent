"""从 owner-only 文件向 First Agent 注入 key；key 不进入 argv 或输出。"""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-agent", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--audit-ledger", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, action="append", default=[])
    memory = parser.add_mutually_exclusive_group()
    memory.add_argument("--memory-create", type=Path)
    memory.add_argument("--memory-store", type=Path)
    parser.add_argument("--memory-profile", default="qa-deepseek-v4-flash")
    parser.add_argument("--mcp-catalog", type=Path)
    parser.add_argument("--mcp-safety-state", type=Path)
    parser.add_argument("--subagent", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--tui", action="store_true")
    args = parser.parse_args()
    entry = args.first_agent.absolute()
    if not entry.is_file() or not os.access(entry, os.X_OK):
        parser.error("installed First Agent executable unavailable")
    # launcher 是操作者的本机配置注入器，不属于产品 runtime。
    path = args.key_file.absolute()
    try:
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid():
            raise ValueError
        if stat.S_IMODE(parent.st_mode) != 0o700:
            raise ValueError
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size > 256
            ):
                raise ValueError
            key = os.read(fd, 257).decode("ascii").strip()
        finally:
            os.close(fd)
        if not key.startswith("sk-") or not key[3:].isalnum():
            raise ValueError
    except (OSError, ValueError):
        parser.error("credential file unavailable or unsafe; no key was displayed")
    argv = [
        str(entry), "--workspace", str(args.workspace.absolute()),
        "--state-root", str(args.state_root.absolute()),
        "--provider", "openai_compatible", "--model", "deepseek-v4-flash",
        "--base-url", "https://api.deepseek.com", "--request-path", "/chat/completions",
        "--credential-env", "FIRST_AGENT_DOGFOOD_API_KEY", "--thinking-mode", "disabled",
        "--timeout", "90", "--transport-audit-ledger", str(args.audit_ledger.absolute()),
        "--memory-profile", args.memory_profile,
    ]
    for root in args.skill_root:
        argv.extend(("--skill-root", str(root.absolute())))
    for field in ("memory_create", "memory_store", "mcp_catalog", "mcp_safety_state"):
        value = getattr(args, field)
        if value is not None:
            argv.extend(("--" + field.replace("_", "-"), str(value.absolute())))
    for field in ("subagent", "browser", "tui"):
        if getattr(args, field):
            argv.append("--" + field)
    os.environ["FIRST_AGENT_DOGFOOD_API_KEY"] = key
    try:
        os.execv(str(entry), argv)
    except OSError:
        print("First Agent could not start; credential was not displayed.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
