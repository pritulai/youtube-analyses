#!/usr/bin/env python3
"""
Sends top-20 videos as photo cards to Telegram + full.txt as document.
Usage: python tools/send_telegram.py --query "LM Studio"
Env:   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (auto-detected on first run)
"""

import os
import sys
import json
import re
import time
import argparse
import requests
from datetime import datetime, timezone

from dotenv import load_dotenv, set_key

# Resolve .env relative to project root (one level up from tools/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENV_FILE = ".env"


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def api(method: str, **kwargs) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    resp = requests.post(url, timeout=30, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error [{method}]: {data.get('description')}")
    return data["result"]


def detect_chat_id() -> str:
    """Get chat_id from the most recent message sent to the bot."""
    print("TELEGRAM_CHAT_ID не задан. Определяю автоматически...")
    print("Отправь боту любое сообщение в Telegram, затем нажми Enter.")
    input("  [Enter для продолжения]")
    updates = api("getUpdates", json={"limit": 10, "offset": -10})
    if not updates:
        print("[ERROR] Нет входящих сообщений. Напиши /start боту и запусти снова.")
        sys.exit(1)
    chat_id = str(updates[-1]["message"]["chat"]["id"])
    print(f"Определён chat_id: {chat_id}")
    # Save to .env
    set_key(ENV_FILE, "TELEGRAM_CHAT_ID", chat_id)
    print(f"Сохранён в .env как TELEGRAM_CHAT_ID={chat_id}")
    return chat_id


def fmt_views(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def fmt_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def published_ago(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        days = (datetime.now(dt.tzinfo) - dt).days
        if days == 0:
            return "сегодня"
        if days == 1:
            return "вчера"
        return f"{days} дн. назад"
    except Exception:
        return dt_str[:10]


def send_video_card(v: dict, rank: int, query: str):
    """Send one video as photo + caption."""
    views = v["view_count"]
    likes = v["like_count"]
    comments = v["comment_count"]
    eng = round((likes + comments) / views * 100, 1) if views > 100 else 0

    caption = (
        f"🎬 <b>{v['title']}</b>\n"
        f"📺 {v['channel_title']}\n\n"
        f"👁 {fmt_views(views)}  |  👍 {eng}%  |  ⏱ {fmt_duration(v['duration_seconds'])}\n"
        f"💬 {fmt_views(comments)} комм.  |  📅 {published_ago(v['published_at'])}\n\n"
        f"🔗 https://youtube.com/watch?v={v['video_id']}"
    )

    thumb = v.get("thumbnail_url", "")
    try:
        if thumb:
            api("sendPhoto", data={
                "chat_id": CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
            }, files={"photo": requests.get(thumb, timeout=10).content})
        else:
            api("sendMessage", json={
                "chat_id": CHAT_ID,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            })
    except Exception as e:
        print(f"  [WARN] Не удалось отправить видео #{rank}: {e}")


def main():
    global CHAT_ID

    parser = argparse.ArgumentParser(description="Send top videos to Telegram")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    parser.add_argument("--top", type=int, default=20, help="How many videos to send (default 20)")
    args = parser.parse_args()

    if not BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN не задан в .env")
        sys.exit(1)

    if not CHAT_ID:
        CHAT_ID = detect_chat_id()

    slug = make_slug(args.query)
    analysis_path = os.path.join(".tmp", slug, "analysis.json")
    full_txt_path = os.path.join("outputs", slug, "full.txt")

    if not os.path.exists(analysis_path):
        print(f"[ERROR] {analysis_path} не найден. Запусти analyze_trends.py сначала.")
        sys.exit(1)

    with open(analysis_path, encoding="utf-8") as f:
        data = json.load(f)

    top_videos = data.get("top_videos", [])[:args.top]
    total = data.get("total_videos_analyzed", 0)
    stats = data.get("stats", {})
    ai = data.get("ai_insights", {})
    run_date = data.get("generated_at", "")[:10]

    # Header message
    summary_text = (
        f"📊 <b>YouTube Research: {args.query}</b>\n"
        f"📅 {run_date}  |  🎬 {total} видео проанализировано\n\n"
        f"👁 Суммарные просмотры: <b>{fmt_views(stats.get('total_views', 0))}</b>\n"
        f"📈 Средние просмотры: <b>{fmt_views(stats.get('avg_views', 0))}</b>\n"
        f"⏱ Средняя длина: <b>{stats.get('avg_duration_minutes', 0)} мин</b>\n\n"
        f"💡 <b>Резюме:</b> {ai.get('summary', '—')}\n\n"
        f"⬇️ Топ {len(top_videos)} видео:"
    )

    try:
        api("sendMessage", json={
            "chat_id": CHAT_ID,
            "text": summary_text,
            "parse_mode": "HTML",
        })
    except Exception as e:
        print(f"[ERROR] Не удалось отправить заголовок: {e}")
        sys.exit(1)

    print(f"Отправляю {len(top_videos)} видео-карточек...")
    for i, v in enumerate(top_videos, 1):
        safe_title = v['title'][:50].encode('ascii', errors='replace').decode('ascii')
        print(f"  {i}/{len(top_videos)}: {safe_title}")
        send_video_card(v, i, args.query)
        time.sleep(0.4)  # avoid flood limits

    # Send full.txt as document
    if os.path.exists(full_txt_path):
        print("Отправляю full.txt как документ...")
        try:
            with open(full_txt_path, "rb") as f:
                api("sendDocument", data={
                    "chat_id": CHAT_ID,
                    "caption": f"📄 Все ссылки по теме «{args.query}» (URL | название | канал)",
                    "parse_mode": "HTML",
                }, files={"document": (f"{slug}-full.txt", f, "text/plain")})
        except Exception as e:
            print(f"[WARN] Не удалось отправить документ: {e}")
    else:
        print(f"[WARN] {full_txt_path} не найден — документ не отправлен")

    print("Telegram отправка завершена.")


if __name__ == "__main__":
    main()
