#!/usr/bin/env python3
"""Push code files to GitHub without touching data/content.json."""
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = "rocklee520/promo-landing"
ROOT = Path(r"F:\promo-landing")
GH = Path(r"C:\Program Files\GitHub CLI\gh.exe")
MESSAGE = sys.argv[1] if len(sys.argv) > 1 else "Protect admin content from stale full overwrites."
FILES = [
    "server.py",
    "js/admin.js",
    "admin.html",
    ".cursor/rules/content-sync.mdc",
    ".github/workflows/backup-content.yml",
    "scripts/content_sync.py",
]


def token() -> str:
    bin_ = str(GH) if GH.exists() else "gh"
    return subprocess.check_output([bin_, "auth", "token"], text=True).strip()


def api(method: str, path: str, data=None, retries: int = 10):
    body = None if data is None else json.dumps(data).encode()
    last = None
    for i in range(retries):
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "promo-landing-deploy",
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            print("retry", i + 1, method, path, type(e).__name__, flush=True)
            time.sleep(2 + i * 2)
    raise SystemExit(last)


def main() -> None:
    # Safety: refuse if someone added content.json to FILES
    for rel in FILES:
        if rel.replace("\\", "/").endswith("content.json"):
            raise SystemExit("Refusing to push content.json in code-only deploy")
    ref = api("GET", f"/repos/{REPO}/git/ref/heads/main")
    base = ref["object"]["sha"]
    commit = api("GET", f"/repos/{REPO}/git/commits/{base}")
    print("base", base[:7], flush=True)
    tree = []
    for rel in FILES:
        path = ROOT / rel
        if not path.exists():
            print("skip", rel, flush=True)
            continue
        blob = api(
            "POST",
            f"/repos/{REPO}/git/blobs",
            {"content": base64.b64encode(path.read_bytes()).decode(), "encoding": "base64"},
        )
        tree.append({"path": rel.replace("\\", "/"), "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("ok", rel, flush=True)
    new_tree = api(
        "POST",
        f"/repos/{REPO}/git/trees",
        {"base_tree": commit["tree"]["sha"], "tree": tree},
    )
    new_commit = api(
        "POST",
        f"/repos/{REPO}/git/commits",
        {"message": MESSAGE, "tree": new_tree["sha"], "parents": [base]},
    )
    api("PATCH", f"/repos/{REPO}/git/refs/heads/main", {"sha": new_commit["sha"]})
    print("DONE", new_commit["sha"], flush=True)


if __name__ == "__main__":
    main()
