from __future__ import annotations

import argparse


def parse_retry_limit(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-retries", type=int, default=0)
    return parser.parse_args(argv).max_retries
