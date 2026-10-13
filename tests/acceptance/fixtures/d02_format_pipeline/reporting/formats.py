from __future__ import annotations

import csv
import io


def render_csv(rows: list[dict[str, str]]) -> str:
    columns = tuple(rows[0]) if rows else ("name", "value")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
