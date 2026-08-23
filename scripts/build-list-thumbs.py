#!/usr/bin/env python3
"""Build static list thumbs for all post covers -> thumbs/list/assets/....webp"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageOps, ImageSequence

ROOT = Path(r"F:\promo-landing")
CONTENT = ROOT / "data" / "content.json"
OUT = ROOT / "thumbs" / "list"
WIDTHS = (360, 480, 720)


def asset_path(url: str) -> Path | None:
    raw = str(url or "").strip()
    if not raw.startswith("/assets/"):
        return None
    p = (ROOT / raw.lstrip("/")).resolve()
    if not p.is_file():
        return None
    if not str(p).startswith(str((ROOT / "assets").resolve())):
        return None
    return p


def out_path(url: str, width: int) -> Path:
    # /assets/foo/01.jpg -> thumbs/list/360/assets/foo/01.jpg.webp
    rel = url.lstrip("/")
    return OUT / str(width) / f"{rel}.webp"


def make_thumb(src: Path, width: int) -> bytes:
    Image.MAX_IMAGE_PIXELS = 40_000_000
    with Image.open(src) as im:
        # Still frame for animated GIF/WEBP
        try:
            im.seek(0)
        except Exception:  # noqa: BLE001
            pass
        im = ImageOps.exif_transpose(im)
        if im.mode in {"P", "RGBA", "LA"}:
            bg = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        im.thumbnail((width, width * 2), Image.Resampling.LANCZOS)
        import io

        buf = io.BytesIO()
        im.save(buf, format="WEBP", quality=85, method=4)
        return buf.getvalue()


def main() -> None:
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    covers = []
    for p in data.get("posts") or []:
        if not isinstance(p, dict) or p.get("hidden"):
            continue
        c = str(p.get("cover") or "").strip()
        if c:
            covers.append(c)
    covers = sorted(set(covers))
    print("covers", len(covers), flush=True)
    built = 0
    skipped = 0
    for url in covers:
        src = asset_path(url)
        if not src:
            print("missing", url, flush=True)
            skipped += 1
            continue
        for w in WIDTHS:
            dest = out_path(url, w)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                data = make_thumb(src, w)
                dest.write_bytes(data)
                built += 1
                print("ok", w, url, len(data), flush=True)
            except Exception as e:  # noqa: BLE001
                print("fail", url, w, type(e).__name__, e, flush=True)
                skipped += 1
    print("done built", built, "skipped", skipped, flush=True)


if __name__ == "__main__":
    main()
