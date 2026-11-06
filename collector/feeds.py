"""Direct working-paper feeds that OpenAlex does not cover well.

Each fetcher returns (items, status) where items use the same shape as
collect.to_item and status is a short string for data/diagnostics.md.
Fetchers never raise: a broken feed is reported, not fatal.

Sources:
- NEP (RePEc New Economics Papers): weekly, editor-curated field reports that
  pick up NBER, CEPR, IZA, CESifo, IDB, central bank and university series.
  Tries the report's RSS feed, then the IDEAS issue pages.
- NBER new working papers: RSS feed, then the site's JSON listing.
- SocArXiv: OSF preprints API.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "pe-digest/1.0 (weekly reading list; github.com/nicocardenasmiller/pe-digest)"}
NS = {"dc": "http://purl.org/dc/elements/1.1/", "rss1": "http://purl.org/rss/1.0/",
      "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "atom": "http://www.w3.org/2005/Atom"}


def _get(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _clean(s: str | None) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


def _date(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else None


def _item(title, url, abstract="", authors=None, date=None, source="", ident=None) -> dict:
    abstract = _clean(abstract)
    return {
        "id": ident or "U" + hashlib.sha1((url or title).encode()).hexdigest()[:14],
        "doi": None, "title": _clean(title), "abstract": abstract[:2500],
        "missing_abstract": not abstract, "authors": authors or [], "institutions": [],
        "author_ids": [], "date": date, "type": "preprint", "language": None,
        "source": source, "source_kind": "working_paper", "keyword_source": False,
        "tier": 5, "tier_label": "Working paper", "url": url, "cited_by_count": 0,
    }


def parse_rss(raw: bytes, source: str) -> list[dict]:
    """RSS 2.0, RSS 1.0 (RDF) and Atom."""
    root = ET.fromstring(raw)
    out = []
    entries = root.findall(".//item") + root.findall(".//rss1:item", NS) + root.findall(".//atom:entry", NS)
    for e in entries:
        def t(*paths):
            for p in paths:
                el = e.find(p, NS)
                if el is not None and (el.text or el.get("href")):
                    return el.text or el.get("href")
            return ""
        title = t("title", "rss1:title", "atom:title")
        url = t("link", "rss1:link", "atom:link")
        desc = t("description", "rss1:description", "atom:summary", "atom:content")
        date = _date(t("pubDate", "dc:date", "atom:updated", "atom:published"))
        authors = [a.text.strip() for a in e.findall("dc:creator", NS) + e.findall("author") if a.text]
        if len(authors) == 1 and ("," in authors[0] or " and " in authors[0]):
            authors = [a.strip() for a in re.split(r",| and ", authors[0]) if a.strip()]
        if title:
            out.append(_item(title, url, desc, authors, date, source))
    return out


# ---------------------------------------------------------------- NEP

def fetch_nep(code: str, name: str, since: dt.date) -> tuple[list[dict], str]:
    source = f"NEP {name}"
    try:
        items = parse_rss(_get(f"https://nep.repec.org/rss/{code}.rss.xml"), source)
        fresh = [i for i in items if not i["date"] or i["date"] >= since.isoformat()]
        if fresh:
            return fresh, f"rss ok ({len(items)} in feed, {len(fresh)} in window)"
        rss_note = f"rss returned {len(items)} items, none in window"
    except Exception as e:  # noqa: BLE001
        rss_note = f"rss failed ({type(e).__name__})"
    try:
        items = _nep_from_ideas(code, since, source)
        return items, f"{rss_note}; IDEAS pages ok ({len(items)} items)"
    except Exception as e:  # noqa: BLE001
        return [], f"{rss_note}; IDEAS pages failed ({type(e).__name__}: {str(e)[:80]})"


def _nep_from_ideas(code: str, since: dt.date, source: str) -> list[dict]:
    """IDEAS lists each NEP issue at ideas.repec.org/n/<code>/YYYY-MM-DD.html."""
    index = _get(f"https://ideas.repec.org/n/{code}/").decode("utf-8", "replace")
    dates = sorted(set(re.findall(rf"/n/{code}/(\d{{4}}-\d{{2}}-\d{{2}})\.html", index)), reverse=True)
    dates = [d for d in dates if d >= since.isoformat()][:3]
    out = []
    for d in dates:
        page = _get(f"https://ideas.repec.org/n/{code}/{d}.html").decode("utf-8", "replace")
        # Each paper is a link to /p/... (working paper) with its title as link text.
        for href, title in re.findall(r'<a href="(/p/[^"]+)"[^>]*>(.*?)</a>', page, flags=re.S):
            title = _clean(title)
            if len(title) > 15:
                out.append(_item(title, "https://ideas.repec.org" + href, "", [], d, source,
                                 ident="R" + re.sub(r"[^A-Za-z0-9]", "", href)[-40:]))
    seen, uniq = set(), []
    for it in out:
        if it["url"] not in seen:
            seen.add(it["url"])
            uniq.append(it)
    return uniq


# ---------------------------------------------------------------- NBER

def fetch_nber(since: dt.date) -> tuple[list[dict], str]:
    notes = []
    for url in ("https://back.nber.org/rss/new.xml", "https://www.nber.org/rss/new.xml"):
        try:
            items = parse_rss(_get(url), "NBER Working Papers")
            fresh = [i for i in items if not i["date"] or i["date"] >= since.isoformat()]
            if items:
                return fresh, f"rss ok via {url} ({len(items)} in feed, {len(fresh)} kept)"
            notes.append(f"{url}: empty")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{url}: {type(e).__name__}")
    try:
        api = ("https://www.nber.org/api/v1/working_page_listing/contentType/working_paper/_/_/search"
               "?page=1&perPage=100&sortBy=public_date")
        data = json.loads(_get(api))
        out = []
        for r in data.get("results", []):
            date = _date(r.get("displaydate") or "")
            if date and date < since.isoformat():
                continue
            authors = [_clean(a) for a in r.get("authors", [])]
            url = r.get("url", "")
            out.append(_item(r.get("title", ""), "https://www.nber.org" + url if url.startswith("/") else url,
                             r.get("abstract", ""), authors, date, "NBER Working Papers"))
        return out, "; ".join(notes) + f"; JSON listing ok ({len(out)} items)"
    except Exception as e:  # noqa: BLE001
        return [], "; ".join(notes) + f"; JSON listing failed ({type(e).__name__})"


# ---------------------------------------------------------------- SocArXiv

def fetch_socarxiv(since: dt.date, max_pages: int = 5) -> tuple[list[dict], str]:
    params = {"filter[provider]": "socarxiv", "filter[date_created][gte]": since.isoformat(),
              "page[size]": "100", "sort": "-date_created"}
    url = "https://api.osf.io/v2/preprints/?" + urllib.parse.urlencode(params)
    out = []
    try:
        for _ in range(max_pages):
            data = json.loads(_get(url))
            for r in data.get("data", []):
                a = r.get("attributes", {})
                link = (r.get("links") or {}).get("html") or f"https://osf.io/preprints/socarxiv/{r.get('id')}"
                it = _item(a.get("title", ""), link, a.get("description", ""), [],
                           _date(a.get("date_published") or a.get("date_created")), "SocArXiv",
                           ident="O" + str(r.get("id")))
                it["keyword_source"] = True
                it["tags"] = a.get("tags", [])
                out.append(it)
            url = (data.get("links") or {}).get("next")
            if not url:
                break
        return out, f"OSF API ok ({len(out)} items)"
    except Exception as e:  # noqa: BLE001
        return out, f"OSF API failed ({type(e).__name__}: {str(e)[:80]})"


def keyword_match(it: dict, terms: list[str]) -> bool:
    text = f"{it['title']} {it['abstract']} {' '.join(it.get('tags', []))}".lower()
    return any(t in text for t in terms)


def fetch_all(cfg: dict, today: dt.date) -> tuple[list[dict], list[tuple[str, int, str]]]:
    fc = cfg.get("feeds", {})
    since = today - dt.timedelta(days=cfg.get("lookback_days", 14))
    items, report = [], []
    for rep in fc.get("nep", []):
        got, status = fetch_nep(rep["code"], rep["name"], since)
        items += got
        report.append((f"NEP {rep['name']} ({rep['code']})", len(got), status))
    if fc.get("nber", True):
        got, status = fetch_nber(since)
        items += got
        report.append(("NBER Working Papers", len(got), status))
    if fc.get("socarxiv", True):
        got, status = fetch_socarxiv(since)
        terms = [t.lower() for t in fc.get("socarxiv_terms", [])]
        kept = [i for i in got if keyword_match(i, terms)] if terms else got
        items += kept
        report.append(("SocArXiv", len(kept), f"{status}; {len(kept)} matched keywords"))
    return items, report
