# pe-digest

Weekly collector for a comparative and international political economy reading digest.

1. **Collect (GitHub Actions, Sundays 22:17 UTC).** `collector/collect.py` pulls new items from OpenAlex for the journals and working paper series in `config/sources.yaml`, finds rising papers (3 to 12 months old, ranked by citations per month), attaches author h-index, drops anything seen in earlier weeks, runs a lexical prefilter against `config/interests.md`, and commits `data/latest.json`.
2. **Score and publish (Claude scheduled task, Monday mornings).** Reads `data/latest.json`, judges relevance against `config/interests.md`, and updates the digest page.

## Setup

1. Push this folder to a GitHub repository.
2. Optional: get a free OpenAlex API key and add it as the repository secret `OPENALEX_API_KEY` (Settings > Secrets and variables > Actions).
3. Run the workflow once by hand (Actions > Weekly collect > Run workflow).
4. Open `data/resolution_report.md` and fix any row marked UNRESOLVED or matched to the wrong source by editing `config/sources.yaml` (correct the ISSN or the search string), then delete that entry from `config/resolved_sources.json` and rerun.

## Editing

- Interests: edit `config/interests.md`. Bullet lines are what the prefilter matches against.
- Sources: edit `config/sources.yaml`. `prefilter_keep` controls how many candidates reach the scorer.

## Known limits

- OpenAlex indexes some items days to weeks after publication. The 14-day lookback plus deduplication covers most of the lag.
- Items without abstracts in OpenAlex are scored on title only and flagged `missing_abstract`.
- SSRN, SocArXiv and arXiv are restricted by `keyword_query` to keep volume manageable, so off-keyword papers there are missed.
- CEPAL documents and conference programs are not covered.

## Tests

```
pip install -r requirements.txt
python -m pytest -q tests
```
