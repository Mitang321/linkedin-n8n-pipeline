#!/usr/bin/env python3
"""Set up the LinkedIn pipeline on your own n8n.

    python3 scripts/setup.py                 # interactive, reads/writes .env
    python3 scripts/setup.py --no-telegram   # run without the Telegram bot
    python3 scripts/setup.py --dry-run       # change nothing, write the final JSON to workflow/
    python3 scripts/setup.py person <ID>     # set your LinkedIn person ID on the live workflow

Safe to re-run: everything it creates is remembered in .env and reused.
Standard library only, Python 3.8+.
"""

import argparse
import copy
import datetime
import getpass
import json
import os
import re
import secrets
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_n8n import (  # noqa: E402
    CREDENTIALS, DEFAULT_ENV, GENERATED_FILE, MEDIA_PATH, PLACEHOLDER_RE,
    SETTINGS_KEYS, SETTINGS_KEYS_MINIMAL, TABLES, TABLES_FILE, TELEGRAM_TRIGGER,
    WEBHOOK_HEADER, WEBHOOK_PATH, WORKFLOW_FILE, WORKFLOW_NAME,
    N8n, SetupError, Telegram, api_payload, bare_host, explain_n8n_failure, fail,
    header, info, load_env, normalize_url, ok, save_env, say, warn, workflow_is_active,
)

PERSON_PLACEHOLDER = "YOUR_LINKEDIN_PERSON_ID"
CHAT_PLACEHOLDER = "YOUR_TELEGRAM_CHAT_ID"
DOMAIN_PLACEHOLDER = "YOUR_N8N_DOMAIN"


# --------------------------------------------------------------------------
# Config / prompting
# --------------------------------------------------------------------------

class Config(object):
    def __init__(self, args):
        self.args = args
        self.path = os.path.abspath(args.env_file)
        self.values = load_env(self.path)
        self.pending = {}  # what a dry run would have written

    def get(self, key, default=""):
        return (self.values.get(key) or "").strip() or default

    def set(self, key, value):
        value = "" if value is None else str(value)
        self.values[key] = value
        if self.args.dry_run:
            self.pending[key] = value
            return
        save_env(self.path, {key: value})

    def ask(self, key, label, secret=False, default=None, required=True, validate=None, hint=None):
        """Return .env value, or prompt for it (and save it)."""
        current = self.get(key)
        if current:
            if validate:
                err = validate(current)
                if err:
                    raise SetupError("%s in %s looks wrong: %s" % (key, self.path, err))
            return current
        if self.args.yes:
            if default is not None:
                self.set(key, default)
                return default
            if not required:
                return ""
            raise SetupError("%s is not set in %s (needed because of --yes)." % (key, self.path))
        if hint:
            for line in hint.strip("\n").split("\n"):
                info(line)
        while True:
            suffix = " [%s]" % default if default else ""
            if not required and not default:
                suffix = " (leave empty to skip)"
            prompt = "    %s%s: " % (label, suffix)
            try:
                value = getpass.getpass(prompt) if secret else input(prompt)
            except EOFError:
                raise SetupError("No input available. Fill %s in %s or run with --yes." % (key, self.path))
            value = value.strip()
            if not value and default is not None:
                value = default
            if not value and not required:
                return ""
            if not value:
                say("      This one is required.")
                continue
            if validate:
                err = validate(value)
                if err:
                    say("      " + err)
                    continue
            self.set(key, value)
            return value


def confirm(cfg, question, default=True):
    if cfg.args.yes:
        return default
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input("    %s %s " % (question, hint)).strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer.startswith("y")


def choose(cfg, question, options, default):
    """options: list of (key, label). Returns key."""
    if cfg.args.yes:
        return default
    for key, label in options:
        say("      [%s] %s%s" % (key, label, "  (default)" if key == default else ""))
    while True:
        try:
            answer = input("    %s " % question).strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        for key, _ in options:
            if answer == key or answer.startswith(key):
                return key
        say("      Please type one of: " + ", ".join(k for k, _ in options))


def validate_url(value):
    if not re.match(r"^(https?://)?[A-Za-z0-9.-]+(:\d+)?(/.*)?$", value.strip()):
        return "That doesn't look like a URL, e.g. https://n8n.example.com"
    return None


def validate_timezone(value):
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
    except ImportError:
        return None if re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)*$", value) else "Use an IANA name like Europe/Paris"
    try:
        ZoneInfo(value)
    except Exception:
        return "Unknown time zone %r. Use an IANA name like Europe/Paris or America/New_York." % value
    return None


def validate_person(value):
    if not re.match(r"^[A-Za-z0-9_-]{3,64}$", value):
        return "A LinkedIn person ID looks like 'AbC123xYz' (letters, digits, - and _)."
    return None


def clean_person(value):
    value = (value or "").strip()
    for prefix in ("urn:li:person:", "urn:li:member:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def clean_table_id(value):
    value = (value or "").strip().rstrip("/")
    # Accept a pasted URL like https://n8n.example.com/projects/x/datatables/AbCd1234
    m = re.search(r"/data-?tables/([A-Za-z0-9_-]+)", value)
    if m:
        return m.group(1)
    return value


# --------------------------------------------------------------------------
# Step 1: n8n
# --------------------------------------------------------------------------

def step_n8n(cfg):
    header("1. n8n")
    url = cfg.ask("N8N_URL", "n8n URL (e.g. https://n8n.example.com)", validate=validate_url)
    norm = normalize_url(url)
    if norm != url:
        cfg.set("N8N_URL", norm)
    key = cfg.ask("N8N_API_KEY", "n8n API key", secret=True,
                  hint="Create one in n8n → Settings → n8n API → Create API key.")
    client = N8n(norm, key)
    resp = client.check()
    if resp.ok:
        ok("n8n reachable at %s and the API key works" % norm)
        return client, True
    if cfg.args.dry_run:
        fail("Could not talk to n8n (%s). Dry run continues offline." % resp.describe(),
             explain_n8n_failure(resp, norm))
        return client, False
    fail("n8n check failed: %s" % resp.describe(), explain_n8n_failure(resp, norm))
    raise SetupError("Fix the n8n connection and run setup again.")


# --------------------------------------------------------------------------
# Step 2: Telegram
# --------------------------------------------------------------------------

def step_telegram(cfg):
    header("2. Telegram")
    if cfg.args.no_telegram:
        ok("Skipped (--no-telegram). Telegram nodes will be disabled.")
        return None
    token = cfg.ask("TELEGRAM_BOT_TOKEN", "Telegram bot token", secret=True, required=False,
                    hint="Optional. Get one from @BotFather (/newbot). Leave empty to run without Telegram.")
    if not token:
        ok("No bot token, running without Telegram. Telegram nodes will be disabled.")
        cfg.args.no_telegram = True
        return None

    tg = Telegram(token)
    resp = tg.call("getMe")
    data = resp.json() or {}
    if not (resp.ok and data.get("ok")):
        if resp.status in (401, 404):
            fail("Telegram rejected the bot token.",
                 "Copy the token again from @BotFather and update TELEGRAM_BOT_TOKEN in .env.")
        else:
            fail("Could not reach Telegram: %s" % resp.describe(),
                 "Check your internet connection, or run with --no-telegram.")
        if cfg.args.dry_run:
            warn("Dry run: continuing with a placeholder chat ID.")
            return {"token": token, "chat_id": cfg.get("TELEGRAM_CHAT_ID", "0"), "username": "?"}
        raise SetupError("Telegram check failed.")
    username = data["result"].get("username", "?")
    ok("Bot token works: @%s" % username)

    chat_id = cfg.get("TELEGRAM_CHAT_ID")
    if chat_id:
        ok("Chat ID from .env: %s" % chat_id)
        return {"token": token, "chat_id": chat_id, "username": username}

    chat_id = detect_chat_id(cfg, tg, username)
    cfg.set("TELEGRAM_CHAT_ID", chat_id)
    ok("Chat ID: %s" % chat_id)
    return {"token": token, "chat_id": chat_id, "username": username}


def _chat_from_update(update):
    for key in ("message", "edited_message", "channel_post"):
        if key in update:
            return update[key].get("chat")
    if "callback_query" in update:
        return (update["callback_query"].get("message") or {}).get("chat")
    return None


def manual_chat_id(cfg, reason):
    fail(reason)
    if cfg.args.yes or cfg.args.dry_run:
        if cfg.args.dry_run:
            warn("Dry run: using chat ID 0 as a stand-in.")
            return "0"
        raise SetupError("Set TELEGRAM_CHAT_ID in .env (message @userinfobot on Telegram to see your ID).")
    info("Message @userinfobot (https://t.me/userinfobot) on Telegram; it replies with your ID.")
    while True:
        try:
            value = input("    Your Telegram chat ID: ").strip()
        except EOFError:
            raise SetupError("Set TELEGRAM_CHAT_ID in .env and run setup again.")
        if re.match(r"^-?\d+$", value):
            return value
        say("      A chat ID is a number, like 123456789.")


def detect_chat_id(cfg, tg, username):
    interactive = not (cfg.args.yes or cfg.args.dry_run)
    if interactive:
        info("Open Telegram, find @%s and send it any message (e.g. hi)." % username)
        info("Waiting up to 60 seconds…")
    deadline = time.time() + (60 if interactive else 0)
    while True:
        remaining = max(0, int(deadline - time.time()))
        resp = tg.call("getUpdates", {"timeout": min(10, remaining), "allowed_updates": '["message","callback_query"]'},
                       timeout=min(10, remaining) + 15)
        if resp.status == 409:
            return manual_chat_id(
                cfg, "This bot already has a webhook (probably n8n's Telegram trigger), so setup can't read its messages.\n"
                     "      → Enter your chat ID by hand, or deactivate the workflow in n8n (that removes the\n"
                     "        webhook), run setup again and message the bot when asked.")
        data = resp.json() or {}
        if not (resp.ok and data.get("ok")):
            return manual_chat_id(cfg, "getUpdates failed: %s" % resp.describe())
        chats = [c for c in (_chat_from_update(u) for u in data.get("result") or []) if c]
        if chats:
            chat = chats[-1]
            who = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
            info("Got a message from %s" % (("@" + who) if chat.get("username") else who or "someone"))
            return str(chat["id"])
        if time.time() >= deadline:
            break
    return manual_chat_id(cfg, "No message reached @%s." % username)


# --------------------------------------------------------------------------
# Step 3: Data tables
# --------------------------------------------------------------------------

def load_table_specs():
    with open(TABLES_FILE, encoding="utf-8") as fh:
        specs = json.load(fh)
    return {t["name"]: t for t in specs}


def step_tables(cfg, client, online):
    header("3. Data tables")
    specs = load_table_specs()
    ids = {}

    if not online:
        for name, placeholder, env_key in TABLES:
            ids[name] = cfg.get(env_key) or ("dryrun-" + name.replace("_", "-"))
            ok("%s → %s (dry run, nothing created)" % (name, ids[name]))
        return ids

    tables, resp = client.list_all("/data-tables")
    if tables is None:
        if resp.status in (404, 405):
            warn("This n8n has no data-table API (added in n8n 2.7). Setting them up by hand.")
            return manual_tables(cfg, specs)
        if resp.status == 403:
            warn("The API key may not use data tables (403). Setting them up by hand.")
            return manual_tables(cfg, specs)
        fail("Listing data tables failed: %s" % resp.describe(), explain_n8n_failure(resp, client.base))
        raise SetupError("Could not list data tables.")

    by_id = {t.get("id"): t for t in tables}
    by_name = {}
    for t in tables:
        by_name.setdefault(t.get("name"), t)

    for name, placeholder, env_key in TABLES:
        spec = specs[name]
        known = cfg.get(env_key)
        table = by_id.get(known) if known else None
        if not table:
            table = by_name.get(name)
        if table:
            ok("%s exists → %s" % (name, table["id"]))
            add_missing_columns(cfg, client, table, spec)
        elif cfg.args.dry_run:
            ids[name] = known or ("dryrun-" + name.replace("_", "-"))
            ok("%s would be created with %d columns" % (name, len(spec["columns"])))
            continue
        else:
            body = {"name": name, "columns": [{"name": c["name"], "type": c["type"]} for c in spec["columns"]]}
            r = client.call("POST", "/data-tables", body)
            if not r.ok:
                fail("Creating table %s failed: %s" % (name, r.describe()))
                raise SetupError("Create the table by hand (n8n → Data tables) and put its ID in %s." % env_key)
            table = r.json() or {}
            ok("%s created → %s" % (name, table.get("id")))
        ids[name] = table["id"]
        if cfg.get(env_key) != table["id"]:
            cfg.set(env_key, table["id"])

    seed_settings(cfg, client, ids["pipeline_settings"], specs["pipeline_settings"])
    return ids


def add_missing_columns(cfg, client, table, spec):
    have = {c.get("name") for c in table.get("columns") or []}
    missing = [c for c in spec["columns"] if c["name"] not in have]
    for col in missing:
        if cfg.args.dry_run:
            info("would add column %s.%s (%s)" % (table["name"], col["name"], col["type"]))
            continue
        r = client.call("POST", "/data-tables/%s/columns" % table["id"], {"name": col["name"], "type": col["type"]})
        if r.ok:
            info("added missing column %s (%s)" % (col["name"], col["type"]))
        else:
            fail("Could not add column %s.%s: %s" % (table["name"], col["name"], r.describe()),
                 "Add it by hand in n8n → Data tables → %s." % table["name"])


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def seed_settings(cfg, client, table_id, spec):
    if table_id.startswith("dryrun-"):
        return
    rows, resp = client.list_all("/data-tables/%s/rows" % table_id)
    if rows is None:
        warn("Could not read pipeline_settings rows (%s). Add the row by hand." % resp.describe())
        return
    for seed in spec.get("seed_rows") or []:
        if any(r.get("key") == seed["key"] for r in rows):
            ok("pipeline_settings already has %s" % seed["key"])
            continue
        if cfg.args.dry_run:
            ok("would add pipeline_settings row %s = <now>" % seed["key"])
            continue
        value = now_iso() if seed["key"].endswith("_at") else seed["value"]
        r = client.call("POST", "/data-tables/%s/rows" % table_id,
                        {"data": [{"key": seed["key"], "value": value}], "returnType": "count"})
        if r.ok:
            ok("pipeline_settings row %s = %s" % (seed["key"], value))
        else:
            fail("Could not add the %s row: %s" % (seed["key"], r.describe()),
                 "Add it by hand: n8n → Data tables → pipeline_settings → key=%s, value=%s" % (seed["key"], value))


def manual_tables(cfg, specs):
    ids = {}
    say("")
    say("    Create these 3 tables in n8n → Overview → Data tables → Create data table.")
    say("    Use the exact names and columns (types in brackets):")
    for name, _, _ in TABLES:
        spec = specs[name]
        cols = ", ".join("%s [%s]" % (c["name"], c["type"]) for c in spec["columns"])
        say("")
        say("      %s" % name)
        say("        columns: %s" % cols)
        for seed in spec.get("seed_rows") or []:
            say("        then add one row: key = %s, value = %s" % (seed["key"], now_iso()))
    say("")
    say("    The table ID is the last part of the URL when the table is open,")
    say("    e.g. …/datatables/AbCdEf1234567890 → AbCdEf1234567890")
    say("")
    for name, _, env_key in TABLES:
        if cfg.args.dry_run and not cfg.get(env_key):
            ids[name] = "dryrun-" + name.replace("_", "-")
            continue
        value = cfg.ask(env_key, "ID of table %s" % name,
                        validate=lambda v: None if re.match(r"^[A-Za-z0-9_-]+$", clean_table_id(v))
                        else "Paste the table ID (or the table's URL).")
        cleaned = clean_table_id(value)
        if cleaned != value:
            cfg.set(env_key, cleaned)
        ids[name] = cleaned
        ok("%s → %s" % (name, cleaned))
    return ids


# --------------------------------------------------------------------------
# Step 4: Credentials
# --------------------------------------------------------------------------

def _schema_default(prop):
    if "default" in prop:
        return prop["default"]
    if "enum" in prop and prop["enum"]:
        return prop["enum"][0]
    t = prop.get("type")
    if isinstance(t, list):
        t = t[0]
    return {"boolean": False, "number": 0, "integer": 0, "string": "", "object": {}, "array": []}.get(t, "")


def build_cred_data(schema, wanted):
    """Fill `wanted` up so the schema's required fields are present."""
    if not isinstance(schema, dict):
        return dict(wanted)
    props = schema.get("properties") or {}
    data = dict(wanted)
    required = set(schema.get("required") or [])
    # n8n puts conditional requirements in allOf/if/then; booleans we set to
    # false normally take the "else" branch, so only top-level required matters.
    for name in required:
        if name not in data and name in props:
            data[name] = _schema_default(props[name])
    if schema.get("additionalProperties") is False and props:
        data = {k: v for k, v in data.items() if k in props}
    return data


def credential_exists(listing, cred_id):
    if listing is None:
        return None  # older n8n can't list credentials over the API: can't tell
    return any(c.get("id") == cred_id for c in listing)


def step_credentials(cfg, client, online, telegram):
    header("4. Credentials")
    wanted = {
        "linkedin": {
            "clientId": cfg.ask("LINKEDIN_CLIENT_ID", "LinkedIn app Client ID",
                                hint="From your app at https://www.linkedin.com/developers/apps → Auth."),
            "clientSecret": cfg.ask("LINKEDIN_CLIENT_SECRET", "LinkedIn app Client Secret", secret=True),
            "organizationSupport": False,
            "legacy": False,
        },
        "webhook": {"name": WEBHOOK_HEADER, "value": cfg.get("WEBHOOK_KEY")},
    }
    if telegram:
        wanted["telegram"] = {"accessToken": telegram["token"]}

    ids = {}
    if not online:
        for key in wanted:
            ids[key] = cfg.get(CREDENTIALS[key]["env"]) or "dryrun-%s-cred" % key
            ok("%s → %s (dry run, nothing created)" % (CREDENTIALS[key]["name"], ids[key]))
        return ids

    listing = None
    r = client.call("GET", "/credentials", query={"limit": 250})
    if r.ok:
        body = r.json()
        listing = body.get("data") if isinstance(body, dict) else body

    for key, data in wanted.items():
        meta = CREDENTIALS[key]
        known = cfg.get(meta["env"])
        existing = None
        if known:
            exists = credential_exists(listing, known)
            if exists is True:
                existing = known
            elif exists is None:
                warn("Can't check credential %s on this n8n version; reusing it." % known)
                existing = known
        if not existing and listing is not None:
            for c in listing:
                if c.get("name") == meta["name"] and c.get("type") == meta["type"]:
                    existing = c.get("id")
                    break
        if existing:
            ok("%s exists → %s" % (meta["name"], existing))
            if key == "webhook" and not cfg.args.dry_run:
                # keep the key in n8n in sync with .env
                p = client.call("PATCH", "/credentials/%s" % existing,
                                {"data": data, "type": meta["type"], "name": meta["name"]})
                if not p.ok and p.status not in (404, 405):
                    warn("Could not refresh the webhook key in n8n (%s)." % p.describe())
            ids[key] = existing
            if known != existing:
                cfg.set(meta["env"], existing)
            continue
        if cfg.args.dry_run:
            ids[key] = "dryrun-%s-cred" % key
            ok("%s (%s) would be created" % (meta["name"], meta["type"]))
            continue

        schema_resp = client.call("GET", "/credentials/schema/%s" % meta["type"])
        schema = schema_resp.json() if schema_resp.ok else None
        payload = build_cred_data(schema, data)
        r = client.call("POST", "/credentials", {"name": meta["name"], "type": meta["type"], "data": payload})
        if not r.ok:
            fix = "n8n's schema for %s:\n%s" % (
                meta["type"],
                json.dumps({k: (schema or {}).get(k) for k in ("required", "properties")}, indent=2)[:1500]
                if schema else "(could not fetch: %s)" % schema_resp.describe())
            fix += "\nSent fields: %s" % ", ".join(sorted(payload))
            fix += "\nYou can also create it by hand in n8n → Credentials and put its ID in %s." % meta["env"]
            fail("Creating %s failed: %s" % (meta["name"], r.describe()), fix)
            raise SetupError("Credential creation failed.")
        cred_id = (r.json() or {}).get("id")
        ids[key] = cred_id
        cfg.set(meta["env"], cred_id)
        ok("%s created → %s" % (meta["name"], cred_id))
    return ids


# --------------------------------------------------------------------------
# Step 5: Build the workflow
# --------------------------------------------------------------------------

def _roots(wf):
    targets = set()
    for outs in wf["connections"].values():
        for branches in outs.values():
            for branch in branches or []:
                for c in branch or []:
                    targets.add(c["node"])
    return [n["name"] for n in wf["nodes"] if n["name"] not in targets]


def _reach(wf, start):
    seen, todo = {start}, [start]
    while todo:
        name = todo.pop()
        for branches in wf["connections"].get(name, {}).values():
            for branch in branches or []:
                for c in branch or []:
                    if c["node"] not in seen:
                        seen.add(c["node"])
                        todo.append(c["node"])
    return seen


def prune_telegram(wf):
    """Drop the Telegram trigger and its private branch, disable other Telegram nodes."""
    names = {n["name"] for n in wf["nodes"]}
    if TELEGRAM_TRIGGER not in names:
        return [], [], []
    others = set()
    for root in _roots(wf):
        if root != TELEGRAM_TRIGGER:
            others |= _reach(wf, root)
    removed = _reach(wf, TELEGRAM_TRIGGER) - others

    wf["nodes"] = [n for n in wf["nodes"] if n["name"] not in removed]
    new_conns = {}
    for src, outs in wf["connections"].items():
        if src in removed:
            continue
        new_outs = {}
        for kind, branches in outs.items():
            new_outs[kind] = [[c for c in (branch or []) if c["node"] not in removed] for branch in (branches or [])]
        new_conns[src] = new_outs
    wf["connections"] = new_conns

    disabled = []
    for n in wf["nodes"]:
        if n["type"] == "n8n-nodes-base.telegram":
            n["disabled"] = True
            n.pop("credentials", None)
            disabled.append(n["name"])

    groups = []
    for g in wf.get("nodeGroups") or []:
        if any(name in removed for name in g.get("nodeNames") or []):
            kept = [x for x in g["nodeNames"] if x not in removed]
            if not kept:
                continue
            g = dict(g, nodeNames=kept)
        groups.append(g)
    if "nodeGroups" in wf:
        wf["nodeGroups"] = groups

    # Warn if something left behind still points at a removed node.
    dangling = []
    for n in wf["nodes"]:
        text = json.dumps(n.get("parameters") or {})
        for name in removed:
            if "$('%s')" % name in text or '$("%s")' % name in text:
                dangling.append((n["name"], name))
    return sorted(removed), disabled, dangling


def build_workflow(template, cfg, tables, creds, telegram, n8n_url):
    wf = copy.deepcopy(template)
    report = {"removed": [], "disabled": [], "dangling": []}
    if not telegram:
        removed, disabled, dangling = prune_telegram(wf)
        report.update(removed=removed, disabled=disabled, dangling=dangling)

    for node in wf["nodes"]:
        for ctype, ref in (node.get("credentials") or {}).items():
            for key, meta in CREDENTIALS.items():
                if ref.get("id") == meta["placeholder"] and key in creds:
                    ref["id"] = creds[key]
                    ref["name"] = meta["name"]

    wf.setdefault("settings", {})["timezone"] = cfg.get("TIMEZONE", "Europe/Paris")

    replacements = {"https://" + DOMAIN_PLACEHOLDER: normalize_url(n8n_url),
                    DOMAIN_PLACEHOLDER: bare_host(n8n_url),
                    CHAT_PLACEHOLDER: telegram["chat_id"] if telegram else ""}
    for name, placeholder, _ in TABLES:
        replacements[placeholder] = tables[name]
    person = clean_person(cfg.get("LINKEDIN_PERSON_ID"))
    if person:
        replacements[PERSON_PLACEHOLDER] = person

    text = json.dumps(wf, ensure_ascii=False)
    for old, new in replacements.items():
        text = text.replace(old, json.dumps(new)[1:-1])
    wf = json.loads(text)

    left = sorted(set(PLACEHOLDER_RE.findall(json.dumps(wf))) - {PERSON_PLACEHOLDER})
    report["left"] = left
    return wf, report


def step_build(cfg, tables, creds, telegram):
    header("5. Build the workflow")
    with open(WORKFLOW_FILE, encoding="utf-8") as fh:
        template = json.load(fh)
    wf, report = build_workflow(template, cfg, tables, creds, telegram, cfg.get("N8N_URL"))
    ok("Filled in domain, table IDs, credentials and time zone (%s)" % wf["settings"]["timezone"])
    if not telegram:
        ok("Removed '%s' and %d nodes only it used; disabled %d Telegram nodes"
           % (TELEGRAM_TRIGGER, len(report["removed"]) - 1, len(report["disabled"])))
        info("Disabled nodes just pass data through, so posting still works.")
        for node, ref in report["dangling"]:
            warn("Node '%s' still references removed node '%s'." % (node, ref))
    if report["left"]:
        fail("Placeholders still in the workflow: %s" % ", ".join(report["left"]))
        raise SetupError("Workflow template has placeholders setup doesn't know about.")
    if PERSON_PLACEHOLDER in json.dumps(wf):
        info("LinkedIn person ID is still a placeholder; you'll set it after connecting LinkedIn.")
    if cfg.args.dry_run:
        with open(GENERATED_FILE, "w", encoding="utf-8") as fh:
            json.dump(wf, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        ok("Wrote %s" % os.path.relpath(GENERATED_FILE, os.getcwd()))
    return wf


# --------------------------------------------------------------------------
# Step 6/7: Import + activate
# --------------------------------------------------------------------------

def _settings_variants(wf):
    full = dict(wf.get("settings") or {})
    seen, out = set(), []
    for keys in (None, SETTINGS_KEYS, SETTINGS_KEYS_MINIMAL):
        s = full if keys is None else {k: v for k, v in full.items() if k in keys}
        sig = json.dumps(s, sort_keys=True)
        if sig not in seen:
            seen.add(sig)
            out.append(s)
    return out


def send_workflow(client, method, path, wf):
    """POST/PUT, retrying with fewer settings keys if this n8n rejects some."""
    resp = None
    for settings in _settings_variants(wf):
        payload = api_payload(wf)
        payload["settings"] = settings
        resp = client.call(method, path, payload, timeout=60)
        if resp.ok:
            return resp
        if resp.status != 400 or "setting" not in resp.body.lower():
            return resp
    return resp


def step_import(cfg, client, online, wf):
    header("6. Import")
    if not online:
        ok("Dry run: would create or update workflow '%s' (%d nodes)" % (wf["name"], len(wf["nodes"])))
        return None
    name = wf.get("name") or WORKFLOW_NAME
    matches, resp = client.find_workflows(name)
    if matches is None:
        fail("Listing workflows failed: %s" % resp.describe(), explain_n8n_failure(resp, client.base))
        raise SetupError("Could not list workflows.")
    known = cfg.get("N8N_WORKFLOW_ID")
    target = None
    if matches:
        target = next((w for w in matches if w.get("id") == known), matches[0])
        say("    A workflow named '%s' already exists (id %s%s)." % (
            name, target["id"], ", active" if workflow_is_active(target) else ""))
        action = choose(cfg, "Update it, create a second one, or stop? [u/c/s]",
                        [("u", "update the existing workflow"), ("c", "create a second copy"), ("s", "stop")], "u")
        if action == "s":
            raise SetupError("Stopped before importing. Nothing in the workflow changed.")
        if action == "c":
            target = None

    if target:
        r = send_workflow(client, "PUT", "/workflows/%s" % target["id"], wf)
        verb = "Updated"
    else:
        r = send_workflow(client, "POST", "/workflows", wf)
        verb = "Imported"
    if not r.ok:
        fail("%s failed: %s" % ("Update" if target else "Import", r.describe()),
             "If n8n complains about an unknown node type, update n8n: the workflow needs the Data table node.")
        raise SetupError("Workflow import failed.")
    wf_id = (r.json() or {}).get("id") or (target or {}).get("id")
    cfg.set("N8N_WORKFLOW_ID", wf_id)
    ok("%s '%s' → id %s" % (verb, name, wf_id))
    return wf_id


def activate(client, wf_id):
    r = client.call("POST", "/workflows/%s/activate" % wf_id, {}, timeout=60)
    if r.ok:
        return True, r
    if "already active" in r.body.lower():
        return True, r
    return False, r


def step_activate(cfg, client, wf_id):
    header("7. Activate")
    if not wf_id:
        ok("Dry run: would activate the workflow")
        return True
    good, r = activate(client, wf_id)
    if good:
        ok("Workflow is active")
        return True
    fail("Activation failed: %s" % r.describe(),
         "Open the workflow in n8n and press Publish/Activate to see which node complains.\n"
         "The Telegram trigger needs N8N_URL to be public https, or Telegram won't accept the webhook.")
    return False


# --------------------------------------------------------------------------
# Step 8: Checklist
# --------------------------------------------------------------------------

def step_checklist(cfg, wf_id, telegram, webhook_key_new):
    url = normalize_url(cfg.get("N8N_URL"))
    header("Done. What's left (by hand):")
    say("")
    say("  1. Connect LinkedIn")
    say("     In your LinkedIn app (developers → Auth) add this redirect URL:")
    say("       %s/rest/oauth2-credential/callback" % url)
    say("     Then n8n → Credentials → \"LinkedIn account\" → Connect my account.")
    say("")
    say("  2. Set your LinkedIn person ID")
    say("     In n8n open the workflow, open any \"LinkedIn:\" node and pick yourself in the")
    say("     Person dropdown; the ID is shown there. Then run:")
    say("       python3 scripts/setup.py person <ID>")
    say("")
    say("  3. Check everything")
    say("       python3 scripts/doctor.py")
    if telegram:
        say("")
        say("  Telegram: send /start to @%s once the workflow is active." % telegram["username"])
    say("")
    say("  Webhook URL:  %s/webhook/%s" % (url, WEBHOOK_PATH))
    say("  Header:       %s" % WEBHOOK_HEADER)
    if webhook_key_new:
        say("  Key:          %s" % cfg.get("WEBHOOK_KEY"))
        if cfg.args.dry_run:
            say("                (dry run: this key was not saved)")
        else:
            say("                (shown once; it is also saved in %s)" % os.path.relpath(cfg.path, os.getcwd()))
    else:
        say("  Key:          the WEBHOOK_KEY value in %s" % os.path.relpath(cfg.path, os.getcwd()))
    say("  Media links:  %s/webhook/%s?f=<file>" % (url, MEDIA_PATH))
    say("")


# --------------------------------------------------------------------------
# person subcommand
# --------------------------------------------------------------------------

def find_live_workflow(cfg, client):
    known = cfg.get("N8N_WORKFLOW_ID")
    if known:
        r = client.call("GET", "/workflows/%s" % known)
        if r.ok:
            return r.json()
        if r.status != 404:
            fail("Reading workflow %s failed: %s" % (known, r.describe()), explain_n8n_failure(r, client.base))
            raise SetupError("Could not read the workflow.")
        warn("Workflow %s from .env no longer exists; looking it up by name." % known)
    matches, resp = client.find_workflows(WORKFLOW_NAME)
    if matches is None:
        fail("Listing workflows failed: %s" % resp.describe(), explain_n8n_failure(resp, client.base))
        raise SetupError("Could not list workflows.")
    if not matches:
        raise SetupError("No workflow named '%s' in n8n. Run python3 scripts/setup.py first." % WORKFLOW_NAME)
    if len(matches) > 1:
        raise SetupError("Several workflows are named '%s'. Put the right one's ID in N8N_WORKFLOW_ID in .env "
                         "(it's in the URL: …/workflow/<ID>)." % WORKFLOW_NAME)
    r = client.call("GET", "/workflows/%s" % matches[0]["id"])
    if not r.ok:
        raise SetupError("Reading workflow failed: %s" % r.describe())
    wf = r.json()
    cfg.set("N8N_WORKFLOW_ID", wf["id"])
    return wf


def set_person(wf, new, old):
    changed = 0
    for node in wf["nodes"]:
        params = node.get("parameters") or {}
        before = json.dumps(params)
        if node.get("type") == "n8n-nodes-base.linkedIn" and "person" in params:
            p = params["person"]
            if isinstance(p, dict) and "value" in p:   # resource-locator form
                p["value"] = new
            else:
                params["person"] = new
        text = json.dumps(params).replace(PERSON_PLACEHOLDER, new)
        if old and old != new:
            text = text.replace("urn:li:person:" + old, "urn:li:person:" + new)
        node["parameters"] = json.loads(text)
        if json.dumps(node["parameters"]) != before:
            changed += 1
    return changed


def cmd_person(cfg, person_id):
    header("Set LinkedIn person ID")
    new = clean_person(person_id)
    err = validate_person(new)
    if err:
        raise SetupError(err)
    url = cfg.ask("N8N_URL", "n8n URL", validate=validate_url)
    key = cfg.ask("N8N_API_KEY", "n8n API key", secret=True)
    client = N8n(url, key)
    resp = client.check()
    if not resp.ok:
        fail("n8n check failed: %s" % resp.describe(), explain_n8n_failure(resp, client.base))
        raise SetupError("Fix the n8n connection first.")
    wf = find_live_workflow(cfg, client)
    old = clean_person(cfg.get("LINKEDIN_PERSON_ID"))
    changed = set_person(wf, new, old)
    ok("Found '%s' (id %s); %d node(s) to update" % (wf.get("name"), wf["id"], changed))
    if cfg.args.dry_run:
        ok("Dry run: not saving.")
        return 0
    if changed:
        r = send_workflow(client, "PUT", "/workflows/%s" % wf["id"], wf)
        if not r.ok:
            fail("Saving the workflow failed: %s" % r.describe())
            raise SetupError("Update failed.")
        ok("Workflow saved")
    good, r = activate(client, wf["id"])
    if good:
        ok("Workflow is active")
    else:
        fail("Activation failed: %s" % r.describe(), "Open the workflow in n8n and press Publish/Activate.")
    cfg.set("LINKEDIN_PERSON_ID", new)
    ok("Saved LINKEDIN_PERSON_ID in %s" % os.path.relpath(cfg.path, os.getcwd()))
    say("")
    say("  Next: python3 scripts/doctor.py")
    return 0 if good else 1


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def run_setup(cfg):
    say("LinkedIn pipeline setup" + ("  (dry run: nothing in n8n will change)" if cfg.args.dry_run else ""))
    say("Settings file: %s" % cfg.path)

    client, online = step_n8n(cfg)
    if cfg.args.dry_run and online:
        online = "read-only"

    cfg.ask("TIMEZONE", "Time zone for schedules", default="Europe/Paris", validate=validate_timezone)
    webhook_key_new = False
    if not cfg.get("WEBHOOK_KEY"):
        cfg.set("WEBHOOK_KEY", secrets.token_hex(24))
        webhook_key_new = True

    telegram = step_telegram(cfg)
    tables = step_tables(cfg, client, bool(online))
    creds = step_credentials(cfg, client, online is True, telegram)
    wf = step_build(cfg, tables, creds, telegram)
    wf_id = step_import(cfg, client, online is True, wf)
    active = step_activate(cfg, client, wf_id)
    step_checklist(cfg, wf_id, telegram, webhook_key_new)
    if cfg.args.dry_run and cfg.pending:
        say("Dry run: would save to %s: %s" % (os.path.relpath(cfg.path, os.getcwd()), ", ".join(sorted(cfg.pending))))
    return 0 if active else 1


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", default=DEFAULT_ENV, help="settings file (default: .env in the repo root)")
    common.add_argument("--yes", "-y", action="store_true", help="never prompt; use .env values and defaults")
    common.add_argument("--dry-run", action="store_true",
                        help="change nothing in n8n; write workflow/linkedin-pipeline.generated.json")

    parser = argparse.ArgumentParser(
        prog="setup.py", parents=[common],
        description="Set up the LinkedIn pipeline on your n8n. Safe to re-run.")
    parser.add_argument("--no-telegram", action="store_true", help="run without the Telegram bot")
    sub = parser.add_subparsers(dest="command")
    person = sub.add_parser("person", parents=[common], help="set your LinkedIn person ID on the live workflow")
    person.add_argument("person_id", help="your LinkedIn person ID (or urn:li:person:<ID>)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not hasattr(args, "no_telegram"):
        args.no_telegram = False
    cfg = Config(args)
    try:
        if args.command == "person":
            return cmd_person(cfg, args.person_id)
        return run_setup(cfg)
    except SetupError as e:
        say("")
        fail(str(e))
        return 1
    except KeyboardInterrupt:
        say("")
        say("Stopped. Run it again any time; finished steps are reused.")
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # output piped into head/less that closed early
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
