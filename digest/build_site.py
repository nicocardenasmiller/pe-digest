#!/usr/bin/env python3
"""Build the digest website from every committed week.

For each data/scores/<week>.json it pairs the matching collector output
data/weekly/<week>.json, renders a page, and writes:

    _site/index.html            latest issue
    _site/weeks/<week>.html     each issue
    _site/archive.html          list of all issues

Usage: python digest/build_site.py [OUT_DIR]   (default _site)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import esc, render, standalone  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site"
    (out / "weeks").mkdir(parents=True, exist_ok=True)
    (out / ".nojekyll").write_text("")

    issues = []
    prev = None
    for path in sorted((ROOT / "data/scores").glob("*.json")):
        scores = json.loads(path.read_text())
        week = scores.get("week_of") or path.stem
        data_path = ROOT / "data/weekly" / f"{week}.json"
        if not data_path.exists():
            print(f"skip {week}: no collector output at {data_path}")
            continue
        data = json.loads(data_path.read_text())
        previous = {"week_of": prev.get("week_of"), "flagged_titles": prev.get("flagged_titles", [])} if prev else None
        page = standalone(render(data, scores, previous, site=True),
                          title=f"The Political Economy Digest, week of {week}")
        # Issue pages live one level down, so the archive link needs a ../ prefix there.
        (out / "weeks" / f"{week}.html").write_text(page.replace('href="archive.html"', 'href="../archive.html"'))
        headline = (scores.get("overview") or {}).get("headline", "")
        issues.append((week, headline, len(scores.get("flagged", []))))
        prev = scores
        latest = page

    if not issues:
        print("no issues to build")
        return 1
    (out / "index.html").write_text(latest)

    rows = "".join(
        f'<li><a href="weeks/{w}.html"><span class="d num">{esc(dt.date.fromisoformat(w).strftime("%-d %b %Y"))}</span>'
        f'<span class="h">{esc(h) or "Weekly issue"}</span><span class="n num">{n} flagged</span></a></li>'
        for w, h, n in reversed(issues))
    (out / "archive.html").write_text(ARCHIVE.format(rows=rows, count=len(issues)))
    print(f"built {len(issues)} issue(s) into {out}")
    return 0


ARCHIVE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Past issues · The Political Economy Digest</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Caslon+Display&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Mono&display=swap">
<style>
:root {{ --paper:#f4f1ea; --ink:#1d1a17; --ink-2:#4f4a43; --rule:#cfc8bb; --claret:#8c1d2f; }}
@media (prefers-color-scheme: dark) {{ :root {{ --paper:#191816; --ink:#ebe6dc; --ink-2:#b3ab9e; --rule:#3a3631; --claret:#e0798a; color-scheme: dark; }} }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:400 16px/1.5 "Source Serif 4", Georgia, serif; }}
main {{ max-width:760px; margin:0 auto; padding:32px max(16px, env(safe-area-inset-right, 0px)) 56px max(16px, env(safe-area-inset-left, 0px)); }}
h1 {{ font:400 clamp(30px,6vw,52px)/1 "Libre Caslon Display", Georgia, serif; margin:0 0 8px; text-align:center; }}
.sub {{ text-align:center; font:500 12px/1.3 "IBM Plex Sans Condensed", sans-serif; letter-spacing:.08em; text-transform:uppercase;
  border-top:3px double var(--ink); border-bottom:1px solid var(--ink); padding:6px 0; margin-bottom:24px; }}
.sub a {{ color:inherit; }}
ul {{ list-style:none; margin:0; padding:0; }}
li a {{ display:grid; grid-template-columns:7.5em minmax(0,1fr) auto; gap:12px; padding:12px 0; border-bottom:1px solid var(--rule);
  color:inherit; text-decoration:none; align-items:baseline; }}
li a:hover .h, li a:focus-visible .h {{ color:var(--claret); text-decoration:underline; }}
.num {{ font-family:"IBM Plex Mono", monospace; font-size:13px; color:var(--ink-2); font-variant-numeric:tabular-nums; }}
.h {{ font-weight:600; }}
@media (max-width:520px) {{ li a {{ grid-template-columns:minmax(0,1fr); gap:2px; }} }}
</style></head>
<body><main>
<h1>The Political Economy Digest</h1>
<p class="sub">Past issues · {count} · <a href="index.html">Latest issue</a></p>
<ul>{rows}</ul>
</main></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
