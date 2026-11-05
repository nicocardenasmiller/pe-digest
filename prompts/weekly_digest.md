# Weekly digest task prompt

Used as the instruction for the Monday scheduled task. Replace REPO_URL before creating the task, and DIGEST_URL after the first run publishes the page.

---

Build this week's political economy reading digest for Felix.

1. Clone REPO_URL and read `config/interests.md` and `data/latest.json`. If `week_of` in latest.json is more than 8 days old, the collector did not run: publish nothing, and send a short message saying the collector is stale and to check the GitHub Actions run.
2. Score every item in `candidates` from 0 to 10 for relevance to the interest statement. Core topics weigh most, then methods and data, then adjacent topics. Judge from title and abstract; `prefilter_score` is a crude lexical screen, not a relevance judgment, so do not defer to it. Items with `missing_abstract: true` are scored on title only and marked as such.
3. Build the page with four sections:
   - **Flagged for you**: items scoring 7 or higher, at most 15, highest first. For each: title linked to `url`, authors, source, date, and one plain sentence on why it matches, naming the specific interest it touches.
   - **High-signal in the field**: up to 5 candidates or `other` items from Tier 1 or Tier 2 venues, or with `max_author_h_index` of 40 or more, that are not already flagged. One line each on why it matters to CPE or IPE broadly.
   - **Rising**: the `rising` list, with citations per month (`velocity_per_month`) shown.
   - **Everything else**: all remaining candidates and `other` items as title links, grouped by source, collapsed by default.
4. Header: week of `week_of`, the counts from `counts`, and any `unresolved_sources` listed as a warning.
5. Writing: plain and direct, no praise or hype, no em dashes. Do not invent details absent from the data.
6. Publish as an HTML artifact. If DIGEST_URL is set, update that artifact in place and keep last week's flagged list in a collapsed "Previous week" section at the bottom. If DIGEST_URL is not set, publish a new artifact and report its URL in your final message.
7. Send a short message: number of flagged items and the top three titles.
