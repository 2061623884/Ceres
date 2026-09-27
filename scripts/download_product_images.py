#!/usr/bin/env python3
"""Download 400px product images for all rows in sale_guide.db."""

from __future__ import annotations

import gzip
import os
import re
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "sale_guide.db"
OUTDIR = DATA_DIR / "images"
FAILED_PATH = DATA_DIR / "image_failed.tsv"
KEYS_PATH = ROOT.parent / "reference/openfoodfacts/data_keys.gz"
AWS = "https://openfoodfacts-images.s3.eu-west-3.amazonaws.com"
UA = "Sale-guide/1.0 (local-import)"
WORKERS = 8


def barcode_folder(code: str) -> str:
    s = "".join(c for c in code if c.isdigit())
    if len(s) < 13:
        s = s.zfill(13)
    return f"{s[0:3]}/{s[3:6]}/{s[6:9]}/{s[9:]}"


def load_products(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT barcode, COALESCE(image_url, '') FROM products ORDER BY barcode"
    ).fetchall()
    return [(code, url) for code, url in rows if code]


def aws_keys_for(folders: set[str]) -> dict[str, tuple[int, str]]:
    chosen: dict[str, tuple[int, str]] = {}
    rx = re.compile(r"^data/(.+)/(\d+)\.400\.jpg$")
    with gzip.open(KEYS_PATH, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            m = rx.match(line)
            if not m:
                continue
            folder, num = m.group(1), int(m.group(2))
            if folder not in folders:
                continue
            prev = chosen.get(folder)
            if prev is None or num < prev[0]:
                chosen[folder] = (num, line)
    return chosen


def curl_get(url: str, dest: Path) -> tuple[bool, str | int]:
    tmp = dest.with_suffix(dest.suffix + ".part")
    r = subprocess.run(
        [
            "curl",
            "-L",
            "-f",
            "-sS",
            "--connect-timeout",
            "8",
            "--max-time",
            "20",
            "-A",
            UA,
            "-o",
            str(tmp),
            url,
        ],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1000:
        with tmp.open("rb") as f:
            head = f.read(3)
        if head.startswith(b"\xff\xd8") or head.startswith(b"\x89P"):
            tmp.replace(dest)
            return True, dest.stat().st_size
    if tmp.exists():
        tmp.unlink()
    return False, r.stderr.strip() or f"curl:{r.returncode}"


def fetch(
    item: tuple[str, str, str],
    chosen: dict[str, tuple[int, str]],
) -> tuple[str, str, str | int]:
    code, folder, cdn = item
    dest = OUTDIR / f"{code}.jpg"
    rel = f"images/{code}.jpg"
    if dest.exists() and dest.stat().st_size > 1000:
        return "skip", code, rel

    urls: list[str] = []
    hit = chosen.get(folder)
    if hit:
        urls.append(f"{AWS}/{hit[1]}")
    else:
        urls.extend(
            [
                f"{AWS}/data/{folder}/1.400.jpg",
                f"{AWS}/data/{folder}/2.400.jpg",
            ]
        )
    if cdn:
        urls.append(cdn)

    last: str | int = "no-url"
    for url in urls:
        ok, info = curl_get(url, dest)
        if ok:
            return "ok", code, rel
        last = info
        time.sleep(0.2)
    return "fail", code, str(last)


def main() -> int:
    if not DB_PATH.exists():
        print(f"Missing database: {DB_PATH}", flush=True)
        return 1
    if not KEYS_PATH.exists():
        print(f"Missing AWS key index: {KEYS_PATH}", flush=True)
        return 1

    OUTDIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    products = load_products(conn)
    print(f"products={len(products)} indexing AWS keys...", flush=True)

    items: list[tuple[str, str, str]] = []
    folders: set[str] = set()
    for code, url in products:
        folder = barcode_folder(code)
        folders.add(folder)
        items.append((code, folder, url))

    chosen = aws_keys_for(folders)
    print(f"aws_hits={len(chosen)}", flush=True)

    ok = skip = fail = 0
    failed_rows: list[tuple[str, str]] = []
    updates: list[tuple[str, str]] = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(fetch, item, chosen) for item in items]
        for i, fut in enumerate(as_completed(futs), 1):
            status, code, info = fut.result()
            if status == "ok":
                ok += 1
                updates.append((str(info), code))
            elif status == "skip":
                skip += 1
                updates.append((f"images/{code}.jpg", code))
            else:
                fail += 1
                failed_rows.append((code, str(info)))
            if i % 25 == 0 or i == len(items):
                print(
                    f"{i}/{len(items)} ok={ok} skip={skip} fail={fail} "
                    f"elapsed={time.time() - t0:.0f}s",
                    flush=True,
                )

    conn.executemany(
        "UPDATE products SET image_file = ? WHERE barcode = ?",
        updates,
    )
    conn.commit()
    conn.close()

    with FAILED_PATH.open("w", encoding="utf-8") as f:
        f.write("barcode\terror\n")
        for code, err in sorted(failed_rows):
            f.write(f"{code}\t{err}\n")

    file_count = len(list(OUTDIR.glob("*.jpg")))
    print(
        f"DONE products={len(products)} ok={ok} skip={skip} fail={fail} "
        f"files={file_count}"
    )
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
