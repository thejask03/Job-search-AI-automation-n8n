# Setup

The committed workflow has every instance-specific value replaced with a placeholder. Importing it will not
work until you supply your own — that is by design.

## 1. Import

n8n → **Workflows** → **Import from File** → `workflow/job-search-automation.json`.

All 31 nodes load with the graph intact, and every credential slot shows as unset. That unset state is
expected; it means the export was scrubbed properly.

## 2. Create the eight credentials

Each node's credential dropdown is labelled with the name below, so you can match them up by name.

| Credential type | Name in the workflow | Used by |
|---|---|---|
| Apify OAuth2 | `Apify account` | LinkedIn, YC ×2, Wellfound scrapers |
| Google Sheets OAuth2 | `Google Sheets account` | tracker read + append/update |
| Gmail OAuth2 | `Gmail account` | inbound trigger, send, mark-as-read |
| Google Gemini (PaLM) API | `Google Gemini(PaLM) Api account` | scoring, email draft, reply classifier |
| Anthropic API | `Anthropic account` | resume + cover letter tailoring |
| Telegram API | `Telegram account` | submission and recruiter alerts |
| Google Drive OAuth2 | `Google Drive account` | master resume download + tailored PDF upload |
| HTTP Custom Auth | `Custom Auth account` | the `texapi.ovh` LaTeX compiler |

## 3. Replace the placeholders

| Placeholder | What to put there |
|---|---|
| `YOUR_GOOGLE_SHEET_ID` | The document ID of your tracker sheet (from its URL). 9 occurrences. |
| `YOUR_DRIVE_FOLDER_ID` | The Drive folder that tailored resumes get uploaded into. |
| `YOUR_RESUME_FILE_ID` | The Drive file ID of your **master LaTeX resume**, uploaded as a plain `.tex` file (not a Google Doc — the download node does no export conversion). `Google Drive (Get Master Resume)` fetches it on every accepted job and it is what Claude edits. |
| `YOUR_TELEGRAM_CHAT_ID` | Your Telegram chat ID — message `@userinfobot` to find it. |
| `your-email@example.com` | The address the application email is sent to. |
| `YOUR_*_CREDENTIAL_ID` | Set by picking the credential in the node UI; do not type these in by hand. |
| `YOUR_N8N_INSTANCE_ID` | Leave it. n8n overwrites `meta.instanceId` on import. |

Easiest path is to open each Google Sheets / Drive / Telegram / Gmail node and re-pick the resource from its
dropdown, which rewrites both the ID and n8n's cached display name together.

## 4. Prepare the tracker sheet

Create a Google Sheet named `Job_Tracker` with a tab called `Applications`. It is keyed on a **`Job_ID`**
column, which must exist for the inbound branch's `appendOrUpdate` to match rows. The workflow also reads
and writes `Resume_URL` among other columns — run the outbound branch once and let it append a row to see
the full set.

## 5. Check the ATS board tokens

`Target Companies (ATS Boards)1` holds a hand-verified list of company tokens, with comments explaining why
certain companies were excluded. Before adding one, confirm it resolves:

- `boards.greenhouse.io/<token>`
- `jobs.lever.co/<token>`
- `jobs.ashbyhq.com/<token>`

Keep the `c.token !== '<<ADD_TOKEN>>'` placeholder filter in place — it is what stops unverified entries from
reaching the HTTP loop.

## 6. Run it manually first

The workflow ships `active: false`. Execute the outbound branch by hand and read what it produces before
enabling the `0 8 * * *` cron — it sends email and writes to your sheet on every run.

Note the [known limitations](../README.md#known-limitations) first: as shipped, the application email goes to
your own address with no PDF attached, so a manual run is safe to inspect.
