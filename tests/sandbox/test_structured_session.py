"""owner-only structured session 的 descriptor-pinned readback。"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace

import pytest

from agent.sandbox.contracts import (
    StructuredResultKind,
    StructuredSandboxInputV1,
    StructuredSandboxIoPlanV1,
)
from agent.sandbox.structured_session import (
    create_structured_session,
    read_structured_session,
)


def io_plan(
    *, expected_result_kind: StructuredResultKind = StructuredResultKind.OBSERVATION
) -> StructuredSandboxIoPlanV1:
    request = b'{"task":"inspect"}'
    source = b"pdf"
    return StructuredSandboxIoPlanV1(
        package_digest="a" * 64,
        entrypoint_id="inspect",
        entrypoint_digest="b" * 64,
        request_bytes=request,
        request_digest=hashlib.sha256(request).hexdigest(),
        inputs=(
            StructuredSandboxInputV1(
                slot="source",
                content=source,
                content_digest=hashlib.sha256(source).hexdigest(),
            ),
        ),
        result_cap_bytes=1024,
        artifact_cap_bytes=1024,
        aggregate_output_cap_bytes=2048,
        expected_result_kind=expected_result_kind,
    )


def _write_existing(session, name: str, value: bytes) -> None:  # noqa: ANN001
    fd = os.open(name, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, dir_fd=session.root_fd)
    try:
        assert os.write(fd, value) == len(value)
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_file(session, name: str, value: bytes) -> None:  # noqa: ANN001
    os.fchmod(session.root_fd, 0o700)
    os.unlink(name, dir_fd=session.root_fd)
    fd = os.open(
        name,
        os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
        0o600,
        dir_fd=session.root_fd,
    )
    try:
        assert os.write(fd, value) == len(value)
        os.fsync(fd)
    finally:
        os.close(fd)


def _valid_observation() -> bytes:
    return json.dumps(
        {
            "kind": "observation",
            "payload": {},
            "protocol": "first-agent-skill-result-v1",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def replace_result_with_symlink(session) -> None:  # noqa: ANN001
    os.fchmod(session.root_fd, 0o700)
    os.unlink("result.json", dir_fd=session.root_fd)
    os.symlink("/dev/null", "result.json", dir_fd=session.root_fd)


def replace_result_inode(session) -> None:  # noqa: ANN001
    _replace_file(session, "result.json", _valid_observation())


def unlink_result(session) -> None:  # noqa: ANN001
    os.fchmod(session.root_fd, 0o700)
    os.unlink("result.json", dir_fd=session.root_fd)


def write_oversize_result(session) -> None:  # noqa: ANN001
    _write_existing(session, "result.json", b"x" * 1025)


def write_malformed_result(session) -> None:  # noqa: ANN001
    _write_existing(session, "result.json", b"not-json")


def create_third_output(session) -> None:  # noqa: ANN001
    os.fchmod(session.root_fd, 0o700)
    fd = os.open(
        "surprise.bin",
        os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY,
        0o600,
        dir_fd=session.root_fd,
    )
    os.close(fd)


def write_artifact_for_observation(session) -> None:  # noqa: ANN001
    _write_existing(session, "result.json", _valid_observation())
    _write_existing(session, "artifact.bin", b"unexpected")


def test_session_has_only_fixed_owner_files_and_read_only_inputs(tmp_path):
    session = create_structured_session(tmp_path, io_plan())
    try:
        assert set(os.listdir(session.root_fd)) == {
            "request.json",
            "inputs",
            "result.json",
            "artifact.bin",
        }
        assert stat.S_IMODE(os.fstat(session.root_fd).st_mode) == 0o500
        assert stat.S_IMODE(
            os.stat("request.json", dir_fd=session.root_fd, follow_symlinks=False).st_mode
        ) == 0o400
        assert stat.S_IMODE(
            os.stat("result.json", dir_fd=session.root_fd, follow_symlinks=False).st_mode
        ) == 0o600
        assert stat.S_IMODE(
            os.stat("source", dir_fd=session.inputs_fd, follow_symlinks=False).st_mode
        ) == 0o400
    finally:
        session.close_and_remove()


@pytest.mark.parametrize(
    "attack,code",
    [
        (replace_result_with_symlink, "result_replaced"),
        (replace_result_inode, "result_replaced"),
        (unlink_result, "result_missing"),
        (write_oversize_result, "result_too_large"),
        (write_malformed_result, "result_malformed"),
        (create_third_output, "extra_output"),
        (write_artifact_for_observation, "artifact_unexpected"),
    ],
)
def test_readback_fails_closed_after_execution(tmp_path, attack, code):  # noqa: ANN001
    plan = io_plan()
    session = create_structured_session(tmp_path, plan)
    try:
        attack(session)
        result = read_structured_session(session, plan)
        assert result.outcome.value == code
        assert result.result_bytes == b""
        assert result.artifact_bytes is None
    finally:
        if code == "extra_output":
            os.unlink("surprise.bin", dir_fd=session.root_fd)
        session.close_and_remove()


def test_readback_accepts_only_canonical_expected_result(tmp_path):
    plan = io_plan()
    session = create_structured_session(tmp_path, plan)
    try:
        raw = _valid_observation()
        _write_existing(session, "result.json", raw)
        result = read_structured_session(session, plan)
        assert result.outcome.value == "valid"
        assert result.result_bytes == raw
        assert result.artifact_bytes is None
    finally:
        session.close_and_remove()


def test_artifact_result_requires_nonempty_artifact(tmp_path):
    plan = io_plan(expected_result_kind=StructuredResultKind.ARTIFACT)
    session = create_structured_session(tmp_path, plan)
    try:
        raw = json.dumps(
            {
                "kind": "artifact",
                "payload": {},
                "protocol": "first-agent-skill-result-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        _write_existing(session, "result.json", raw)
        result = read_structured_session(session, plan)
        assert result.outcome.value == "artifact_missing"
    finally:
        session.close_and_remove()


def test_magic_allowlist_is_checked_before_the_child_can_read_input(tmp_path):
    plan = replace(
        io_plan(),
        inputs=(
            replace(
                io_plan().inputs[0],
                allowed_magic_hex=("25504446",),
            ),
        ),
    )
    with pytest.raises(ValueError, match="magic"):
        create_structured_session(tmp_path, plan)
