#!/usr/bin/env python3
"""Render the weekly digest page from data/latest.json plus a scores file.

Usage:
    python digest/render.py SCORES_JSON OUT_HTML [--previous PREV_SCORES_JSON]

The scores file is written by the weekly scoring step:
{
  "week_of": "2026-11-06",
  "overview": {
    "headline": "short newspaper-style headline for the week",
    "standfirst": "one or two sentences summarizing the week",
    "sections": [{"head": "section headline", "body": "paragraph; cite papers as {W123}"}]
  },
  "flagged":     [{"id": "W...", "score": 8, "why": "one sentence"}],
  "high_signal": [{"id": "W...", "why": "one sentence"}],
  "near_misses": [{"id": "W...", "score": 6}],
  "notes": "optional coverage note"
}
IDs may refer to items in candidates, other or rising. In overview bodies, {W123}
becomes the paper's linked title.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def authors(it: dict, n: int = 3) -> str:
    a = it.get("authors") or []
    return ", ".join(a[:n]) + (" et al." if len(a) > n else "")


def link(it: dict, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{esc(it.get("url"))}" target="_blank" rel="noopener">{esc(it.get("title"))}</a>'


def byline(it: dict, extra: str = "") -> str:
    bits = [esc(authors(it)), f'<span class="src">{esc(it.get("source"))}</span>']
    if it.get("missing_abstract"):
        bits.append('<span class="flag">title only</span>')
    return f'<p class="byline">{" · ".join(b for b in bits if b)}{extra}</p>'


def story(it: dict, r: dict, lead: bool = False) -> str:
    kicker = esc((r.get("why") or "").split(":", 1)[0]) if ":" in (r.get("why") or "") else esc(it.get("tier_label"))
    why = (r.get("why") or "").split(":", 1)[-1].strip()
    score = f'<span class="score num" title="Relevance, out of 10">{r["score"]}/10</span>' if r.get("score") is not None else ""
    cls = "story lead-story" if lead else "story"
    return f"""<article class="{cls}">
  <p class="kicker">{kicker}{score}</p>
  <h3>{link(it)}</h3>
  <p class="dek">{esc(why)}</p>
  {byline(it)}
</article>"""


def render_overview(ov: dict, pool: dict) -> str:
    if not ov:
        return ""

    def cite(m):
        it = pool.get(m.group(1))
        return f"<em>{link(it)}</em>" if it else ""

    secs = []
    for s in ov.get("sections", []):
        body = re.sub(r"\{(W\d+)\}", cite, esc(s.get("body")))
        secs.append(f'<h4>{esc(s.get("head"))}</h4><p>{body}</p>')
    return f"""<section class="brief" aria-labelledby="brief-h">
  <p class="section-label">The week in brief</p>
  <h2 id="brief-h">{esc(ov.get("headline"))}</h2>
  <p class="standfirst">{esc(ov.get("standfirst"))}</p>
  <div class="brief-cols">{''.join(secs)}</div>
</section>"""


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
    week = scores.get("week_of") or data.get("week_of")
    d = dt.date.fromisoformat(week)
    iso = d.isocalendar()
    window = data.get("window", {})

    if flagged:
        front = story(*flagged[0], lead=True) + '<div class="story-grid">' + \
            "".join(story(it, r) for it, r in flagged[1:]) + "</div>"
    else:
        front = '<p class="empty">Nothing scored 7 or higher this week.</p>'

    signal_html = "".join(
        f'<li><h4>{link(it)}</h4><p class="dek small">{esc(r.get("why"))}</p>{byline(it)}</li>' for it, r in signal
    ) or '<li class="empty">No items selected.</li>'

    near_html = "".join(
        f'<li><span class="score num">{r.get("score", "")}</span><span>{link(it)}'
        f'<span class="src-inline"> · {esc(it.get("source"))}</span></span></li>' for it, r in near
    ) or '<li class="empty">None.</li>'

    rising_rows = "".join(
        f'<tr><td class="t">{link(it)}<span class="src-inline">{esc(it.get("source"))}</span></td>'
        f'<td class="num">{esc((it.get("date") or "")[:7])}</td>'
        f'<td class="num">{it.get("cited_by_count", 0)}</td>'
        f'<td class="num strong">{it.get("velocity_per_month", 0):.1f}</td></tr>' for it in rising)

    groups = []
    for src in sorted(rest, key=lambda s: (-len(rest[s]), s)):
        items = "".join(f'<li>{link(it)}<span class="src-inline"> · {esc(authors(it, 2))}</span></li>' for it in rest[src])
        groups.append(f'<details><summary><span>{esc(src)}</span><span class="num count">{len(rest[src])}</span>'
                      f'</summary><ul>{items}</ul></details>')

    prev_html = ""
    if previous and previous.get("flagged_titles"):
        lis = "".join(f'<li><a href="{esc(p.get("url"))}" target="_blank" rel="noopener">{esc(p.get("title"))}</a></li>'
                      for p in previous["flagged_titles"])
        prev_html = (f'<details class="prev"><summary><span>Last week\'s flagged papers, {esc(previous.get("week_of"))}'
                     f'</span><span class="num count">{len(previous["flagged_titles"])}</span></summary><ul>{lis}</ul></details>')

    notes = esc(scores.get("notes"))
    if c.get("unresolved_sources"):
        notes += f' Sources not found in OpenAlex: {esc(", ".join(c["unresolved_sources"]))}.'

    return TEMPLATE.format(
        dateline=esc(d.strftime("%A %-d %B %Y")), week_no=iso[1], year=iso[0],
        wfrom=esc(window.get("from")), wto=esc(window.get("to")),
        n_new=c.get("new_after_dedupe", 0), n_flag=len(flagged),
        brief=render_overview(scores.get("overview"), pool),
        front=front, signal=signal_html, near=near_html, rising=rising_rows,
        groups="".join(groups), n_rest=sum(len(v) for v in rest.values()), prev=prev_html,
        notes=f'<p class="notes">{notes}</p>' if notes else "",
    )


TEMPLATE = """<title>Political Economy Digest</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Caslon+Display&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: broadsheet front page. Masthead and dateline rule; the week in brief as a
   two-column lead; flagged papers as front-page stories; a rail of field news; a
   citation-velocity table set like a markets page; an index of everything else. */
:root {{
  --paper: #f4f1ea; --ink: #1d1a17; --ink-2: #4f4a43; --rule: #cfc8bb; --rule-strong: #1d1a17;
  --claret: #8c1d2f; --panel: #ebe6dc;
  --masthead: "Libre Caslon Display", "Didot", "Bodoni 72", Georgia, serif;
  --serif: "Source Serif 4", Georgia, "Times New Roman", serif;
  --label: "IBM Plex Sans Condensed", "Arial Narrow", "Helvetica Neue", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --paper: #191816; --ink: #ebe6dc; --ink-2: #b3ab9e; --rule: #3a3631; --rule-strong: #ebe6dc;
  --claret: #e0798a; --panel: #22201d; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --paper: #191816; --ink: #ebe6dc; --ink-2: #b3ab9e; --rule: #3a3631; --rule-strong: #ebe6dc;
  --claret: #e0798a; --panel: #22201d; color-scheme: dark; }}
body {{ background: var(--paper); color: var(--ink); font: 400 16px/1.55 var(--serif); }}
a {{ color: inherit; text-decoration: none; }}
a:hover, a:focus-visible {{ color: var(--claret); text-decoration: underline; text-underline-offset: 3px; }}
:focus-visible {{ outline: 2px solid var(--claret); outline-offset: 2px; }}
.page {{ max-width: 1120px; margin: 0 auto; padding-block: 28px 56px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: flex; flex-direction: column; gap: 32px; }}
.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}

/* Masthead */
.masthead {{ display: flex; flex-direction: column; align-items: center; gap: 10px; text-align: center; }}
.masthead h1 {{ font: 400 clamp(34px, 7vw, 68px)/1 var(--masthead); margin: 0; letter-spacing: .01em; text-wrap: balance; }}
.dateline {{ width: 100%; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 16px;
  border-top: 3px double var(--rule-strong); border-bottom: 1px solid var(--rule-strong); padding: 6px 0;
  font: 500 12px/1.3 var(--label); letter-spacing: .06em; text-transform: uppercase; }}
.dateline span:nth-child(2) {{ text-align: center; }}

.section-label {{ font: 600 12px/1 var(--label); letter-spacing: .1em; text-transform: uppercase; color: var(--claret); margin: 0; }}
h2 {{ font: 700 clamp(26px, 4vw, 40px)/1.1 var(--serif); margin: 0; text-wrap: balance; }}
h3 {{ font: 600 21px/1.25 var(--serif); margin: 0; text-wrap: balance; }}
h4 {{ font: 700 16px/1.3 var(--serif); margin: 0; }}
.rubric {{ display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
  border-top: 2px solid var(--rule-strong); padding-top: 8px; }}
.rubric h2 {{ font: 600 14px/1 var(--label); letter-spacing: .1em; text-transform: uppercase; }}
.rubric small {{ font: 400 13px var(--serif); color: var(--ink-2); font-style: italic; }}

/* The week in brief */
.brief {{ display: flex; flex-direction: column; gap: 12px; }}
.standfirst {{ font: 400 20px/1.45 var(--serif); color: var(--ink-2); margin: 0; max-width: 60ch; }}
.brief-cols {{ columns: 2 320px; column-gap: 40px; column-rule: 1px solid var(--rule); margin-top: 8px; }}
.brief-cols h4 {{ break-after: avoid; margin-top: 14px; }}
.brief-cols h4:first-child {{ margin-top: 0; }}
.brief-cols p {{ margin: 4px 0 0; hyphens: auto; }}
.brief-cols em a {{ font-style: italic; text-decoration: underline; text-decoration-color: var(--rule); text-underline-offset: 3px; }}

/* Front page: flagged stories with a rail */
.front {{ display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(0, 1fr); gap: 32px; }}
.front > * {{ min-width: 0; }}
.main-col, .rail {{ display: flex; flex-direction: column; gap: 16px; }}
.story {{ display: flex; flex-direction: column; gap: 6px; }}
.lead-story {{ padding-bottom: 18px; border-bottom: 1px solid var(--rule); }}
.lead-story h3 {{ font-size: clamp(24px, 3.4vw, 32px); line-height: 1.15; }}
.lead-story .dek {{ font-size: 18px; }}
.story-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 28px; }}
.story-grid .story {{ border-top: 1px solid var(--rule); padding-top: 12px; }}
.kicker {{ margin: 0; display: flex; justify-content: space-between; gap: 12px;
  font: 600 12px/1.2 var(--label); letter-spacing: .08em; text-transform: uppercase; color: var(--claret); }}
.score {{ color: var(--ink-2); font-size: 12px; letter-spacing: 0; font-weight: 400; }}
.dek {{ margin: 0; color: var(--ink-2); }}
.dek.small {{ font-size: 14.5px; }}
.byline {{ margin: 0; font: 500 12.5px/1.4 var(--label); color: var(--ink-2); letter-spacing: .02em; }}
.byline .src {{ color: var(--ink); }}
.flag {{ color: var(--claret); }}
.rail {{ border-left: 1px solid var(--rule); padding-left: 24px; }}
.rail ul {{ list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }}
.rail li {{ padding: 12px 0; border-top: 1px solid var(--rule); display: flex; flex-direction: column; gap: 4px; }}

/* Lower page */
.lower {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 32px; }}
.lower > section {{ min-width: 0; display: flex; flex-direction: column; gap: 10px; }}
.table-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{ font: 600 11px/1.2 var(--label); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-2);
  text-align: right; padding: 6px 0 6px 12px; border-bottom: 1px solid var(--rule-strong); white-space: nowrap; }}
th:first-child, td.t {{ text-align: left; padding-left: 0; }}
td {{ padding: 8px 0 8px 12px; border-bottom: 1px solid var(--rule); text-align: right; vertical-align: top; white-space: nowrap; }}
td.t {{ white-space: normal; display: flex; flex-direction: column; gap: 2px; }}
td.strong {{ color: var(--claret); font-weight: 500; }}
.src-inline {{ font: 500 12px/1.3 var(--label); color: var(--ink-2); letter-spacing: .02em; }}
.inbrief {{ list-style: none; margin: 0; padding: 0; }}
.inbrief li {{ display: flex; gap: 10px; align-items: baseline; padding: 7px 0; border-bottom: 1px solid var(--rule); font-size: 15px; }}
.inbrief .score {{ flex: none; width: 1.4em; color: var(--claret); }}
.table-note {{ margin: 0; font-size: 13px; font-style: italic; color: var(--ink-2); }}

/* Index */
.index {{ display: flex; flex-direction: column; gap: 10px; }}
.index-cols {{ columns: 2 300px; column-gap: 32px; }}
details {{ break-inside: avoid; border-top: 1px solid var(--rule); }}
summary {{ cursor: pointer; list-style: none; display: flex; justify-content: space-between; gap: 12px; padding: 8px 0;
  font: 600 13px/1.3 var(--label); letter-spacing: .04em; text-transform: uppercase; }}
summary::-webkit-details-marker {{ display: none; }}
summary span:first-child::before {{ content: "+ "; font-family: var(--mono); color: var(--ink-2); }}
details[open] summary span:first-child::before {{ content: "\\2212 "; }}
.count {{ color: var(--ink-2); font-weight: 400; }}
details ul {{ list-style: none; margin: 0; padding: 0 0 10px; display: flex; flex-direction: column; gap: 6px; font-size: 14.5px; }}
.prev {{ border-bottom: 1px solid var(--rule); }}
.notes {{ margin: 0; font-size: 13.5px; font-style: italic; color: var(--ink-2); max-width: 75ch; }}
footer {{ border-top: 3px double var(--rule-strong); padding-top: 10px; font: 500 12px/1.4 var(--label); color: var(--ink-2); letter-spacing: .03em; }}
.empty {{ color: var(--ink-2); font-style: italic; }}

@media (max-width: 820px) {{
  .front, .lower {{ grid-template-columns: minmax(0, 1fr); }}
  .rail {{ border-left: 0; padding-left: 0; }}
  .story-grid {{ grid-template-columns: minmax(0, 1fr); }}
  .dateline {{ justify-content: center; text-align: center; }}
}}
</style>
<div class="page">
<header class="masthead">
  <h1>The Political Economy Digest</h1>
  <div class="dateline"><span>{dateline}</span><span>Week {week_no}, {year}</span><span class="num">{n_new} new · {n_flag} flagged</span></div>
</header>

{brief}

<div class="front">
  <section class="main-col" aria-labelledby="front-h">
    <div class="rubric"><h2 id="front-h">Flagged for you</h2><small>relevance 7 or higher, out of 10</small></div>
    {front}
  </section>
  <aside class="rail" aria-labelledby="signal-h">
    <div class="rubric"><h2 id="signal-h">Across the field</h2><small>top venues, senior authors</small></div>
    <ul>{signal}</ul>
  </aside>
</div>

<div class="lower">
  <section aria-labelledby="rising-h">
    <div class="rubric"><h2 id="rising-h">Rising</h2><small>3 to 12 months old</small></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Paper</th><th>Published</th><th>Citations</th><th>Per month</th></tr></thead>
      <tbody>{rising}</tbody>
    </table></div>
    <p class="table-note">Political science and economics are ranked separately, since economics papers are cited faster.</p>
  </section>
  <section aria-labelledby="near-h">
    <div class="rubric"><h2 id="near-h">In brief</h2><small>near misses, relevance 5 to 6</small></div>
    <ul class="inbrief">{near}</ul>
  </section>
</div>

<section class="index" aria-labelledby="index-h">
  <div class="rubric"><h2 id="index-h">Index</h2><small>{n_rest} other new items, {wfrom} to {wto}</small></div>
  <div class="index-cols">{groups}</div>
  {prev}
</section>

{notes}
<footer>Compiled from OpenAlex. Relevance is judged against the interest statement in the pe-digest repository; per-source counts are in data/diagnostics.md.</footer>
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
    pool = {it["id"]: it for key in ("candidates", "other", "rising") for it in data.get(key, [])}
    scores["flagged_titles"] = [{"title": pool[r["id"]]["title"], "url": pool[r["id"]]["url"]}
                                for r in scores.get("flagged", []) if r["id"] in pool]
    Path(args.scores).write_text(json.dumps(scores, indent=1, ensure_ascii=False))
    Path(args.out).write_text(render(data, scores, previous))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
