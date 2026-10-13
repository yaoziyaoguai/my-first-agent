from __future__ import annotations

from .exporter import export_rows


class ExportService:
    def export_csv(
        self,
        rows: list[dict[str, str]],
        columns: tuple[str, ...] = ("name", "note"),
    ) -> str:
        return export_rows(rows, columns)
