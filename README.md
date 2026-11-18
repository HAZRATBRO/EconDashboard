# National Accounts Dashboard (India)

A local web dashboard for India's **National Accounts Statistics** (GDP, GVA, national income, consumption, capital formation, saving, state GSDP), built on data and reports published by **MoSPI / NSO**.

| Tab | What it does |
|---|---|
| **Overview** | Headline GDP tiles and charts (level, real growth, deflator) from a bundled reference snapshot. |
| **Data Explorer** | Queries MoSPI's official NAS API (`api.mospi.gov.in`, eSankhyiki) for any of the 34 NAS indicators: base year 2022-23 or 2011-12, current/back series, annual/quarterly, year/state/industry filters. Results in a sortable table and a configurable chart. |
| **Reports** | Scrapes report listings from `mospi.gov.in` publication pages (e.g. [/publications-reports](https://www.mospi.gov.in/publications-reports), [/innerpage/2861](https://www.mospi.gov.in/publications-reports/innerpage/2861)) with title, release date and PDF/XLSX links. Search, filter by date and type, follow sub-sections, or paste any mospi.gov.in listing URL. Includes the NAS release-cycle reference. |
| **Definitions** | Searchable glossary of 45 National Accounts concepts (GDP, GVA at basic prices, NNI, PFCE, GFCF, deflator, Advance/Provisional/Revised Estimates, …) with formulas. |
| **Import Excel** | Upload a MoSPI NAS statement / press-release annex (.xlsx); title rows are detected and each sheet becomes a table and chart. |

**Every view exports to Excel** (.xlsx with styled headers, numeric cells, clickable links, query notes, an indicator-definition sheet where relevant, and a source sheet).

## Run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --app-dir backend --port 8000
```

Open http://localhost:8000. The two dots in the header show whether this machine can reach `mospi.gov.in` and the MoSPI API.

### Configuration

| Env var | Default | Purpose |
|---|---|---|
| `MOSPI_API_BASE` | `https://api.mospi.gov.in` | API base URL |
| `MOSPI_INSECURE_TLS` | `0` | Set to `1` only if MoSPI's servers fail TLS verification on your machine (their certificate chain is sometimes incomplete). Legacy TLS renegotiation, which MoSPI needs, is always enabled. |

## Tests

```bash
pip install pytest httpx
python -m pytest tests
```

## Notes and limits

- **The overview snapshot is not live.** It holds annual GDP for 2011-12 to 2024-25 (2011-12 base), entered by hand from MoSPI releases up to May 2025. MoSPI has since moved to a 2022-23 base. Use the Data Explorer for official current figures.
- MoSPI's NAS API documents its query parameters but not its response fields, so the explorer shows whatever columns come back and guesses the chart's X/value/series columns. You can change the guess with the dropdowns.
- The reports scraper does not rely on MoSPI's CSS classes. It finds document links (PDF/XLS/XLSX/ZIP, `/sites/default/files/`, `/uploads/`) and reads the surrounding row for the title and date. If MoSPI loads a listing with JavaScript, that page will show no documents. Open it on mospi.gov.in from the link shown instead.
- Only `mospi.gov.in` URLs can be scraped.
- Endpoint details come from MoSPI's own MCP server spec ([nso-india/esankhyiki-mcp](https://github.com/nso-india/esankhyiki-mcp), MIT). `backend/data/nas_indicators.json` is copied from that repo.
- Chart.js 4.4.1 is vendored in `frontend/vendor` (MIT).
