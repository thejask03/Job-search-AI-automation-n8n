# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A single exported **n8n workflow** — `workflow/job-search-automation.json` — not an application. There is no build, no package manager, and no test suite. All "code" lives inside `jsCode` fields of `n8n-nodes-base.code` nodes and inside `=`-prefixed n8n expressions in node parameters.

The committed JSON is **sanitized output**: every instance-specific value (Sheet/Drive/Telegram IDs, the operator's email, credential IDs) is a `YOUR_*` placeholder. The personal copy lives at `.local/workflow.raw.json`, which is gitignored. After changing anything in n8n, re-export to that path and run `python scripts/sanitize_workflow.py` to regenerate the committed file — never hand-edit it, and never commit a raw export.

Editing means editing JSON, then re-importing into n8n (Workflows → Import from File) to run it. Node `parameters.jsCode` strings are `\n`-escaped JavaScript; when changing more than a token or two, prefer a script that loads the JSON, mutates the node, and dumps it back with `json.dump(..., indent=2, ensure_ascii=False)` over hand-editing escaped strings.

Inspect the graph without opening n8n:

```bash
python -c "import json;d=json.load(open('workflow/job-search-automation.json',encoding='utf-8'));[print(n['type'],'|',n['name']) for n in d['nodes']]"
```

## Architecture

Two independent trigger branches share one Google Sheet (`Job_Tracker`, tab `Applications`, keyed on `Job_ID`).

**Outbound (daily cron `0 8 * * *`)** — Schedule Trigger fans out to six parallel sources, five of which land on `Merge Job Sources1` (a 5-input merge):

| Merge input | Source |
|---|---|
| 0 | Apify LinkedIn scraper (`Apify Actor (Job Boards)1`) |
| 1 | Direct ATS pulls → `Target Companies (ATS Boards)1` → HTTP loop → `Code Node (Normalize ATS Jobs)1` |
| 2 | Existing tracker rows → `Code Node (Tag Seen Job IDs)1` (tagged `_seen: true`) |
| 3 | Two YC Apify runs (SWE + DS) → `Code Node (Tag YC Jobs)1` |
| 4 | Wellfound Apify run → `Code Node (Flatten Wellfound Jobs)1` |

Then: `Code Node (Deduplication & Hash)1` → regex prefilter → Gemini scoring → threshold filter → `Google Drive (Get Master Resume)` → `Extract Master Resume Text` → Gemini email draft → Claude tailoring → `LaTeX to PDF Compiler1`, which fans out to **both** `Gmail (Send Application)1` (PDF attached) and `Google Drive (Save PDF)1` → `Set (Tracker Row)` → tracker append, plus a Telegram alert.

The tailoring input is the operator's **master resume**, held as a PDF file in Drive (`YOUR_RESUME_FILE_ID`). `Google Drive (Get Master Resume)` downloads it to binary `data`; `Extract Master Resume Text` (`operation: pdf`) turns that into `$json.master_resume_text`, plain text with no LaTeX markup, which both the Claude and Gemini prompts interpolate. Claude writes the LaTeX (including the preamble) from scratch each time, constrained to the facts in that text. Without that pair the tailoring node has no resume to edit and Claude invents one — which is exactly what the workflow used to do.

**Inbound (Gmail trigger, polls every minute, unread INBOX)** — spam/newsletter blacklist code node → Gemini classifier (`jsonOutput: true`) → `appendOrUpdate` on the tracker matched by `Job_ID` → Telegram alert → mark the message read (that last step is what prevents reprocessing).

### Key invariants

- **The `_seen` tag is the dedup contract.** Prior tracker rows enter the merge alongside fresh listings; `Code Node (Deduplication & Hash)1` splits them by `data._seen`, collects their `job_id` into a seen-set, and drops matching new jobs. Removing the seen-IDs branch silently re-applies to every job every day.
- **`job_id` is a non-crypto djb2-style hash of `company_title`, lowercased** (`'job_' + Math.abs(hash).toString(16)`). It must be computed identically anywhere else it is derived, or dedup and the sheet's `Job_ID` matching both break.
- **Every downstream node reads job fields via `$('Code Node (Deduplication & Hash)1').item.json...`**, not `$json`, because Claude/Gemini/Drive nodes replace the item payload. Renaming that node requires updating ~8 expressions.
- Each source's own code node normalizes to the common shape `{title, company, url, description, location, source_platform}` before the merge; the dedup node then applies fallbacks for shapes it hasn't seen (`absolute_url`/`hostedUrl`, `content`, nested `location.name`).
- The ATS branch is index-coupled: `Code Node (Normalize ATS Jobs)1` pairs `$input.all()[i]` with `$('Target Companies (ATS Boards)1').all()[i]` to re-stamp the company, and the HTTP node sets `neverError: true` so failed boards come back as `{error}` items rather than aborting the run. Keep both properties in sync.
- ATS board tokens in `Target Companies (ATS Boards)1` are hand-verified and commented with why companies were excluded; verify a new token against `boards.greenhouse.io/<token>` / `jobs.lever.co/<token>` / `jobs.ashbyhq.com/<token>` before adding, and keep the placeholder filter (`c.token !== '<<ADD_TOKEN>>'`).

### Models and thresholds

- Gemini `models/gemini-2.5-pro` scores relevance; `gemini-2.5-flash` drafts the email; `models/gemini-pro-latest` classifies recruiter replies. All use `jsonOutput: true` and prompts that end with `Return ONLY JSON: {...}` — changing the prompt's JSON shape breaks the filter/expressions that consume it.
- Claude `claude-sonnet-5` writes the LaTeX resume from scratch each run, grounded in the master PDF's extracted text (`master_resume_text`). Its prompt forbids inventing experience, employers, degrees, dates or metrics absent from the source — that constraint is the only thing keeping the output truthful, so do not soften it. `options.maxTokens` is 8000 because a full resume truncates under the default.
- The acceptance gate is `score >= 75 AND meets_criteria === true AND salary_inr_lpa >= 30`, with `typeValidation: strict` — the Gemini output must be a real number/boolean, not a string. The upstream regex filter also hard-excludes senior titles and restricts to India/remote.

### Known rough edges (do not "fix" silently — confirm intent first)

- `Gmail (Send Application)1` sends to the operator's own address (`your-email@example.com` in the committed file), i.e. the workflow is in review mode rather than actually applying.
- There is no cover letter. The Gemini-drafted email body is the cover note; the old `Claude AI (Tailor Cover Letter)1` node was removed.
- `Gmail (Send Application)1` and `Google Drive (Save PDF)1` both hang directly off `LaTeX to PDF Compiler1` rather than in series, because each drops binary from its own output and both need the PDF. Putting them back in a chain silently un-attaches the file.
- The workflow ships with `active: false` and `binaryMode: separate`.

### Credentials (referenced by ID; must exist in the target n8n instance)

Apify OAuth2, Google Sheets OAuth2, Gmail OAuth2, Google Drive, Google Gemini (PaLM) API, Anthropic API, Telegram, and an HTTP custom-auth credential for the LaTeX compiler. In the committed file these are all `YOUR_*_CREDENTIAL_ID` placeholders, as are the Sheet, Drive folder, and Telegram chat IDs — see `docs/SETUP.md` for what a fresh import has to remap.
