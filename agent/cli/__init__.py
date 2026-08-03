"""Thin CLI and headless adapters for the Runtime Kernel."""

from agent.cli.app import run_headless, run_repl
from agent.cli.render import TerminalRenderer

__all__ = ["TerminalRenderer", "run_headless", "run_repl"]
