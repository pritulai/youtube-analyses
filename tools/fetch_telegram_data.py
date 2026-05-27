#!/usr/bin/env python3
"""
Fetches posts from public Telegram channels for any topic/keyword.
Requires Telethon + Telegram API credentials (my.telegram.org):
  TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env

Output format: same as youtube_data.json.

Usage:
  python tools/fetch_telegram_data.py --query "AI tools"
  python tools/fetch_telegram_data.py --query "нейросети" --days 14 --max_videos 100
Output: .tmp/{slug}/youtube_data.json

First run: Telegram will send SMS code to TELEGRAM_PHONE for login.
Session saved to .tmp/telegram_session.session (gitignored).
"""

import os
import sys
import json
import re
import asyncio
import argparse
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

TG_API_ID = os.getenv("TELEGRAM_API_ID")
TG_API_HASH = os.getenv("TELEGRAM_API_HASH")
TG_PHONE = os.getenv("TELEGRAM_PHONE")

SESSION_FILE = os.path.join(_ROOT, ".tmp", "telegram_session")


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def check_deps():
    try:
        import telethon  # noqa
    except ImportError:
        print("[ERROR] Telethon не установлен. Выполни: pip install telethon")
        sys.exit(1)
    if not TG_API_ID or not TG_API_HASH:
        print("[ERROR] TELEGRAM_API_ID и TELEGRAM_API_HASH не заданы в .env")
        print("  Получи на https://my.telegram.org → API development tools")
        sys.exit(1)
    if not TG_PHONE:
        print("[ERROR] TELEGRAM_PHONE не задан в .env (формат: +79991234567)")
        sys.exit(1)


# Known AI/tech channels (fallback if search returns nothing)
KNOWN_CHANNELS = {
    "ai": ["artificialintelligentnews", "OpenAI", "anthropic_news"],
    "default": ["tgstat", "durov"],
}


async def find_channels(client, query: str, limit: int = 10) -> list:
    """Search public channels by query."""
    from telethon.tl.functions.contacts import SearchRequest
    try:
        result = await client(SearchRequest(q=query, limit=limit))
        channels = []
        for chat in result.chats:
            if hasattr(chat, "username") and chat.username:
                channels.append(chat.username)
        return channels[:limit]
    except Exception as e:
        print(f"[WARN] Channel search failed: {e}")
        return []


async def fetch_channel_posts(client, channel_username: str, days: int, limit: int) -> list:
    """Fetch recent posts from a channel."""
    from telethon.tl.types import MessageMediaPhoto
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    posts = []
    try:
        entity = await client.get_entity(channel_username)
        channel_title = getattr(entity, "title", channel_username)
        channel_id = str(getattr(entity, "id", channel_username))

        async for msg in client.iter_messages(entity, limit=limit, reverse=False):
            if not msg.date:
                continue
            msg_date = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
            if msg_date < cutoff:
                break
            if not msg.text:
                continue

            url = f"https://t.me/{channel_username}/{msg.id}"
            has_photo = isinstance(getattr(msg, "media", None), MessageMediaPhoto)

            views = getattr(msg, "views", 0) or 0
            forwards = getattr(msg, "forwards", 0) or 0
            replies = getattr(msg.replies, "replies", 0) if msg.replies else 0

            title = msg.text[:100].replace("\n", " ").strip()
            posts.append({
                "video_id": f"tg_{channel_username}_{msg.id}",
                "url": url,
                "title": title,
                "channel_id": channel_id,
                "channel_title": channel_title,
                "published_at": msg_date.isoformat(),
                "description": msg.text[:500],
                "tags": [],
                "thumbnail_url": "",
                "view_count": views,
                "like_count": forwards,
                "comment_count": replies,
                "duration": f"{forwards} пересылок",
                "duration_seconds": 0,
                "search_query": f"@{channel_username}",
                "has_photo": has_photo,
            })
    except Exception as e:
        safe_err = str(e)[:100].encode("ascii", errors="replace").decode("ascii")
        print(f"[WARN] Не удалось получить посты из @{channel_username}: {safe_err}")
    return posts


async def run(query: str, days: int, max_videos: int, out_path: str):
    from telethon import TelegramClient
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

    async with TelegramClient(SESSION_FILE, int(TG_API_ID), TG_API_HASH) as client:
        await client.start(phone=TG_PHONE)
        print("Telegram авторизован.")

        # Find channels matching query
        channels = await find_channels(client, query, limit=10)
        if not channels:
            print("[WARN] Каналы не найдены по запросу, используем fallback.")
            channels = KNOWN_CHANNELS.get("ai", [])

        print(f"Найдено каналов: {len(channels)}: {channels[:5]}")

        seen_ids = set()
        all_posts = []
        per_channel = max(10, max_videos // max(len(channels), 1))

        for ch in channels:
            print(f"  Читаю @{ch}...")
            posts = await fetch_channel_posts(client, ch, days=days, limit=per_channel * 2)
            for p in posts:
                pid = p["video_id"]
                if pid not in seen_ids:
                    seen_ids.add(pid)
                    all_posts.append(p)
            if len(all_posts) >= max_videos:
                break

    all_posts.sort(key=lambda x: x["view_count"], reverse=True)
    all_posts = all_posts[:max_videos]
    return all_posts, channels


def main():
    check_deps()

    parser = argparse.ArgumentParser(description="Fetch Telegram channel posts")
    parser.add_argument("--query", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max_videos", type=int, default=100)
    args = parser.parse_args()

    slug = make_slug(args.query)
    out_dir = os.path.join(".tmp", slug)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "youtube_data.json")

    print(f"Ищу посты в Telegram-каналах по теме: {args.query}")

    posts, channels = asyncio.run(run(args.query, args.days, args.max_videos, out_path))

    result = {
        "query": args.query,
        "slug": slug,
        "source": "telegram-channels",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days_back": args.days,
        "total_videos": len(posts),
        "total_channels": len({p["channel_id"] for p in posts}),
        "search_queries": [f"@{c}" for c in channels],
        "videos": posts,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Сохранено {len(posts)} постов → {out_path}")


if __name__ == "__main__":
    main()
