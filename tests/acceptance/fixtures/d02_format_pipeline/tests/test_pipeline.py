from reporting.cli import run
from reporting.service import ExportService

ROWS = [{"name": "alpha", "value": "1"}]


def test_service_keeps_csv_as_the_default() -> None:
    assert ExportService().export(ROWS) == "name,value\r\nalpha,1\r\n"


def test_cli_keeps_existing_invocation() -> None:
    assert run(['[{"name":"alpha","value":"1"}]']) == (
        "name,value\r\nalpha,1\r\n"
    )
