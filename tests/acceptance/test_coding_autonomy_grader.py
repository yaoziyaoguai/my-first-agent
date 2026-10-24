from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.coding_scenario_grader import (
    grade_d01,
    grade_d02,
    grade_d03,
    grade_d04,
    grade_d05,
    grade_d06,
)
from scripts.grade_coding_autonomy import grade
from scripts.materialize_coding_scenario import materialize

ROOT = Path(__file__).parents[2]
MANIFEST = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-09-13-coding-autonomy-repair"
    / "TASK-MANIFEST.json"
)
D01_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d01_csv_export"
D02_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d02_format_pipeline"
D03_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d03_parser_refactor"
D04_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d04_resume_correction"
D05_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d05_config_precedence"
D06_FIXTURE = ROOT / "tests" / "acceptance" / "fixtures" / "d06_local_page"


def _git_status(candidate: Path) -> str:
    return subprocess.run(
        ["git", "status", "--short"],
        cwd=candidate,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _result(manifest: dict, *, execution_identity: str = "scripted_provider") -> dict:
    from scripts.run_real_coding_scenario import build_record_v2

    scenario = manifest["scenarios"][0]
    resolved = (
        "offline_scripted"
        if execution_identity == "scripted_provider"
        else execution_identity
    )
    return build_record_v2(
        scenario_id=scenario["id"],
        manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        candidate_digest="a" * 64,
        fixture_digest="b" * 64,
        source_digest="c" * 64,
        grader_digest="d" * 64,
        execution_identity=resolved,
        model_identity={
            "provider": "openai_compatible",
            "model_id": "offline-fixture",
            "reasoning_mode": "disabled",
        },
        product_status="completed",
        checks={name: True for name in scenario["required_checks"]},
        unverified_reasons={},
        metrics={
            "business_reminders": 0,
            "human_check_rescues": 0,
            "human_finish_rescues": 0,
            "consent_decisions": 1,
            "external_grader_runs": 1,
            "ledger_start": 0,
            "ledger_end": 0,
        },
        physical_requests=0,
        stop_reason="verified_done",
    )


def _write_result(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_manifest_freezes_all_scenarios_and_separates_held_out_cases() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    # 授权状态是 owner 在 manifest 里的显式记录（2026-10-04 起授权 DeepSeek
    # flash 真实 dogfood；2026-10-24 owner 重绑 flash 档到现役名
    # deepseek-flash——v4-flash 已退役导致准入 pin fail-closed）；本断言随
    # owner 记录更新，门本身由门测试覆盖。
    assert manifest["real_dispatch_authorized"] is True
    assert manifest["window_budget"]["max_physical_requests"] > 0
    assert manifest["model"] == {
        "provider": "openai_compatible",
        "model_id": "deepseek-flash",
        "reasoning_mode": "disabled",
    }
    assert [item["id"] for item in manifest["scenarios"]] == [
        f"D{index:02d}" for index in range(1, 13)
    ]
    assert manifest["baseline_scenarios"] == ["D01", "D02", "D04"]
    assert manifest["held_out_scenarios"] == ["D03", "D05", "D09", "D10"]
    assert all(item["required_checks"] for item in manifest["scenarios"])
    materialized = {item["id"]: item for item in manifest["scenarios"][:4] if "fixture" in item}
    assert set(materialized) == {"D01", "D02", "D03", "D04"}
    for scenario in materialized.values():
        assert (ROOT / scenario["fixture"]).is_dir()
        assert scenario["external_grader"] == "scripts/grade_coding_scenario.py"


def _unauthorized_manifest_copy(tmp_path: Path) -> Path:
    """门合同不依赖线上授权值：对强制未授权的副本测门。"""

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["real_dispatch_authorized"] = False
    manifest["window_budget"]["max_physical_requests"] = 0
    copy_path = tmp_path / "manifest-unauthorized.json"
    copy_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return copy_path


def test_offline_record_is_validated_but_never_promoted_to_product_pass(
    tmp_path: Path,
) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    unauthorized_manifest = _unauthorized_manifest_copy(tmp_path)

    offline = grade(MANIFEST, _write_result(tmp_path, _result(manifest)))
    unauthorized_real = grade(
        unauthorized_manifest,
        _write_result(tmp_path, _result(manifest, execution_identity="real_model")),
    )

    assert offline["status"] == "RECORD_VALID"
    assert offline["evidence_level"] == "offline_scripted"
    assert offline["errors"] == []
    assert offline["product_status"] == "completed"
    assert unauthorized_real["status"] == "FAIL"
    assert unauthorized_real["evidence_level"] == "real_model"
    assert "real_dispatch_not_authorized" in unauthorized_real["errors"]


def test_grader_rejects_completed_record_without_basis(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = _result(manifest)
    result["independent_checks"]["empty_rows"] = False
    result["metrics"]["human_check_rescues"] = 1

    report = grade(MANIFEST, _write_result(tmp_path, result))

    # F3d：completed 记录必须有 checks/度量依据；缺依据 → FAIL（不一致记录）。
    assert report["status"] == "FAIL"
    assert "completed_without_basis" in report["errors"]
    # 救场度量为正 → 降级为警告：诚实记录仍可消费，RECORD_VALID ≠ 产品 PASS。
    assert any(
        warning.startswith("metric_nonzero_rescue")
        for warning in report["warnings"]
    )


def test_d01_external_grader_catches_the_public_fixture_defects(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D01_FIXTURE, candidate)

    checks = grade_d01(candidate)

    assert checks == {
        "empty_rows": False,
        "quoted_commas": False,
        "existing_behavior": True,
    }


def test_d01_external_grader_accepts_a_reference_behavior(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D01_FIXTURE, candidate)
    (candidate / "csv_export" / "exporter.py").write_text(
        "from __future__ import annotations\n"
        "import csv\n"
        "import io\n\n"
        "def export_rows(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:\n"
        "    output = io.StringIO(newline='')\n"
        "    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')\n"
        "    writer.writeheader()\n"
        "    writer.writerows(rows)\n"
        "    return output.getvalue()\n",
        encoding="utf-8",
    )

    assert all(grade_d01(candidate).values())


def test_d02_external_grader_catches_the_unimplemented_format_path(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D02_FIXTURE, candidate)

    assert grade_d02(candidate) == {
        "cli_to_service": False,
        "invalid_format": False,
        "default_compatibility": False,
        "tests_and_docs": False,
    }


def test_d02_external_grader_accepts_reference_end_to_end_behavior(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D02_FIXTURE, candidate)
    (candidate / "reporting" / "formats.py").write_text(
        "from __future__ import annotations\n"
        "import csv\n"
        "import io\n"
        "import json\n\n"
        "def render_csv(rows):\n"
        "    columns = tuple(rows[0]) if rows else ('name', 'value')\n"
        "    output = io.StringIO(newline='')\n"
        "    writer = csv.DictWriter(output, fieldnames=columns)\n"
        "    writer.writeheader()\n"
        "    writer.writerows(rows)\n"
        "    return output.getvalue()\n\n"
        "def render_json(rows):\n"
        "    return json.dumps(rows, separators=(',', ':'))\n",
        encoding="utf-8",
    )
    (candidate / "reporting" / "service.py").write_text(
        "from .formats import render_csv, render_json\n\n"
        "class ExportService:\n"
        "    def export(self, rows, fmt='csv'):\n"
        "        if fmt == 'csv':\n"
        "            return render_csv(rows)\n"
        "        if fmt == 'json':\n"
        "            return render_json(rows)\n"
        "        raise ValueError('unsupported output format')\n",
        encoding="utf-8",
    )
    (candidate / "reporting" / "cli.py").write_text(
        "import argparse\n"
        "import json\n"
        "from .service import ExportService\n\n"
        "def run(argv):\n"
        "    parser = argparse.ArgumentParser()\n"
        "    parser.add_argument('--format', default='csv', choices=('csv', 'json'))\n"
        "    parser.add_argument('rows_json')\n"
        "    args = parser.parse_args(argv)\n"
        "    return ExportService().export(json.loads(args.rows_json), fmt=args.format)\n",
        encoding="utf-8",
    )
    (candidate / "README.md").write_text(
        "CSV remains the default. Use `--format json` to request JSON.\n",
        encoding="utf-8",
    )

    assert all(grade_d02(candidate).values())


def test_d03_external_grader_requires_a_shared_parser_and_preserves_user_work(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"

    result = materialize("D03", candidate)

    assert result["scenario_id"] == "D03"
    assert grade_d03(candidate) == {
        "behavior_equivalence": True,
        "imports": False,
        "dirty_sentinel_preserved": True,
        "untracked_sentinel_preserved": True,
    }
    assert " M USER_NOTES.md" in _git_status(candidate)
    assert "?? scratch.txt" in _git_status(candidate)


def test_d03_external_grader_accepts_reference_refactor(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    materialize("D03", candidate)
    (candidate / "legacy_parser" / "records.py").write_text(
        "def parse_record(text):\n"
        "    fields = {}\n"
        "    for chunk in text.split(';'):\n"
        "        if not chunk.strip():\n"
        "            continue\n"
        "        key, separator, value = chunk.partition('=')\n"
        "        if not separator:\n"
        "            raise ValueError('record fields must use key=value')\n"
        "        fields[key.strip()] = value.strip()\n"
        "    return fields\n",
        encoding="utf-8",
    )
    (candidate / "legacy_parser" / "loader.py").write_text(
        "from .records import parse_record\n\n"
        "def load_line(text):\n"
        "    return parse_record(text)\n",
        encoding="utf-8",
    )
    (candidate / "legacy_parser" / "cli.py").write_text(
        "from .records import parse_record\n\n"
        "def run(argv):\n"
        "    if len(argv) != 1:\n"
        "        raise ValueError('exactly one record is required')\n"
        "    return parse_record(argv[0])\n",
        encoding="utf-8",
    )

    assert all(grade_d03(candidate).values())


def test_d04_external_grader_rejects_missing_retry_and_legacy_alias(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D04_FIXTURE, candidate)

    assert not any(grade_d04(candidate).values())


def test_d05_materializes_large_project_and_catches_precedence_bug(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"

    materialize("D05", candidate)

    assert len(tuple((candidate / "docs" / "generated").glob("*.txt"))) == 225
    # F3c：过程项（嵌套说明/截断搜索/敏感路径）不再由文件存在性自证，恒 false；
    # 业务矩阵仍由外置 grader 如实判定（该候选未修复，保持 False）。
    assert grade_d05(candidate) == {
        "nested_instructions": False,
        "search_after_truncation": False,
        "protected_paths_unread": False,
        "precedence_matrix": False,
    }


def test_d05_external_grader_accepts_reference_precedence_fix(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    materialize("D05", candidate)
    (candidate / "config_app" / "resolver.py").write_text(
        "def resolve_config(defaults, environment, project, cli):\n"
        "    result = dict(defaults)\n"
        "    result.update(environment)\n"
        "    result.update(project)\n"
        "    result.update(cli)\n"
        "    return result\n",
        encoding="utf-8",
    )

    # F3c：业务项可 true，过程项必须诚实 false + 理由（不删项、不降门槛）。
    checks = grade_d05(candidate)
    assert checks["precedence_matrix"] is True
    assert checks["nested_instructions"] is False
    assert checks["search_after_truncation"] is False
    assert checks["protected_paths_unread"] is False
    from scripts.coding_scenario_grader import unverified_reasons

    assert set(unverified_reasons("D05")) == {
        "nested_instructions",
        "search_after_truncation",
        "protected_paths_unread",
    }


def test_d06_external_grader_catches_stale_list_after_submit(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"

    materialize("D06", candidate)

    checks = grade_d06(candidate)
    assert checks["managed_server"] is True
    assert checks["browser_behavior"] is False
    assert checks["regression"] is False
    assert checks["owned_resources_closed"] is False


def test_d06_external_grader_accepts_reference_page_behavior(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    materialize("D06", candidate)
    app = candidate / "web" / "app.mjs"
    app.write_text(
        app.read_text(encoding="utf-8").replace(
            '    input.value = "";\n',
            '    input.value = "";\n    render();\n',
        ),
        encoding="utf-8",
    )

    checks = grade_d06(candidate)

    assert checks["managed_server"] is True
    assert checks["browser_behavior"] is True
    assert checks["regression"] is True
    assert checks["owned_resources_closed"] is False


def test_d04_external_grader_accepts_reference_corrected_behavior(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(D04_FIXTURE, candidate)
    (candidate / "retry_app" / "service.py").write_text(
        "from __future__ import annotations\n\n"
        "class RetryService:\n"
        "    def run(self, operation, *, max_retries=None, retry_count=None):\n"
        "        if max_retries is not None and retry_count is not None:\n"
        "            raise ValueError('retry limit is ambiguous')\n"
        "        limit = (retry_count if retry_count is not None else "
        "max_retries if max_retries is not None else 0)\n"
        "        if limit < 0:\n"
        "            raise ValueError('retry limit must not be negative')\n"
        "        for attempt in range(limit + 1):\n"
        "            try:\n"
        "                return operation()\n"
        "            except RuntimeError:\n"
        "                if attempt == limit:\n"
        "                    raise\n",
        encoding="utf-8",
    )
    (candidate / "retry_app" / "cli.py").write_text(
        "import argparse\n\n"
        "def parse_retry_limit(argv):\n"
        "    parser = argparse.ArgumentParser()\n"
        "    group = parser.add_mutually_exclusive_group()\n"
        "    group.add_argument('--max-retries', type=int)\n"
        "    group.add_argument('--retry-count', type=int)\n"
        "    args = parser.parse_args(argv)\n"
        "    value = args.retry_count if args.retry_count is not None else "
        "args.max_retries\n"
        "    return 0 if value is None else value\n",
        encoding="utf-8",
    )

    # F3c：业务项可 true；过程项（resume/effect-replay）本轮不可证明，诚实 false。
    checks = grade_d04(candidate)
    assert checks["latest_correction"] is True
    assert checks["final_validation"] is True
    assert checks["resume_without_restatement"] is False
    assert checks["no_effect_replay"] is False
    from scripts.coding_scenario_grader import unverified_reasons as _ur

    assert set(_ur("D04")) == {"resume_without_restatement", "no_effect_replay"}


def test_materializer_copies_only_the_fixture_and_freezes_task(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"

    result = materialize("D01", candidate)

    assert result["scenario_id"] == "D01"
    assert "CSV" in result["task"]
    assert candidate.is_dir()
    assert (candidate / "csv_export" / "service.py").is_file()
    assert not (candidate / "scripts" / "coding_scenario_grader.py").exists()
    with pytest.raises(FileExistsError):
        materialize("D01", candidate)
