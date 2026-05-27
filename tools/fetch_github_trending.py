#!/usr/bin/env python3
"""
Fetches trending GitHub repositories for any topic/keyword.
Uses GitHub Search API — free, optional GH_TOKEN for higher rate limits.
Output format: same as youtube_data.json.

Usage:
  python tools/fetch_github_trending.py --query "LM Studio"
  python tools/fetch_github_trending.py --query "AI agents" --days 7 --max_videos 50
Output: .tmp/{slug}/youtube_data.json
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
PROXIES = {"https": _proxy, "http": _proxy} if _proxy else None

GH_TOKEN = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
GITHUB_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if GH_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GH_TOKEN}"


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def search_repos(query: str, days: int = 7, limit: int = 100) -> list:
    """Search GitHub repos created/pushed in the last N days, sorted by stars."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    search_query = f"{query} pushed:>={cutoff}"
    repos = []
    page = 1
    per_page = min(100, limit)

    while len(repos) < limit:
        try:
            resp = requests.get(
                f"{GITHUB_BASE}/search/repositories",
                params={"q": search_query, "sort": "stars", "order": "desc",
                        "per_page": per_page, "page": page},
                headers=HEADERS, proxies=PROXIES, timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            repos.extend(items)
            page += 1
            if len(items) < per_page:
                break
        except Exception as e:
            print(f"[WARN] GitHub search page {page} failed: {e}")
            break

    return repos[:limit]


def repo_to_item(repo: dict, search_query: str) -> dict:
    """Convert GitHub repo to unified item format."""
    full_name = repo.get("full_name", "")
    url = repo.get("html_url", f"https://github.com/{full_name}")
    owner = repo.get("owner", {})
    avatar = owner.get("avatar_url", "")
    pushed_at = repo.get("pushed_at") or repo.get("created_at") or ""
    topics = repo.get("topics", [])
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    issues = repo.get("open_issues_count", 0)
    lang = repo.get("language") or ""

    description = repo.get("description") or ""
    if lang:
        description = f"[{lang}] {description}"
    if topics:
        description += f"\nТеги: {', '.join(topics[:8])}"

    return {
        "video_id": f"gh_{full_name.replace('/', '_')}",
        "url": url,
        "title": repo.get("name", full_name),
        "channel_id": owner.get("login", ""),
        "channel_title": owner.get("login", ""),
        "published_at": pushed_at,
        "description": description,
        "tags": topics,
        "thumbnail_url": avatar,
        "view_count": stars,
        "like_count": stars,
        "comment_count": issues,
        "duration": f"{forks} forks",
        "duration_seconds": 0,
        "search_query": search_query,
        # GitHub-specific extras
        "forks": forks,
        "language": lang,
        "full_name": full_name,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch trending GitHub repos for a topic")
    parser.add_argument("--query", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max_videos", type=int, default=100)
    args = parser.parse_args()

    slug = make_slug(args.query)
    out_dir = os.path.join(".tmp", slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "youtube_data.json")

    if not GH_TOKEN:
        print("[INFO] GH_TOKEN не задан — используется anonymous API (60 req/h). Добавьте GH_TOKEN в .env для большего лимита.")

    print(f"Ищу GitHub репозитории по теме: {args.query} (за последние {args.days} дней)")

    repos = search_repos(args.query, days=args.days, limit=args.max_videos)
    items = [repo_to_item(r, args.query) for r in repos]

    result = {
        "query": args.query,
        "slug": slug,
        "source": "github",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": args.days,
        "total_videos": len(items),
        "total_channels": len({i["channel_id"] for i in items}),
        "search_queries": [args.query],
        "videos": items,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Сохранено {len(items)} репозиториев → {out_path}")


if __name__ == "__main__":
    main()
