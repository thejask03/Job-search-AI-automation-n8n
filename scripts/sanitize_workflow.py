#!/usr/bin/env python3
"""Produce the committable workflow JSON from a personal n8n export.

n8n exports carry the operator's own Sheet/Drive/Telegram targets, their email,
the credential IDs of the instance that produced the export, and an instanceId.
None of that belongs in a public repo, and none of it is useful to someone
importing the workflow -- they have to supply their own anyway.

    python scripts/sanitize_workflow.py [RAW_EXPORT] [OUT]

Defaults: .local/workflow.raw.json -> workflow/job-search-automation.json

The values to scrub are *discovered* from the export, never hardcoded here --
this file is public, so a literal table of secrets in it would defeat the point.
Each is located structurally (the documentId of a Sheets node, the chatId of a
Telegram node, ...) and then replaced by plain string substitution across the
serialized JSON, so that copies living in n8n's resource-locator caches
(cachedResultUrl, cachedResultName) are caught too.

Re-run this after every re-export from n8n; never hand-edit the committed file.
The node graph, node names, jsCode bodies and connections are left untouched --
downstream expressions reference nodes by name, so renaming anything breaks the
workflow silently.
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_RAW = REPO / ".local" / "workflow.raw.json"
DEFAULT_OUT = REPO / "workflow" / "job-search-automation.json"

# Credential *names* are kept: they tell an importer which slot to bind. Only
# the IDs, which are meaningless outside the exporting instance, are replaced.
CREDENTIAL_ID_PLACEHOLDER = "YOUR_{}_CREDENTIAL_ID"

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Where each secret lives: node-type substring -> (parameter path, placeholder).
# A path element may be a dict key; resource-locator params are dicts carrying
# the id under "value", which _param_value unwraps.
NODE_SECRETS = [
    ("googleSheets", "documentId", "YOUR_GOOGLE_SHEET_ID"),
    ("googleDrive", "folderId", "YOUR_DRIVE_FOLDER_ID"),
    ("googleDrive", "fileId", "YOUR_RESUME_FILE_ID"),
    ("telegram", "chatId", "YOUR_TELEGRAM_CHAT_ID"),
]


def _param_value(params, key):
    """Read a node parameter, unwrapping n8n's resource-locator shape."""
    v = params.get(key)
    if isinstance(v, dict):
        v = v.get("value")
    if not isinstance(v, str) or not v:
        return None
    # "=..." is an n8n expression, not a literal. "YOUR_..." is a placeholder the
    # importer has not filled in yet -- scrubbing it to itself would trip the
    # leak check below, so treat it as nothing to find.
    if v.startswith("=") or v.startswith("YOUR_"):
        return None
    return v


def discover(doc):
    """Return {literal value found in this export: placeholder to write}."""
    found = {}

    for node in doc.get("nodes", []):
        node_type = node.get("type", "")
        params = node.get("parameters") or {}

        for type_match, key, placeholder in NODE_SECRETS:
            if type_match.lower() in node_type.lower():
                value = _param_value(params, key)
                if value:
                    found[value] = placeholder

        # The application recipient. Only literal addresses -- a "=..." value is
        # an n8n expression and carries no address of its own.
        if "gmail" in node_type.lower():
            for key in ("sendTo", "toEmail"):
                value = _param_value(params, key)
                if value and EMAIL_RE.fullmatch(value.strip()):
                    found[value.strip()] = "your-email@example.com"

    instance_id = (doc.get("meta") or {}).get("instanceId")
    if instance_id:
        found[instance_id] = "YOUR_N8N_INSTANCE_ID"

    return found


def sanitize(doc):
    secrets = discover(doc)

    for node in doc.get("nodes", []):
        for cred_type, cred in (node.get("credentials") or {}).items():
            if "id" in cred:
                cred["id"] = CREDENTIAL_ID_PLACEHOLDER.format(cred_type.upper())

    # Export metadata that pins the file to one n8n instance and one save point.
    doc.pop("id", None)
    doc.pop("versionId", None)
    (doc.get("meta") or {}).pop("instanceId", None)

    text = json.dumps(doc, indent=2, ensure_ascii=False)
    for value, placeholder in secrets.items():
        text = text.replace(value, placeholder)
    return text, secrets


def main():
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RAW
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT

    if not raw.exists():
        sys.exit(
            f"error: {raw} not found.\n"
            "Export the workflow from n8n (Workflows -> ... -> Download) and save it there.\n"
            ".local/ is gitignored, so the personal copy stays out of the repo."
        )

    doc = json.loads(raw.read_text(encoding="utf-8"))
    node_count = len(doc.get("nodes", []))
    text, secrets = sanitize(doc)

    if not secrets:
        print("warning: found nothing to scrub -- is this really a personal export?")

    leaked = [v for v in secrets if v in text]
    if leaked:
        sys.exit(f"error: sanitization incomplete, still present: {leaked}")

    # Anything that still looks like an email address is a value discover() did
    # not know to look for. Fail loudly rather than publish it.
    stray = {e for e in EMAIL_RE.findall(text) if not e.endswith("example.com")}
    if stray:
        sys.exit(f"error: unrecognized email address(es) left in output: {sorted(stray)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)} ({node_count} nodes, {len(text)} bytes)")
    for value, placeholder in sorted(secrets.items(), key=lambda kv: kv[1]):
        print(f"  scrubbed {placeholder:<26} ({len(value)} chars)")


if __name__ == "__main__":
    main()
