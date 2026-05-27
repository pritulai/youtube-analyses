#!/usr/bin/env python3
"""
Saves source links to text files with deduplication across runs.
Works for YouTube, Reddit, GitHub, Google Maps and any source
that stores items in data["videos"] with a "video_id" and optional "url" field.
Input:  .tmp/{slug}/youtube_data.json
Output: outputs/{slug}/urls.txt   — one URL per line
        outputs/{slug}/full.txt   — URL | title | channel (one per line)
"""

import os
import sys
import json
import re
import argparse


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def load_existing_ids(filepath: str) -> set:
    """Extract known IDs from urls.txt (YouTube video IDs or full URLs for other sources)."""
    existing = set()
    if not os.path.exists(filepath):
        return existing
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # YouTube: extract video ID from ?v=XXXX
            yt = re.search(r"v=([A-Za-z0-9_-]{11})", line)
            if yt:
                existing.add(yt.group(1))
            else:
                # For other sources store the full URL as dedup key
                existing.add(line.split(" | ")[0])
    return existing


def build_url(item: dict) -> str:
    """Return canonical URL for any source item."""
    # Prefer explicit url field (non-YouTube sources)
    if item.get("url"):
        return item["url"]
    # Fallback: YouTube URL from video_id
    return f"https://youtube.com/watch?v={item['video_id']}"


def main():
    parser = argparse.ArgumentParser(description="Save YouTube links with deduplication")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    args = parser.parse_args()

    slug = make_slug(args.query)

    in_path = os.path.join(".tmp", slug, "youtube_data.json")
    if not os.path.exists(in_path):
        print(f"[ERROR] {in_path} not found. Run fetch_youtube_data.py first.")
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    videos = data.get("videos", [])
    if not videos:
        print("[WARN] No videos in data file.")
        sys.exit(0)

    out_dir = os.path.join("outputs", slug)
    os.makedirs(out_dir, exist_ok=True)

    urls_path = os.path.join(out_dir, "urls.txt")
    full_path = os.path.join(out_dir, "full.txt")

    existing_ids = load_existing_ids(urls_path)
    print(f"Existing URLs in file: {len(existing_ids)}")

    # Sort by views descending for consistent ordering
    videos_sorted = sorted(videos, key=lambda v: v["view_count"], reverse=True)

    new_urls = []
    new_full = []
    skipped = 0

    for v in videos_sorted:
        url = build_url(v)
        dedup_key = v.get("video_id") or url
        if dedup_key in existing_ids or url in existing_ids:
            skipped += 1
            continue

        title = v["title"].replace("|", "-").replace("\n", " ").strip()
        channel = v["channel_title"].replace("|", "-").strip()

        new_urls.append(url)
        new_full.append(f"{url} | {title} | {channel}")
        existing_ids.add(dedup_key)
        existing_ids.add(url)

    # Append only new entries
    if new_urls:
        with open(urls_path, "a", encoding="utf-8") as f:
            f.write("\n".join(new_urls) + "\n")

        with open(full_path, "a", encoding="utf-8") as f:
            f.write("\n".join(new_full) + "\n")

    total = len(existing_ids)
    print(f"Добавлено {len(new_urls)} новых ссылок, пропущено {skipped} дублей")
    print(f"Итого в файле: {total} уникальных видео")
    print(f"  urls -> {urls_path}")
    print(f"  full -> {full_path}")


if __name__ == "__main__":
    main()
