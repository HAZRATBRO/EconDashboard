"""Build the single-file hosted version (for tablets/phones) from template.html
and the shared reference data in backend/data. Output: hosted/dist/index.html"""

import json
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent / "backend" / "data"


def compact(name: str) -> str:
    return json.dumps(json.loads((DATA / name).read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))


html = (HERE / "template.html").read_text(encoding="utf-8")
html = (html.replace("/*GLOSSARY*/[]", compact("glossary.json"))
            .replace("/*SNAPSHOT*/{}", compact("snapshot.json"))
            .replace("/*SERIES*/[]", compact("report_series.json")))
out = HERE / "dist" / "index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
