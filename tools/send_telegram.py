#!/usr/bin/env python3
"""
Sends top-20 items as photo cards to Telegram + full.txt as document.
Works with all sources: youtube, reddit, github, google-maps, telegram-channels.
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENV_FILE = ".env"

# Source metadata: (emoji, label, primary_metric_label, secondary_metric_label)
SOURCE_META = {
    "youtube":           ("🎬", "YouTube Research",          "👁 Просмотры",  "👍 Engagement"),
    "reddit":            ("🟠", "Reddit Research",            "🔺 Score",      "💬 Комментарии"),
    "github":            ("⭐", "GitHub Trending",            "⭐ Stars",      "🍴 Forks"),
    "google-maps":       ("🗺", "Google Maps Research",       "⭐ Рейтинг",    "💬 Отзывы"),
    "telegram-channels": ("📢", "Telegram Channels Research", "👁 Просмотры",  "↩️ Пересылок"),
}


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
    set_key(ENV_FILE, "TELEGRAM_CHAT_ID", chat_id)
    print(f"Сохранён в .env как TELEGRAM_CHAT_ID={chat_id}")
    return chat_id


def fmt_num(n: int) -> str:
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


def item_url(v: dict) -> str:
    """Return canonical URL for this item regardless of source."""
    if v.get("url"):
        return v["url"]
    vid = v.get("video_id", "")
    return f"https://youtube.com/watch?v={vid}"


def build_caption(v: dict, source: str) -> str:
    """Build source-adapted card caption."""
    views = v.get("view_count", 0)
    likes = v.get("like_count", 0)
    comments = v.get("comment_count", 0)
    title = v.get("title", "—")[:80]
    channel = v.get("channel_title", "—")
    published = published_ago(v.get("published_at", ""))
    url = item_url(v)

    if source == "youtube":
        dur = fmt_duration(v.get("duration_seconds", 0))
        eng = round((likes + comments) / views * 100, 1) if views > 100 else 0
        metrics = (
            f"👁 {fmt_num(views)}  |  👍 {eng}%  |  ⏱ {dur}\n"
            f"💬 {fmt_num(comments)} комм.  |  📅 {published}"
        )
        icon = "🎬"

    elif source == "reddit":
        ratio = v.get("upvote_ratio", 0)
        awards = v.get("awards", 0)
        ratio_str = f"{round(ratio * 100)}% upvoted" if ratio else ""
        awards_str = f"  🏅 {awards}" if awards else ""
        metrics = (
            f"🔺 {fmt_num(views)} score  |  💬 {fmt_num(comments)} комм.\n"
            f"📅 {published}  {ratio_str}{awards_str}"
        )
        icon = "🟠"

    elif source == "github":
        forks = v.get("forks", likes)
        lang = v.get("language", "")
        lang_str = f"  [{lang}]" if lang else ""
        metrics = (
            f"⭐ {fmt_num(views)} stars  |  🍴 {fmt_num(forks)} forks\n"
            f"💬 {fmt_num(comments)} issues  |  📅 {published}{lang_str}"
        )
        icon = "⭐"

    elif source == "google-maps":
        rating = v.get("rating", 0)
        rating_str = f"★{rating:.1f}" if rating else "N/A"
        address = v.get("address", v.get("description", "")[:60])
        metrics = (
            f"{rating_str}  |  💬 {fmt_num(comments)} отзывов\n"
            f"📍 {address}"
        )
        icon = "🗺"

    elif source == "telegram-channels":
        forwards = likes
        metrics = (
            f"👁 {fmt_num(views)} просм.  |  ↩️ {fmt_num(forwards)} пересыл.\n"
            f"💬 {fmt_num(comments)} отв.  |  📅 {published}"
        )
        icon = "📢"

    else:
        metrics = f"👁 {fmt_num(views)}  |  💬 {fmt_num(comments)}  |  📅 {published}"
        icon = "📌"

    return (
        f"{icon} <b>{title}</b>\n"
        f"📺 {channel}\n\n"
        f"{metrics}\n\n"
        f"🔗 {url}"
    )


def send_item_card(v: dict, rank: int, source: str):
    """Send one item as photo + caption (or text if no thumbnail)."""
    caption = build_caption(v, source)
    thumb = v.get("thumbnail_url", "")
    try:
        if thumb:
            try:
                photo_bytes = requests.get(thumb, timeout=10).content
                api("sendPhoto", data={
                    "chat_id": CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML",
                }, files={"photo": photo_bytes})
                return
            except Exception:
                pass  # Fall through to sendMessage
        api("sendMessage", json={
            "chat_id": CHAT_ID,
            "text": caption,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })
    except Exception as e:
        print(f"  [WARN] Не удалось отправить карточку #{rank}: {e}")


def build_header(query: str, source: str, data: dict) -> str:
    """Build source-adapted header summary message."""
    meta = SOURCE_META.get(source, ("📊", "Research", "👁 Просмотры", "💬 Комментарии"))
    icon, label, metric1_lbl, metric2_lbl = meta

    total = data.get("total_videos_analyzed", 0)
    stats = data.get("stats", {})
    ai = data.get("ai_insights", {})
    run_date = data.get("generated_at", "")[:10]
    top_count = len(data.get("top_videos", []))

    total_views = stats.get("total_views", 0)
    avg_views = stats.get("avg_views", 0)

    if source == "youtube":
        avg_dur = stats.get("avg_duration_minutes", 0)
        extra = f"⏱ Средняя длина: <b>{avg_dur} мин</b>\n"
        count_label = f"🎬 {total} видео"
    elif source == "reddit":
        extra = ""
        count_label = f"📝 {total} постов"
        metric1_lbl = "🔺 Суммарный score"
        metric2_lbl = "📈 Средний score"
    elif source == "github":
        extra = ""
        count_label = f"📦 {total} репозиториев"
        metric1_lbl = "⭐ Суммарные звёзды"
        metric2_lbl = "📈 Средние звёзды"
    elif source == "google-maps":
        extra = ""
        count_label = f"📍 {total} мест"
        metric1_lbl = "💬 Суммарные отзывы"
        metric2_lbl = "📈 Средние отзывы"
    elif source == "telegram-channels":
        extra = ""
        count_label = f"📢 {total} постов"
        metric1_lbl = "👁 Суммарные просмотры"
        metric2_lbl = "📈 Средние просмотры"
    else:
        extra = ""
        count_label = f"📊 {total} результатов"

    return (
        f"{icon} <b>{label}: {query}</b>\n"
        f"📅 {run_date}  |  {count_label}\n\n"
        f"{metric1_lbl}: <b>{fmt_num(total_views)}</b>\n"
        f"{metric2_lbl}: <b>{fmt_num(avg_views)}</b>\n"
        f"{extra}\n"
        f"💡 <b>Резюме:</b> {ai.get('summary', '—')}\n\n"
        f"⬇️ Топ {top_count} результатов:"
    )


def main():
    global CHAT_ID

    parser = argparse.ArgumentParser(description="Send top items to Telegram")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    parser.add_argument("--top", type=int, default=20, help="How many items to send (default 20)")
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

    # Detect source — stored in analysis.json or youtube_data.json
    source = data.get("source", "youtube")
    if source == "youtube":
        # Also check the raw data file in case analyze_trends didn't propagate it
        raw_path = os.path.join(".tmp", slug, "youtube_data.json")
        if os.path.exists(raw_path):
            try:
                with open(raw_path, encoding="utf-8") as f:
                    raw = json.load(f)
                source = raw.get("source", "youtube")
            except Exception:
                pass

    top_items = data.get("top_videos", [])[:args.top]

    # Header message
    header = build_header(args.query, source, data)
    try:
        api("sendMessage", json={
            "chat_id": CHAT_ID,
            "text": header,
            "parse_mode": "HTML",
        })
    except Exception as e:
        print(f"[ERROR] Не удалось отправить заголовок: {e}")
        sys.exit(1)

    print(f"Отправляю {len(top_items)} карточек (источник: {source})...")
    for i, v in enumerate(top_items, 1):
        safe_title = v.get("title", "")[:50].encode("ascii", errors="replace").decode("ascii")
        print(f"  {i}/{len(top_items)}: {safe_title}")
        send_item_card(v, i, source)
        time.sleep(0.4)  # avoid flood limits

    # Send full.txt as document
    if os.path.exists(full_txt_path):
        print("Отправляю full.txt как документ...")
        try:
            with open(full_txt_path, "rb") as f:
                api("sendDocument", data={
                    "chat_id": CHAT_ID,
                    "caption": f"📄 Все ссылки по теме «{args.query}» (URL | название | источник)",
                    "parse_mode": "HTML",
                }, files={"document": (f"{slug}-full.txt", f, "text/plain")})
        except Exception as e:
            print(f"[WARN] Не удалось отправить документ: {e}")
    else:
        print(f"[WARN] {full_txt_path} не найден — документ не отправлен")

    print("Telegram отправка завершена.")


if __name__ == "__main__":
    main()
