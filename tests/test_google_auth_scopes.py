from types import SimpleNamespace

from app.services import google_auth
from app.services.google_auth import BASE_SCOPES


def test_default_google_scopes_do_not_include_gmail():
    assert BASE_SCOPES == ["https://www.googleapis.com/auth/spreadsheets"]
    assert all("gmail" not in scope for scope in BASE_SCOPES)


def test_service_account_json_takes_priority(monkeypatch):
    fake_settings = SimpleNamespace(
        google_service_account_json='{"type":"service_account","client_email":"bot@example.com"}',
        google_token_json='{"token":"old-oauth-token"}',
        google_token_file="missing-token.json",
        google_credentials_file="missing-client.json",
        google_oauth_client_json="",
    )
    calls = {}

    def fake_from_service_account_info(info, scopes):
        calls["info"] = info
        calls["scopes"] = scopes
        return "service-account-creds"

    monkeypatch.setattr(google_auth, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(
        google_auth.service_account.Credentials,
        "from_service_account_info",
        fake_from_service_account_info,
    )

    creds = google_auth.get_google_credentials()

    assert creds == "service-account-creds"
    assert calls["info"]["client_email"] == "bot@example.com"
    assert calls["scopes"] == BASE_SCOPES
