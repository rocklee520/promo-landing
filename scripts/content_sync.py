#!/usr/bin/env python3
"""
Safe content sync for promo-landing.

Problem this solves:
  Agent/local scripts used to push a full stale data/content.json and wipe
  admin UI edits (prices, pay QR, fulfillment links, PushPlus token).

Rules for future changes:
  1. Prefer live upsert: upsert_live(posts=[...], site={...})
  2. Never commit/push a full content.json built from public GET without merge.
  3. Code-only deploys must NOT include data/content.json.
  4. Always pull live first; merge secrets from local/repo trusted copy.

Env:
  ADMIN_PASSWORD  — required for upsert_live / fetch_admin
  RENDER_URL      — default https://promo-landing.onrender.com
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = os.environ.get("RENDER_URL", "https://promo-landing.onrender.com").rstrip("/")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()


def _req(url: str, *, method: str = "GET", data: dict | None = None, password: str = "") -> Any:
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": "promo-landing-content-sync",
        "Connection": "close",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if password:
        headers["X-Admin-Password"] = password
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_live_public() -> dict:
    return _req(f"{LIVE}/api/content?ts=1")


def fetch_live_admin(password: str | None = None) -> dict:
    pw = (password or ADMIN_PASSWORD).strip()
    if not pw:
        raise SystemExit("ADMIN_PASSWORD required for admin content fetch")
    return _req(f"{LIVE}/api/content?ts=1", password=pw)


def load_local() -> dict:
    path = ROOT / "data" / "content.json"
    return json.loads(path.read_text(encoding="utf-8"))


def write_local(content: dict) -> None:
    text = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
    (ROOT / "data" / "content.json").write_text(text, encoding="utf-8")
    (ROOT / "backups" / "content-latest.json").write_text(text, encoding="utf-8")


def merge_backup(live_public: dict, trusted_repo: dict) -> dict:
    """Merge public live snapshot with repo copy so redacted secrets survive backup."""
    # Import merge helpers from server when available
    import sys

    sys.path.insert(0, str(ROOT))
    import server  # noqa: WPS433

    return server.rehydrate_secrets_from_trusted(live_public, trusted_repo)


def upsert_live(
    posts: list[dict] | None = None,
    site: dict | None = None,
    *,
    nav: list | None = None,
    tags: list | None = None,
    password: str | None = None,
) -> dict:
    """Push only changed posts/site/nav/tags into live; never replace whole catalog."""
    pw = (password or ADMIN_PASSWORD).strip()
    if not pw:
        raise SystemExit("ADMIN_PASSWORD required for upsert_live")
    payload: dict[str, Any] = {}
    if posts:
        payload["posts"] = posts
    if site:
        payload["site"] = site
    if nav is not None:
        payload["nav"] = nav
    if tags is not None:
        payload["tags"] = tags
    if not payload.get("posts") and "site" not in payload and "nav" not in payload and "tags" not in payload:
        raise SystemExit("upsert_live needs posts and/or site and/or nav/tags")
    # Never use PUT /api/content from scripts — that path is for admin UI only.
    try:
        return _req(
            f"{LIVE}/api/content/upsert",
            method="POST",
            data=payload,
            password=pw,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"upsert failed HTTP {exc.code}: {detail}") from exc


def sync_local_from_live_admin(password: str | None = None) -> dict:
    """Refresh local content.json from live admin API (full secrets)."""
    content = fetch_live_admin(password)
    write_local(content)
    return content


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Safe promo-landing content sync")
    p.add_argument("cmd", choices=["pull", "merge-demo"], help="pull=admin pull to local")
    args = p.parse_args()
    if args.cmd == "pull":
        c = sync_local_from_live_admin()
        print("pulled posts", len(c.get("posts") or []))
    else:
        live = fetch_live_public()
        local = load_local()
        merged = merge_backup(live, local)
        print("merged posts", len(merged.get("posts") or []))
