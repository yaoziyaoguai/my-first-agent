from __future__ import annotations


def export_rows(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    """Return CSV text for rows using the caller supplied column order."""

    if not rows:
        return ""
    lines = [",".join(columns)]
    lines.extend(",".join(str(row.get(column, "")) for column in columns) for row in rows)
    return "\n".join(lines) + "\n"
