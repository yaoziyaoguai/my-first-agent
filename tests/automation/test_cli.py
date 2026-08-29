from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agent.automation.cli import build_parser, run_cli
from agent.automation.store import encode_definition_body_json

from .test_composition import _active_core


def test_public_parser_has_management_surface_without_old_raw_scheduler_fields() -> None:
    parser = build_parser()
    command_action = next(action for action in parser._actions if action.dest == "command")  # noqa: SLF001

    assert set(command_action.choices) == {
        "create",
        "preview",
        "approve",
        "list",
        "show",
        "open",
        "update",
        "pause",
        "resume",
        "cancel",
        "purge",
        "wake",
        "reconcile",
    }
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "reconcile",
                "--state-root",
                "/tmp/forbidden",
                "--message",
                "forbidden",
            ]
        )


def test_reconcile_cli_renders_only_bounded_closed_result() -> None:
    core, _, _, _ = _active_core(now=datetime(2026, 8, 27, tzinfo=UTC))
    output: list[str] = []

    exit_code = run_cli(
        ["reconcile", "--delivery-id", "delivery:one"],
        core=core,
        write_fn=output.append,
    )

    assert exit_code == 0
    assert json.loads(output[0]) == {"code": "not_due"}


def test_create_cli_translates_definition_to_management_service_without_echoing_task() -> None:
    core, repository, _, _ = _active_core(now=datetime(2026, 8, 27, tzinfo=UTC))
    existing = repository.load().records[0]
    assert existing.definition is not None
    body = existing.definition.body
    raw = encode_definition_body_json(
        replace(body, revision=2, definition_body_digest="")
    )
    output: list[str] = []

    exit_code = run_cli(
        [
            "update",
            body.automation_id,
            "--definition-json",
            raw,
            "--expected-token",
            repository.load().snapshot_token,
            "--next-token",
            "snapshot-token-update",
        ],
        core=core,
        write_fn=output.append,
    )

    assert exit_code == 0
    assert json.loads(output[0])["code"] == "proposal"
    assert body.task_text not in output[0]


def test_purge_cli_requires_a_fresh_human_preview_before_confirmation() -> None:
    core, repository, _, _ = _active_core(now=datetime(2026, 8, 27, tzinfo=UTC))
    record = repository.load().records[0]
    assert record.definition is not None
    body = record.definition.body
    core.management.cancel(
        body.automation_id,
        expected_snapshot_token=repository.load().snapshot_token,
        next_snapshot_token="snapshot-token-canceled",
    )
    output: list[str] = []

    assert (
        run_cli(
            ["purge", body.automation_id],
            core=core,
            write_fn=output.append,
        )
        == 0
    )
    preview = json.loads(output.pop())
    assert preview["code"] == "purge_preview"
    assert body.task_text not in json.dumps(preview)

    assert (
        run_cli(
            [
                "purge",
                body.automation_id,
                "--preview-digest",
                preview["preview_digest"],
                "--expected-token",
                repository.load().snapshot_token,
                "--next-token",
                "snapshot-token-purge",
            ],
            core=core,
            write_fn=output.append,
        )
        == 0
    )
    assert json.loads(output.pop())["code"] == "purge_pending"
