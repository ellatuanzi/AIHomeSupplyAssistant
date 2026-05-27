from fastapi import FastAPI
from fastapi.responses import JSONResponse
from google.auth.exceptions import GoogleAuthError, RefreshError
from googleapiclient.errors import HttpError

from app.api.routes import router
from app.config import get_settings


def google_api_exception_handler(request, exc: HttpError) -> JSONResponse:
    status_code = getattr(getattr(exc, "resp", None), "status", 502)
    return JSONResponse(
        status_code=503,
        content={
            "status": "Google API 配置错误",
            "google_status": status_code,
            "detail": _safe_google_error_message(exc),
            "next_step": "请检查 Render 环境变量、Google Sheet 分享权限，以及 Google Sheets/Gmail API 是否启用。",
        },
    )


def google_auth_exception_handler(request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "status": "Google OAuth 授权错误",
            "detail": str(exc),
            "next_step": "请重新生成 GOOGLE_TOKEN_JSON，并在 Render 保存后重新部署。",
        },
    )


def _safe_google_error_message(exc: HttpError) -> str:
    try:
        return exc.error_details[0].get("message", str(exc))
    except Exception:
        return str(exc)


def generic_exception_handler(request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "status": "内部错误",
            "error_type": exc.__class__.__name__,
            "detail": _safe_error_text(str(exc)),
            "next_step": "请把这一段 JSON 发给我，我会根据 error_type 和 detail 定位配置问题。",
        },
    )


def _safe_error_text(value: str) -> str:
    text = value.replace("\n", " ").strip()
    for word in ["refresh_token", "client_secret", "access_token"]:
        text = text.replace(word, f"{word[:3]}***")
    return text[:800] or "没有错误详情"


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(router)
    app.add_exception_handler(HttpError, google_api_exception_handler)
    app.add_exception_handler(RefreshError, google_auth_exception_handler)
    app.add_exception_handler(GoogleAuthError, google_auth_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
    return app


app = create_app()
