from csv_export import ExportService


def test_exports_existing_simple_rows() -> None:
    assert ExportService().export_csv(
        [{"name": "Ada", "note": "first programmer"}]
    ) == "name,note\nAda,first programmer\n"
