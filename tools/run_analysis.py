#!/usr/bin/env python3
"""
Master runner — full YouTube research pipeline for any keyword.

Usage:
  python tools/run_analysis.py --query "LM Studio"
  python tools/run_analysis.py --query "Obsidian AI" --days 14 --max-videos 150
  python tools/run_analysis.py --query "Claude Code" --skip-email --skip-telegram
  python tools/run_analysis.py --query "NotebookLM" --skip-fetch  # reuse cached data

Steps:
  1. fetch_youtube_data.py  → .tmp/{slug}/youtube_data.json
  2. save_links.py          → outputs/{slug}/urls.txt + full.txt (dedup)
  3. analyze_trends.py      → .tmp/{slug}/analysis.json
  4. generate_dashboard.py  → .tmp/{slug}/dashboard.html  (opens in browser)
  5. export_to_sheets.py    → Google Sheets master file (append)
  6. send_gmail.py          → email with dashboard (optional)
  7. send_telegram.py       → top-20 cards + full.txt (optional)
  8. create_notebooklm.py   → new NotebookLM notebook (optional)
"""

import argparse
import subprocess
import sys
import os
import time
import re
import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))


def send_tg_summary(query: str, slug: str):
    """Send final summary message to Telegram with notebook and sheets links."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    notebook_url = ""
    nb_path = os.path.join("outputs", slug, "notebook_url.txt")
    if os.path.exists(nb_path):
        with open(nb_path, encoding="utf-8") as f:
            notebook_url = f.read().strip()

    sheets_id = os.getenv("GOOGLE_SHEETS_ID", "")
    sheets_url = f"https://docs.google.com/spreadsheets/d/{sheets_id}" if sheets_id else ""

    lines = [f"✅ <b>Анализ завершён: {query}</b>\n"]
    if notebook_url:
        lines.append(f"📓 <b>NotebookLM:</b>\n{notebook_url}")
    if sheets_url:
        lines.append(f"📊 <b>Google Sheets:</b>\n{sheets_url}")
    if not notebook_url and not sheets_url:
        return

    text = "\n\n".join(lines)
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"[WARN] Не удалось отправить итог в Telegram: {e}")


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def run_step(name: str, cmd: list, required: bool = True) -> bool:
    print(f"\n{'='*60}")
    print(f"  ШАГ: {name}")
    print(f"{'='*60}")
    start = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n[FAILED] {name} завершился с кодом {result.returncode} ({elapsed:.1f}s)")
        if required:
            sys.exit(result.returncode)
        return False

    print(f"\n[OK] {name} — {elapsed:.1f}s")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Research — полный цикл анализа по ключевому запросу"
    )
    parser.add_argument("--query", required=True, help='Ключевой запрос, например "LM Studio"')
    parser.add_argument("--days", type=int, default=7, help="Глубина поиска в днях (default: 7)")
    parser.add_argument("--max-videos", type=int, default=100, help="Макс. видео (default: 100)")
    parser.add_argument("--skip-fetch", action="store_true", help="Не качать данные заново (переиспользовать кэш)")
    parser.add_argument("--skip-email", action="store_true", help="Не отправлять на email")
    parser.add_argument("--skip-telegram", action="store_true", help="Не отправлять в Telegram")
    parser.add_argument("--skip-notebook", action="store_true", help="Не создавать ноутбук в NotebookLM")
    parser.add_argument("--skip-sheets", action="store_true", help="Не экспортировать в Google Sheets")
    args = parser.parse_args()

    # Run from project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    os.chdir(project_root)

    slug = make_slug(args.query)
    python = sys.executable

    print(f"\n{'='*60}")
    print(f"  YOUTUBE RESEARCH PIPELINE")
    print(f"  Запрос:  {args.query}")
    print(f"  Период:  {args.days} дней  |  Видео: {args.max_videos}")
    print(f"  Email:   {'SKIP' if args.skip_email else 'musicboxer@gmail.com'}")
    print(f"  Telegram:{'SKIP' if args.skip_telegram else 'ON'}")
    print(f"  Sheets:  {'SKIP' if args.skip_sheets else 'ON'}")
    print(f"  NLM:     {'SKIP' if args.skip_notebook else 'ON'}")
    print(f"{'='*60}")

    # ── Шаг 1: Сбор данных ────────────────────────────────────
    if not args.skip_fetch:
        run_step(
            "1/8 — Сбор данных YouTube",
            [python, "tools/fetch_youtube_data.py",
             "--query", args.query,
             "--days", str(args.days),
             "--max_videos", str(args.max_videos)],
            required=True,
        )
    else:
        data_path = os.path.join(".tmp", slug, "youtube_data.json")
        if not os.path.exists(data_path):
            print(f"[ERROR] --skip-fetch указан, но {data_path} не существует!")
            sys.exit(1)
        print(f"\n[SKIP] Шаг 1 — переиспользуем {data_path}")

    # ── Шаг 2: Сохранение ссылок ──────────────────────────────
    run_step(
        "2/8 — Сохранение ссылок (дедупликация)",
        [python, "tools/save_links.py", "--query", args.query],
        required=True,
    )

    # ── Шаг 3: Анализ трендов ─────────────────────────────────
    run_step(
        "3/8 — Анализ трендов (OpenAI)",
        [python, "tools/analyze_trends.py", "--query", args.query],
        required=True,
    )

    # ── Шаг 4: Генерация дашборда ─────────────────────────────
    run_step(
        "4/8 — Генерация HTML-дашборда",
        [python, "tools/generate_dashboard.py", "--query", args.query],
        required=True,
    )

    # ── Шаг 5: Экспорт в Google Sheets ───────────────────────
    if not args.skip_sheets:
        run_step(
            "5/8 — Экспорт в Google Sheets",
            [python, "tools/export_to_sheets.py", "--query", args.query],
            required=False,
        )
    else:
        print("\n[SKIP] Шаг 5 — Google Sheets (--skip-sheets)")

    # ── Шаг 6: Email ──────────────────────────────────────────
    if not args.skip_email:
        dashboard_path = os.path.join(".tmp", slug, "dashboard.html")
        run_step(
            "6/8 — Отправка на email",
            [python, "tools/send_gmail.py",
             "--dashboard", dashboard_path,
             "--subject", f"YouTube Research: {args.query}"],
            required=False,
        )
    else:
        print("\n[SKIP] Шаг 6 — Email (--skip-email)")

    # ── Шаг 7: Telegram ───────────────────────────────────────
    if not args.skip_telegram:
        run_step(
            "7/8 — Отправка в Telegram",
            [python, "tools/send_telegram.py", "--query", args.query],
            required=False,
        )
    else:
        print("\n[SKIP] Шаг 7 — Telegram (--skip-telegram)")

    # ── Шаг 8: NotebookLM ─────────────────────────────────────
    if not args.skip_notebook:
        run_step(
            "8/8 — Создание ноутбука NotebookLM",
            [python, "tools/create_notebooklm.py", "--query", args.query],
            required=False,
        )
    else:
        print("\n[SKIP] Шаг 8 — NotebookLM (--skip-notebook)")

    # ── Итог ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ПАЙПЛАЙН ЗАВЕРШЁН")
    print(f"  Запрос:    {args.query}")
    print(f"  Дашборд:   .tmp/{slug}/dashboard.html")
    print(f"  Ссылки:    outputs/{slug}/urls.txt")
    print(f"  Full list: outputs/{slug}/full.txt")
    print(f"{'='*60}\n")

    # ── Итоговое сообщение в Telegram ─────────────────────────
    if not args.skip_telegram:
        send_tg_summary(args.query, slug)


if __name__ == "__main__":
    main()
