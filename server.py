#!/usr/bin/env python3
"""Promo landing server: static files + content API + real view counters."""

from __future__ import annotations

import base64
import gzip
import json
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
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
ORDERS_PATH = DATA_DIR / "orders.json"
THUMBS_DIR = DATA_DIR / "thumbs"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
THUMB_WIDTHS = {240, 360, 480, 720, 960}
# Free Render instances are ~512MB; avoid loading many full images at once.
THUMB_MAX_SRC_BYTES = int(os.environ.get("THUMB_MAX_SRC_BYTES", str(1_500_000)))
THUMB_SEM = threading.Semaphore(int(os.environ.get("THUMB_CONCURRENCY", "1")))
STATIC_CHUNK = 64 * 1024

# Persist across Render redeploys via GitHub (public raw read; token optional for write-back)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "rocklee520/promo-landing").strip()
GITHUB_CONTENT_PATH = os.environ.get("GITHUB_CONTENT_PATH", "data/content.json").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip()
# Preferred admin password for production (set in Render Environment)
ADMIN_PASSWORD_ENV = os.environ.get("ADMIN_PASSWORD", "").strip()
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
PUSHPLUS_TOKEN_ENV = os.environ.get("PUSHPLUS_TOKEN", "").strip()

CONTENT_LOCK = threading.RLock()
ORDERS_LOCK = threading.RLock()
# ip+post_id -> last view timestamp (anti-refresh spam, in-memory)
RECENT_VIEWS: dict[str, float] = {}
VIEW_COOLDOWN_SEC = 6 * 60 * 60  # 6 hours per IP per post
VIEWS_DIRTY = False
LAST_GITHUB_PUSH = 0.0
GITHUB_PUSH_MIN_INTERVAL = 60.0  # seconds


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


def ensure_orders_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not ORDERS_PATH.exists():
        _write_json(ORDERS_PATH, {"orders": []})


def ensure_thumbs_dir() -> None:
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_asset_path(url_path: str) -> Path | None:
    """Only allow files under ROOT/assets."""
    raw = str(url_path or "").strip()
    if not raw.startswith("/assets/"):
        return None
    rel = raw.lstrip("/")
    candidate = (ROOT / rel).resolve()
    assets_root = (ROOT / "assets").resolve()
    if not str(candidate).startswith(str(assets_root)):
        return None
    if not candidate.is_file():
        return None
    return candidate


def is_animated_image(src: Path) -> bool:
    suf = src.suffix.lower()
    if suf == ".gif":
        return True
    if suf != ".webp":
        return False
    try:
        with src.open("rb") as fh:
            head = fh.read(64)
        return len(head) > 20 and head[12:16] == b"VP8X" and bool(head[20] & 0x02)
    except OSError:
        return False


def make_thumb_bytes(src: Path, width: int) -> tuple[bytes, str]:
    """Return (bytes, content_type) WebP thumbnail, falling back to JPEG."""
    from PIL import Image, ImageOps  # lazy import
    import io

    # Cap decode size to avoid huge RGBA buffers on free instances
    Image.MAX_IMAGE_PIXELS = 25_000_000

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        # Prefer thumbnail() over full-res decode+resize when possible
        try:
            im.draft("RGB", (width, width * 4))
        except Exception:  # noqa: BLE001
            pass
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        im.thumbnail((width, width * 4), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        try:
            if im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.save(buf, format="WEBP", quality=70, method=0)
            return buf.getvalue(), "image/webp"
        except Exception:  # noqa: BLE001
            buf = io.BytesIO()
            if im.mode != "RGB":
                im = im.convert("RGB")
            im.save(buf, format="JPEG", quality=75, optimize=True)
            return buf.getvalue(), "image/jpeg"


def get_or_create_thumb(src: Path, width: int) -> tuple[bytes, str]:
    ensure_thumbs_dir()
    width = int(width)
    if width not in THUMB_WIDTHS:
        width = min(THUMB_WIDTHS, key=lambda x: abs(x - width))
    # Cache key from relative path + mtime + width
    try:
        rel = src.resolve().relative_to((ROOT / "assets").resolve()).as_posix()
    except Exception:  # noqa: BLE001
        rel = src.name
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", rel)
    mtime = int(src.stat().st_mtime)
    cache_path = THUMBS_DIR / f"{safe}.w{width}.{mtime}.webp"
    # Also accept jpeg fallback cache name
    cache_jpg = THUMBS_DIR / f"{safe}.w{width}.{mtime}.jpg"
    if cache_path.exists():
        return cache_path.read_bytes(), "image/webp"
    if cache_jpg.exists():
        return cache_jpg.read_bytes(), "image/jpeg"
    with THUMB_SEM:
        # Re-check cache after waiting (another thread may have filled it)
        if cache_path.exists():
            return cache_path.read_bytes(), "image/webp"
        if cache_jpg.exists():
            return cache_jpg.read_bytes(), "image/jpeg"
        data, ctype = make_thumb_bytes(src, width)
        try:
            out = cache_path if ctype == "image/webp" else cache_jpg
            tmp = out.with_suffix(out.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(out)
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(f"thumb cache write skipped: {exc}\n")
        return data, ctype


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
    """Prefer public raw URL (works without token); fall back to Contents API."""
    if GITHUB_REPO:
        raw = (
            f"https://raw.githubusercontent.com/{GITHUB_REPO}/"
            f"{GITHUB_BRANCH}/{GITHUB_CONTENT_PATH}?t={int(time.time())}"
        )
        try:
            req = urllib.request.Request(raw, headers={"User-Agent": "promo-landing"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(f"GitHub raw read skipped: {exc}\n")
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
        sys.stdout.write(f"GitHub API read skipped: {exc}\n")
        return None


def write_content_to_github(data: dict, message: str = "chore: sync site content/views") -> None:
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
    # Never push admin password from env-only setups as empty wipe incorrectly
    body_data = json.loads(json.dumps(data))
    site = body_data.get("site")
    if isinstance(site, dict) and ADMIN_PASSWORD_ENV:
        # Keep file password blank; auth uses env
        site["adminPassword"] = ""
    body = json.dumps(body_data, ensure_ascii=False, indent=2) + "\n"
    payload = {
        "message": message,
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    _github_api(api, method="PUT", payload=payload)


def merge_remote_views(local_content: dict, remote: dict) -> dict:
    """Keep the higher view count for each post id."""
    remote_map = {
        str(p.get("id")): int(p.get("views") or 0)
        for p in (remote.get("posts") or [])
        if isinstance(p, dict) and p.get("id")
    }
    for post in local_content.get("posts") or []:
        if not isinstance(post, dict) or not post.get("id"):
            continue
        pid = str(post["id"])
        post["views"] = max(int(post.get("views") or 0), remote_map.get(pid, 0))
    return local_content


def _post_updated_at(post: dict) -> str:
    return str(post.get("updatedAt") or post.get("date") or "")


_PRESERVE_POST_KEYS = (
    "title",
    "price",
    "subtitle",
    "summary",
    "cover",
    "link",
    "downloadNote",
    "fulfillmentLink",
    "updates",
    "series",
)


def _fill_empties(keep: dict, older: dict) -> dict:
    """Don't let blank/redacted fields wipe known good values."""
    for key in _PRESERVE_POST_KEYS:
        if not str(keep.get(key) or "").strip() and str(older.get(key) or "").strip():
            keep[key] = older.get(key)
    if not keep.get("gallery") and older.get("gallery"):
        keep["gallery"] = older.get("gallery")
    if not keep.get("tags") and older.get("tags"):
        keep["tags"] = older.get("tags")
    return keep


def merge_posts_by_id(primary: dict, secondary: dict) -> dict:
    """Merge posts by id. Newer updatedAt wins field values; views always take max."""
    merged = json.loads(json.dumps(primary))
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for source in (merged.get("posts") or []) + (secondary.get("posts") or []):
        if not isinstance(source, dict) or not source.get("id"):
            continue
        pid = str(source["id"])
        if pid not in by_id:
            by_id[pid] = json.loads(json.dumps(source))
            order.append(pid)
            continue
        cur = by_id[pid]
        views = max(int(cur.get("views") or 0), int(source.get("views") or 0))
        if _post_updated_at(source) >= _post_updated_at(cur):
            keep = _fill_empties(json.loads(json.dumps(source)), cur)
            keep["views"] = views
            by_id[pid] = keep
        else:
            cur = _fill_empties(cur, source)
            cur["views"] = views
            by_id[pid] = cur
    merged["posts"] = [by_id[pid] for pid in order if pid in by_id]
    # Prefer secondary site/nav/tags only when primary missing pieces
    if secondary.get("nav") and not merged.get("nav"):
        merged["nav"] = secondary.get("nav")
    if secondary.get("tags") and not merged.get("tags"):
        merged["tags"] = secondary.get("tags")
    return merged


def merge_site_config(base: dict | None, overlay: dict | None) -> dict:
    """Merge site objects; never blank out password / pay secrets with empty overlay values."""
    out = {}
    if isinstance(base, dict):
        out.update(base)
    if isinstance(overlay, dict):
        for key, val in overlay.items():
            if key == "pay":
                continue
            if key == "adminPassword" and not str(val or "").strip():
                continue
            out[key] = val
    base_pay = (base or {}).get("pay") if isinstance(base, dict) else {}
    over_pay = (overlay or {}).get("pay") if isinstance(overlay, dict) else {}
    pay: dict = {}
    if isinstance(base_pay, dict):
        pay.update(base_pay)
    if isinstance(over_pay, dict):
        for key, val in over_pay.items():
            if not str(val or "").strip() and str(pay.get(key) or "").strip():
                continue
            pay[key] = val
    if pay:
        out["pay"] = pay
    return out


def content_updated_at(content: dict | None) -> str:
    if not isinstance(content, dict):
        return ""
    site = content.get("site")
    if not isinstance(site, dict):
        return ""
    return str(site.get("contentUpdatedAt") or "").strip()


def stamp_content_updated(content: dict) -> dict:
    site = content.setdefault("site", {})
    if not isinstance(site, dict):
        site = {}
        content["site"] = site
    site["contentUpdatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return content


def merge_admin_put(current: dict, incoming: dict) -> dict:
    """
    Admin full save: incoming catalog wins, but never clobber a post that became
    newer on the server (e.g. concurrent upsert) since the admin form was loaded.
    """
    out = json.loads(json.dumps(incoming))
    cur_by_id = {
        str(p.get("id")): p
        for p in (current.get("posts") or [])
        if isinstance(p, dict) and p.get("id")
    }
    posts_out: list[dict] = []
    seen: set[str] = set()
    for post in out.get("posts") or []:
        if not isinstance(post, dict) or not post.get("id"):
            continue
        pid = str(post["id"])
        seen.add(pid)
        cur = cur_by_id.get(pid)
        if cur and _post_updated_at(cur) > _post_updated_at(post):
            keep = _fill_empties(json.loads(json.dumps(cur)), post)
            keep["views"] = max(int(cur.get("views") or 0), int(post.get("views") or 0))
            posts_out.append(keep)
        else:
            keep = _fill_empties(json.loads(json.dumps(post)), cur or {})
            if cur:
                keep["views"] = max(int(cur.get("views") or 0), int(post.get("views") or 0))
            posts_out.append(keep)
    out["posts"] = posts_out
    out["site"] = merge_site_config(
        current.get("site") if isinstance(current.get("site"), dict) else {},
        out.get("site") if isinstance(out.get("site"), dict) else {},
    )
    if not out.get("nav") and current.get("nav"):
        out["nav"] = current.get("nav")
    if not out.get("tags") and current.get("tags"):
        out["tags"] = current.get("tags")
    stamp_content_updated(out)
    return out


def merge_stale_put(current: dict, incoming: dict) -> dict:
    """Agent/stale full PUT: keep current as base; only apply newer incoming posts/site."""
    out = json.loads(json.dumps(current))
    cur_by_id = {
        str(p.get("id")): p
        for p in (out.get("posts") or [])
        if isinstance(p, dict) and p.get("id")
    }
    newer_posts: list[dict] = []
    for src in incoming.get("posts") or []:
        if not isinstance(src, dict) or not src.get("id"):
            continue
        pid = str(src["id"])
        cur = cur_by_id.get(pid)
        # New ids always apply; existing ids only if incoming is as new or newer
        if not cur or _post_updated_at(src) >= _post_updated_at(cur):
            newer_posts.append(src)
    if newer_posts:
        out = upsert_posts_into(out, newer_posts)
    inc_ts = content_updated_at(incoming)
    cur_ts = content_updated_at(current)
    if inc_ts and (not cur_ts or inc_ts >= cur_ts):
        out["site"] = merge_site_config(
            current.get("site") if isinstance(current.get("site"), dict) else {},
            incoming.get("site") if isinstance(incoming.get("site"), dict) else {},
        )
        if incoming.get("nav"):
            out["nav"] = incoming["nav"]
        if incoming.get("tags"):
            out["tags"] = incoming["tags"]
    else:
        # Keep current site; fill only empty pay/name fields from incoming
        out["site"] = merge_site_config(
            incoming.get("site") if isinstance(incoming.get("site"), dict) else {},
            current.get("site") if isinstance(current.get("site"), dict) else {},
        )
    stamp_content_updated(out)
    return out


def rehydrate_secrets_from_trusted(incoming: dict, trusted: dict) -> dict:
    """
    Public /api/content redacts fulfillmentLink / pushPlusToken.
    Restore those from trusted disk/repo copy without blocking intentional admin clears
    (admin sends fulfillmentLink:"" explicitly; public omits the key or sets purchaseRequired).
    """
    out = json.loads(json.dumps(incoming))
    trusted_posts = {
        str(p.get("id")): p
        for p in (trusted.get("posts") or [])
        if isinstance(p, dict) and p.get("id")
    }
    for post in out.get("posts") or []:
        if not isinstance(post, dict) or not post.get("id"):
            continue
        old = trusted_posts.get(str(post["id"])) or {}
        if not old:
            continue
        # Missing key => redacted / omitted — restore
        for key in _PRESERVE_POST_KEYS:
            if key not in post and str(old.get(key) or "").strip():
                post[key] = old.get(key)
        # Paid public payload blanks link and drops fulfillmentLink
        if post.get("purchaseRequired") and not str(post.get("fulfillmentLink") or "").strip():
            if str(old.get("fulfillmentLink") or "").strip():
                post["fulfillmentLink"] = old.get("fulfillmentLink")
            elif str(old.get("link") or "").strip():
                post["fulfillmentLink"] = old.get("link")
        if not post.get("gallery") and old.get("gallery"):
            post["gallery"] = old.get("gallery")
    out["site"] = merge_site_config(
        trusted.get("site") if isinstance(trusted.get("site"), dict) else {},
        out.get("site") if isinstance(out.get("site"), dict) else {},
    )
    return out


def upsert_posts_into(content: dict, posts: list) -> dict:
    """Insert/update posts by id (incoming wins field merge); preserve empties from existing."""
    out = json.loads(json.dumps(content))
    by_id = {
        str(p.get("id")): p
        for p in (out.get("posts") or [])
        if isinstance(p, dict) and p.get("id")
    }
    order = [str(p.get("id")) for p in (out.get("posts") or []) if isinstance(p, dict) and p.get("id")]
    for src in posts:
        if not isinstance(src, dict) or not src.get("id"):
            continue
        pid = str(src["id"])
        if pid in by_id:
            cur = by_id[pid]
            views = max(int(cur.get("views") or 0), int(src.get("views") or 0))
            keep = _fill_empties(json.loads(json.dumps(src)), cur)
            # Explicit incoming fields win even if empty when key present? Prefer fill empties for safety.
            keep["views"] = views
            if not keep.get("updatedAt"):
                keep["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            by_id[pid] = keep
        else:
            neu = json.loads(json.dumps(src))
            if not neu.get("updatedAt"):
                neu["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            by_id[pid] = neu
            order.insert(0, pid)
    out["posts"] = [by_id[pid] for pid in order if pid in by_id]
    return out


def restore_from_github() -> bool:
    """On boot: pull latest content/views from GitHub so redeploys don't reset counters."""
    remote = read_content_from_github()
    if not remote or "posts" not in remote:
        return False
    with CONTENT_LOCK:
        local = _read_json(CONTENT_PATH) if CONTENT_PATH.exists() else {"posts": []}
        # Rehydrate secrets that public backups may have blanked, then merge both ways
        remote = rehydrate_secrets_from_trusted(remote, local)
        local_ts = content_updated_at(local)
        remote_ts = content_updated_at(remote)
        # Prefer whichever side the admin (or upsert) stamped more recently.
        # This stops a stale GitHub content.json from wiping Render-disk admin edits.
        local_newer = bool(local_ts and (not remote_ts or local_ts >= remote_ts))
        if local_newer:
            merged = merge_posts_by_id(local, remote)
            merged["site"] = merge_site_config(
                remote.get("site") if isinstance(remote.get("site"), dict) else {},
                local.get("site") if isinstance(local.get("site"), dict) else {},
            )
            if local.get("nav"):
                merged["nav"] = local["nav"]
            elif remote.get("nav"):
                merged["nav"] = remote["nav"]
            if local.get("tags"):
                merged["tags"] = local["tags"]
            elif remote.get("tags"):
                merged["tags"] = remote["tags"]
        else:
            merged = merge_posts_by_id(remote, local)
            merged["site"] = merge_site_config(
                local.get("site") if isinstance(local.get("site"), dict) else {},
                remote.get("site") if isinstance(remote.get("site"), dict) else {},
            )
            if remote.get("nav"):
                merged["nav"] = remote["nav"]
            elif local.get("nav"):
                merged["nav"] = local["nav"]
            if remote.get("tags"):
                merged["tags"] = remote["tags"]
            elif local.get("tags"):
                merged["tags"] = local["tags"]
        merged = merge_remote_views(merged, local)
        views = {
            str(p.get("id")): int(p.get("views") or 0)
            for p in (merged.get("posts") or [])
            if isinstance(p, dict) and p.get("id")
        }
        write_content_local(merged)
        write_views(views)
    return True


def mark_views_dirty() -> None:
    global VIEWS_DIRTY
    VIEWS_DIRTY = True


def flush_views_to_github(force: bool = False) -> None:
    global VIEWS_DIRTY, LAST_GITHUB_PUSH
    if not github_enabled():
        return
    now = time.time()
    with CONTENT_LOCK:
        if not VIEWS_DIRTY and not force:
            return
        if not force and now - LAST_GITHUB_PUSH < GITHUB_PUSH_MIN_INTERVAL:
            return
        content = merge_views_into_content(_read_json(CONTENT_PATH), read_views())
        try:
            write_content_to_github(content, message="backup: sync view counts")
            VIEWS_DIRTY = False
            LAST_GITHUB_PUSH = now
            sys.stdout.write("已回写浏览量到 GitHub\n")
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(f"GitHub 回写失败: {exc}\n")


def github_flusher() -> None:
    while True:
        time.sleep(30)
        try:
            flush_views_to_github(force=False)
        except Exception as exc:  # noqa: BLE001
            sys.stdout.write(f"flusher error: {exc}\n")


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


def expected_admin_password(content: dict | None = None) -> str:
    if ADMIN_PASSWORD_ENV:
        return ADMIN_PASSWORD_ENV
    content = content if content is not None else read_content(with_views=False)
    return (content.get("site") or {}).get("adminPassword") or "admin123"


def post_fulfillment_link(post: dict) -> str:
    return str(post.get("fulfillmentLink") or post.get("link") or "").strip()


def post_requires_purchase(post: dict) -> bool:
    return bool(str(post.get("price") or "").strip() and post_fulfillment_link(post))


def format_amount_label(price) -> str:
    s = str(price or "").strip()
    if not s:
        return ""
    return s if re.search(r"[元￥$¥]", s) else f"{s}元"


def public_pay_config(site: dict | None) -> dict:
    pay = (site or {}).get("pay") if isinstance(site, dict) else None
    if not isinstance(pay, dict):
        pay = {}
    return {
        "wechatQr": str(pay.get("wechatQr") or "").strip(),
        "alipayQr": str(pay.get("alipayQr") or "").strip(),
        "note": str(pay.get("note") or "付款时请在备注/说明里填写订单号，付完回到本页点「我已付款」。").strip(),
    }


def pushplus_token(content: dict | None = None) -> str:
    if PUSHPLUS_TOKEN_ENV:
        return PUSHPLUS_TOKEN_ENV
    content = content if content is not None else read_content(with_views=False)
    pay = (content.get("site") or {}).get("pay") if isinstance(content.get("site"), dict) else {}
    if isinstance(pay, dict):
        return str(pay.get("pushPlusToken") or "").strip()
    return ""


def public_content(content: dict, *, admin: bool = False, lite: bool = False) -> dict:
    """Hide secrets from public API; admin=True keeps fulfillment links / push token.

    lite=True strips gallery arrays and long text — for homepage/search mobile speed.
    """
    clone = json.loads(json.dumps(content))
    site = clone.get("site")
    if isinstance(site, dict):
        site["adminPassword"] = ""
        pay = site.get("pay")
        if not isinstance(pay, dict):
            pay = {}
            site["pay"] = pay
        if admin:
            site["pay"] = {
                "wechatQr": str(pay.get("wechatQr") or "").strip(),
                "alipayQr": str(pay.get("alipayQr") or "").strip(),
                "note": str(pay.get("note") or "").strip(),
                "pushPlusToken": str(pay.get("pushPlusToken") or "").strip(),
            }
        else:
            site["pay"] = public_pay_config(site)
    if not admin:
        for post in clone.get("posts") or []:
            if not isinstance(post, dict):
                continue
            if post_requires_purchase(post):
                post["purchaseRequired"] = True
                post["link"] = ""
                post.pop("fulfillmentLink", None)
            else:
                post["purchaseRequired"] = False
                post.pop("fulfillmentLink", None)
            if lite:
                # Homepage only needs cover + meta; drop heavy gallery payloads
                gal = post.get("gallery")
                post["galleryCount"] = len(gal) if isinstance(gal, list) else 0
                post.pop("gallery", None)
                summary = str(post.get("summary") or "")
                if len(summary) > 180:
                    post["summary"] = summary[:180] + "…"
                updates = str(post.get("updates") or "")
                if updates:
                    post.pop("updates", None)
    return clone


def read_orders() -> list[dict]:
    ensure_orders_file()
    data = _read_json(ORDERS_PATH)
    orders = data.get("orders")
    return orders if isinstance(orders, list) else []


def write_orders(orders: list[dict]) -> None:
    _write_json(ORDERS_PATH, {"orders": orders})


def find_order(order_id: str) -> dict | None:
    oid = str(order_id or "").strip()
    if not oid:
        return None
    for order in read_orders():
        if isinstance(order, dict) and str(order.get("id")) == oid:
            return order
    return None


def public_order(order: dict, *, buyer: bool = False, include_link: bool = False) -> dict:
    out = {
        "id": order.get("id"),
        "postId": order.get("postId"),
        "title": order.get("title"),
        "amount": order.get("amount"),
        "amountLabel": order.get("amountLabel"),
        "status": order.get("status"),
        "createdAt": order.get("createdAt"),
        "claimedAt": order.get("claimedAt"),
        "paidAt": order.get("paidAt"),
    }
    if buyer:
        out["buyerToken"] = order.get("buyerToken")
    if include_link and order.get("status") == "paid":
        out["fulfillmentLink"] = order.get("fulfillmentLink") or ""
    return out


def send_pushplus(token: str, title: str, content: str) -> tuple[bool, str]:
    if not token:
        return False, "未配置 PushPlus token"
    body = json.dumps(
        {
            "token": token,
            "title": title,
            "content": content,
            "template": "html",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "promo-landing"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return True, raw[:200]
        if str(data.get("code")) in {"200", "0"} or data.get("success") is True:
            return True, str(data.get("msg") or "ok")
        return False, str(data.get("msg") or raw[:200])
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def request_base_url(handler: BaseHTTPRequestHandler) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    proto = handler.headers.get("X-Forwarded-Proto") or "https"
    host = handler.headers.get("X-Forwarded-Host") or handler.headers.get("Host") or f"127.0.0.1:{PORT}"
    if host.startswith("127.") or host.startswith("localhost"):
        proto = "http"
    return f"{proto}://{host}".rstrip("/")


def create_order(post_id: str) -> dict:
    content = read_content(with_views=False)
    post = next(
        (
            p
            for p in (content.get("posts") or [])
            if isinstance(p, dict) and str(p.get("id")) == post_id and not p.get("hidden")
        ),
        None,
    )
    if not post:
        raise ValueError("内容不存在或已下架")
    link = post_fulfillment_link(post)
    price = str(post.get("price") or "").strip()
    if not price or not link:
        raise ValueError("该内容未配置付费发货")
    order = {
        "id": "O" + secrets.token_hex(4).upper(),
        "postId": str(post["id"]),
        "title": str(post.get("title") or post_id),
        "amount": price,
        "amountLabel": format_amount_label(price),
        "status": "pending",
        "buyerToken": secrets.token_urlsafe(18),
        "confirmToken": secrets.token_urlsafe(18),
        "fulfillmentLink": link,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "claimedAt": "",
        "paidAt": "",
    }
    with ORDERS_LOCK:
        orders = read_orders()
        orders.insert(0, order)
        # keep last 500
        write_orders(orders[:500])
    return order


def update_order(order_id: str, mutator) -> dict:
    with ORDERS_LOCK:
        orders = read_orders()
        for i, order in enumerate(orders):
            if isinstance(order, dict) and str(order.get("id")) == order_id:
                updated = mutator(dict(order))
                orders[i] = updated
                write_orders(orders)
                return updated
    raise ValueError("订单不存在")


def write_content_local(data: dict) -> None:
    _write_json(CONTENT_PATH, data)


def write_content(data: dict) -> None:
    """Admin save: views in payload are authoritative (can reset to 0)."""
    with CONTENT_LOCK:
        stamp_content_updated(data)
        views = read_views()
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
            views[pid] = max(0, incoming)
            post["views"] = views[pid]
        write_views(views)
        write_content_local(data)
        mark_views_dirty()
    # Persist to GitHub when token is set; otherwise free-tier disk is wiped on redeploy
    if not github_enabled():
        sys.stdout.write(
            "WARN: GITHUB_TOKEN unset — content saved to ephemeral disk only; "
            "redeploy may restore stale repo content.json until backup Action runs.\n"
        )
        return
    try:
        flush_views_to_github(force=True)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(f"GitHub flush failed, trying direct write: {exc}\n")
        try:
            write_content_to_github(data)
        except Exception as exc2:  # noqa: BLE001
            sys.stdout.write(f"GitHub write failed: {exc2}\n")


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
        mark_views_dirty()
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
            "Content-Type, X-Admin-Password, X-View-Token, X-Content-Source, X-Force-Content",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")

    def _wants_gzip(self) -> bool:
        accept = (self.headers.get("Accept-Encoding") or "").lower()
        return "gzip" in accept

    def _send_body(
        self,
        code: int,
        data: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
        set_cookie: str | None = None,
        compressible: bool = True,
    ) -> None:
        use_gzip = compressible and self._wants_gzip() and len(data) >= 512
        body = gzip.compress(data, compresslevel=6) if use_gzip else data
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self._cors()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(
        self,
        code: int,
        payload: dict,
        set_cookie: str | None = None,
        *,
        cache_control: str = "no-store",
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_body(
            code,
            body,
            "application/json; charset=utf-8",
            cache_control=cache_control,
            set_cookie=set_cookie,
            compressible=True,
        )

    def _bytes(
        self,
        code: int,
        data: bytes,
        content_type: str,
        *,
        cache_control: str = "no-cache",
        compressible: bool = True,
    ) -> None:
        self._send_body(
            code,
            data,
            content_type,
            cache_control=cache_control,
            compressible=compressible,
        )

    def _redirect(self, location: str, *, cache_control: str = "public, max-age=3600") -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", cache_control)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _stream_file(
        self,
        file_path: Path,
        content_type: str,
        *,
        cache_control: str = "public, max-age=86400",
    ) -> None:
        """Send a file in chunks so concurrent asset requests don't OOM."""
        size = file_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(size))
        self._cors()
        self.end_headers()
        with file_path.open("rb") as fh:
            while True:
                chunk = fh.read(STATIC_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)

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

    def _is_admin(self, content: dict | None = None) -> bool:
        password = self.headers.get("X-Admin-Password") or ""
        return bool(password) and password == expected_admin_password(content)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/content":
            try:
                content = read_content(with_views=True)
                admin = self._is_admin(content)
                lite = (qs.get("lite") or [""])[0].strip() in {"1", "true", "yes"}
                payload = public_content(content, admin=admin, lite=lite and not admin)
                # Public list can be briefly cached on phone; admin always fresh
                cache = "no-store" if admin else "public, max-age=30"
                self._json(200, payload, cache_control=cache)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/img":
            # On-demand thumbnail: /img?u=/assets/xxx/01.jpg&w=480
            src_url = (qs.get("u") or qs.get("src") or [""])[0].strip()
            try:
                width = int((qs.get("w") or ["480"])[0])
            except ValueError:
                width = 480
            asset = resolve_asset_path(src_url)
            if not asset:
                self._json(404, {"error": "image not found"})
                return
            # Never buffer animated / huge originals in /img — redirect to static path
            try:
                src_size = asset.stat().st_size
            except OSError:
                src_size = 0
            if is_animated_image(asset) or src_size > THUMB_MAX_SRC_BYTES:
                self._redirect(src_url, cache_control="public, max-age=86400")
                return
            try:
                data, ctype = get_or_create_thumb(asset, width)
                self._bytes(
                    200,
                    data,
                    ctype,
                    cache_control="public, max-age=604800, immutable",
                    compressible=False,
                )
            except Exception as exc:  # noqa: BLE001
                sys.stdout.write(f"thumb failed {src_url}: {exc}\n")
                self._redirect(src_url, cache_control="public, max-age=3600")
            return

        if path == "/api/orders":
            order_id = (qs.get("id") or [""])[0].strip()
            token = (qs.get("token") or [""])[0].strip()
            if not order_id:
                if not self._is_admin():
                    self._json(401, {"error": "密码错误"})
                    return
                orders = [public_order(o) for o in read_orders()[:100] if isinstance(o, dict)]
                self._json(200, {"orders": orders})
                return
            order = find_order(order_id)
            if not order:
                self._json(404, {"error": "订单不存在"})
                return
            is_buyer = token and token == order.get("buyerToken")
            is_confirm = token and token == order.get("confirmToken")
            if not (is_buyer or is_confirm or self._is_admin()):
                self._json(403, {"error": "无权查看"})
                return
            self._json(
                200,
                {
                    "order": public_order(
                        order,
                        buyer=is_buyer,
                        include_link=bool(is_buyer and order.get("status") == "paid"),
                    )
                },
            )
            return

        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "persist": "github" if github_enabled() else "github-raw+local",
                    "views": True,
                    "orders": True,
                    "admin_env": bool(ADMIN_PASSWORD_ENV),
                    "github_repo": GITHUB_REPO,
                    "github_write": github_enabled(),
                    "pushplus": bool(PUSHPLUS_TOKEN_ENV),
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
            elif path in ("/confirm", "/confirm.html"):
                file_path = ROOT / "confirm.html"
            else:
                self._json(404, {"error": "not found"})
                return

        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.suffix in {".html", ".css", ".js", ".json"}:
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
            }[file_path.suffix]
        # Cache static assets on mobile; HTML stays short-lived
        is_binary_asset = (
            "/assets/" in str(file_path).replace("\\", "/")
            or file_path.suffix.lower()
            in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".gif",
                ".svg",
                ".ico",
                ".woff2",
            }
        )
        if is_binary_asset:
            cache = "public, max-age=604800, immutable"
            # Stream images/fonts — never hold full file + gzip copy in RAM
            if file_path.suffix.lower() in {".svg", ".ico"}:
                data = file_path.read_bytes()
                self._bytes(200, data, ctype, cache_control=cache, compressible=True)
            else:
                self._stream_file(file_path, ctype, cache_control=cache)
            return
        if file_path.suffix in {".css", ".js"}:
            cache = "public, max-age=86400"
            compressible = True
        elif file_path.suffix == ".html":
            cache = "public, max-age=60"
            compressible = True
        else:
            cache = "public, max-age=300"
            compressible = True
        data = file_path.read_bytes()
        self._bytes(200, data, ctype, cache_control=cache, compressible=compressible)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                payload = {}
        except Exception:  # noqa: BLE001
            payload = {}

        if path == "/api/login":
            password = str(payload.get("password") or "").strip()
            if password and password == expected_admin_password():
                self._json(200, {"ok": True})
            else:
                self._json(401, {"error": "密码错误"})
            return

        if path == "/api/content/upsert":
            # Agent/script safe path: merge posts into live content without wiping admin edits
            current = read_content(with_views=True)
            if not self._is_admin(current):
                self._json(401, {"error": "密码错误"})
                return
            posts = payload.get("posts")
            if posts is not None and not isinstance(posts, list):
                self._json(400, {"error": "posts 必须是数组"})
                return
            if not posts and not isinstance(payload.get("site"), dict):
                self._json(400, {"error": "需要 posts 和/或 site"})
                return
            try:
                merged = upsert_posts_into(current, posts or [])
                if isinstance(payload.get("site"), dict):
                    merged["site"] = merge_site_config(
                        current.get("site") if isinstance(current.get("site"), dict) else {},
                        payload.get("site"),
                    )
                if isinstance(payload.get("nav"), list) and payload.get("nav"):
                    merged["nav"] = payload["nav"]
                if isinstance(payload.get("tags"), list) and payload.get("tags"):
                    merged["tags"] = payload["tags"]
                write_content(merged)
                self._json(
                    200,
                    {"ok": True, "content": public_content(read_content(with_views=True), admin=True)},
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/orders":
            post_id = str(payload.get("postId") or payload.get("id") or "").strip()
            if not post_id:
                self._json(400, {"error": "缺少 postId"})
                return
            try:
                order = create_order(post_id)
                content = read_content(with_views=False)
                self._json(
                    200,
                    {
                        "ok": True,
                        "order": public_order(order, buyer=True),
                        "pay": public_pay_config(content.get("site") if isinstance(content.get("site"), dict) else {}),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/orders/claim":
            order_id = str(payload.get("id") or "").strip()
            token = str(payload.get("token") or "").strip()
            order = find_order(order_id)
            if not order or token != order.get("buyerToken"):
                self._json(403, {"error": "订单无效"})
                return
            if order.get("status") == "paid":
                self._json(200, {"ok": True, "order": public_order(order, buyer=True, include_link=True)})
                return
            if order.get("status") == "rejected":
                self._json(400, {"error": "订单已驳回，请重新下单"})
                return

            def mark_claimed(o: dict) -> dict:
                if o.get("status") != "claimed":
                    o["status"] = "claimed"
                    o["claimedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return o

            try:
                order = update_order(order_id, mark_claimed)
            except ValueError as exc:
                self._json(404, {"error": str(exc)})
                return

            content = read_content(with_views=False)
            token_pp = pushplus_token(content)
            base = request_base_url(self)
            confirm_url = (
                f"{base}/confirm.html?id={urllib.parse.quote(order_id)}"
                f"&token={urllib.parse.quote(str(order.get('confirmToken') or ''))}"
            )
            html = (
                f"<p><b>待确认付款</b></p>"
                f"<p>订单号：<b>{order_id}</b></p>"
                f"<p>商品：{order.get('title')}</p>"
                f"<p>金额：<b>{order.get('amountLabel')}</b></p>"
                f"<p>请对照微信/支付宝到账后点击："
                f"<a href=\"{confirm_url}\">确认放行</a></p>"
                f"<p style=\"word-break:break-all\">{confirm_url}</p>"
            )
            ok, msg = send_pushplus(token_pp, f"待确认 {order.get('amountLabel')} {order.get('title')}", html)
            self._json(
                200,
                {
                    "ok": True,
                    "pushed": ok,
                    "pushMessage": msg,
                    "order": public_order(order, buyer=True),
                },
            )
            return

        if path in ("/api/orders/confirm", "/api/orders/reject"):
            order_id = str(payload.get("id") or "").strip()
            token = str(payload.get("token") or "").strip()
            order = find_order(order_id)
            if not order:
                self._json(404, {"error": "订单不存在"})
                return
            allowed = token == order.get("confirmToken") or self._is_admin()
            if not allowed:
                self._json(403, {"error": "无权操作"})
                return
            if order.get("status") == "paid" and path.endswith("confirm"):
                self._json(200, {"ok": True, "order": public_order(order)})
                return
            action = "paid" if path.endswith("confirm") else "rejected"

            def mutator(o: dict) -> dict:
                o["status"] = action
                if action == "paid":
                    o["paidAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return o

            try:
                order = update_order(order_id, mutator)
                self._json(200, {"ok": True, "order": public_order(order)})
            except ValueError as exc:
                self._json(404, {"error": str(exc)})
            return

        if path != "/api/view":
            self._json(404, {"error": "not found"})
            return

        post_id = str(payload.get("id") or "").strip()
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
        expected = expected_admin_password(current)
        if password != expected:
            self._json(401, {"error": "密码错误"})
            return

        if not isinstance(incoming, dict) or "posts" not in incoming:
            self._json(400, {"error": "内容格式不正确"})
            return

        # Rehydrate redacted/blank secrets from current disk before merge/replace
        incoming = rehydrate_secrets_from_trusted(incoming, current)
        site = incoming.setdefault("site", {})
        if isinstance(site, dict) and not str(site.get("adminPassword") or "").strip():
            site["adminPassword"] = (current.get("site") or {}).get("adminPassword") or expected

        source = (self.headers.get("X-Content-Source") or "").strip().lower()
        force = (self.headers.get("X-Force-Content") or "").strip() in {"1", "true", "yes"}
        cur_ts = content_updated_at(current)
        inc_ts = content_updated_at(incoming)

        try:
            merged_stale = False
            if source == "admin" or force:
                to_write = merge_admin_put(current, incoming)
            elif cur_ts and (not inc_ts or inc_ts < cur_ts):
                # Stale full catalog from scripts/GitHub — do not wipe newer admin disk state
                to_write = merge_stale_put(current, incoming)
                merged_stale = True
            else:
                # Fresh enough full PUT without admin header — still protect concurrent newer posts
                to_write = merge_admin_put(current, incoming)

            write_content(to_write)
            payload_out = {
                "ok": True,
                "content": public_content(read_content(with_views=True), admin=True),
            }
            if merged_stale:
                payload_out["merged"] = True
                payload_out["warning"] = "检测到旧版 content，已与线上合并，未整包覆盖"
            self._json(200, payload_out)
        except Exception as exc:  # noqa: BLE001
            self._json(500, {"error": str(exc)})


def main() -> None:
    ensure_content_file()
    ensure_views_file()
    ensure_orders_file()
    ensure_thumbs_dir()
    if restore_from_github():
        print(f"已从 GitHub 恢复内容/浏览量: {GITHUB_REPO}@{GITHUB_BRANCH}")
    else:
        print("GitHub 恢复跳过，使用本地种子")
    if github_enabled():
        threading.Thread(target=github_flusher, name="github-flusher", daemon=True).start()
        print("已启用浏览量回写 GitHub")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"前台:  http://127.0.0.1:{PORT}/")
    print(f"后台:  http://127.0.0.1:{PORT}/admin.html")
    print(f"浏览量: {VIEWS_PATH}")
    print(f"订单: {ORDERS_PATH}")
    print(f"持久化: GitHub {GITHUB_REPO} (write={'on' if github_enabled() else 'off, backup-action'})")
    print("按 Ctrl+C 停止")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
