#!/usr/bin/env python3
"""Check that the LinkedIn pipeline is set up and working.

    python3 scripts/doctor.py [--env-file .env]

Read-only: it never posts to LinkedIn and never changes anything in n8n.
The webhook calls it makes are `list` (read) and an empty body (rejected).
Exits with code 1 if any check fails.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_n8n import (  # noqa: E402
    DEFAULT_ENV, MEDIA_PATH, PLACEHOLDER_RE, TABLES, TABLES_FILE, WEBHOOK_HEADER,
    WEBHOOK_PATH, WORKFLOW_NAME, N8n, Telegram, explain_n8n_failure, header, http,
    load_env, normalize_url, say, workflow_is_active,
)
import lib_n8n  # noqa: E402


class Doctor(object):
    def __init__(self):
        self.failures = 0
        self.passed = 0
        self.skipped = 0

    def ok(self, text):
        self.passed += 1
        lib_n8n.ok(text)

    def fail(self, text, fix=None):
        self.failures += 1
        lib_n8n.fail(text, fix)

    def skip(self, text):
        self.skipped += 1
        say("  - " + text)


def first_json(resp):
    data = resp.json()
    if isinstance(data, list) and data:
        data = data[0]
    return data if isinstance(data, dict) else None


def check_n8n(d, env):
    header("n8n")
    url, key = normalize_url(env.get("N8N_URL")), env.get("N8N_API_KEY")
    if not url or not key:
        d.fail("N8N_URL / N8N_API_KEY missing in .env", "Run python3 scripts/setup.py")
        return None
    client = N8n(url, key)
    r = client.check()
    if r.ok:
        d.ok("Reachable at %s, API key accepted" % url)
        return client
    d.fail("n8n API: %s" % r.describe(), explain_n8n_failure(r, url).split("\n")[-1])
    return None


def check_workflow(d, env, client):
    header("Workflow")
    wf = None
    wf_id = env.get("N8N_WORKFLOW_ID")
    if wf_id:
        r = client.call("GET", "/workflows/%s" % wf_id)
        if r.ok:
            wf = r.json()
        elif r.status != 404:
            d.fail("Reading workflow %s: %s" % (wf_id, r.describe()))
            return None
    if wf is None:
        matches, r = client.find_workflows(WORKFLOW_NAME)
        if matches is None:
            d.fail("Listing workflows: %s" % r.describe())
            return None
        if not matches:
            d.fail("No workflow named '%s'" % WORKFLOW_NAME, "Run python3 scripts/setup.py")
            return None
        if len(matches) > 1:
            d.fail("%d workflows are named '%s'" % (len(matches), WORKFLOW_NAME),
                   "Delete the extra copy, or put the right ID in N8N_WORKFLOW_ID in .env")
        r = client.call("GET", "/workflows/%s" % matches[0]["id"])
        wf = r.json() if r.ok else matches[0]
    d.ok("Found '%s' (id %s, %d nodes)" % (wf.get("name"), wf.get("id"), len(wf.get("nodes") or [])))

    if workflow_is_active(wf):
        d.ok("Workflow is active")
    else:
        d.fail("Workflow is not active", "Open it in n8n and press Publish/Activate (or re-run setup.py)")

    text = json.dumps(wf.get("nodes") or [])
    left = sorted(set(PLACEHOLDER_RE.findall(text)))
    if not left:
        d.ok("No placeholders left")
    else:
        if "YOUR_LINKEDIN_PERSON_ID" in left:
            d.fail("LinkedIn person ID not set",
                   "Pick yourself in any 'LinkedIn:' node's Person dropdown, then: python3 scripts/setup.py person <ID>")
            left.remove("YOUR_LINKEDIN_PERSON_ID")
        if left:
            d.fail("Placeholders still in the live workflow: %s" % ", ".join(left), "Re-run python3 scripts/setup.py")
    return wf


def check_webhook(d, env, wf_active):
    header("Webhook")
    base = normalize_url(env.get("N8N_URL"))
    key = env.get("WEBHOOK_KEY")
    url = "%s/webhook/%s" % (base, WEBHOOK_PATH)
    inactive_hint = "Webhook not registered: activate the workflow" if not wf_active else \
        "n8n doesn't know this webhook path; re-import with setup.py"

    r = http("POST", url, body={"action": "list"})
    if r.status in (401, 403):
        d.ok("Without the key → %s (rejected, as it should be)" % r.status)
    elif r.status == 404:
        d.fail("POST %s → 404" % url, inactive_hint)
        return
    elif r.status is None:
        d.fail("Webhook unreachable: %s" % r.error, "Check N8N_URL and your reverse proxy")
        return
    else:
        d.fail("Without the key → %s; anyone could call your webhook" % r.describe(),
               "Set Authentication = Header Auth on the 'Webhook from Claude' node")

    if not key:
        d.fail("WEBHOOK_KEY missing in .env", "Run python3 scripts/setup.py")
        return
    r = http("POST", url, headers={WEBHOOK_HEADER: key}, body={"action": "list"}, timeout=60)
    data = first_json(r)
    if r.ok and data is not None and isinstance(data.get("posts"), list):
        d.ok("With the key, list → %d post(s)" % len(data["posts"]))
    elif r.status in (401, 403):
        d.fail("With the key → %s" % r.status,
               "WEBHOOK_KEY in .env differs from the 'Pipeline webhook key' credential in n8n; re-run setup.py")
    else:
        d.fail("list → %s" % r.describe(),
               "Open n8n → Executions to see which node failed (often a data-table ID)")

    r = http("POST", url, headers={WEBHOOK_HEADER: key}, body={}, timeout=60)
    data = first_json(r)
    if data is not None and data.get("status") == "rejected":
        d.ok("Empty body → rejected (input validation works)")
    else:
        d.fail("Empty body → %s (expected status 'rejected')" % r.describe(),
               "Check the 'Route by action' node in n8n")

    media = "%s/webhook/%s?f=does-not-exist" % (base, MEDIA_PATH)
    r = http("GET", media)
    if r.status == 404:
        d.ok("Media link for a missing file → 404")
    else:
        d.fail("Media link for a missing file → %s (expected 404)" % r.describe(),
               "Check the 'Media link' webhook branch in n8n → Executions")


def check_telegram(d, env, wf):
    header("Telegram")
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        d.skip("No TELEGRAM_BOT_TOKEN, Telegram not used")
        return
    if wf and not any(n.get("type") == "n8n-nodes-base.telegramTrigger" for n in wf.get("nodes") or []):
        d.skip("Workflow was set up without Telegram (--no-telegram)")
        return
    tg = Telegram(token)
    r = tg.call("getMe")
    data = r.json() or {}
    if r.ok and data.get("ok"):
        d.ok("Bot token works: @%s" % data["result"].get("username", "?"))
    else:
        d.fail("getMe → %s" % ("token rejected" if r.status in (401, 404) else r.describe()),
               "Check TELEGRAM_BOT_TOKEN (from @BotFather)")
        return
    if not env.get("TELEGRAM_CHAT_ID"):
        d.fail("TELEGRAM_CHAT_ID missing in .env", "Re-run setup.py, or message @userinfobot to get it")

    r = tg.call("getWebhookInfo")
    info = (r.json() or {}).get("result") or {}
    if not r.ok:
        d.fail("getWebhookInfo → %s" % r.describe())
        return
    hook = info.get("url") or ""
    base = normalize_url(env.get("N8N_URL"))
    if not hook:
        d.fail("No Telegram webhook set", "Activate the workflow; n8n registers it (needs public https N8N_URL)")
    elif hook.startswith(base + "/"):
        d.ok("Telegram webhook points at this n8n")
    else:
        host = hook.split("/")[2] if hook.count("/") >= 2 else hook
        d.fail("Telegram webhook points at %s, not %s" % (host, base),
               "Another tool uses this bot. Deactivate/activate the workflow so n8n takes it back")
    if info.get("last_error_message"):
        d.fail("Telegram's last delivery error: %s" % info["last_error_message"],
               "Usually an expired TLS cert or n8n not reachable from the internet")
    if info.get("pending_update_count"):
        say("    %d update(s) waiting to be delivered" % info["pending_update_count"])


def check_tables(d, env, client):
    header("Data tables")
    r = client.call("GET", "/data-tables", query={"limit": 100})
    if r.status in (404, 405):
        d.skip("This n8n has no data-table API (n8n < 2.7); open them in n8n → Data tables to check")
        return
    if not r.ok:
        d.fail("Listing data tables: %s" % r.describe())
        return
    body = r.json() or {}
    tables = body.get("data") if isinstance(body, dict) else body
    by_id = {t.get("id"): t for t in tables or []}
    with open(TABLES_FILE, encoding="utf-8") as fh:
        specs = {t["name"]: t for t in json.load(fh)}
    for name, _, env_key in TABLES:
        tid = env.get(env_key)
        table = by_id.get(tid) if tid else None
        if table is None and tid:
            g = client.call("GET", "/data-tables/%s" % tid)
            table = g.json() if g.ok else None
        if table is None:
            d.fail("%s: table %s not found" % (name, tid or "(no ID in .env)"),
                   "Re-run setup.py, or put the table's ID in %s" % env_key)
            continue
        have = {c.get("name") for c in table.get("columns") or []}
        missing = [c["name"] for c in specs[name]["columns"] if c["name"] not in have]
        if missing:
            d.fail("%s: missing columns %s" % (name, ", ".join(missing)), "Re-run setup.py (it adds them)")
        else:
            d.ok("%s (%s)" % (name, table.get("id")))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="doctor.py", description="Read-only health check for the LinkedIn pipeline.")
    parser.add_argument("--env-file", default=DEFAULT_ENV, help="settings file (default: .env in the repo root)")
    args = parser.parse_args(argv)

    say("LinkedIn pipeline doctor (read-only)")
    if not os.path.exists(args.env_file):
        lib_n8n.fail("No %s found" % args.env_file, "Copy .env.example to .env, or run python3 scripts/setup.py")
        return 1
    env = load_env(args.env_file)
    d = Doctor()

    client = check_n8n(d, env)
    wf = check_workflow(d, env, client) if client else None
    check_webhook(d, env, workflow_is_active(wf) if wf else False)
    check_telegram(d, env, wf)
    if client:
        check_tables(d, env, client)

    say("")
    if d.failures:
        say("%d check(s) failed, %d passed%s." % (d.failures, d.passed,
                                                   ", %d skipped" % d.skipped if d.skipped else ""))
        return 1
    say("All %d checks passed%s." % (d.passed, " (%d skipped)" % d.skipped if d.skipped else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:  # output piped into head/less that closed early
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
