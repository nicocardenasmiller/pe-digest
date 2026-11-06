# Weekly digest task prompt

This is the instruction for the Monday scheduled task. DIGEST_URL is the published digest page: https://claude.ai/artifact/XfapVjSksb5yDXNtQ6ghs4

---

Build this week's political economy reading digest for Felix and update the existing digest page.

Repository: https://github.com/nicocardenasmiller/pe-digest
Digest page: DIGEST_URL

1. Attach the repository with push access (add_repo, owner nicocardenasmiller, repo pe-digest, access push) and clone it. Read `config/interests.md`, `data/latest.json` and `data/diagnostics.md`.
2. If `week_of` in latest.json is more than 8 days old, the collector did not run. Do not update the page. Send a short message saying the collector is stale and to check the Actions tab of the repository.
3. Score every item in `candidates` from 0 to 10 for relevance to the interest statement. Core topics weigh most, then methods and data, then adjacent topics. Judge from title and abstract; `prefilter_score` is a crude lexical screen, so do not defer to it. Also read the titles in `other`, since the prefilter misses relevant items, and score any that look relevant. Items with `missing_abstract: true` are scored on title only.
4. Write `data/scores/<week_of>.json` in the format documented at the top of `digest/render.py`:
   - `flagged`: items scoring 7 or higher, at most 15, highest first, each with one plain sentence naming the specific interest it touches. Say so when a paper is US only or outside Latin America and that matters.
   - `high_signal`: up to 5 items not already flagged, from Tier 1 or Tier 2 venues or with `max_author_h_index` of 40 or more, each with one sentence on why it matters to CPE or IPE broadly.
   - `near_misses`: items scoring 5 or 6, ids and scores only.
   - `notes`: one or two sentences only if something about this week's data needs saying, such as a source returning nothing in diagnostics.md. Otherwise omit.
   Write plainly. No praise or hype, no em dashes, and nothing that is not in the data.
5. Render: `python digest/render.py data/scores/<week_of>.json /tmp/digest.html --previous <the most recent earlier file in data/scores/>`.
6. Publish `/tmp/digest.html` with the Artifact tool, passing `url` DIGEST_URL so the existing page is updated in place. Read the artifact first if the publish asks for it.
7. Commit the scores file and push to main.
8. Send a short message: the number of flagged items and the top three titles.
