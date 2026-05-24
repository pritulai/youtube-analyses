#!/usr/bin/env python3
"""
Sends the HTML dashboard via Gmail using OAuth2.
First run: opens browser for Google auth and saves token.json.
Usage: python tools/send_gmail.py [--to email] [--subject "..."]
"""

import os
import sys
import base64
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
DEFAULT_TO = "musicboxer@gmail.com"


def build_credentials_json():
    """Create credentials.json from .env if it doesn't exist."""
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
    import json
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump(creds_data, f)
    print(f"Created {CREDENTIALS_FILE} from .env credentials.")


def get_gmail_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
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
        print(f"Auth token saved → {TOKEN_FILE}")

    return build("gmail", "v1", credentials=creds)


def create_message(to, subject, html_body, attachment_path=None):
    msg = MIMEMultipart("mixed")
    msg["To"] = to
    msg["From"] = "me"
    msg["Subject"] = subject

    # HTML body
    html_part = MIMEMultipart("alternative")
    html_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(html_part)

    # Attach the full HTML file as well
    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        filename = os.path.basename(attachment_path)
        part.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Send dashboard via Gmail")
    parser.add_argument("--to", default=DEFAULT_TO, help="Recipient email")
    parser.add_argument("--subject", default=None, help="Email subject")
    parser.add_argument("--dashboard", default=None, help="Path to dashboard HTML file")
    args = parser.parse_args()

    dashboard_path = args.dashboard or os.path.join(".tmp", "dashboard.html")
    if not os.path.exists(dashboard_path):
        print(f"[ERROR] {dashboard_path} not found. Run generate_dashboard.py first.")
        sys.exit(1)

    with open(dashboard_path, encoding="utf-8") as f:
        html_body = f.read()

    today = datetime.now().strftime("%B %d, %Y")
    subject = args.subject or f"🤖 AI Content Intelligence Dashboard — {today}"

    print(f"Authenticating with Gmail...")
    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"[ERROR] Gmail auth failed: {e}")
        print("Tip: Delete token.json and try again, or check your credentials in .env")
        sys.exit(1)

    print(f"Sending to {args.to}...")
    message = create_message(args.to, subject, html_body, dashboard_path)

    try:
        service.users().messages().send(userId="me", body=message).execute()
        print(f"Email sent to {args.to}")
    except HttpError as e:
        print(f"[ERROR] Failed to send email: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
