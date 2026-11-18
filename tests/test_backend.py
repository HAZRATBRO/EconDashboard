import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import app as app_module  # noqa: E402
import excel  # noqa: E402
import mospi_client  # noqa: E402
import scraper  # noqa: E402

client = TestClient(app_module.app)

LISTING_HTML = """
<html><head><title>Publications | MoSPI</title></head><body>
<h1>National Accounts</h1>
<ul class="menu"><li><a href="/publications-reports/innerpage/2862">Press Releases</a></li></ul>
<table>
 <tr><td>1</td><td>Press Note on Provisional Estimates of Annual GDP for 2024-25</td>
     <td>30/05/2025</td><td><a href="/sites/default/files/press_release/PE_2024-25.pdf">Download</a>
     <a href="/sites/default/files/press_release/PE_2024-25_hindi.pdf">Download</a></td></tr>
 <tr><td>2</td><td>National Accounts Statistics 2025</td>
     <td>June 27, 2025</td><td><a href="/uploads/publications/NAS2025.xlsx">XLSX</a></td></tr>
</table>
<div class="card"><h4>Quarterly Estimates of GDP Q2 2025-26</h4><span>28 Nov 2025</span>
  <a href="https://www.mospi.gov.in/sites/default/files/q2.pdf">View</a></div>
<a href="/publications-reports?page=1" rel="next">Next</a>
</body></html>
"""


def test_parse_listing_extracts_reports_dates_and_navigation():
    res = scraper.parse_listing(LISTING_HTML, "https://www.mospi.gov.in/publications-reports/innerpage/2861")
    titles = [r["title"] for r in res["reports"]]
    assert "Press Note on Provisional Estimates of Annual GDP for 2024-25" in titles
    assert "National Accounts Statistics 2025" in titles
    assert "Quarterly Estimates of GDP Q2 2025-26" in titles
    pe = next(r for r in res["reports"] if r["title"].startswith("Press Note"))
    assert pe["date"] == "2025-05-30"
    assert pe["url"] == "https://www.mospi.gov.in/sites/default/files/press_release/PE_2024-25.pdf"
    assert len(pe["other_files"]) == 1  # Hindi version grouped with English
    assert [r["date"] for r in res["reports"]] == ["2025-11-28", "2025-06-27", "2025-05-30"]
    assert res["next_page"] == "https://www.mospi.gov.in/publications-reports?page=1"
    assert any("2862" in c["url"] for c in res["categories"])
    assert res["page_title"] == "National Accounts"


@pytest.mark.parametrize("text,iso", [
    ("released on 07-01-2025", "2025-01-07"), ("2024-02-29", "2024-02-29"),
    ("31st May 2024", "2024-05-31"), ("Sept 30, 2023", "2023-09-30"), ("no date", None),
])
def test_parse_date(text, iso):
    assert scraper.parse_date(text) == iso


def test_reports_endpoint_rejects_non_mospi_urls():
    r = client.get("/api/reports", params={"url": "http://169.254.169.254/latest"})
    assert r.status_code == 400
    assert not scraper.is_allowed("https://mospi.gov.in.evil.com/x")
    assert scraper.is_allowed("https://www.mospi.gov.in/x")


def test_extract_records_handles_nesting():
    assert mospi_client.extract_records({"data": [{"a": 1}]}) == [{"a": 1}]
    assert mospi_client.extract_records({"data": {"rows": [{"a": 1}]}}) == [{"a": 1}]
    assert mospi_client.extract_records({"statusCode": True, "data": []}) == []


def test_nas_data_paginates(monkeypatch):
    calls = []

    def fake(path, params):
        calls.append(dict(params))
        n = 500 if params["page"] == 1 else 3
        return {"statusCode": True, "data": [{"year": "2024-25", "value": i} for i in range(n)]}

    monkeypatch.setattr(mospi_client, "_get_json", fake)
    r = client.get("/api/nas/data", params={"indicator_code": "5", "base_year": "2022-23"})
    assert r.status_code == 200
    assert len(r.json()["records"]) == 503
    assert [c["page"] for c in calls] == [1, 2]
    assert calls[0]["indicator_code"] == "5" and calls[0]["Format"] == "JSON" and "year" not in calls[0]


def test_nas_data_upstream_error_is_502(monkeypatch):
    monkeypatch.setattr(mospi_client, "_get_json", lambda p, q: {"statusCode": False, "message": "Invalid request body"})
    r = client.get("/api/nas/data", params={"indicator_code": "5"})
    assert r.status_code == 502 and "Invalid request body" in r.json()["detail"]


def test_indicators_fall_back_to_bundled(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(mospi_client, "_get_json", boom)
    res = client.get("/api/nas/indicators").json()
    assert res["source"] == "bundled" and any(i["name"] == "Gross Domestic Product" for i in res["indicators"])


def test_reference_endpoints():
    g = client.get("/api/glossary").json()
    assert {"term", "definition", "category"} <= set(g[0]) and len(g) > 30
    s = client.get("/api/snapshot").json()
    assert all(len(r) == len(s["columns"]) for r in s["rows"])
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_export_produces_valid_xlsx():
    body = {"filename": "test file", "sheets": [
        {"name": "GDP/Data?", "title": "T", "notes": ["n1"], "columns": ["Year", "Value", "Link"],
         "rows": [["2023-24", "1,234.5", "https://www.mospi.gov.in/a.pdf"], ["2024-25", 99, None]]},
        {"name": "GDP/Data?", "columns": ["a"], "rows": []},
    ]}
    r = client.post("/api/export", json=body)
    assert r.status_code == 200
    assert 'filename="test-file-' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["GDP Data", "GDP Data (2)", "About"]
    ws = wb["GDP Data"]
    assert ws["A1"].value == "T" and ws["A4"].value == "Year"
    assert ws["B5"].value == 1234.5  # numeric strings become numbers
    assert ws["C5"].hyperlink.target == "https://www.mospi.gov.in/a.pdf"


def test_import_detects_header_below_titles():
    wb = Workbook()
    ws = wb.active
    ws.title = "Statement 1.1"
    ws.append(["Statement 1.1: Key aggregates"])
    ws.append(["(Rs. crore)"])
    ws.append(["Item", "2022-23", "2023-24", "2024-25"])
    ws.append(["GDP", 100, 110, 120])
    ws.append(["GVA", 90, 99, 108])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/import", files={"file": ("s.xlsx", buf.getvalue())})
    sheet = r.json()["sheets"][0]
    assert sheet["columns"] == ["Item", "2022-23", "2023-24", "2024-25"]
    assert sheet["notes"] == ["Statement 1.1: Key aggregates", "(Rs. crore)"]
    assert sheet["rows"][0] == ["GDP", 100, 110, 120]


def test_import_rejects_garbage():
    r = client.post("/api/import", files={"file": ("x.xlsx", b"not a workbook")})
    assert r.status_code == 400
