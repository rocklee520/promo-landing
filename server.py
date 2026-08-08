#!/usr/bin/env python3
"""Promo landing server: static files + content API + real view counters."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
SEED_CONTENT = ROOT / "data" / "content.json"
DATA_DIR = Path(os.environ.get("DATA_DIR") or (ROOT / "data"))
CONTENT_PATH = DATA_DIR / "content.json"
VIEWS_PATH = DATA_DIR / "views.json"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))

# Optional: persist content to a GitHub file so free hosts keep edits after restart
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "").strip()  # owner/repo
GITHUB_CONTENT_PATH = os.environ.get("GITHUB_CONTENT_PATH", "data/content.json").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()

CONTENT_LOCK = threading.RLock()
# ip+post_id -> last view timestamp (anti-refresh spam, in-memory)
RECENT_VIEWS: dict[str, float] = {}
VIEW_COOLDOWN_SEC = 6 * 60 * 60  # 6 hours per IP per post


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


def ensure_views_file() -> None:
    """Seed views.json from content.json so existing numbers become the baseline."""
    existing = read_views() if VIEWS_PATH.exists() else {}
    if existing:
        return
    try:
        content = _read_json(CONTENT_PATH)
    except Exception:  # noqa: BLE001
        content = {}
    views: dict[str, int] = {}
    for post in content.get("posts") or []:
        pid = post.get("id")
        if pid:
            views[str(pid)] = int(post.get("views") or 0)
    _write_json(VIEWS_PATH, views)


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


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


def read_views() -> dict[str, int]:
    if not VIEWS_PATH.exists():
        return {}
    raw = _read_json(VIEWS_PATH)
    out: dict[str, int] = {}
    for key, val in raw.items():
        try:
            out[str(key)] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def write_views(views: dict[str, int]) -> None:
    _write_json(VIEWS_PATH, views)


def merge_views_into_content(content: dict, views: dict[str, int] | None = None) -> dict:
    views = views if views is not None else read_views()
    posts = content.get("posts")
    if not isinstance(posts, list):
        return content
    for post in posts:
        if not isinstance(post, dict):
            continue
        pid = str(post.get("id") or "")
        if not pid:
            continue
        if pid in views:
            post["views"] = int(views[pid])
        else:
            post["views"] = int(post.get("views") or 0)
            views[pid] = post["views"]
    return content


def read_content(*, with_views: bool = True) -> dict:
    with CONTENT_LOCK:
        content = _read_json(CONTENT_PATH)
        if with_views:
            content = merge_views_into_content(content)
        return content


def write_content_local(data: dict) -> None:
    _write_json(CONTENT_PATH, data)


def write_content(data: dict) -> None:
    with CONTENT_LOCK:
        views = read_views()
        # Keep real counters unless admin explicitly changed a post's views.
        for post in data.get("posts") or []:
            if not isinstance(post, dict):
                continue
            pid = str(post.get("id") or "")
            if not pid:
                continue
            try:
                incoming = int(post.get("views") or 0)
            except (TypeError, ValueError):
                incoming = 0
            current = int(views.get(pid, 0))
            # Admin form may send stale lower number; never decrease automatically.
            views[pid] = max(current, incoming)
            post["views"] = views[pid]
        write_views(views)
        write_content_local(data)
    write_content_to_github(data)


def increment_view(post_id: str, client_key: str) -> tuple[bool, int]:
    """Return (counted, views). counted=False when cooldown hit."""
    now = time.time()
    gate = f"{client_key}:{post_id}"
    with CONTENT_LOCK:
        last = RECENT_VIEWS.get(gate, 0)
        views = read_views()
        # Ensure post exists
        content = _read_json(CONTENT_PATH)
        ids = {str(p.get("id")) for p in (content.get("posts") or []) if isinstance(p, dict)}
        if post_id not in ids:
            return False, 0
        current = int(views.get(post_id, 0))
        if now - last < VIEW_COOLDOWN_SEC:
            return False, current
        current += 1
        views[post_id] = current
        write_views(views)
        # Mirror into content.json so backups / redeploys keep counts
        for post in content.get("posts") or []:
            if isinstance(post, dict) and str(post.get("id")) == post_id:
                post["views"] = current
                break
        write_content_local(content)
        RECENT_VIEWS[gate] = now
        # light cleanup
        if len(RECENT_VIEWS) > 5000:
            cutoff = now - VIEW_COOLDOWN_SEC
            for key in list(RECENT_VIEWS.keys()):
                if RECENT_VIEWS[key] < cutoff:
                    RECENT_VIEWS.pop(key, None)
        return True, current


class Handler(BaseHTTPRequestHandler):
    server_version = "PromoLanding/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, X-Admin-Password, X-View-Token",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")

    def _json(self, code: int, payload: dict, set_cookie: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._cors()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
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

    def _client_key(self) -> str:
        # Prefer cookie token; fallback to IP
        cookie = SimpleCookie()
        if "Cookie" in self.headers:
            cookie.load(self.headers["Cookie"])
        if "vid" in cookie and cookie["vid"].value:
            return f"c:{cookie['vid'].value}"
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        ip = forwarded or (self.client_address[0] if self.client_address else "unknown")
        return f"ip:{ip}"

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/content":
            try:
                self._json(200, read_content(with_views=True))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "persist": "github" if github_enabled() else "local",
                    "views": True,
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

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path != "/api/view":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        post_id = ""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if isinstance(payload, dict):
                post_id = str(payload.get("id") or "").strip()
        except Exception:  # noqa: BLE001
            payload = {}
        if not post_id:
            qs = parse_qs(parsed.query)
            post_id = (qs.get("id") or [""])[0].strip()
        if not post_id:
            self._json(400, {"error": "missing id"})
            return

        cookie = SimpleCookie()
        if "Cookie" in self.headers:
            cookie.load(self.headers["Cookie"])
        set_cookie = None
        if "vid" not in cookie or not cookie["vid"].value:
            token = base64.urlsafe_b64encode(os.urandom(12)).decode("ascii").rstrip("=")
            set_cookie = f"vid={token}; Path=/; Max-Age=31536000; SameSite=Lax"

        # Cooldown by IP (stable even when cookie not yet stored by client)
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        ip = forwarded or (self.client_address[0] if self.client_address else "unknown")
        client_key = f"ip:{ip}"

        try:
            counted, views = increment_view(post_id, client_key)
            self._json(
                200,
                {"ok": True, "id": post_id, "counted": counted, "views": views},
                set_cookie=set_cookie,
            )
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/content":
            self._json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            incoming = json.loads(raw.decode("utf-8"))
            current = read_content(with_views=True)
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
            self._json(200, {"ok": True, "content": read_content(with_views=True)})
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})


def main() -> None:
    ensure_content_file()
    ensure_views_file()
    # Prefer remote content when GitHub sync is configured (survives free-host restarts)
    remote = read_content_from_github()
    if remote is not None:
        with CONTENT_LOCK:
            write_content_local(remote)
            # Refresh views baseline from remote content if views file empty-ish
            views = read_views()
            for post in remote.get("posts") or []:
                if not isinstance(post, dict):
                    continue
                pid = str(post.get("id") or "")
                if not pid:
                    continue
                views[pid] = max(int(views.get(pid, 0)), int(post.get("views") or 0))
            write_views(views)
        print("已从 GitHub 同步内容")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"前台:  http://127.0.0.1:{PORT}/")
    print(f"后台:  http://127.0.0.1:{PORT}/admin.html")
    print(f"浏览量: {VIEWS_PATH}")
    print(f"持久化: {'GitHub ' + GITHUB_REPO if github_enabled() else str(CONTENT_PATH)}")
    print("按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
