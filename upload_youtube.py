"""Upload the finished video to YouTube (Data API v3, resumable upload).

One-time setup (local machine):
  1. console.cloud.google.com -> new project -> enable "YouTube Data API v3"
  2. OAuth consent screen -> set Publishing status to "In production"
     (in "Testing" mode refresh tokens expire after 7 days and unattended runs break)
  3. Credentials -> Create OAuth client ID -> "Desktop app" -> download as client_secret.json
  4. python upload_youtube.py --auth      (opens a browser once, writes token.json)
  5. For GitHub Actions: store the contents of token.json and client_secret.json as the
     secrets YT_TOKEN_JSON and YT_CLIENT_SECRET_JSON.

NOTE: videos uploaded through an *unaudited* API project created after 28 Jul 2020 are forced to
"private" by YouTube until the project passes the YouTube API compliance audit. Until then the
upload still works - you open YouTube Studio and review/publish it yourself (a good human check anyway).
"""
import argparse
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("youtube")
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
HERE = Path(__file__).parent


def get_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token, secret = HERE / "token.json", HERE / "client_secret.json"
    if os.getenv("YT_TOKEN_JSON"):
        token.write_text(os.environ["YT_TOKEN_JSON"])
    if os.getenv("YT_CLIENT_SECRET_JSON"):
        secret.write_text(os.environ["YT_CLIENT_SECRET_JSON"])

    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not secret.exists():
            raise SystemExit("client_secret.json missing - see the setup notes at the top of upload_youtube.py")
        creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
    token.write_text(creds.to_json())
    return creds


def upload(video: Path, title: str, description: str, tags: list[str],
           thumbnail: Path | None = None, privacy: str = "private", category: str = "27") -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=get_credentials())
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags,
                    "categoryId": category, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},   # AI voice disclosure
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info("uploaded %d%%", int(status.progress() * 100))
    vid = resp["id"]
    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail))).execute()
        except Exception as ex:   # needs a phone-verified channel
            log.warning("thumbnail not set: %s", ex)
    url = f"https://youtu.be/{vid}"
    log.info("uploaded: %s (privacy=%s)", url, resp.get("status", {}).get("privacyStatus"))
    return url


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true", help="run the one-time browser login")
    ap.add_argument("--meta", help="path to build/<date>/meta.json to upload")
    a = ap.parse_args()
    if a.auth:
        get_credentials()
        print("token.json written.")
    elif a.meta:
        m = json.loads(Path(a.meta).read_text(encoding="utf-8"))
        d = Path(a.meta).parent
        print(upload(d / "video.mp4", m["title"], m["description"], m["tags"], d / "thumbnail.png"))
