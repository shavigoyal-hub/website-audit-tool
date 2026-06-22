#!/usr/bin/env python3
"""Upload an audit xlsx to Google Drive and convert to a Google Sheet.

First-time setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project > Enable Google Drive API
  3. Create credentials > OAuth 2.0 Client ID > Desktop app
  4. Download as 'credentials.json' into this folder
  5. Run: python3 upload_to_drive.py clients/invisionaz.json
     (Browser opens once for auth; token saved to token.json for future runs)

Usage:
  python3 upload_to_drive.py clients/<name>.json [--folder-id <drive-folder-id>]
"""
import argparse
import json
import os
import sys

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")
CREDS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")


def get_creds():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print("ERROR: credentials.json not found.")
                print("See the docstring at the top of this file for setup steps.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def upload(xlsx_path, client_name, folder_id=None):
    creds = get_creds()
    service = build("drive", "v3", credentials=creds)

    file_meta = {
        "name": f"{client_name} SEO Audit",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    if folder_id:
        file_meta["parents"] = [folder_id]

    media = MediaFileUpload(
        xlsx_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True,
    )

    print(f"Uploading {xlsx_path} → Google Drive as '{file_meta['name']}'...")
    result = service.files().create(
        body=file_meta, media_body=media, fields="id,webViewLink"
    ).execute()

    sheet_id = result["id"]
    link = result.get("webViewLink", f"https://docs.google.com/spreadsheets/d/{sheet_id}")
    print(f"✓ Uploaded: {link}")
    return sheet_id, link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="path to clients/<name>.json")
    ap.add_argument("--folder-id", help="Google Drive folder ID to upload into")
    args = ap.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    client = cfg["client"]
    folder_id = args.folder_id or cfg.get("drive_folder_id")
    xlsx = os.path.join(os.path.dirname(__file__), "output", f"{client}_audit.xlsx")

    if not os.path.exists(xlsx):
        print(f"ERROR: {xlsx} not found. Run audit.py first.")
        sys.exit(1)

    sheet_id, link = upload(xlsx, client, folder_id)

    # Save sheet ID back to config
    cfg["drive_sheet_id"] = sheet_id
    with open(args.config, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Saved sheet ID to {args.config}")


if __name__ == "__main__":
    sys.exit(main())
