"""Client for MoSPI's public data API (api.mospi.gov.in) - National Accounts.

Endpoint paths and parameters follow MoSPI's published swagger spec
(see github.com/nso-india/esankhyiki-mcp, swagger/swagger_user_nas.yaml):

  GET /api/nas/getNasIndicatorList
  GET /api/nas/getNasFilterByIndicatorId   base_year, series, frequency_code (1|2), indicator_code
  GET /api/nas/getNASData                  base_year, series, frequency_code (Annually|Quarterly),
                                           indicator_code, year, quarterly_code, ... , limit, page, Format
"""

from __future__ import annotations

import json
import os
import ssl
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager
from urllib3.util.retry import Retry

API_BASE = os.environ.get("MOSPI_API_BASE", "https://api.mospi.gov.in")
DATA_DIR = Path(__file__).parent / "data"

# MoSPI servers sometimes need legacy TLS renegotiation and occasionally serve
# an incomplete certificate chain. Verification stays ON unless the user opts
# out with MOSPI_INSECURE_TLS=1.
INSECURE_TLS = os.environ.get("MOSPI_INSECURE_TLS", "0") == "1"


class _LegacyTLSAdapter(HTTPAdapter):
    def __init__(self, ssl_context: ssl.SSLContext, **kwargs):
        self._ctx = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **kw):
        kw["ssl_context"] = self._ctx
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **kw)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (EconDashboard)"})
    ctx = ssl.create_default_context()
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca and os.path.exists(ca):
        ctx.load_verify_locations(ca)
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
    if INSECURE_TLS:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        s.verify = False
    retry = Retry(total=3, backoff_factor=0.6, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=frozenset({"GET"}))
    adapter = _LegacyTLSAdapter(ctx, max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_session = make_session()
_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 60 * 60  # 1 hour


def _get_json(path: str, params: dict | None = None) -> Any:
    params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    key = path + "?" + json.dumps(params, sort_keys=True)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    r = _session.get(f"{API_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    _cache[key] = (time.time(), data)
    return data


def bundled_indicators() -> list[dict]:
    return json.loads((DATA_DIR / "nas_indicators.json").read_text(encoding="utf-8"))


_indicator_failure: tuple[float, str] | None = None


def get_indicators() -> dict:
    """Indicator list; falls back to the bundled list if the API is unreachable.

    A failure is remembered for 5 minutes so the UI isn't slowed by retries."""
    global _indicator_failure
    if _indicator_failure and time.time() - _indicator_failure[0] < 300:
        return {"source": "bundled", "error": _indicator_failure[1], "indicators": bundled_indicators()}
    try:
        res = _get_json("/api/nas/getNasIndicatorList")
        data = res.get("data") if isinstance(res, dict) else None
        inds = data.get("indicator") if isinstance(data, dict) else data
        if inds:
            return {"source": "live", "indicators": inds}
        raise ValueError(res.get("message") if isinstance(res, dict) else "empty response")
    except Exception as e:  # noqa: BLE001
        _indicator_failure = (time.time(), f"{type(e).__name__}: {e}"[:300])
        return {"source": "bundled", "error": _indicator_failure[1], "indicators": bundled_indicators()}


def get_filters(indicator_code: int, base_year: str, series: str, frequency: str) -> dict:
    freq_code = 2 if frequency.lower().startswith("q") else 1
    return _get_json("/api/nas/getNasFilterByIndicatorId", {
        "base_year": base_year, "series": series,
        "frequency_code": freq_code, "indicator_code": indicator_code,
    })


def extract_records(payload: Any) -> list[dict]:
    """Find the list of row dicts inside a MoSPI JSON payload, whatever its nesting."""
    if isinstance(payload, list):
        if payload and all(isinstance(x, dict) for x in payload):
            return payload
        return []
    if isinstance(payload, dict):
        for key in ("data", "records", "result", "rows", "Data"):
            if key in payload:
                found = extract_records(payload[key])
                if found:
                    return found
        for v in payload.values():
            if isinstance(v, (list, dict)):
                found = extract_records(v)
                if found:
                    return found
    return []


def get_data(params: dict, max_pages: int = 20, page_size: int = 500) -> dict:
    """Fetch every page of a getNASData query and return flat records."""
    base = {k: v for k, v in params.items() if v not in (None, "")}
    base.setdefault("Format", "JSON")
    base["limit"] = page_size
    records: list[dict] = []
    raw_first = None
    for page in range(1, max_pages + 1):
        base["page"] = page
        res = _get_json("/api/nas/getNASData", base)
        if raw_first is None:
            raw_first = res
        if isinstance(res, dict) and res.get("statusCode") is False:
            if page == 1:
                raise ValueError(res.get("message") or "MoSPI API returned an error")
            break
        batch = extract_records(res)
        records.extend(batch)
        if len(batch) < page_size:
            break
    meta = {k: v for k, v in raw_first.items() if k not in ("data",)} if isinstance(raw_first, dict) else {}
    return {"records": records, "meta": meta}
