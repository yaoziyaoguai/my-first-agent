"""用 owner-only 文件注入 DeepSeek key，并强制本轮累计模型请求预算。"""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path


def _positive_budget(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer no greater than 40") from None
    if not 1 <= value <= 40:
        raise argparse.ArgumentTypeError("must be a positive integer no greater than 40")
    return value


def _read_key(path: Path, parser: argparse.ArgumentParser) -> str:
    absolute = path.absolute()
    try:
        parent = absolute.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.getuid()
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise ValueError
        descriptor = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or info.st_size > 256
            ):
                raise ValueError
            key = os.read(descriptor, 257).decode("ascii").strip()
        finally:
            os.close(descriptor)
        if not key.startswith("sk-") or not key[3:].isalnum():
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        parser.error("credential file unavailable or unsafe; no key was displayed")
    return key


def _minimal_environment(key: str) -> dict[str, str]:
    environment = {"FIRST_AGENT_DOGFOOD_API_KEY": key}
    for name in (
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ):
        if value := os.environ.get(name):
            environment[name] = value
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--first-agent", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--audit-ledger", type=Path, required=True)
    parser.add_argument("--max-model-attempts", type=_positive_budget, required=True)
    parser.add_argument("--project-path", action="append", default=[])
    parser.add_argument("--without-owner-preferences", action="store_true")
    args = parser.parse_args()

    entry = args.first_agent.absolute()
    if not entry.is_file() or not os.access(entry, os.X_OK):
        parser.error("installed First Agent executable unavailable")
    key = _read_key(args.key_file, parser)
    argv = [
        str(entry),
        "--workspace",
        str(args.workspace.absolute()),
        "--state-root",
        str(args.state_root.absolute()),
        "--provider",
        "openai_compatible",
        "--model",
        "deepseek-v4-flash",
        "--base-url",
        "https://api.deepseek.com",
        "--request-path",
        "/chat/completions",
        "--credential-env",
        "FIRST_AGENT_DOGFOOD_API_KEY",
        "--thinking-mode",
        "disabled",
        "--timeout",
        "90",
        "--transport-audit-ledger",
        str(args.audit_ledger.absolute()),
        "--max-model-attempts",
        str(args.max_model_attempts),
    ]
    for project_path in args.project_path:
        argv.extend(("--project-path", project_path))
    if args.without_owner_preferences:
        argv.append("--without-owner-preferences")
    try:
        os.execve(str(entry), argv, _minimal_environment(key))
    except OSError:
        print("First Agent could not start; credential was not displayed.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
