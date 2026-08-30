# Job Search AI Automation (n8n)

An end-to-end n8n workflow that finds relevant job listings across six sources every morning, scores them
with an LLM, tailors your master resume for the ones that pass, emails the application, logs it to a
Google Sheet, and then classifies recruiter replies as they land in Gmail.

This repo is a single exported workflow — [`workflow/job-search-automation.json`](workflow/job-search-automation.json),
31 nodes. There is no build and no runtime here; the "code" lives inside the `jsCode` fields of Code nodes
and in `=`-prefixed n8n expressions. See [`docs/SETUP.md`](docs/SETUP.md) to run it.

## Architecture

Two independent trigger branches share one Google Sheet (`Job_Tracker`, tab `Applications`, keyed on `Job_ID`).

### Outbound — daily cron `0 8 * * *`

A Schedule Trigger fans out to six sources, five of which land on a 5-input merge:

| Merge input | Source |
|---|---|
| 0 | Apify LinkedIn scraper |
| 1 | Direct ATS pulls (Greenhouse / Lever / Ashby) → HTTP loop → normalizer |
| 2 | Existing tracker rows, tagged `_seen: true` |
| 3 | Two YC Apify runs (SWE + DS) |
| 4 | Wellfound Apify run |

Each source normalizes to a common shape — `{title, company, url, description, location, source_platform}` —
before the merge. From there:

```
Merge → Dedup & Hash → regex prefilter → Gemini scoring → threshold filter
      → Claude tailoring → LaTeX→PDF → Drive → Gemini email draft → Gmail send
      → tracker append + Telegram alert
```

### Inbound — Gmail trigger, polls unread INBOX every minute

```
spam/newsletter blacklist → Gemini classifier → Sheets appendOrUpdate (matched on Job_ID)
      → Telegram alert → mark message read
```

Marking the message read is what prevents reprocessing — it is the branch's idempotency mechanism, not a
cosmetic final step.

## How it decides

- **Relevance scoring** — Gemini `models/gemini-2.5-pro`, `jsonOutput: true`.
- **Acceptance gate** — `score >= 75 AND meets_criteria === true AND salary_inr_lpa >= 30`, with
  `typeValidation: strict`, so the model's output must be a real number/boolean rather than a string.
- **Prefilter** — a regex filter ahead of the LLM hard-excludes senior titles and restricts to India/remote,
  so scoring spend goes only to plausible roles.
- **Tailoring** — Claude `claude-sonnet-5` edits the master LaTeX resume pulled from Drive against the
  job description, under an instruction not to invent anything absent from the source.
- **Email draft** — Gemini `gemini-2.5-flash`. **Recruiter-reply classification** — `models/gemini-pro-latest`.

## Two invariants worth knowing before editing

**The `_seen` tag is the dedup contract.** Prior tracker rows are fed into the merge alongside fresh
listings. The dedup node splits items on `data._seen`, collects those `job_id`s into a seen-set, and drops
matching new jobs. Delete the seen-IDs branch and the workflow silently re-applies to every job, every day.

**Nodes are addressed by name.** Because the Claude, Gemini, and Drive nodes replace the item payload,
every downstream node reads job fields via `$('Code Node (Deduplication & Hash)1').item.json...` rather than
`$json`. Renaming that node breaks roughly eight expressions at once, and n8n will not warn you.

Related: `job_id` is a non-cryptographic djb2-style hash of `company_title` lowercased
(`'job_' + Math.abs(hash).toString(16)`). Anywhere else it gets derived, it must be computed identically or
both dedup and the sheet's `Job_ID` matching break.

## Known limitations

These are real and tracked as issues, not oversights:

1. Both Claude nodes feed the LaTeX compiler on the same input, so the cover letter — plain prose, not
   LaTeX — is POSTed to `texapi.ovh` as if it were LaTeX source.
2. The Gmail send node's `attachmentsBinary` entry is empty, so the tailored PDF is never actually attached.
3. That same node sends to the operator's own address. The workflow is in review mode: it drafts and shows
   you the application rather than submitting it.

The workflow also ships `active: false` by design — import it, bind credentials, and run it manually before
letting a cron loose on your inbox.

## Repo layout

```
workflow/job-search-automation.json   the workflow (sanitized; import this)
scripts/sanitize_workflow.py          regenerates the above from a personal export
docs/SETUP.md                         credentials and placeholders to fill in
CLAUDE.md                             working notes for Claude Code
```

The committed JSON is generated output. After changing anything in n8n, re-export to
`.local/workflow.raw.json` (gitignored) and run `python scripts/sanitize_workflow.py` — don't hand-edit the
committed file.

## License

MIT — see [LICENSE](LICENSE).
