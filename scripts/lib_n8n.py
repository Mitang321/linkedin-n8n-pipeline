"""Shared helpers for scripts/setup.py and scripts/doctor.py.

Standard library only, Python 3.8+.
"""

import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_FILE = os.path.join(REPO_ROOT, "workflow", "linkedin-pipeline.json")
TABLES_FILE = os.path.join(REPO_ROOT, "workflow", "data-tables.json")
GENERATED_FILE = os.path.join(REPO_ROOT, "workflow", "linkedin-pipeline.generated.json")
DEFAULT_ENV = os.path.join(REPO_ROOT, ".env")

WORKFLOW_NAME = "LinkedIn pipeline"
WEBHOOK_PATH = "claude-linkedin-post"
MEDIA_PATH = "media"
WEBHOOK_HEADER = "X-Claude-Key"
TELEGRAM_TRIGGER = "Telegram in"

# Table name in data-tables.json -> (placeholder in the workflow, .env key)
TABLES = [
    ("linkedin_posts", "YOUR_POSTS_TABLE_ID", "N8N_POSTS_TABLE_ID"),
    ("ideas", "YOUR_IDEAS_TABLE_ID", "N8N_IDEAS_TABLE_ID"),
    ("pipeline_settings", "YOUR_SETTINGS_TABLE_ID", "N8N_SETTINGS_TABLE_ID"),
]

# Credential placeholder id in the workflow -> what we create in n8n
CREDENTIALS = {
    "linkedin": {
        "placeholder": "REPLACE_LINKEDIN_CREDENTIAL",
        "type": "linkedInOAuth2Api",
        "name": "LinkedIn account",
        "env": "N8N_LINKEDIN_CREDENTIAL_ID",
    },
    "webhook": {
        "placeholder": "REPLACE_HEADER_AUTH_CREDENTIAL",
        "type": "httpHeaderAuth",
        "name": "Pipeline webhook key",
        "env": "N8N_WEBHOOK_CREDENTIAL_ID",
    },
    "telegram": {
        "placeholder": "REPLACE_TELEGRAM_CREDENTIAL",
        "type": "telegramApi",
        "name": "Telegram bot",
        "env": "N8N_TELEGRAM_CREDENTIAL_ID",
    },
}

PLACEHOLDER_RE = re.compile(r"YOUR_[A-Z0-9_]+|REPLACE_[A-Z_]+_CREDENTIAL")

# Keys the public API accepts when creating/updating a workflow.
WORKFLOW_KEYS = ("name", "nodes", "connections", "settings")
SETTINGS_KEYS = ("executionOrder", "timezone", "binaryMode")
SETTINGS_KEYS_MINIMAL = ("executionOrder", "timezone")


# --------------------------------------------------------------------------
# Terminal output
# --------------------------------------------------------------------------

def _supports_color():
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None and os.name != "nt"


_COLOR = _supports_color()


def _c(code, text):
    return "\033[%sm%s\033[0m" % (code, text) if _COLOR else text


def _safe(text):
    """Fall back to ASCII on terminals that can't print the check marks."""
    enc = (getattr(sys.stdout, "encoding", None) or "ascii").lower()
    if "utf" in enc:
        return text
    return (text.replace("✓", "OK").replace("✗", "X").replace("→", "->")
            .replace("·", "-").replace("…", "..."))


def say(text=""):
    print(_safe(text))


def header(text):
    say("")
    say(_c("1", text))


def ok(text):
    say("  " + _c("32", "✓") + " " + text)


def fail(text, fix=None):
    say("  " + _c("31", "✗") + " " + text)
    if fix:
        for line in fix.strip("\n").split("\n"):
            say("      → " + line if line.strip() else "")


def warn(text):
    say("  " + _c("33", "!") + " " + text)


def info(text):
    say("    " + text)


class SetupError(Exception):
    """A step failed; message already explains what to do."""


# --------------------------------------------------------------------------
# .env handling
# --------------------------------------------------------------------------

def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    # strip inline comments for unquoted values: FOO=bar # comment
    m = re.match(r"^(.*?)\s+#.*$", value)
    if m:
        value = m.group(1)
    return value.strip()


def load_env(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = _unquote(value)
    return values


def _quote(value):
    value = "" if value is None else str(value)
    if value == "" or re.match(r"^[A-Za-z0-9_./:@+=,-]*$", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_env(path, updates):
    """Update keys in place (keeping comments and order), append new ones."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    remaining = dict(updates)
    out = []
    for raw in lines:
        stripped = raw.strip()
        m = re.match(r"^(export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped)
        if m and m.group(2) in remaining:
            key = m.group(2)
            out.append("%s%s=%s" % (m.group(1) or "", key, _quote(remaining.pop(key))))
        else:
            out.append(raw)
    if remaining:
        for key, value in remaining.items():
            out.append("%s=%s" % (key, _quote(value)))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Response(object):
    def __init__(self, status, body, headers=None, error=None):
        self.status = status          # int, or None on connection error
        self.body = body or ""        # str
        self.headers = headers or {}
        self.error = error            # str for connection errors

    @property
    def ok(self):
        return self.status is not None and 200 <= self.status < 300

    def json(self):
        try:
            return json.loads(self.body) if self.body else None
        except ValueError:
            return None

    def snippet(self, limit=300):
        text = re.sub(r"\s+", " ", self.body or "").strip()
        return text[:limit] + ("…" if len(text) > limit else "")

    def describe(self):
        if self.status is None:
            return "connection failed: %s" % self.error
        snip = self.snippet()
        return "HTTP %s%s" % (self.status, (" · " + snip) if snip else "")


def http(method, url, headers=None, body=None, timeout=20):
    data = None
    hdrs = {"Accept": "application/json", "User-Agent": "linkedin-n8n-pipeline-setup"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return Response(resp.status, raw, dict(resp.headers))
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return Response(e.code, raw, dict(e.headers or {}))
    except ssl.SSLError as e:
        return Response(None, "", error="TLS error (%s)" % e)
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, ssl.SSLError):
            return Response(None, "", error="TLS error (%s)" % reason)
        if isinstance(reason, socket.gaierror):
            return Response(None, "", error="host not found (%s)" % reason)
        return Response(None, "", error=str(reason))
    except (socket.timeout, TimeoutError):
        return Response(None, "", error="timed out after %ss" % timeout)
    except (ConnectionError, OSError) as e:
        return Response(None, "", error=str(e))


def normalize_url(url):
    url = (url or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        url = "https://" + url
    # People sometimes paste the API or editor URL.
    for suffix in ("/api/v1", "/home/workflows", "/home"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def bare_host(url):
    """https://n8n.example.com/ -> n8n.example.com (keeps a non-default port)."""
    parsed = urllib.parse.urlparse(normalize_url(url))
    return parsed.netloc + parsed.path.rstrip("/")


class N8n(object):
    def __init__(self, base_url, api_key):
        self.base = normalize_url(base_url)
        self.key = api_key

    def call(self, method, path, body=None, query=None, timeout=30):
        url = self.base + "/api/v1" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return http(method, url, {"X-N8N-API-KEY": self.key}, body, timeout=timeout)

    def check(self):
        return self.call("GET", "/workflows", query={"limit": 1})

    def list_all(self, path, query=None, limit=100, max_pages=50):
        """Follow nextCursor. Returns (items, Response-of-last-call)."""
        items, cursor = [], None
        resp = None
        for _ in range(max_pages):
            q = dict(query or {})
            q["limit"] = limit
            if cursor:
                q["cursor"] = cursor
            resp = self.call("GET", path, query=q)
            if not resp.ok:
                return None, resp
            data = resp.json() or {}
            if isinstance(data, list):
                return data, resp
            items.extend(data.get("data") or [])
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return items, resp

    def find_workflows(self, name):
        items, resp = self.list_all("/workflows", {"name": name})
        if items is None:
            return None, resp
        return [w for w in items if w.get("name") == name], resp


def explain_n8n_failure(resp, base_url):
    """Human hint for a failed n8n API call."""
    if resp.status is None:
        return ("Could not reach %s (%s).\n"
                "Check N8N_URL in .env: it must be the address you open n8n at, "
                "e.g. https://n8n.example.com, and the server must be running." % (base_url, resp.error))
    if resp.status == 401:
        return ("n8n rejected the API key (401).\n"
                "Create a new one in n8n → Settings → n8n API → Create API key, "
                "then put it in N8N_API_KEY in .env.")
    if resp.status == 403:
        return ("The API key has no permission for this call (403).\n"
                "If your API key has scopes, give it access to workflows, credentials and data tables.")
    if resp.status == 404:
        return ("n8n answered 404 at %s/api/v1. Is the public API enabled "
                "(N8N_PUBLIC_API_DISABLED must not be true) and is N8N_URL the n8n root URL?" % base_url)
    return "n8n answered %s" % resp.describe()


def workflow_is_active(wf):
    if "activeVersionId" in wf:
        return bool(wf.get("activeVersionId")) or bool(wf.get("active"))
    return bool(wf.get("active"))


def api_payload(wf, minimal_settings=False):
    keys = SETTINGS_KEYS_MINIMAL if minimal_settings else SETTINGS_KEYS
    settings = {k: v for k, v in (wf.get("settings") or {}).items() if k in keys}
    return {
        "name": wf.get("name") or WORKFLOW_NAME,
        "nodes": wf.get("nodes") or [],
        "connections": wf.get("connections") or {},
        "settings": settings,
    }


# --------------------------------------------------------------------------
# Telegram
# --------------------------------------------------------------------------

def telegram_api_base():
    # TELEGRAM_API_BASE lets the test suite point at a mock server.
    return os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")


class Telegram(object):
    def __init__(self, token):
        self.token = token

    def call(self, method, params=None, timeout=20):
        url = "%s/bot%s/%s" % (telegram_api_base(), self.token, method)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        resp = http("GET", url, timeout=timeout)
        # never let the token leak into error text
        if resp.error:
            resp.error = resp.error.replace(self.token, "<token>")
        return resp

