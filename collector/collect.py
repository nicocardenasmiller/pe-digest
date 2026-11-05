#!/usr/bin/env python3
"""Weekly OpenAlex collector for the political economy digest.

Pulls new items from the journals and working paper series in config/sources.yaml,
plus "rising" papers (3-12 months old, fast citation growth), attaches author
impact signals, prefilters by text similarity to config/interests.md, and writes
data/weekly/<date>.json and data/latest.json for the weekly scoring step.

Usage:
    python collector/collect.py [--today YYYY-MM-DD]

Environment:
    OPENALEX_API_KEY   optional; raises the free daily budget
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.openalex.org"
WORK_TYPES = "article|preprint|report|review"
WORK_FIELDS = ",".join([
    "id", "doi", "display_name", "publication_date", "type", "language",
    "authorships", "abstract_inverted_index", "primary_location",
    "cited_by_count", "counts_by_year",
])
TIER_LABELS = {1: "Core PE", 2: "Generalist", 3: "Latin America", 4: "Economics", 5: "Working paper"}


# ---------------------------------------------------------------- HTTP client

class OpenAlexClient:
    def __init__(self, api_key: str | None = None, pause: float = 0.12):
        self.api_key = api_key
        self.pause = pause
        self.calls = 0

    def get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        if self.api_key:
            params["api_key"] = self.api_key
        url = f"{API}{path}?{urllib.parse.urlencode(params, safe=':|,*')}"
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "pe-digest/1.0"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    self.calls += 1
                    time.sleep(self.pause)
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {}
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
            except urllib.error.URLError:
                if attempt < 4:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
        return {}

    def paginate(self, path: str, params: dict, limit: int = 2000) -> list[dict]:
        out, cursor = [], "*"
        while cursor and len(out) < limit:
            page = self.get(path, {**params, "per_page": 100, "cursor": cursor})
            results = page.get("results", [])
            out.extend(results)
            cursor = page.get("meta", {}).get("next_cursor")
            if not results:
                break
        return out[:limit]


# ---------------------------------------------------------------- helpers

def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"^the\s+", "", text.lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def short_id(openalex_id: str | None) -> str:
    return (openalex_id or "").rsplit("/", 1)[-1]


def abstract_from_index(inv: dict | None) -> str:
    if not inv:
        return ""
    positions = [(pos, word) for word, idxs in inv.items() for pos in idxs]
    return " ".join(word for _, word in sorted(positions))


# ---------------------------------------------------------------- source resolution

def resolve_sources(cfg: dict, client, cache_path: Path) -> list[dict]:
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    resolved = []

    for j in cfg.get("journals", []):
        hit = cache.get(j["name"])
        if not (hit and hit.get("ok")):
            hit = _resolve_journal(j, client)
            cache[j["name"]] = hit
        resolved.append({**hit, "name": j["name"], "tier": j["tier"], "kind": "journal",
                         "keyword_filter": False})

    for w in cfg.get("working_papers", []):
        hit = cache.get(w["name"])
        if not (hit and hit.get("ok")):
            hit = _resolve_by_search(w["search"], client, threshold=0.55)
            cache[w["name"]] = hit
        resolved.append({**hit, "name": w["name"], "tier": 5, "kind": "working_paper",
                         "keyword_filter": bool(w.get("keyword_filter"))})

    cache_path.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    return resolved


def _resolve_journal(j: dict, client) -> dict:
    if j.get("issn"):
        src = client.get(f"/sources/issn:{j['issn']}")
        if src.get("id"):
            score = similar(j["name"], src.get("display_name", ""))
            if score >= 0.8:
                return {"ok": True, "openalex_id": short_id(src["id"]),
                        "display_name": src["display_name"], "method": "issn", "score": round(score, 2)}
    return _resolve_by_search(j["name"], client, threshold=0.8)


def _resolve_by_search(query: str, client, threshold: float) -> dict:
    page = client.get("/sources", {"search": query, "per_page": 10})
    best, best_score = None, 0.0
    for src in page.get("results", []):
        score = similar(query, src.get("display_name", ""))
        # Prefer the larger source when names tie closely (e.g. duplicate series records).
        score += min(src.get("works_count", 0), 100000) / 1e7
        if score > best_score:
            best, best_score = src, score
    if best and best_score >= threshold:
        return {"ok": True, "openalex_id": short_id(best["id"]), "display_name": best["display_name"],
                "method": "search", "score": round(best_score, 2)}
    return {"ok": False, "openalex_id": None,
            "display_name": best.get("display_name") if best else None,
            "method": "search", "score": round(best_score, 2)}


def write_resolution_report(sources: list[dict], path: Path) -> None:
    lines = ["# Source resolution report", "",
             "Check every row marked UNRESOLVED or with a display name that is not the intended source.", "",
             "| Configured name | OpenAlex match | ID | Method | Score | Status |",
             "| --- | --- | --- | --- | --- | --- |"]
    for s in sources:
        status = "ok" if s.get("ok") else "UNRESOLVED"
        lines.append(f"| {s['name']} | {s.get('display_name') or ''} | {s.get('openalex_id') or ''} "
                     f"| {s.get('method')} | {s.get('score')} | {status} |")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- fetching

def fetch_works(client, sources: list[dict], from_date: str, to_date: str,
                keyword_query: str, extra: dict | None = None, limit: int = 3000) -> list[dict]:
    plain = [s for s in sources if s.get("ok") and not s["keyword_filter"]]
    keyed = [s for s in sources if s.get("ok") and s["keyword_filter"]]
    base = f"from_publication_date:{from_date},to_publication_date:{to_date},type:{WORK_TYPES}"
    out = []
    for i in range(0, len(plain), 40):
        ids = "|".join(s["openalex_id"] for s in plain[i:i + 40])
        out += client.paginate("/works", {"filter": f"{base},primary_location.source.id:{ids}",
                                          "select": WORK_FIELDS, **(extra or {})}, limit=limit)
    for s in keyed:
        out += client.paginate("/works", {"filter": f"{base},primary_location.source.id:{s['openalex_id']}",
                                          "search": keyword_query, "select": WORK_FIELDS,
                                          **(extra or {})}, limit=500)
    return out


def fetch_rising(client, sources: list[dict], today: dt.date, window: list[int], top_n: int) -> list[dict]:
    lo, hi = window
    pool = [s for s in sources if s.get("ok") and not s["keyword_filter"]]
    works = fetch_works(client, pool, (today - dt.timedelta(days=hi)).isoformat(),
                        (today - dt.timedelta(days=lo)).isoformat(), "",
                        extra={"sort": "cited_by_count:desc"}, limit=200)
    for w in works:
        pub = dt.date.fromisoformat(w["publication_date"])
        months = max((today - pub).days / 30.4, 1.0)
        w["_velocity"] = round(w.get("cited_by_count", 0) / months, 2)
    works.sort(key=lambda w: w["_velocity"], reverse=True)
    return works[:top_n]


def attach_author_stats(client, items: list[dict]) -> None:
    ids = sorted({a for it in items for a in it["author_ids"]})
    stats = {}
    for i in range(0, len(ids), 50):
        page = client.get("/authors", {"filter": "openalex_id:" + "|".join(ids[i:i + 50]),
                                       "select": "id,summary_stats", "per_page": 50})
        for a in page.get("results", []):
            stats[short_id(a["id"])] = (a.get("summary_stats") or {}).get("h_index", 0)
    for it in items:
        hs = [stats.get(a, 0) for a in it["author_ids"]]
        it["max_author_h_index"] = max(hs) if hs else 0


# ---------------------------------------------------------------- shaping

def to_item(w: dict, source_lookup: dict) -> dict:
    loc = w.get("primary_location") or {}
    src = loc.get("source") or {}
    meta = source_lookup.get(short_id(src.get("id")), {})
    authors, insts, author_ids = [], [], []
    for a in w.get("authorships", [])[:12]:
        author = a.get("author") or {}
        authors.append(author.get("display_name", ""))
        author_ids.append(short_id(author.get("id")))
        for inst in a.get("institutions", [])[:1]:
            insts.append(inst.get("display_name", ""))
    abstract = abstract_from_index(w.get("abstract_inverted_index"))
    return {
        "id": short_id(w["id"]),
        "doi": w.get("doi"),
        "title": w.get("display_name") or "",
        "abstract": abstract[:2500],
        "missing_abstract": not abstract,
        "authors": [a for a in authors if a],
        "institutions": sorted({i for i in insts if i}),
        "author_ids": [a for a in author_ids if a],
        "date": w.get("publication_date"),
        "type": w.get("type"),
        "language": w.get("language"),
        "source": meta.get("name") or src.get("display_name"),
        "source_kind": meta.get("kind", "unknown"),
        "tier": meta.get("tier"),
        "tier_label": TIER_LABELS.get(meta.get("tier"), ""),
        "url": w.get("doi") or loc.get("landing_page_url") or w["id"],
        "cited_by_count": w.get("cited_by_count", 0),
    }


def dedupe(items: list[dict], seen: dict) -> list[dict]:
    """Drop items seen in earlier weeks, and collapse same-title duplicates this week
    (keeping the journal version over a working paper)."""
    seen_ids, seen_titles = set(seen.get("ids", [])), set(seen.get("titles", []))
    by_title: dict[str, dict] = {}
    for it in items:
        key = norm(it["title"])
        if not key or it["id"] in seen_ids or key in seen_titles:
            continue
        prev = by_title.get(key)
        if prev is None or (prev["source_kind"] != "journal" and it["source_kind"] == "journal"):
            by_title[key] = it
    return list(by_title.values())


def interest_chunks(text: str) -> list[str]:
    return [ln.strip("- ").strip() for ln in text.splitlines()
            if ln.strip().startswith("- ") and len(ln.strip()) > 10]


def prefilter(items: list[dict], interests_text: str, keep: int) -> tuple[list[dict], list[dict]]:
    """Crude lexical screen so the scorer sees a manageable list. Similarity is the max
    cosine between an item and any single interest bullet. Not a relevance judgment."""
    if not items:
        return [], []
    chunks = interest_chunks(interests_text) or [interests_text]
    docs = [f"{it['title']} {it['title']} {it['abstract']}" for it in items]
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
    mat = vec.fit_transform(chunks + docs)
    sims = cosine_similarity(mat[len(chunks):], mat[:len(chunks)]).max(axis=1)
    for it, s in zip(items, sims):
        boost = 0.02 if it.get("tier") in (1, 3) else 0.0
        it["prefilter_score"] = round(float(s) + boost, 4)
    ranked = sorted(items, key=lambda it: it["prefilter_score"], reverse=True)
    return ranked[:keep], ranked[keep:]


def compact(it: dict) -> dict:
    return {k: it[k] for k in ("id", "title", "authors", "source", "tier_label", "url", "date")}


# ---------------------------------------------------------------- main

def run(today: dt.date, client, root: Path = ROOT) -> dict:
    cfg = yaml.safe_load((root / "config/sources.yaml").read_text())
    interests = (root / "config/interests.md").read_text()
    data = root / "data"
    (data / "weekly").mkdir(parents=True, exist_ok=True)

    sources = resolve_sources(cfg, client, root / "config/resolved_sources.json")
    write_resolution_report(sources, data / "resolution_report.md")
    lookup = {s["openalex_id"]: s for s in sources if s.get("ok")}

    from_date = (today - dt.timedelta(days=cfg.get("lookback_days", 14))).isoformat()
    raw = fetch_works(client, sources, from_date, today.isoformat(), cfg.get("keyword_query", ""))
    seen_path = data / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {"ids": [], "titles": []}
    items = dedupe([to_item(w, lookup) for w in raw], seen)

    candidates, rest = prefilter(items, interests, cfg.get("prefilter_keep", 80))
    rising = [to_item(w, lookup) | {"velocity_per_month": w["_velocity"]}
              for w in fetch_rising(client, sources, today, cfg.get("rising_window_days", [90, 365]),
                                    cfg.get("rising_top_n", 15))]
    attach_author_stats(client, candidates + rising)

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "week_of": today.isoformat(),
        "window": {"from": from_date, "to": today.isoformat()},
        "counts": {"raw": len(raw), "new_after_dedupe": len(items), "candidates": len(candidates),
                   "other": len(rest), "rising": len(rising),
                   "missing_abstract": sum(it["missing_abstract"] for it in items),
                   "unresolved_sources": [s["name"] for s in sources if not s.get("ok")],
                   "api_calls": getattr(client, "calls", None)},
        "candidates": candidates,
        "rising": rising,
        "other": [compact(it) for it in rest],
    }
    text = json.dumps(out, indent=1, ensure_ascii=False)
    (data / "weekly" / f"{today.isoformat()}.json").write_text(text)
    (data / "latest.json").write_text(text)

    # Append in arrival order and keep the most recent ~50 weeks.
    seen["ids"] = (seen["ids"] + [it["id"] for it in items])[-25000:]
    seen["titles"] = (seen["titles"] + [norm(it["title"]) for it in items])[-25000:]
    seen_path.write_text(json.dumps(seen))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="override run date (YYYY-MM-DD)")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    out = run(today, OpenAlexClient(os.environ.get("OPENALEX_API_KEY")))
    print(json.dumps(out["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
