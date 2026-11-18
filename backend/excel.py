"""Excel export (styled .xlsx from table specs) and import (MoSPI statement files)."""

from __future__ import annotations

import io
import re
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=13)
NOTE_FONT = Font(italic=True, size=9, color="555555")
_BAD_SHEET_CHARS = re.compile(r"[\[\]\*\?/\\:]")


def _sheet_name(name: str, used: set[str]) -> str:
    base = _BAD_SHEET_CHARS.sub(" ", name or "Sheet").strip()[:31] or "Sheet"
    out, i = base, 2
    while out.lower() in used:
        suffix = f" ({i})"
        out = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(out.lower())
    return out


def _num(v):
    """Convert numeric-looking strings ("1,23,456.7") to numbers so Excel can compute with them."""
    if isinstance(v, str):
        s = v.replace(",", "").strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return float(s) if "." in s else int(s)
    return v


def build_workbook(sheets: list[dict]) -> bytes:
    """sheets: [{name, title?, notes?: [str], columns: [str], rows: [[...]]}]"""
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for spec in sheets:
        ws = wb.create_sheet(_sheet_name(spec.get("name", "Sheet"), used))
        r = 1
        if spec.get("title"):
            ws.cell(r, 1, spec["title"]).font = TITLE_FONT
            r += 1
        for note in spec.get("notes") or []:
            ws.cell(r, 1, note).font = NOTE_FONT
            r += 1
        if r > 1:
            r += 1
        cols = spec.get("columns") or []
        header_row = r
        for c, name in enumerate(cols, 1):
            cell = ws.cell(r, c, name)
            cell.fill, cell.font = HEADER_FILL, HEADER_FONT
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        widths = [min(max(len(str(n)), 8), 60) for n in cols]
        for row in spec.get("rows") or []:
            r += 1
            for c, v in enumerate(row, 1):
                cell = ws.cell(r, c, _num(v))
                if isinstance(cell.value, str) and cell.value.startswith(("http://", "https://")):
                    cell.hyperlink = cell.value
                    cell.font = Font(color="0563C1", underline="single")
                elif isinstance(cell.value, float):
                    cell.number_format = "#,##0.00"
                if c <= len(widths):
                    widths[c - 1] = min(max(widths[c - 1], len(str(v)) if v is not None else 0), 60)
                if isinstance(cell.value, str) and len(cell.value) > 60:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w + 2
        if cols:
            ws.freeze_panes = ws.cell(header_row + 1, 1)
            ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(cols))}{max(r, header_row)}"
    if not wb.sheetnames:
        wb.create_sheet("Empty")
    info = wb.create_sheet(_sheet_name("About", used))
    info["A1"] = "Exported from EconDashboard"
    info["A1"].font = TITLE_FONT
    info["A2"] = f"Generated: {datetime.now():%Y-%m-%d %H:%M}"
    info["A3"] = "Primary source: Ministry of Statistics and Programme Implementation (MoSPI), Government of India - www.mospi.gov.in"
    info.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def read_workbook(content: bytes, max_rows: int = 2000) -> list[dict]:
    """Parse an uploaded workbook (e.g. a MoSPI NAS statement) into table specs.

    MoSPI statements have title/notes rows above the table; the header row is
    taken to be the first row whose non-empty cells span at least half the
    sheet's used width.
    """
    wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(v not in (None, "") for v in r)][: max_rows + 20]
        if not rows:
            continue
        width = max(len(r) for r in rows)
        # trim fully-empty trailing columns
        while width > 1 and all(len(r) < width or r[width - 1] in (None, "") for r in rows):
            width -= 1
        rows = [(r + [None] * width)[:width] for r in rows]
        header_idx = 0
        for i, r in enumerate(rows[:25]):
            if sum(v not in (None, "") for v in r) >= max(2, width // 2):
                header_idx = i
                break
        notes = [" ".join(str(v) for v in r if v not in (None, "")) for r in rows[:header_idx]]
        header = [str(v).strip() if v not in (None, "") else f"Col {j + 1}" for j, v in enumerate(rows[header_idx])]
        body = [[_jsonable(v) for v in r] for r in rows[header_idx + 1:][:max_rows]]
        out.append({"name": ws.title, "notes": notes, "columns": header, "rows": body})
    return out


def _jsonable(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, float) and v != v:  # NaN
        return None
    return v
