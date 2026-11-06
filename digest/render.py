#!/usr/bin/env python3
"""Render the weekly digest page from data/latest.json plus a scores file.

Usage:
    python digest/render.py SCORES_JSON OUT_HTML [--previous PREV_SCORES_JSON]

The scores file is written by the weekly scoring step:
{
  "week_of": "2026-11-06",
  "flagged":     [{"id": "W...", "score": 8, "why": "one sentence"}],
  "high_signal": [{"id": "W...", "why": "one sentence"}],
  "near_misses": [{"id": "W...", "score": 6}],
  "notes": "optional one-paragraph note shown under the header"
}
IDs may refer to items in candidates, other or rising.
"""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def authors(it: dict, n: int = 3) -> str:
    a = it.get("authors") or []
    return ", ".join(a[:n]) + (" et al." if len(a) > n else "")


def meta_line(it: dict) -> str:
    bits = [f'<span class="src">{esc(it.get("source"))}</span>']
    if it.get("tier_label"):
        bits.append(f'<span class="tier">{esc(it["tier_label"])}</span>')
    if it.get("date"):
        bits.append(f'<span class="num">{esc(it["date"])}</span>')
    if it.get("max_author_h_index"):
        bits.append(f'<span class="num">max h {it["max_author_h_index"]}</span>')
    if it.get("missing_abstract"):
        bits.append('<span class="warn">title only</span>')
    return '<span class="sep">·</span>'.join(bits)


def entry(it: dict, why: str = "", score=None, extra: str = "") -> str:
    sc = f'<span class="score num" title="Relevance score out of 10">{score}</span>' if score is not None else ""
    why_html = f'<p class="why">{esc(why)}</p>' if why else ""
    return f"""<li class="entry">
  <div class="entry-head">{sc}<a class="title" href="{esc(it.get('url'))}" target="_blank" rel="noopener">{esc(it.get('title'))}</a></div>
  <p class="by">{esc(authors(it))}</p>
  <p class="meta">{meta_line(it)}{extra}</p>
  {why_html}
</li>"""


def render(data: dict, scores: dict, previous: dict | None = None) -> str:
    pool = {it["id"]: it for key in ("candidates", "other", "rising") for it in data.get(key, [])}
    used = set()

    def pick(rows):
        out = []
        for r in rows:
            it = pool.get(r["id"])
            if it:
                used.add(r["id"])
                out.append((it, r))
        return out

    flagged = pick(scores.get("flagged", []))
    signal = pick(scores.get("high_signal", []))
    near = pick(scores.get("near_misses", []))
    rising = data.get("rising", [])
    used |= {r["id"] for r in rising}

    rest = defaultdict(list)
    for key in ("candidates", "other"):
        for it in data.get(key, []):
            if it["id"] not in used:
                rest[it.get("source") or "Other"].append(it)

    c = data.get("counts", {})
    warn = ""
    if c.get("unresolved_sources"):
        warn = f'<p class="alert">Sources not found in OpenAlex this week: {esc(", ".join(c["unresolved_sources"]))}.</p>'
    notes = f'<p class="note">{esc(scores["notes"])}</p>' if scores.get("notes") else ""

    flagged_html = "\n".join(entry(it, r.get("why"), r.get("score")) for it, r in flagged) or \
        '<li class="empty">Nothing scored 7 or higher this week.</li>'
    signal_html = "\n".join(entry(it, r.get("why")) for it, r in signal) or \
        '<li class="empty">No items selected.</li>'
    near_html = "\n".join(
        f'<li class="compact"><span class="score small num">{r.get("score", "")}</span>'
        f'<a href="{esc(it.get("url"))}" target="_blank" rel="noopener">{esc(it.get("title"))}</a>'
        f'<span class="src-inline">{esc(it.get("source"))}</span></li>' for it, r in near)
    rising_html = "\n".join(
        entry(it, extra=f'<span class="sep">·</span><span class="velocity num">{it.get("velocity_per_month", 0)} cites/mo</span>'
              f'<span class="sep">·</span><span class="num">{it.get("cited_by_count", 0)} total</span>')
        for it in rising)

    groups = []
    for src in sorted(rest, key=lambda s: (-len(rest[s]), s)):
        items = "\n".join(f'<li><a href="{esc(it.get("url"))}" target="_blank" rel="noopener">{esc(it.get("title"))}</a>'
                          f'<span class="by-inline">{esc(authors(it, 2))}</span></li>' for it in rest[src])
        groups.append(f'<details class="group"><summary><span>{esc(src)}</span>'
                      f'<span class="count num">{len(rest[src])}</span></summary><ul>{items}</ul></details>')

    prev_html = ""
    if previous and previous.get("flagged_titles"):
        lis = "\n".join(f'<li><a href="{esc(p.get("url"))}" target="_blank" rel="noopener">{esc(p.get("title"))}</a></li>'
                        for p in previous["flagged_titles"])
        prev_html = (f'<section><details class="group prev"><summary><span>Previous week ({esc(previous.get("week_of"))})'
                     f'</span><span class="count num">{len(previous["flagged_titles"])}</span></summary><ul>{lis}</ul>'
                     f'</details></section>')

    total_rest = sum(len(v) for v in rest.values())
    window = data.get("window", {})
    return TEMPLATE.format(
        week=esc(scores.get("week_of") or data.get("week_of")),
        wfrom=esc(window.get("from")), wto=esc(window.get("to")),
        n_new=c.get("new_after_dedupe", 0), n_flag=len(flagged), n_rising=len(rising),
        n_missing=c.get("missing_abstract", 0),
        warn=warn, notes=notes, flagged=flagged_html, signal=signal_html,
        near=near_html or '<li class="empty">None.</li>', rising=rising_html,
        groups="\n".join(groups), n_rest=total_rest, prev=prev_html,
    )


TEMPLATE = """<title>Political Economy Digest</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: single reading column; a ledger-like header strip with the week's counts, then ranked lists. */
:root {{
  --bg: #f6f7f9; --surface: #ffffff; --fg: #1b2330; --muted: #5b6676; --rule: #dde2e9;
  --accent: #1f5f8b; --accent-soft: #e3eef6; --warn: #8a5a00; --warn-soft: #fbf1dc;
  --display: "Source Serif 4", Georgia, "Times New Roman", serif;
  --body: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #12161c; --surface: #1a2029; --fg: #e3e7ee; --muted: #98a3b3; --rule: #2b3340;
  --accent: #7fb6dc; --accent-soft: #1d3346; --warn: #e2b55c; --warn-soft: #33290f; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #12161c; --surface: #1a2029; --fg: #e3e7ee; --muted: #98a3b3; --rule: #2b3340;
  --accent: #7fb6dc; --accent-soft: #1d3346; --warn: #e2b55c; --warn-soft: #33290f; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 15px; line-height: 1.55; }}
.wrap {{ max-width: 760px; margin: 0 auto; padding-block: 40px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: flex; flex-direction: column; gap: 40px; }}
header {{ display: flex; flex-direction: column; gap: 14px; }}
.eyebrow {{ font: 500 12px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }}
h1 {{ font: 600 clamp(28px, 5vw, 38px)/1.12 var(--display); margin: 0; text-wrap: balance; }}
.ledger {{ display: flex; flex-wrap: wrap; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }}
.ledger div {{ flex: 1 1 120px; padding: 10px 12px 10px 0; display: flex; flex-direction: column; gap: 2px; }}
.ledger b {{ font: 500 20px/1.2 var(--mono); font-variant-numeric: tabular-nums; }}
.ledger span {{ font-size: 12px; color: var(--muted); }}
.note, .alert {{ margin: 0; font-size: 14px; color: var(--muted); max-width: 65ch; }}
.alert {{ color: var(--warn); background: var(--warn-soft); padding: 8px 12px; border-radius: 4px; }}
section {{ display: flex; flex-direction: column; gap: 14px; }}
h2 {{ font: 600 21px/1.25 var(--display); margin: 0; display: flex; align-items: baseline; gap: 10px; }}
h2 small {{ font: 400 13px var(--body); color: var(--muted); }}
ol, ul {{ list-style: none; margin: 0; padding: 0; }}
.list {{ display: flex; flex-direction: column; }}
.entry {{ padding: 14px 0; border-top: 1px solid var(--rule); display: flex; flex-direction: column; gap: 3px; min-width: 0; }}
.entry:last-child {{ border-bottom: 1px solid var(--rule); }}
.entry-head {{ display: flex; gap: 10px; align-items: baseline; }}
.title {{ font: 600 17px/1.35 var(--display); color: var(--fg); text-decoration: none; min-width: 0; }}
.title:hover, .title:focus-visible {{ color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }}
.score {{ flex: none; font: 500 13px/1 var(--mono); color: var(--accent); background: var(--accent-soft);
  padding: 4px 6px; border-radius: 3px; min-width: 2.2em; text-align: center; }}
.score.small {{ font-size: 12px; padding: 2px 5px; }}
.by, .meta, .why {{ margin: 0; }}
.by {{ font-size: 14px; color: var(--muted); }}
.meta {{ font-size: 12.5px; color: var(--muted); display: flex; flex-wrap: wrap; gap: 0 2px; }}
.sep {{ padding: 0 6px; opacity: .6; }}
.src {{ font-weight: 500; color: var(--fg); }}
.tier {{ text-transform: uppercase; letter-spacing: .05em; font-size: 11px; }}
.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.warn {{ color: var(--warn); }}
.velocity {{ color: var(--accent); font-weight: 500; }}
.why {{ font-size: 14.5px; max-width: 65ch; margin-top: 4px; }}
.empty {{ color: var(--muted); padding: 12px 0; border-top: 1px solid var(--rule); }}
.compact {{ display: flex; gap: 10px; align-items: baseline; padding: 7px 0; border-top: 1px solid var(--rule); flex-wrap: wrap; }}
.compact a, .group li a {{ color: var(--fg); text-decoration: none; min-width: 0; }}
.compact a:hover, .group li a:hover, .compact a:focus-visible, .group li a:focus-visible {{ color: var(--accent); text-decoration: underline; }}
.src-inline, .by-inline {{ font-size: 12.5px; color: var(--muted); }}
.group {{ border-top: 1px solid var(--rule); }}
.groups .group:last-child {{ border-bottom: 1px solid var(--rule); }}
.group summary {{ cursor: pointer; padding: 10px 0; display: flex; justify-content: space-between; gap: 12px; font-weight: 500; list-style: none; }}
.group summary::-webkit-details-marker {{ display: none; }}
.group summary::before {{ content: "+"; font-family: var(--mono); color: var(--muted); width: 1em; }}
.group[open] summary::before {{ content: "\\2212"; }}
.group summary span:first-of-type {{ flex: 1; }}
.group summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.count {{ color: var(--muted); font-size: 13px; }}
.group ul {{ padding: 0 0 12px 1.6em; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }}
.group li {{ display: flex; flex-direction: column; }}
footer {{ font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--rule); padding-top: 14px; }}
</style>
<div class="wrap">
<header>
  <span class="eyebrow">Week of {week}</span>
  <h1>Political Economy Digest</h1>
  <div class="ledger">
    <div><b>{n_new}</b><span>new items, {wfrom} to {wto}</span></div>
    <div><b>{n_flag}</b><span>flagged for you</span></div>
    <div><b>{n_rising}</b><span>rising papers</span></div>
    <div><b>{n_missing}</b><span>without abstracts</span></div>
  </div>
  {warn}
  {notes}
</header>

<section>
  <h2>Flagged for you <small>score 7 or higher, out of 10</small></h2>
  <ol class="list">{flagged}</ol>
</section>

<section>
  <h2>High-signal in the field <small>Tier 1 and 2 venues or senior authors, any topic</small></h2>
  <ul class="list">{signal}</ul>
</section>

<section>
  <h2>Near misses <small>score 5 to 6</small></h2>
  <ul>{near}</ul>
</section>

<section>
  <h2>Rising <small>published 3 to 12 months ago, by citations per month</small></h2>
  <ol class="list">{rising}</ol>
</section>

<section>
  <h2>Everything else <small>{n_rest} items by source</small></h2>
  <div class="groups">{groups}</div>
</section>
{prev}
<footer>Collected from OpenAlex. Relevance scores are judged against your interest statement in the pe-digest repository. Working-paper coverage depends on what OpenAlex indexes; per-source counts are in data/diagnostics.md.</footer>
</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scores")
    ap.add_argument("out")
    ap.add_argument("--data", default=str(ROOT / "data/latest.json"))
    ap.add_argument("--previous", help="previous week's scores file, for the collapsed history section")
    args = ap.parse_args()
    data = json.loads(Path(args.data).read_text())
    scores = json.loads(Path(args.scores).read_text())
    previous = None
    if args.previous and Path(args.previous).exists():
        prev = json.loads(Path(args.previous).read_text())
        previous = {"week_of": prev.get("week_of"), "flagged_titles": prev.get("flagged_titles", [])}
    # Store flagged titles in the scores file so next week can show them without old data.
    pool = {it["id"]: it for key in ("candidates", "other", "rising") for it in data.get(key, [])}
    scores["flagged_titles"] = [{"title": pool[r["id"]]["title"], "url": pool[r["id"]]["url"]}
                                for r in scores.get("flagged", []) if r["id"] in pool]
    Path(args.scores).write_text(json.dumps(scores, indent=1, ensure_ascii=False))
    Path(args.out).write_text(render(data, scores, previous))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
