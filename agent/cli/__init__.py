"""CLI adapter helpers.

本包只放命令行入口的 I/O adapter 与维护命令路由，不拥有 Agent Runtime
状态机，也不写 checkpoint。`main.py` 仍是进程入口，但不再承载所有 CLI 细节。
"""
