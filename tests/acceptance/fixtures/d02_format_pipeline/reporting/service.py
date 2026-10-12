from __future__ import annotations

from .formats import render_csv


class ExportService:
    def export(self, rows: list[dict[str, str]]) -> str:
        return render_csv(rows)
