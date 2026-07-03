#!/usr/bin/env python3
"""
Telegram bot service — runs locally in polling mode.
Provides a single "Settings" button that opens the MiniApp.
Receives web_app_data from MiniApp → runs run_analysis.py as subprocess.

Usage:
  python tools/bot_service.py          # foreground
  pythonw tools/bot_service.py         # background (Windows, no console)

Env: TELEGRAM_BOT_TOKEN, MINIAPP_URL (GitHub Pages URL of miniapp/index.html)
"""

import os
import sys
import json
import subprocess
import threading
import time
import re
import atexit

import requests
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_ROOT, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MINIAPP_URL = os.getenv("MINIAPP_URL", "https://pritulai.github.io/youtube-analyses/")
PYTHON = sys.executable
RUNNER = os.path.join(_ROOT, "tools", "run_analysis.py")

TG = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Track running pipelines per chat: chat_id -> subprocess
_running: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def _cleanup():
    for proc in list(_running.values()):
        if isinstance(proc, subprocess.Popen):
            try:
                proc.terminate()
            except Exception:
                pass


atexit.register(_cleanup)


def send(chat_id, text: str, **extra):
    try:
        requests.post(f"{TG}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            **extra,
        }, timeout=15)
    except Exception as e:
        print(f"[WARN] send failed: {e}")


REPLY_KEYBOARD = json.dumps({
    "keyboard": [[{"text": "⚙️ Настройки и запуск", "web_app": {"url": MINIAPP_URL}}]],
    "resize_keyboard": True,
    "persistent": True,
})


def send_start_keyboard(chat_id):
    """Send welcome message with persistent MiniApp reply button."""
    send(chat_id,
         "👋 <b>Research Bot</b>\n\n"
         "Нажми кнопку ниже чтобы настроить поиск и запустить анализ.",
         reply_markup=REPLY_KEYBOARD)


def build_cmd(settings: dict) -> list:
    """Convert MiniApp JSON settings to run_analysis.py CLI args."""
    cmd = [PYTHON, RUNNER,
           "--query", settings.get("query", ""),
           "--source", settings.get("source", "youtube"),
           "--days", str(settings.get("days", 7)),
           "--max-videos", str(settings.get("max_videos", 100))]

    if settings.get("skip_email"):
        cmd.append("--skip-email")
    if settings.get("skip_telegram"):
        cmd.append("--skip-telegram")
    if settings.get("skip_sheets"):
        cmd.append("--skip-sheets")
    if settings.get("skip_notebook"):
        cmd.append("--skip-notebook")
    if settings.get("skip_slides"):
        cmd.append("--skip-slides")

    return cmd


def run_pipeline(chat_id: str, settings: dict):
    """Run pipeline in a thread; send status updates to user."""
    query = settings.get("query", "?")
    source = settings.get("source", "youtube")
    send(chat_id, f"🚀 <b>Запускаю анализ:</b> «{query}» ({source})\n⏳ Это займёт несколько минут...")

    cmd = build_cmd(settings)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        _running[str(chat_id)] = proc

        # Stream stdout — send step completions to Telegram
        for line in proc.stdout:
            line = line.strip()
            if line:
                print(line)
            # Notify user at key steps
            if "[OK]" in line or "ПАЙПЛАЙН ЗАВЕРШЁН" in line or "[FAILED]" in line:
                send(chat_id, f"<code>{line[:200]}</code>")

        proc.wait()
        _running.pop(str(chat_id), None)

        if proc.returncode == 0:
            slug = re.sub(r"[^a-z0-9\s-]", "", query.lower())
            slug = re.sub(r"\s+", "-", slug.strip()) or "query"
            send(chat_id,
                 f"✅ <b>Анализ завершён!</b>\n"
                 f"Запрос: «{query}»\n"
                 f"Результаты отправлены выше ↑")
        else:
            send(chat_id, f"❌ <b>Ошибка анализа</b> (код {proc.returncode})\nПроверь логи.")
    except Exception as e:
        send(chat_id, f"❌ <b>Ошибка запуска:</b> {e}")
        _running.pop(str(chat_id), None)


def run_notebook_only(chat_id: str, query: str):
    """Run only the NotebookLM step on an existing analysis."""
    send(chat_id, f"📓 <b>Создаю ноутбук NotebookLM</b> для «{query}»...")
    cmd = [PYTHON, RUNNER, "--query", query,
           "--skip-fetch", "--skip-email", "--skip-telegram", "--skip-sheets",
           # run_analysis with these flags goes straight to NLM step
           ]
    # Override: run create_notebooklm.py directly
    nlm_script = os.path.join(_ROOT, "tools", "create_notebooklm.py")
    cmd = [PYTHON, nlm_script, "--query", query]
    try:
        proc = subprocess.Popen(
            cmd, cwd=_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        _running[str(chat_id)] = proc
        for line in proc.stdout:
            line = line.strip()
            if line:
                print(line)
            if "[OK]" in line or "[ERROR]" in line or "ноутбук" in line.lower():
                send(chat_id, f"<code>{line[:200]}</code>")
        proc.wait()
        _running.pop(str(chat_id), None)
        if proc.returncode == 0:
            send(chat_id, "✅ <b>NotebookLM готов!</b> Ссылка отправлена выше ↑")
        else:
            send(chat_id, f"❌ <b>Ошибка NotebookLM</b> (код {proc.returncode})")
    except Exception as e:
        send(chat_id, f"❌ <b>Ошибка:</b> {e}")
        _running.pop(str(chat_id), None)


def handle_update(update: dict):
    """Dispatch incoming Telegram update."""
    # /start command
    msg = update.get("message", {})
    if msg:
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is None:
            return
        text = msg.get("text", "")

        # MiniApp sends data via web_app_data (special message type)
        web_app_data = msg.get("web_app_data", {})
        if web_app_data:
            raw = web_app_data.get("data", "{}")
            try:
                settings = json.loads(raw)
            except json.JSONDecodeError:
                send(chat_id, "❌ Некорректные данные от MiniApp.")
                return

            query = settings.get("query", "").strip()
            if not query:
                send(chat_id, "❌ Запрос не может быть пустым.")
                return

            # Check if already running (atomic check+insert under lock)
            with _lock:
                if str(chat_id) in _running:
                    send(chat_id, "⚠️ Анализ уже запущен. Дождитесь завершения.")
                    return
                _running[str(chat_id)] = "starting"

            action = settings.get("action", "run")
            if action == "notebook_only":
                t = threading.Thread(target=run_notebook_only, args=(chat_id, query), daemon=True)
            else:
                t = threading.Thread(target=run_pipeline, args=(chat_id, settings), daemon=True)
            t.start()
            return

        if text in ("/start", "/help"):
            send_start_keyboard(chat_id)
            return

        if text == "/status":
            if str(chat_id) in _running:
                send(chat_id, "⏳ Анализ выполняется...", reply_markup=REPLY_KEYBOARD)
            else:
                send(chat_id, "✅ Нет активных задач.", reply_markup=REPLY_KEYBOARD)
            return

    # Inline button callback
    callback = update.get("callback_query", {})
    if callback:
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        # Answer callback to remove loading spinner
        try:
            requests.post(f"{TG}/answerCallbackQuery",
                          json={"callback_query_id": callback["id"]}, timeout=10)
        except Exception:
            pass


def poll():
    """Long-polling loop."""
    offset = 0
    print(f"[BOT] Запущен. MiniApp URL: {MINIAPP_URL}")
    print("[BOT] Нажми Ctrl+C для остановки.")

    while True:
        try:
            resp = requests.get(f"{TG}/getUpdates",
                                params={"offset": offset, "timeout": 30},
                                timeout=40)
            data = resp.json()
            if not data.get("ok"):
                print(f"[WARN] getUpdates error: {data.get('description')}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    handle_update(update)
                except Exception as e:
                    print(f"[ERROR] handle_update: {e}")

        except requests.exceptions.Timeout:
            pass  # Normal — long poll timed out
        except Exception as e:
            print(f"[ERROR] poll: {e}")
            time.sleep(5)


def main():
    if not BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN не задан в .env")
        sys.exit(1)

    # Verify token
    try:
        info = requests.get(f"{TG}/getMe", timeout=10).json()
        if not info.get("ok"):
            print(f"[ERROR] Неверный BOT_TOKEN: {info.get('description')}")
            sys.exit(1)
        username = info["result"]["username"]
        print(f"[BOT] Авторизован как @{username}")
    except Exception as e:
        print(f"[ERROR] Не удалось подключиться к Telegram: {e}")
        sys.exit(1)

    poll()


if __name__ == "__main__":
    main()
