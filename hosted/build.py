"""Build the single-file browser version of the dashboard.

Outputs:
  hosted/dist/index.html - page body for the claude.ai artifact (wrapped in a skeleton at publish)
  docs/index.html        - complete page for GitHub Pages (Settings > Pages > branch, /docs folder)

Both come from template.html plus the shared reference data in backend/data.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = ROOT / "backend" / "data"

SKELETON_HEAD = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
    "<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);"
    "padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}"
    "[hidden]{display:none!important}</style>\n</head>\n<body>\n"
)


def compact(name: str) -> str:
    return json.dumps(json.loads((DATA / name).read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))


body = (HERE / "template.html").read_text(encoding="utf-8")
body = (body.replace("/*GLOSSARY*/[]", compact("glossary.json"))
            .replace("/*SNAPSHOT*/{}", compact("snapshot.json"))
            .replace("/*SERIES*/[]", compact("report_series.json"))
            .replace("/*INDICATORS*/[]", compact("nas_indicators.json")))

artifact = HERE / "dist" / "index.html"
artifact.parent.mkdir(exist_ok=True)
artifact.write_text(body, encoding="utf-8")

pages = ROOT / "docs" / "index.html"
pages.parent.mkdir(exist_ok=True)
pages.write_text(SKELETON_HEAD + body + "\n</body>\n</html>\n", encoding="utf-8")
(ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")

for f in (artifact, pages):
    print(f"wrote {f.relative_to(ROOT)} ({f.stat().st_size // 1024} KB)")
