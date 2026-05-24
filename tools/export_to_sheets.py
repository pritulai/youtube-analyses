#!/usr/bin/env python3
"""
Exports video data to a master Google Sheets file (append rows, no duplicates).
Input:  .tmp/{slug}/youtube_data.json
Output: appends rows to master Google Sheet (GOOGLE_SHEETS_ID in .env)
Usage:  python tools/export_to_sheets.py --query "LM Studio"
"""

import os
import sys
import json
import re
import argparse
import urllib.parse
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"

SHEET_HEADERS = [
    "run_date", "keyword", "video_id", "title", "channel",
    "subscribers", "views", "likes", "comments",
    "duration_sec", "duration_min", "engagement_rate",
    "published_at", "days_since_publish", "url", "search_query_variant",
]


def make_slug(query: str) -> str:
    slug = query.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug or "query"


def build_credentials_json():
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("[ERROR] GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be in .env")
        sys.exit(1)
    creds_data = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(creds_data, f)


def get_sheets_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(CREDENTIALS_FILE):
                build_credentials_json()
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            flow.redirect_uri = "http://localhost:8765"
            auth_url, _ = flow.authorization_url(prompt="consent")
            print(f"\n1. Открой эту ссылку в браузере:\n{auth_url}\n")
            print("2. Авторизуйся. Браузер покажет ошибку 'localhost недоступен' — это нормально.")
            print("3. Скопируй ПОЛНЫЙ URL из адресной строки браузера (начинается с http://localhost:8765/...)")
            redirect_url = input("\nВставь URL из адресной строки: ").strip()
            parsed = urllib.parse.urlparse(redirect_url)
            code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
            if not code:
                print("[ERROR] Код не найден в URL. Попробуй ещё раз.")
                sys.exit(1)
            flow.fetch_token(code=code)
            creds = flow.credentials

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def get_or_create_spreadsheet(service) -> str:
    """Return existing GOOGLE_SHEETS_ID or create a new master spreadsheet."""
    sheets_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    if sheets_id:
        return sheets_id

    print("GOOGLE_SHEETS_ID not set — creating new master spreadsheet...")
    spreadsheet = service.spreadsheets().create(body={
        "properties": {"title": "YouTube Research — Master Database"},
        "sheets": [{"properties": {"title": "Videos"}}],
    }).execute()

    sheets_id = spreadsheet["spreadsheetId"]
    url = f"https://docs.google.com/spreadsheets/d/{sheets_id}"
    print(f"Created: {url}")

    # Save to .env
    env_path = ".env"
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\nGOOGLE_SHEETS_ID={sheets_id}\n")
    print(f"Saved GOOGLE_SHEETS_ID to .env")
    return sheets_id


def ensure_headers(service, sheets_id: str):
    """Add header row if sheet is empty."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheets_id, range="Videos!A1:A1"
    ).execute()
    if not result.get("values"):
        service.spreadsheets().values().update(
            spreadsheetId=sheets_id,
            range="Videos!A1",
            valueInputOption="RAW",
            body={"values": [SHEET_HEADERS]},
        ).execute()
        print("Headers written to sheet.")


def get_existing_keys(service, sheets_id: str) -> set:
    """Return set of 'video_id|run_date' already in the sheet."""
    result = service.spreadsheets().values().get(
        spreadsheetId=sheets_id, range="Videos!A:C"
    ).execute()
    rows = result.get("values", [])
    keys = set()
    for row in rows[1:]:  # skip header
        if len(row) >= 3:
            run_date = row[0]
            vid_id = row[2]
            keys.add(f"{vid_id}|{run_date}")
    return keys


def main():
    parser = argparse.ArgumentParser(description="Export YouTube data to Google Sheets")
    parser.add_argument("--query", required=True, help='Topic keyword, e.g. "LM Studio"')
    args = parser.parse_args()

    slug = make_slug(args.query)
    in_path = os.path.join(".tmp", slug, "youtube_data.json")

    if not os.path.exists(in_path):
        print(f"[ERROR] {in_path} not found.")
        sys.exit(1)

    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    videos = data.get("videos", [])
    channels = data.get("channels", {})

    print("Connecting to Google Sheets...")
    try:
        service = get_sheets_service()
    except Exception as e:
        print(f"[ERROR] Google Sheets auth failed: {e}")
        sys.exit(1)

    sheets_id = get_or_create_spreadsheet(service)
    ensure_headers(service, sheets_id)
    existing_keys = get_existing_keys(service, sheets_id)

    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    new_rows = []
    skipped = 0

    for v in sorted(videos, key=lambda x: x["view_count"], reverse=True):
        key = f"{v['video_id']}|{run_date}"
        if key in existing_keys:
            skipped += 1
            continue

        # Days since publish
        try:
            pub = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            days_ago = (now - pub).days
        except Exception:
            days_ago = ""

        # Engagement rate
        views = v["view_count"]
        eng_rate = ""
        if views > 100:
            eng_rate = round((v["like_count"] + v["comment_count"]) / views * 100, 2)

        ch = channels.get(v["channel_id"], {})
        subs = ch.get("subscriber_count", "")

        url = f"https://youtube.com/watch?v={v['video_id']}"

        new_rows.append([
            run_date,
            args.query,
            v["video_id"],
            v["title"],
            v["channel_title"],
            subs,
            views,
            v["like_count"],
            v["comment_count"],
            v["duration_seconds"],
            round(v["duration_seconds"] / 60, 1),
            eng_rate,
            v["published_at"][:10],
            days_ago,
            url,
            v.get("search_query", ""),
        ])

    if new_rows:
        service.spreadsheets().values().append(
            spreadsheetId=sheets_id,
            range="Videos!A1",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": new_rows},
        ).execute()

    sheets_url = f"https://docs.google.com/spreadsheets/d/{sheets_id}"
    print(f"Добавлено {len(new_rows)} строк, пропущено {skipped} дублей")
    print(f"Google Sheets -> {sheets_url}")


if __name__ == "__main__":
    main()
