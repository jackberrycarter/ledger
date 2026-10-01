#!/usr/bin/env python3
"""
Ledger server. Serves register.html and stores the ledger as a real
file on disk, so it can actually be backed up.

Standard library only - no pip, no venv, no dependencies.

  python3 ledger-server.py --dir /srv/ledger --port 8787

Endpoints:
  GET  /              -> register.html
  GET  /api/ping      -> {"ledger": true}      (the app probes this)
  GET  /api/data      -> current ledger JSON
  PUT  /api/data      -> replace ledger JSON (atomic write + rolling snapshots)
  GET  /api/bank-sync -> pulls accounts+transactions from SimpleFIN and hands
                          back a trimmed JSON blob; the frontend does all the
                          matching. Reads the access URL from
                          simplefin-access-url in --dir (never sent to the
                          browser). ?since=<unix ts>, defaults to 90 days back.

Bind to the LAN only. Do not port-forward this and do not put it behind a
public tunnel; it has no authentication and it is your household finances.
"""

import argparse, json, os, shutil, sys, tempfile, datetime, threading
import base64, urllib.request, urllib.error
from urllib.parse import urlsplit, urlunsplit, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
MAX_BODY = 8 * 1024 * 1024        # 8 MB ceiling; a big ledger is ~1 MB
SNAPSHOTS = 30                    # rolling in-place snapshots
ACCESS_URL_NAME = "simplefin-access-url"


class Handler(BaseHTTPRequestHandler):
    server_version = "ledger/1.0"

    # ---------- helpers ----------
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj).encode("utf-8"))

    @property
    def data_file(self):
        return os.path.join(self.server.data_dir, "ledger.json")

    def log_message(self, fmt, *args):
        sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------- routes ----------
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"

        if path in ("/", "/index.html"):
            page = os.path.join(self.server.data_dir, "register.html")
            if not os.path.exists(page):
                return self._send(404, b"register.html not found in data dir", "text/plain")
            with open(page, "rb") as fh:
                body = fh.read()
            return self._send(200, body, "text/html; charset=utf-8")

        if path == "/retirement.html":
            page = os.path.join(self.server.data_dir, "retirement.html")
            if not os.path.exists(page):
                return self._send(404, b"retirement.html not found in data dir", "text/plain")
            with open(page, "rb") as fh:
                body = fh.read()
            return self._send(200, body, "text/html; charset=utf-8")

        if path == "/api/ping":
            return self._json(200, {"ledger": True, "version": 1})

        if path == "/api/bank-sync":
            qs = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            return self._bank_sync(qs)

        if path == "/api/data":
            with LOCK:
                if not os.path.exists(self.data_file):
                    return self._json(200, {})
                try:
                    with open(self.data_file, "r", encoding="utf-8") as fh:
                        return self._send(200, fh.read().encode("utf-8"))
                except Exception as exc:
                    return self._json(500, {"error": str(exc)})

        return self._json(404, {"error": "not found"})

    def do_PUT(self):
        if self.path.split("?")[0].rstrip("/") != "/api/data":
            return self._json(404, {"error": "not found"})

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"error": "bad length"})
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"error": "body too large or empty"})

        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "not valid JSON"})
        # refuse to overwrite good data with something that isn't a ledger
        if not isinstance(parsed, dict) or "accounts" not in parsed:
            return self._json(400, {"error": "not a ledger payload"})

        with LOCK:
            try:
                self._snapshot()
                d = os.path.dirname(self.data_file)
                fd, tmp = tempfile.mkstemp(dir=d, prefix=".ledger-", suffix=".tmp")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(raw)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, self.data_file)          # atomic
            except Exception as exc:
                return self._json(500, {"error": str(exc)})

        return self._json(200, {"ok": True, "bytes": len(raw)})

    # ---------- bank sync (SimpleFIN) ----------
    def _bank_sync(self, qs):
        access_path = os.path.join(self.server.data_dir, ACCESS_URL_NAME)
        if not os.path.exists(access_path):
            return self._json(503, {"error": "no bank access configured"})
        with open(access_path, "r", encoding="utf-8") as fh:
            access_url = fh.read().strip()

        try:
            since = int(qs.get("since", ["0"])[0])
        except ValueError:
            since = 0
        if since <= 0:
            since = int(datetime.datetime.now().timestamp()) - 90 * 86400

        parts = urlsplit(access_url)
        auth = base64.b64encode(("%s:%s" % (parts.username, parts.password)).encode()).decode()
        netloc = parts.hostname + (":%d" % parts.port if parts.port else "")
        base = urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))
        req = urllib.request.Request(
            "%s/accounts?start-date=%d" % (base, since),
            headers={
                "Authorization": "Basic %s" % auth,
                # SimpleFIN Bridge sits behind Cloudflare, which 403s
                # urllib's default "Python-urllib/x.y" UA (Cloudflare error
                # 1010) even though the same request works fine from curl.
                "User-Agent": "Mozilla/5.0 (ledger-server)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            return self._json(exc.code, {"error": "bank sync failed: %s" % exc.reason})
        except urllib.error.URLError as exc:
            return self._json(502, {"error": "bank sync unreachable: %s" % exc.reason})

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            return self._json(502, {"error": "bank returned unreadable data"})

        # Trim to just what the register needs - never forward org/holdings.
        out = {"accounts": [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "balance": a.get("balance"),
                "balanceDate": a.get("balance-date"),
                "transactions": [
                    {
                        "id": t.get("id"),
                        "posted": t.get("posted"),
                        "amount": t.get("amount"),
                        "payee": t.get("payee") or t.get("description") or "",
                        "memo": t.get("memo") or "",
                    }
                    for t in a.get("transactions", [])
                ],
            }
            for a in data.get("accounts", [])
        ]}
        if data.get("errors"):
            out["bankErrors"] = data["errors"]
        return self._json(200, out)

    # ---------- rolling snapshots ----------
    def _snapshot(self):
        if not os.path.exists(self.data_file):
            return
        snaps = os.path.join(self.server.data_dir, "snapshots")
        os.makedirs(snaps, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(self.data_file, os.path.join(snaps, "ledger-%s.json" % stamp))
        keep = sorted(os.listdir(snaps))
        for old in keep[:-SNAPSHOTS]:
            try:
                os.remove(os.path.join(snaps, old))
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/srv/ledger",
                    help="holds register.html, ledger.json and snapshots/")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="0.0.0.0", help="use 0.0.0.0 for LAN access")
    args = ap.parse_args()

    os.makedirs(args.dir, exist_ok=True)
    os.makedirs(os.path.join(args.dir, "snapshots"), exist_ok=True)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.data_dir = os.path.abspath(args.dir)
    print("ledger server on http://%s:%d  (data: %s)" % (args.host, args.port, httpd.data_dir))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
