from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.mcp.catalog import (
    McpCatalog,
    McpCatalogError,
    McpToolDescriptor,
    build_mcp_catalog,
)

PROTO = "2025-11-25"


def _executable(tmp_path: Path) -> Path:
    exe = tmp_path / "server.py"
    exe.write_text("#!/usr/bin/env python\nimport sys\nprint('mcp fixture')\n", encoding="utf-8")
    exe.chmod(0o700)
    return exe


def _config(exe: Path, **overrides) -> dict:
    server = {
        "server_id": "repo",
        "transport": "stdio",
        "command": str(exe),
        "args": [],
        "safety_generation": "gen-1",
        "protocol_revision": PROTO,
        "tools": [
            {
                "remote_name": "search",
                "description": "Search the repository.",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "output_limit_chars": 1000,
            }
        ],
    }
    server.update(overrides)
    return {"servers": [server]}


def test_valid_catalog_maps_to_namespaced_descriptor(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    catalog = build_mcp_catalog(_config(exe))

    assert isinstance(catalog, McpCatalog)
    assert len(catalog.tools) == 1
    tool = catalog.tools[0]
    assert isinstance(tool, McpToolDescriptor)
    assert tool.local_name == "mcp__repo__search"
    assert tool.remote_name == "search"
    assert tool.descriptor_digest
    assert catalog.servers[0].config_digest
    assert catalog.catalog_digest


def test_duplicate_local_name_fails_closed(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"].append(
        {
            "server_id": "repo2",
            "transport": "stdio",
            "command": str(exe),
            "args": [],
            "safety_generation": "gen-1",
            "protocol_revision": PROTO,
            "tools": [
                {
                    "remote_name": "search",
                    "description": "duplicate tool",
                    "input_schema": {"type": "object"},
                    "output_limit_chars": 100,
                }
            ],
        }
    )
    # both map to mcp__<server>__search, but server ids differ; ensure within-server dup fails:
    dup = _config(exe)
    dup["servers"][0]["tools"].append(
        {
            "remote_name": "search",
            "description": "dup",
            "input_schema": {"type": "object"},
            "output_limit_chars": 100,
        }
    )
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(dup)
    del config  # keep lints quiet about the constructed-but-unused variant


def test_credential_looking_value_in_catalog_fails_closed(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["api_key"] = "sk-live-9a8b7c6d5e4f3a2b1c0d"
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)


def test_unsupported_transport_fails_closed(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["transport"] = "http"
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)


def test_missing_safety_generation_fails_closed(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    del config["servers"][0]["safety_generation"]
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)


def test_non_absolute_or_symlinked_command_fails_closed(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["command"] = "./server.py"
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)

    link = tmp_path / "link.py"
    link.symlink_to(exe)
    config2 = _config(exe)
    config2["servers"][0]["command"] = str(link)
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config2)


def test_executable_identity_is_frozen_and_revalidated(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    catalog = build_mcp_catalog(_config(exe))
    spawn = catalog.servers[0].spawn_identity
    identity = spawn.executable
    assert identity["dev"] and identity["ino"]
    assert identity["mode"] == os.stat(exe).st_mode
    assert identity["content_digest"]
    # ancestor（command 父目录）identity 也被冻结。
    assert spawn.ancestor["dev"] and spawn.ancestor["ino"]

    # 内容改动后 digest 变化；descriptor/config identity 依赖它。
    exe.write_text("#!/usr/bin/env python\nprint('changed')\n", encoding="utf-8")
    exe.chmod(0o700)
    catalog2 = build_mcp_catalog(_config(exe))
    exe2 = catalog2.servers[0].spawn_identity.executable
    assert exe2["content_digest"] != identity["content_digest"]
    assert catalog2.servers[0].config_digest != catalog.servers[0].config_digest

    # spawn-time revalidation：用旧 frozen identity 复验被改动的 executable 必须 fail closed。
    from agent.mcp.catalog import revalidate_spawn_identity

    with pytest.raises(McpCatalogError):
        revalidate_spawn_identity(str(exe), None, spawn)


def test_spawn_identity_revalidation_detects_ancestor_drift(tmp_path: Path) -> None:
    """G2：保留 executable inode 但替换其父目录（ancestor）也是 drift——只校验 executable
    digest 检测不到。revalidate_spawn_identity 必须复验 ancestor dev/ino。"""
    import os as _os

    from agent.mcp.catalog import McpLimits, freeze_spawn_identity, revalidate_spawn_identity

    server_bin = tmp_path / "serverbin"
    server_bin.mkdir()
    exe = server_bin / "server.py"
    exe.write_text("#!/usr/bin/env python\nprint('mcp fixture')\n", encoding="utf-8")
    exe.chmod(0o700)
    frozen = freeze_spawn_identity(str(exe), None, McpLimits())
    original_ino = _os.stat(exe).st_ino

    # ancestor drift：move exe 出、替换 serverbin 目录、move 回（exe inode 不变，目录 inode 变）。
    stash = tmp_path / "stash"
    _os.replace(exe, stash)
    server_bin.rmdir()
    server_bin.mkdir()
    _os.replace(stash, exe)
    assert _os.stat(exe).st_ino == original_ino, "test setup: executable inode must match"

    with pytest.raises(McpCatalogError):
        revalidate_spawn_identity(str(exe), None, frozen)


def test_spawn_identity_revalidation_detects_cwd_drift(tmp_path: Path) -> None:
    """G2：cwd 目录被替换（同路径、新 inode）也是 drift——revalidate 必须复验 cwd dev/ino。"""
    from agent.mcp.catalog import McpLimits, freeze_spawn_identity, revalidate_spawn_identity

    exe = _executable(tmp_path)
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    frozen = freeze_spawn_identity(str(exe), str(cwd_dir), McpLimits())
    # baseline：未漂移时不 raise。
    revalidate_spawn_identity(str(exe), str(cwd_dir), frozen)

    # cwd drift：同路径重建目录 → 新 inode。
    cwd_dir.rmdir()
    cwd_dir.mkdir()
    with pytest.raises(McpCatalogError):
        revalidate_spawn_identity(str(exe), str(cwd_dir), frozen)


def test_env_names_must_be_valid_identifiers(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["env_names"] = ["GOOD_VAR", "BAD=VAR"]
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)


def test_protocol_revision_is_pinned(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["protocol_revision"] = "2024-01-01"
    with pytest.raises(McpCatalogError):
        build_mcp_catalog(config)


def test_descriptor_digest_is_deterministic(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    first = build_mcp_catalog(_config(exe))
    second = build_mcp_catalog(_config(exe))
    assert first.catalog_digest == second.catalog_digest
    assert first.tools[0].descriptor_digest == second.tools[0].descriptor_digest


def test_error_messages_do_not_leak_absolute_paths_or_values(tmp_path: Path) -> None:
    exe = _executable(tmp_path)
    config = _config(exe)
    config["servers"][0]["api_key"] = "sk-leak-9a8b7c6d5e4f3a2b1c0d"
    with pytest.raises(McpCatalogError) as info:
        build_mcp_catalog(config)
    assert str(exe.parent) not in str(info.value)
    assert "sk-leak" not in str(info.value)


def test_catalog_parsing_does_not_import_sdk() -> None:
    import subprocess
    import sys

    code = (
        "import sys\n"
        "sys.modules['mcp'] = None\n"
        "from agent.mcp.catalog import build_mcp_catalog\n"
        "print('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
