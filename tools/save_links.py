#!/usr/bin/env python3
"""
Saves YouTube video links to text files with deduplication across runs.
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
    """Extract video IDs already in urls.txt."""
    existing = set()
    if not os.path.exists(filepath):
        return existing
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Extract video_id from https://youtube.com/watch?v=XXXX
            match = re.search(r"v=([A-Za-z0-9_-]{11})", line)
            if match:
                existing.add(match.group(1))
    return existing


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
        vid_id = v["video_id"]
        if vid_id in existing_ids:
            skipped += 1
            continue

        url = f"https://youtube.com/watch?v={vid_id}"
        title = v["title"].replace("|", "-").replace("\n", " ").strip()
        channel = v["channel_title"].replace("|", "-").strip()

        new_urls.append(url)
        new_full.append(f"{url} | {title} | {channel}")
        existing_ids.add(vid_id)

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
