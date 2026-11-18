"""EconDashboard - National Accounts Statistics dashboard (India / MoSPI).

Run:  uvicorn app:app --app-dir backend --port 8000
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import excel
import mospi_client
import scraper

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).parent / "data"
FRONTEND = ROOT / "frontend"

DEFAULT_REPORT_PAGES = [
    {"label": "Publications & Reports", "url": "https://www.mospi.gov.in/publications-reports"},
    {"label": "National Accounts (innerpage 2861)", "url": "https://www.mospi.gov.in/publications-reports/innerpage/2861"},
]

app = FastAPI(title="EconDashboard", version="1.0")


def _load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _upstream_error(e: Exception) -> HTTPException:
    return HTTPException(502, detail=f"Could not reach MoSPI: {type(e).__name__}: {e}")


# ---------- reference data ----------

@app.get("/api/glossary")
def glossary():
    return _load("glossary.json")


@app.get("/api/report-series")
def report_series():
    return _load("report_series.json")


@app.get("/api/snapshot")
def snapshot():
    return _load("snapshot.json")


# ---------- reports (scraped from mospi.gov.in) ----------

@app.get("/api/reports/sources")
def report_sources():
    return DEFAULT_REPORT_PAGES


@app.get("/api/reports")
def reports(url: str = Query(DEFAULT_REPORT_PAGES[1]["url"])):
    if not scraper.is_allowed(url):
        raise HTTPException(400, "Only mospi.gov.in pages can be loaded")
    try:
        return scraper.fetch_listing(url)
    except Exception as e:  # noqa: BLE001
        raise _upstream_error(e) from e


# ---------- NAS data (MoSPI API) ----------

@app.get("/api/nas/indicators")
def nas_indicators():
    return mospi_client.get_indicators()


@app.get("/api/nas/filters")
def nas_filters(indicator_code: int, base_year: str = "2022-23", series: str = "Current", frequency: str = "Annually"):
    try:
        return mospi_client.get_filters(indicator_code, base_year, series, frequency)
    except Exception as e:  # noqa: BLE001
        raise _upstream_error(e) from e


@app.get("/api/nas/data")
def nas_data(
    indicator_code: str,
    base_year: str = "2022-23",
    series: str = "Current",
    frequency_code: str = "Annually",
    year: str | None = None,
    quarterly_code: str | None = None,
    state_code: str | None = None,
    approach_code: str | None = None,
    revision_code: str | None = None,
    account_code: str | None = None,
    institutional_code: str | None = None,
    industry_code: str | None = None,
    subindustry_code: str | None = None,
):
    params = {k: v for k, v in locals().items()}
    try:
        return mospi_client.get_data(params)
    except Exception as e:  # noqa: BLE001
        raise _upstream_error(e) from e


@app.get("/api/status")
def status():
    """Quick reachability check of the two MoSPI hosts."""
    out = {}
    for name, url in (("website", "https://www.mospi.gov.in/"), ("api", mospi_client.API_BASE + "/")):
        try:
            r = mospi_client._session.get(url, timeout=8)
            out[name] = {"ok": r.status_code < 500, "status": r.status_code}
        except Exception as e:  # noqa: BLE001
            out[name] = {"ok": False, "error": type(e).__name__}
    return out


# ---------- Excel ----------

class Sheet(BaseModel):
    name: str = "Sheet"
    title: str | None = None
    notes: list[str] | None = None
    columns: list[str]
    rows: list[list]


class ExportRequest(BaseModel):
    filename: str = "national-accounts"
    sheets: list[Sheet]


@app.post("/api/export")
def export(req: ExportRequest):
    content = excel.build_workbook([s.model_dump() for s in req.sheets])
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in req.filename)[:80] or "export"
    fname = f"{safe}-{date.today().isoformat()}.xlsx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/import")
async def import_excel(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(413, "File too large (25 MB max)")
    try:
        return {"filename": file.filename, "sheets": excel.read_workbook(content)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read workbook: {e}") from e


# ---------- frontend ----------

@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
