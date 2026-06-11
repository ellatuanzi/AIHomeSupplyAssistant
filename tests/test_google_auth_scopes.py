from app.services.google_auth import BASE_SCOPES


def test_default_google_scopes_do_not_include_gmail():
    assert BASE_SCOPES == ["https://www.googleapis.com/auth/spreadsheets"]
    assert all("gmail" not in scope for scope in BASE_SCOPES)
