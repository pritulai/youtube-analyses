#!/usr/bin/env python3
"""
Creates (or updates) a NotebookLM notebook from YouTube URLs.
Uses the 'nlm' CLI tool via subprocess with retry logic.
Input:  outputs/{slug}/urls.txt
Output: outputs/{slug}/notebook_id.txt
Usage:  python tools/create_notebooklm.py --query "LM Studio"
"""

import os
import sys
import re
import argparse
import subprocess
import time
from datetime import datetime


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def clean_env() -> dict:
    """Return env dict with ALL proxy vars removed so nlm (httpx) doesn't choke on socks4."""
    env = os.environ.copy()
    for key in list(env.keys()):
        if "PROXY" in key.upper():
            del env[key]
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def run_nlm(args: list) -> tuple:
    """Run nlm CLI, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["nlm"] + args,
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env=clean_env(),
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def run_nlm_retry(args: list, attempts: int = 3, delay: int = 5) -> tuple:
    """Run nlm with retries on failure."""
    for attempt in range(1, attempts + 1):
        code, out, err = run_nlm(args)
        if code == 0:
            return code, out, err
        msg = (err or out)[:120].encode("ascii", errors="replace").decode("ascii")
        if attempt < attempts:
            print(f"  [RETRY {attempt}/{attempts}] {msg} — повтор через {delay}с...")
            time.sleep(delay)
        else:
            print(f"  [FAIL] Все {attempts} попытки исчерпаны: {msg}")
    return code, out, err


def create_notebook(title: str) -> str | None:
    """Create a new notebook, return its ID."""
    code, out, err = run_nlm_retry(["notebook", "create", title])
    if code != 0:
        return None
    id_match = re.search(r"ID:\s*([a-f0-9\-]{36})", out + "\n" + err)
    if id_match:
        return id_match.group(1)
    uuid_match = re.search(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}", out)
    if uuid_match:
        return uuid_match.group(0)
    print(f"[ERROR] Не удалось распарсить notebook ID из:\n{out}")
    return None


def get_existing_sources(notebook_id: str) -> set:
    code, out, _ = run_nlm(["source", "list", notebook_id])
    if code != 0:
        return set()
    urls = set()
    for line in out.splitlines():
        match = re.search(r"https?://\S+", line)
        if match:
            urls.add(match.group(0).rstrip(".,)"))
    return urls


def get_notebook_id(path: str) -> str | None:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            nb_id = f.read().strip()
            if nb_id:
                return nb_id
    return None


def save_pending(out_dir: str, urls: list):
    """Save unprocessed URLs to pending file for manual retry."""
    pending_path = os.path.join(out_dir, "notebook_pending.txt")
    with open(pending_path, "w", encoding="utf-8") as f:
        f.write("\n".join(urls) + "\n")
    print(f"[INFO] {len(urls)} URL сохранены в {pending_path} для повторной попытки.")


def main():
    parser = argparse.ArgumentParser(description="Create/update NotebookLM notebook from YouTube URLs")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    parser.add_argument("--max-sources", type=int, default=50,
                        help="Max URLs to add (NotebookLM limit ~50)")
    args = parser.parse_args()

    slug = make_slug(args.query)
    out_dir = os.path.join("outputs", slug)
    urls_path = os.path.join(out_dir, "urls.txt")
    notebook_id_path = os.path.join(out_dir, "notebook_id.txt")

    if not os.path.exists(urls_path):
        print(f"[ERROR] {urls_path} не найден. Запусти save_links.py сначала.")
        sys.exit(1)

    with open(urls_path, encoding="utf-8") as f:
        all_urls = [line.strip() for line in f if line.strip()]

    if not all_urls:
        print("[WARN] urls.txt пуст — нечего добавлять.")
        sys.exit(0)

    # ── Шаг 1: Получить или создать ноутбук ───────────────────
    notebook_id = get_notebook_id(notebook_id_path)
    if notebook_id:
        print(f"Используем существующий ноутбук: {notebook_id}")
        existing_urls = get_existing_sources(notebook_id)
        print(f"Источников уже добавлено: {len(existing_urls)}")
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        title = f"{args.query} — {today}"
        print(f'Создаю новый ноутбук: "{title}"')
        notebook_id = create_notebook(title)
        if not notebook_id:
            print("[ERROR] Не удалось создать ноутбук после всех попыток.")
            save_pending(out_dir, all_urls[:args.max_sources])
            sys.exit(1)
        os.makedirs(out_dir, exist_ok=True)
        with open(notebook_id_path, "w", encoding="utf-8") as f:
            f.write(notebook_id)
        print(f"Notebook ID: {notebook_id}")
        existing_urls = set()

    # ── Шаг 2: Добавить новые URL ─────────────────────────────
    new_urls = [u for u in all_urls if u not in existing_urls][:args.max_sources]

    if not new_urls:
        print("Все URL уже добавлены — дублей нет.")
    else:
        print(f"Добавляю {len(new_urls)} источников батчем...")
        batch_size = 10
        added = 0
        failed_urls = []

        for i in range(0, len(new_urls), batch_size):
            batch = new_urls[i: i + batch_size]
            cmd = ["source", "add", notebook_id]
            for url in batch:
                cmd += ["--youtube", url]

            print(f"  Батч {i // batch_size + 1}: {len(batch)} URLs...")
            code, out, err = run_nlm_retry(cmd, attempts=3, delay=5)

            if code == 0:
                added += len(batch)
                if out:
                    safe = out[:120].encode("ascii", errors="replace").decode("ascii")
                    print(f"  {safe}")
            else:
                failed_urls.extend(batch)

        print(f"\nГотово: добавлено {added}, ошибок {len(failed_urls)}")
        if failed_urls:
            save_pending(out_dir, failed_urls)

    # ── Итог ──────────────────────────────────────────────────
    nb_url = f"https://notebooklm.google.com/notebook/{notebook_id}"
    print(f"NotebookLM -> {nb_url}")

    with open(os.path.join(out_dir, "notebook_url.txt"), "w", encoding="utf-8") as f:
        f.write(nb_url + "\n")


if __name__ == "__main__":
    main()
