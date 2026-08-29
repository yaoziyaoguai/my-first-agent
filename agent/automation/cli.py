"""Thin owner CLI for the portable 019 management and reconcile boundary."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict

from agent.automation.composition import AutomationControlCoreV1
from agent.automation.reconcile import ReconcileAutomationsResultV1, ReconcileAutomationsV1
from agent.automation.store import decode_definition_body_json

_MAX_TRIGGER_BYTES = 4_096


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def decode_reconcile_request(raw: str) -> ReconcileAutomationsV1:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_TRIGGER_BYTES:
        raise ValueError("reconcile payload must be bounded text")
    try:
        document = json.loads(raw, object_pairs_hook=_strict_object)
    except json.JSONDecodeError as error:
        raise ValueError("reconcile payload is malformed JSON") from error
    if not isinstance(document, dict) or set(document) != {"schema_version", "delivery_id"}:
        raise ValueError("reconcile payload fields must be exact")
    request = ReconcileAutomationsV1(
        schema_version=document["schema_version"],
        delivery_id=document["delivery_id"],
    )
    if _json({"schema_version": request.schema_version, "delivery_id": request.delivery_id}) != raw:
        raise ValueError("reconcile payload must be canonical JSON")
    return request


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="first-agent-schedule")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    _definition_args(create, include_id=False)
    preview = commands.add_parser("preview")
    preview.add_argument("automation_id")
    approve = commands.add_parser("approve")
    approve.add_argument("automation_id")
    approve.add_argument("--preview-digest", required=True)
    _mutation_tokens(approve)
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("automation_id")
    open_command = commands.add_parser("open")
    open_command.add_argument("automation_id")
    update = commands.add_parser("update")
    _definition_args(update, include_id=True)
    for name in ("pause", "resume", "cancel"):
        command = commands.add_parser(name)
        command.add_argument("automation_id")
        _mutation_tokens(command)
    purge = commands.add_parser("purge")
    purge.add_argument("automation_id")
    purge.add_argument("--preview-digest")
    purge.add_argument("--expected-token")
    purge.add_argument("--next-token")
    wake = commands.add_parser("wake")
    wake.add_argument("operation", choices=("enable", "disable"))
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("--delivery-id")
    return parser


def _definition_args(parser: argparse.ArgumentParser, *, include_id: bool) -> None:
    if include_id:
        parser.add_argument("automation_id")
    parser.add_argument("--definition-json", required=True)
    _mutation_tokens(parser)


def _mutation_tokens(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-token", required=True)
    parser.add_argument("--next-token", required=True)


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    core: AutomationControlCoreV1 | None,
    write_fn: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(argv)
    if core is None:
        write_fn(_json({"code": "needs_019_config", "reason": "host_profile_unavailable"}))
        return 2
    try:
        payload = _dispatch(args, core)
    except Exception as error:
        write_fn(_json({"code": "invalid_request", "reason": type(error).__name__}))
        return 2
    write_fn(_json(payload))
    return 0 if payload.get("code") not in {"needs_019_config", "invalid_request"} else 2


def _dispatch(args: argparse.Namespace, core: AutomationControlCoreV1) -> dict[str, object]:
    management = core.management
    if args.command == "reconcile":
        return _reconcile_payload(
            core.reconcile(ReconcileAutomationsV1(delivery_id=args.delivery_id))
        )
    if args.command == "create":
        result = management.create(
            decode_definition_body_json(args.definition_json),
            expected_snapshot_token=args.expected_token,
            next_snapshot_token=args.next_token,
        )
        return _management_payload(result)
    if args.command == "update":
        result = management.update(
            args.automation_id,
            decode_definition_body_json(args.definition_json),
            expected_snapshot_token=args.expected_token,
            next_snapshot_token=args.next_token,
        )
        return _management_payload(result)
    if args.command == "preview":
        preview = management.preview(args.automation_id)
        return {
            "code": "preview",
            "automation_id": preview.automation_id,
            "revision": preview.revision,
            "preview_digest": preview.preview_digest,
            "sections": [asdict(section) for section in preview.sections],
        }
    if args.command == "approve":
        return _management_payload(
            management.approve(
                args.automation_id,
                preview_digest=args.preview_digest,
                expected_snapshot_token=args.expected_token,
                next_snapshot_token=args.next_token,
            )
        )
    if args.command == "list":
        return {
            "code": "list",
            "items": [
                {
                    "automation_id": item.automation_id,
                    "label": item.label,
                    "revision": item.revision,
                    "status": item.status.value,
                    "terminal_occurrence_count": item.terminal_occurrence_count,
                }
                for item in management.list()
            ],
        }
    if args.command == "show":
        detail = management.show(args.automation_id)
        return {
            "code": "show",
            "automation_id": detail.automation_id,
            "label": detail.label,
            "revision": detail.revision,
            "status": detail.status.value,
            "next_actions": list(detail.next_actions),
            "active_occurrence_id": detail.active_occurrence_id,
            "needs_human_reason": detail.needs_human_reason,
        }
    if args.command == "open":
        handoff = management.open(args.automation_id)
        return {"code": "open", **asdict(handoff)}
    if args.command in {"pause", "resume", "cancel"}:
        method = getattr(management, args.command)
        return _management_payload(
            method(
                args.automation_id,
                expected_snapshot_token=args.expected_token,
                next_snapshot_token=args.next_token,
            )
        )
    if args.command == "purge":
        if args.preview_digest is None:
            preview = management.preview_purge(args.automation_id)
            return {"code": "purge_preview", **asdict(preview)}
        if args.expected_token is None or args.next_token is None:
            raise ValueError("purge confirmation requires both snapshot tokens")
        return _management_payload(
            management.confirm_purge(
                args.automation_id,
                preview_digest=args.preview_digest,
                expected_snapshot_token=args.expected_token,
                next_snapshot_token=args.next_token,
            )
        )
    if args.command == "wake":
        result = (
            management.wake_enable()
            if args.operation == "enable"
            else management.wake_disable()
        )
        payload: dict[str, object] = {
            "code": result.code,
            "policy_digest": result.policy_digest,
        }
        if result.manual_reconcile_required:
            payload["manual_reconcile_required"] = True
        return payload
    return {"code": "needs_019_config", "reason": "lifecycle_command_unavailable"}


def _management_payload(result) -> dict[str, object]:  # noqa: ANN001
    return {
        "code": result.code,
        "snapshot_token": result.snapshot_token,
        "status": result.automation_status.value,
    }


def _reconcile_payload(result: ReconcileAutomationsResultV1) -> dict[str, object]:
    return {
        key: value.value if hasattr(value, "value") else value
        for key, value in asdict(result).items()
        if value is not None
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    return run_cli(core=None)
