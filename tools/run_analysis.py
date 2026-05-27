#!/usr/bin/env python3
"""
Master runner — full research pipeline for any keyword and source platform.

Usage:
  python tools/run_analysis.py --query "LM Studio"
  python tools/run_analysis.py --query "AI tools" --source reddit
  python tools/run_analysis.py --query "Obsidian AI" --days 14 --max-videos 150
  python tools/run_analysis.py --query "Claude Code" --skip-email --skip-telegram
  python tools/run_analysis.py --query "NotebookLM" --skip-fetch  # reuse cached data

Sources: youtube (default), reddit, google-maps, github, telegram-channels

Steps:
  1. fetch_{source}_data.py → .tmp/{slug}/youtube_data.json
  2. save_links.py          → outputs/{slug}/urls.txt + full.txt (dedup)
  3. analyze_trends.py      → .tmp/{slug}/analysis.json
  4. generate_dashboard.py  → .tmp/{slug}/dashboard.html  (opens in browser)
  5. export_to_sheets.py    → Google Sheets master file (append)
  6. send_gmail.py          → email with dashboard + PDF (optional)
  7. send_telegram.py       → summary + full.txt (optional)
  8. create_notebooklm.py   → NotebookLM notebook + master-prompt note + slides PDF (optional)
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
    """Send final summary message to Telegram with links + dashboard file."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot_token or not chat_id:
        return

    tg_base = f"https://api.telegram.org/bot{bot_token}"

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
    lines.append("📈 <b>Дашборд:</b> HTML файл ниже ↓")

    text = "\n\n".join(lines)
    try:
        requests.post(
            f"{tg_base}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as e:
        print(f"[WARN] Не удалось отправить итог в Telegram: {e}")
        return

    # Send dashboard HTML as document
    dashboard_path = os.path.join(".tmp", slug, "dashboard.html")
    if os.path.exists(dashboard_path):
        try:
            with open(dashboard_path, "rb") as f:
                requests.post(
                    f"{tg_base}/sendDocument",
                    data={"chat_id": chat_id, "caption": f"📈 Dashboard: {query}"},
                    files={"document": (f"dashboard_{slug}.html", f, "text/html")},
                    timeout=30,
                )
            print("[OK] Дашборд отправлен в Telegram.")
        except Exception as e:
            print(f"[WARN] Не удалось отправить дашборд в Telegram: {e}")


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
        description="Research pipeline — полный цикл анализа по ключевому запросу"
    )
    parser.add_argument("--query", required=True, help='Ключевой запрос, например "LM Studio"')
    parser.add_argument("--source", default="youtube",
                        choices=["youtube", "reddit", "google-maps", "github", "telegram-channels"],
                        help="Источник данных (default: youtube)")
    parser.add_argument("--days", type=int, default=7, help="Глубина поиска в днях (default: 7)")
    parser.add_argument("--max-videos", type=int, default=100, help="Макс. видео/постов (default: 100)")
    parser.add_argument("--skip-fetch", action="store_true", help="Не качать данные заново (переиспользовать кэш)")
    parser.add_argument("--skip-email", action="store_true", help="Не отправлять на email")
    parser.add_argument("--skip-telegram", action="store_true", help="Не отправлять в Telegram")
    parser.add_argument("--skip-notebook", action="store_true", help="Не создавать ноутбук в NotebookLM")
    parser.add_argument("--skip-sheets", action="store_true", help="Не экспортировать в Google Sheets")
    parser.add_argument("--skip-slides", action="store_true", help="Не генерировать слайды в NotebookLM")
    args = parser.parse_args()

    # Run from project root
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    os.chdir(project_root)

    slug = make_slug(args.query)
    python = sys.executable

    print(f"\n{'='*60}")
    print(f"  RESEARCH PIPELINE")
    print(f"  Запрос:  {args.query}")
    print(f"  Источник:{args.source}")
    print(f"  Период:  {args.days} дней  |  Видео: {args.max_videos}")
    print(f"  Email:   {'SKIP' if args.skip_email else 'musicboxer@gmail.com'}")
    print(f"  Telegram:{'SKIP' if args.skip_telegram else 'ON'}")
    print(f"  Sheets:  {'SKIP' if args.skip_sheets else 'ON'}")
    print(f"  NLM:     {'SKIP' if args.skip_notebook else ('ON (без слайдов)' if args.skip_slides else 'ON + слайды')}")
    print(f"{'='*60}")

    # Map source to fetch script
    source_scripts = {
        "youtube":           "tools/fetch_youtube_data.py",
        "reddit":            "tools/fetch_reddit_data.py",
        "google-maps":       "tools/fetch_googlemaps_data.py",
        "github":            "tools/fetch_github_trending.py",
        "telegram-channels": "tools/fetch_telegram_data.py",
    }
    fetch_script = source_scripts[args.source]

    # ── Шаг 1: Сбор данных ────────────────────────────────────
    if not args.skip_fetch:
        if not os.path.exists(fetch_script):
            print(f"[ERROR] Скрипт для источника '{args.source}' ещё не реализован: {fetch_script}")
            print("  Запустите --source youtube или создайте нужный скрипт.")
            sys.exit(1)
        run_step(
            f"1/8 — Сбор данных ({args.source})",
            [python, fetch_script,
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

    # ── Шаг 6: Telegram ───────────────────────────────────────
    if not args.skip_telegram:
        run_step(
            "6/8 — Отправка в Telegram",
            [python, "tools/send_telegram.py", "--query", args.query],
            required=False,
        )
        # Send Sheets + Dashboard immediately after cards (don't wait for NLM)
        send_tg_summary(args.query, slug)
    else:
        print("\n[SKIP] Шаг 6 — Telegram (--skip-telegram)")

    # ── Шаг 7: NotebookLM (последний — из-за авторизации) ─────
    if not args.skip_notebook:
        nlm_cmd = [python, "tools/create_notebooklm.py", "--query", args.query]
        if args.skip_slides:
            nlm_cmd.append("--skip-slides")
        run_step(
            "7/8 — Создание ноутбука NotebookLM + слайды",
            nlm_cmd,
            required=False,
        )
        # Send NotebookLM link separately after it's ready
        if not args.skip_telegram:
            nb_path = os.path.join("outputs", slug, "notebook_url.txt")
            if os.path.exists(nb_path):
                with open(nb_path, encoding="utf-8") as f:
                    nb_url = f.read().strip()
                if nb_url:
                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    chat_id_env = os.getenv("TELEGRAM_CHAT_ID", "")
                    if bot_token and chat_id_env:
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={
                                    "chat_id": chat_id_env,
                                    "text": f"📓 <b>NotebookLM готов:</b>\n{nb_url}",
                                    "parse_mode": "HTML",
                                },
                                timeout=15,
                            )
                        except Exception:
                            pass
    else:
        print("\n[SKIP] Шаг 7 — NotebookLM (--skip-notebook)")

    # ── Шаг 8: Email (после NLM, чтобы прикрепить PDF) ───────
    if not args.skip_email:
        dashboard_path = os.path.join(".tmp", slug, "dashboard.html")
        email_cmd = [python, "tools/send_gmail.py",
                     "--dashboard", dashboard_path,
                     "--subject", f"Research: {args.query}"]
        # Attach PDF if NotebookLM slides were generated on step 7
        pdf_path_file = os.path.join("outputs", slug, "presentation_path.txt")
        if os.path.exists(pdf_path_file):
            with open(pdf_path_file, encoding="utf-8") as f:
                pdf_path = f.read().strip()
            if pdf_path and os.path.exists(pdf_path):
                email_cmd += ["--attachment", pdf_path]
        run_step("8/8 — Отправка на email (+ PDF)", email_cmd, required=False)
    else:
        print("\n[SKIP] Шаг 8 — Email (--skip-email)")

    # ── Итог ──────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ПАЙПЛАЙН ЗАВЕРШЁН")
    print(f"  Запрос:    {args.query}")
    print(f"  Дашборд:   .tmp/{slug}/dashboard.html")
    print(f"  Ссылки:    outputs/{slug}/urls.txt")
    print(f"  Full list: outputs/{slug}/full.txt")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
