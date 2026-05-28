from pathlib import Path
import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.credentials import Credentials as OAuthCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings


BASE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

SCOPES = BASE_SCOPES


def get_google_credentials(scopes: list[str] | None = None) -> Credentials:
    requested_scopes = scopes or BASE_SCOPES
    settings = get_settings()
    token_path = Path(settings.google_token_file)
    credentials_path = Path(settings.google_credentials_file)

    creds = None
    if settings.google_token_json:
        creds = OAuthCredentials.from_authorized_user_info(
            _json_from_env(settings.google_token_json), requested_scopes
        )
    elif token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), requested_scopes)

    if creds and not creds.has_scopes(requested_scopes):
        if settings.google_token_json:
            raise RuntimeError(
                "GOOGLE_TOKEN_JSON 缺少最新 Google 权限。请在本地重新授权，"
                "再用 scripts/print_render_env.py 更新 Render 环境变量。"
            )
        creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None

    if not creds or not creds.valid:
        if settings.google_oauth_client_json and _running_on_render():
            raise RuntimeError(
                "Render 环境缺少有效的 GOOGLE_TOKEN_JSON，无法在云端打开本地授权页面。"
                "请把本地生成的 Google token JSON 填到 Cron Job 的环境变量里。"
            )
        if settings.google_oauth_client_json:
            flow = InstalledAppFlow.from_client_config(
                _json_from_env(settings.google_oauth_client_json), requested_scopes
            )
            creds = flow.run_local_server(port=0, open_browser=False)
            return creds
        if not credentials_path.exists():
            raise RuntimeError(
                f"找不到 Google OAuth 凭证文件：{credentials_path}. "
                "请先下载 OAuth client JSON，或查看 README 的配置步骤。"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), requested_scopes)
        creds = flow.run_local_server(port=0, open_browser=False)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _running_on_render() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("RENDER_SERVICE_ID"))


def _json_from_env(value: str) -> dict:
    import base64
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return json.loads(base64.b64decode(value).decode("utf-8"))
