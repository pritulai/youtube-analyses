#!/usr/bin/env python3
"""
Fetches YouTube video and channel data for any topic/keyword.
Usage: python tools/fetch_youtube_data.py --query "LM Studio" [--days 7] [--max_videos 100]
Output: .tmp/{slug}/youtube_data.json
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

API_KEY = os.getenv("YOUTUBE_API_KEY")
YT_BASE = "https://www.googleapis.com/youtube/v3"

# SOCKS/HTTP proxy support — set HTTPS_PROXY in .env if needed
_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
PROXIES = {"https": _proxy, "http": _proxy} if _proxy else None


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def expand_queries(base_query: str) -> list:
    q = base_query.strip()
    return [
        f"{q} 2026",
        f"{q} tutorial 2026",
        f"{q} review 2026",
        f"how to use {q} 2026",
        f"{q} beginners guide 2026",
    ]


def parse_duration(duration_str: str) -> int:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_str)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def yt_get(endpoint: str, params: dict) -> dict:
    params["key"] = API_KEY
    resp = requests.get(
        f"{YT_BASE}/{endpoint}",
        params=params,
        proxies=PROXIES,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def search_videos(query: str, published_after: str, max_results: int = 10) -> list:
    try:
        data = yt_get("search", {
            "part": "snippet",
            "q": query,
            "type": "video",
            "publishedAfter": published_after,
            "order": "viewCount",
            "maxResults": min(max_results, 50),
            "relevanceLanguage": "en",
        })
        return [item["id"]["videoId"] for item in data.get("items", [])]
    except Exception as e:
        print(f"  [WARN] Search failed for '{query}': {e}")
        return []


def get_video_details(video_ids: list) -> list:
    all_videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i: i + 50]
        try:
            data = yt_get("videos", {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
            })
        except Exception as e:
            print(f"  [WARN] videos.list failed: {e}")
            continue

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            details = item.get("contentDetails", {})
            duration_str = details.get("duration", "PT0S")

            all_videos.append({
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "description": snippet.get("description", "")[:600],
                "tags": snippet.get("tags", [])[:20],
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration": duration_str,
                "duration_seconds": parse_duration(duration_str),
                "search_query": "",
            })
    return all_videos


def get_channel_details(channel_ids: set) -> dict:
    channels = {}
    ids_list = list(channel_ids)
    for i in range(0, len(ids_list), 50):
        batch = ids_list[i: i + 50]
        try:
            data = yt_get("channels", {
                "part": "snippet,statistics",
                "id": ",".join(batch),
            })
        except Exception as e:
            print(f"  [WARN] channels.list failed: {e}")
            continue

        for item in data.get("items", []):
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            channels[item["id"]] = {
                "channel_id": item["id"],
                "channel_title": snippet.get("title", ""),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "view_count": int(stats.get("viewCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "description": snippet.get("description", "")[:300],
            }
    return channels


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube data for any keyword")
    parser.add_argument("--query", required=True, help='Search topic, e.g. "LM Studio"')
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument("--max_videos", type=int, default=100, help="Max unique videos to collect")
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] YOUTUBE_API_KEY not set in .env")
        sys.exit(1)

    slug = make_slug(args.query)
    out_dir = os.path.join(".tmp", slug)
    os.makedirs(out_dir, exist_ok=True)

    queries = expand_queries(args.query)
    per_query = max(5, args.max_videos // len(queries))

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=args.days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f'Query: "{args.query}" | Last {args.days} days | Target: {args.max_videos} videos')
    print(f"Expanded into {len(queries)} search variants ({per_query} each):")
    if PROXIES:
        print(f"Proxy: {_proxy}\n")
    else:
        print()

    all_video_ids = []
    video_query_map = {}

    for query in queries:
        print(f"  Searching: {query}")
        ids = search_videos(query, published_after, max_results=per_query)
        for vid_id in ids:
            if vid_id not in video_query_map:
                video_query_map[vid_id] = query
                all_video_ids.append(vid_id)

    print(f"\nFound {len(all_video_ids)} unique videos. Fetching full metadata...")
    videos = get_video_details(all_video_ids[: args.max_videos])
    for v in videos:
        v["search_query"] = video_query_map.get(v["video_id"], "")

    channel_ids = {v["channel_id"] for v in videos}
    print(f"Fetching stats for {len(channel_ids)} channels...")
    channels = get_channel_details(channel_ids)

    output = {
        "query": args.query,
        "slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": args.days,
        "total_videos": len(videos),
        "total_channels": len(channels),
        "search_queries": queries,
        "videos": videos,
        "channels": channels,
    }

    out_path = os.path.join(out_dir, "youtube_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(videos)} videos | {len(channels)} channels -> {out_path}")


if __name__ == "__main__":
    main()
