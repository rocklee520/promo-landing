#!/usr/bin/env python3
"""Promo landing server: static files + content API."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
SEED_CONTENT = ROOT / "data" / "content.json"
DATA_DIR = Path(os.environ.get("DATA_DIR") or (ROOT / "data"))
CONTENT_PATH = DATA_DIR / "content.json"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))

# Optional: persist content to a GitHub file so free hosts keep edits after restart
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()  # owner/repo
GITHUB_CONTENT_PATH = os.environ.get("GITHUB_CONTENT_PATH", "data/content.json").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()


def ensure_content_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CONTENT_PATH.exists():
        return
    if SEED_CONTENT.exists() and SEED_CONTENT.resolve() != CONTENT_PATH.resolve():
        CONTENT_PATH.write_bytes(SEED_CONTENT.read_bytes())
    elif SEED_CONTENT.exists():
        return
    else:
        raise SystemExit(f"缺少内容文件: {SEED_CONTENT}")


def _github_api(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "promo-landing",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def github_enabled() -> bool:
    return bool(GITHUB_TOKEN and GITHUB_REPO)


def read_content_from_github() -> dict | None:
    if not github_enabled():
        return None
    api = (
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/"
        f"{GITHUB_CONTENT_PATH}?ref={GITHUB_BRANCH}"
    )
    try:
        meta = _github_api(api)
        encoded = meta.get("content", "").replace("\n", "")
        text = base64.b64decode(encoded).decode("utf-8")
        return json.loads(text)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"GitHub read skipped: {exc}\n")
        return None


def write_content_to_github(data: dict) -> None:
    if not github_enabled():
        return
    api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_CONTENT_PATH}"
    sha = None
    try:
        meta = _github_api(f"{api}?ref={GITHUB_BRANCH}")
        sha = meta.get("sha")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    body = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    payload = {
        "message": "chore: update site content via admin",
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    _github_api(api, method="PUT", payload=payload)


def read_content() -> dict:
    with CONTENT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_content_local(data: dict) -> None:
    CONTENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONTENT_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(CONTENT_PATH)


def write_content(data: dict) -> None:
    write_content_local(data)
    write_content_to_github(data)


class Handler(BaseHTTPRequestHandler):
    server_version = "PromoLanding/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Password")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/content":
            try:
                self._json(200, read_content())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "persist": "github" if github_enabled() else "local",
                },
            )
            return

        rel = path.lstrip("/") or "index.html"
        file_path = (ROOT / rel).resolve()
        if not str(file_path).startswith(str(ROOT)) or not file_path.is_file():
            if path in ("/", "/index", "/index.html"):
                file_path = ROOT / "index.html"
            elif path in ("/admin", "/admin.html"):
                file_path = ROOT / "admin.html"
            elif path in ("/post", "/post.html"):
                file_path = ROOT / "post.html"
            elif path in ("/search", "/search.html"):
                file_path = ROOT / "search.html"
            else:
                self._json(404, {"error": "not found"})
                return

        data = file_path.read_bytes()
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.suffix in {".html", ".css", ".js", ".json"}:
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }[file_path.suffix]
        self._bytes(200, data, ctype)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/content":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            incoming = json.loads(raw.decode("utf-8"))
            current = read_content()
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"error": f"invalid json: {exc}"})
            return

        password = self.headers.get("X-Admin-Password") or ""
        expected = (current.get("site") or {}).get("adminPassword") or "admin123"
        if password != expected:
            self._json(401, {"error": "密码错误"})
            return

        if not isinstance(incoming, dict) or "posts" not in incoming:
            self._json(400, {"error": "内容格式不正确"})
            return

        try:
            write_content(incoming)
            self._json(200, {"ok": True, "content": incoming})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})


def main() -> None:
    ensure_content_file()
    # Prefer remote content when GitHub sync is configured (survives free-host restarts)
    remote = read_content_from_github()
    if remote is not None:
        write_content_local(remote)
        print("已从 GitHub 同步内容")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"前台:  http://127.0.0.1:{PORT}/")
    print(f"后台:  http://127.0.0.1:{PORT}/admin.html")
    print(f"持久化: {'GitHub ' + GITHUB_REPO if github_enabled() else str(CONTENT_PATH)}")
    print("按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
