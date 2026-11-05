"""Offline tests: a fake OpenAlex client stands in for the API."""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
import collect  # noqa: E402


def inv(text):
    out = {}
    for i, w in enumerate(text.split()):
        out.setdefault(w, []).append(i)
    return out


def work(wid, title, abstract, source_id, date="2026-11-01", cites=0, author="A1"):
    return {
        "id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/10.1/{wid}",
        "display_name": title, "publication_date": date, "type": "article", "language": "en",
        "authorships": [{"author": {"id": f"https://openalex.org/{author}", "display_name": "Ana Pérez"},
                         "institutions": [{"display_name": "Universidad de Chile"}]}],
        "abstract_inverted_index": inv(abstract) if abstract else None,
        "primary_location": {"source": {"id": f"https://openalex.org/{source_id}", "display_name": "X"}},
        "cited_by_count": cites,
    }


class FakeClient:
    calls = 0

    def __init__(self, new_works, rising_works):
        self.new_works, self.rising_works = new_works, rising_works

    def get(self, path, params=None):
        self.calls += 1
        if path.startswith("/sources/issn:"):
            issn = path.split(":", 1)[1]
            if issn == "0020-8183":
                return {"id": "https://openalex.org/S1", "display_name": "International Organization"}
            if issn == "0969-2290":  # wrong title returned: must fall back to search
                return {"id": "https://openalex.org/S999", "display_name": "Some Other Journal"}
            return {}
        if path == "/sources":
            q = params["search"]
            if q == "Review of International Political Economy":
                return {"results": [{"id": "https://openalex.org/S2",
                                     "display_name": "Review of International Political Economy",
                                     "works_count": 3000}]}
            if q == "NBER Working Paper":
                return {"results": [{"id": "https://openalex.org/S3", "display_name": "NBER Working Paper Series",
                                     "works_count": 30000}]}
            if q == "SSRN Electronic Journal":
                return {"results": [{"id": "https://openalex.org/S4", "display_name": "SSRN Electronic Journal",
                                     "works_count": 900000}]}
            return {"results": []}
        if path == "/authors":
            return {"results": [{"id": "https://openalex.org/A1", "summary_stats": {"h_index": 31}}]}
        return {}

    def paginate(self, path, params, limit=2000):
        self.calls += 1
        if "sort" in params:
            return [dict(w) for w in self.rising_works]
        if "search" in params:  # keyword-filtered SSRN pull
            return [w for w in self.new_works if w["primary_location"]["source"]["id"].endswith("S4")]
        return [w for w in self.new_works if not w["primary_location"]["source"]["id"].endswith("S4")]


def setup_root(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/sources.yaml").write_text("""
lookback_days: 14
rising_window_days: [90, 365]
rising_top_n: 2
prefilter_keep: 2
journals:
  - {name: "International Organization", issn: "0020-8183", tier: 1}
  - {name: "Review of International Political Economy", issn: "0969-2290", tier: 1}
  - {name: "Journal That Does Not Exist", issn: "1111-1111", tier: 2}
working_papers:
  - {name: "NBER", search: "NBER Working Paper", keyword_filter: false}
  - {name: "SSRN", search: "SSRN Electronic Journal", keyword_filter: true}
keyword_query: trade
""")
    shutil.copy(ROOT / "config/interests.md", tmp_path / "config/interests.md")
    return tmp_path


NEW = [
    work("W1", "Political trust and trade preferences in Latin America",
         "We show trust in leaders shapes trade attitudes among voters in Chile using a survey experiment.", "S1"),
    work("W2", "Monetary policy transmission in the euro area",
         "We estimate interest rate pass-through using bank data.", "S2"),
    work("W3", "Public opinion on foreign direct investment and multinationals",
         "Citizens evaluate FDI and supply chain relocation in a conjoint experiment.", "S3"),
    work("W4", "Political Trust and Trade Preferences in Latin America",  # WP duplicate of W1
         "Working paper version.", "S3"),
    work("W5", "Immigration attitudes and perceived fiscal burden", "", "S4"),  # no abstract
]
RISING = [
    work("R1", "Old but slow", "x", "S1", date="2026-03-01", cites=6),
    work("R2", "Fast riser", "x", "S2", date="2026-07-01", cites=20),
    work("R3", "Mid", "x", "S3", date="2026-05-01", cites=12),
]


def test_end_to_end(tmp_path):
    root = setup_root(tmp_path)
    out = collect.run(dt.date(2026, 11, 9), FakeClient(NEW, RISING), root=root)

    # resolution: issn ok, issn-mismatch falls back to search, missing journal unresolved
    res = json.loads((root / "config/resolved_sources.json").read_text())
    assert res["International Organization"]["method"] == "issn"
    assert res["Review of International Political Economy"]["openalex_id"] == "S2"
    assert res["Review of International Political Economy"]["method"] == "search"
    assert not res["Journal That Does Not Exist"]["ok"]
    assert out["counts"]["unresolved_sources"] == ["Journal That Does Not Exist"]
    assert "UNRESOLVED" in (root / "data/resolution_report.md").read_text()

    # dedupe: W4 collapses into W1 (journal version kept)
    ids = {c["id"] for c in out["candidates"]} | {o["id"] for o in out["other"]}
    assert ids == {"W1", "W2", "W3", "W5"}
    w1 = next(c for c in out["candidates"] if c["title"].startswith("Political trust"))
    assert w1["id"] == "W1" and w1["source_kind"] == "journal"

    # prefilter keeps 2 most relevant; monetary policy paper is not among them
    assert len(out["candidates"]) == 2
    assert "W2" not in {c["id"] for c in out["candidates"]}

    # abstracts reconstructed, missing flagged, author stats attached
    assert w1["abstract"].startswith("We show trust in leaders")
    assert out["counts"]["missing_abstract"] == 1
    assert all(c["max_author_h_index"] == 31 for c in out["candidates"])

    # rising: sorted by citations per month, top 2
    assert [r["id"] for r in out["rising"]] == ["R2", "R3"]

    # second run the same week: everything already seen
    out2 = collect.run(dt.date(2026, 11, 9), FakeClient(NEW, RISING), root=root)
    assert out2["counts"]["new_after_dedupe"] == 0
    assert (root / "data/latest.json").exists()


def test_abstract_order():
    assert collect.abstract_from_index({"b": [1], "a": [0], "c": [2, 3]}) == "a b c c"
