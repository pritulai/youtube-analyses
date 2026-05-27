#!/usr/bin/env python3
"""
Fetches top Reddit posts for any topic/keyword.
Uses Reddit's public JSON API — no API key required.
Output format: same as youtube_data.json so downstream tools work unchanged.

Usage:
  python tools/fetch_reddit_data.py --query "LM Studio"
  python tools/fetch_reddit_data.py --query "AI tools" --days 14 --max_videos 100
Output: .tmp/{slug}/youtube_data.json
"""

import os
import sys
import json
import re
import time
import argparse
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
PROXIES = {"https": _proxy, "http": _proxy} if _proxy else None

REDDIT_BASE = "https://www.reddit.com"
HEADERS = {"User-Agent": "YT-Research-Bot/1.0"}


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def find_subreddits(query: str) -> list:
    """Search for relevant subreddits by query keyword."""
    try:
        resp = requests.get(
            f"{REDDIT_BASE}/subreddits/search.json",
            params={"q": query, "limit": 5, "sort": "relevance"},
            headers=HEADERS, proxies=PROXIES, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        subs = []
        for item in data.get("data", {}).get("children", []):
            d = item.get("data", {})
            name = d.get("display_name", "")
            subscribers = d.get("subscribers", 0)
            if name and subscribers > 1000:
                subs.append(name)
        return subs[:5] or ["ArtificialInteligence", "MachineLearning"]
    except Exception as e:
        print(f"[WARN] Subreddit search failed: {e}")
        return ["ArtificialInteligence", "MachineLearning", "learnprogramming"]


def search_reddit(query: str, subreddit: str = "all", limit: int = 25, days: int = 7) -> list:
    """Search posts on Reddit (or in a specific subreddit)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    posts = []
    try:
        url = f"{REDDIT_BASE}/r/{subreddit}/search.json"
        resp = requests.get(
            url,
            params={"q": query, "sort": "top", "t": "week" if days <= 7 else "month",
                    "limit": limit, "restrict_sr": "true" if subreddit != "all" else "false"},
            headers=HEADERS, proxies=PROXIES, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data", {}).get("children", []):
            d = item.get("data", {})
            created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
            if created < cutoff:
                continue
            posts.append(d)
        time.sleep(0.5)  # Respect rate limit
    except Exception as e:
        print(f"[WARN] Reddit search in r/{subreddit} failed: {e}")
    return posts


def post_to_item(post: dict, search_query: str) -> dict:
    """Convert Reddit post to unified item format."""
    post_id = post.get("id", "")
    subreddit = post.get("subreddit", "")
    url = f"https://www.reddit.com{post.get('permalink', f'/r/{subreddit}/comments/{post_id}/')}"
    thumbnail = post.get("thumbnail", "")
    if thumbnail in ("self", "default", "nsfw", "spoiler", ""):
        thumbnail = ""
    created_utc = post.get("created_utc", 0)
    published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()

    flair = post.get("link_flair_text") or ""
    tags = [flair] if flair else []

    score = post.get("score", 0)
    return {
        "video_id": f"reddit_{post_id}",
        "url": url,
        "title": post.get("title", ""),
        "channel_id": f"r/{subreddit}",
        "channel_title": f"r/{subreddit}",
        "published_at": published_at,
        "description": post.get("selftext", "")[:500] or post.get("url", ""),
        "tags": tags,
        "thumbnail_url": thumbnail,
        "view_count": score,
        "like_count": score,
        "comment_count": post.get("num_comments", 0),
        "duration": "N/A",
        "duration_seconds": 0,
        "search_query": search_query,
        # Reddit-specific extras
        "upvote_ratio": post.get("upvote_ratio", 0),
        "awards": post.get("total_awards_received", 0),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Reddit posts for a topic")
    parser.add_argument("--query", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max_videos", type=int, default=100)
    args = parser.parse_args()

    slug = make_slug(args.query)
    out_dir = os.path.join(".tmp", slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "youtube_data.json")

    print(f"Ищу Reddit посты по теме: {args.query}")

    # Find relevant subreddits
    subreddits = find_subreddits(args.query)
    print(f"Найдены суброддиты: {subreddits}")

    # Search in "all" + specific subreddits
    search_targets = ["all"] + subreddits
    per_target = max(10, args.max_videos // len(search_targets))

    seen_ids = set()
    all_posts = []

    for target in search_targets:
        print(f"  Ищу в r/{target}...")
        posts = search_reddit(args.query, subreddit=target, limit=per_target, days=args.days)
        for post in posts:
            pid = post.get("id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_posts.append(post_to_item(post, f"r/{target}: {args.query}"))

        if len(all_posts) >= args.max_videos:
            break

    # Sort by score (views equivalent) desc
    all_posts.sort(key=lambda x: x["view_count"], reverse=True)
    all_posts = all_posts[:args.max_videos]

    result = {
        "query": args.query,
        "slug": slug,
        "source": "reddit",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": args.days,
        "total_videos": len(all_posts),
        "total_channels": len({p["channel_id"] for p in all_posts}),
        "search_queries": [f"r/{s}: {args.query}" for s in subreddits],
        "videos": all_posts,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nСохранено {len(all_posts)} постов → {out_path}")


if __name__ == "__main__":
    main()
