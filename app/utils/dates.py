from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def now_local_string() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def today_local_string() -> str:
    return now_local().strftime("%Y-%m-%d")


def is_at_or_after_local_time(hour: int, minute: int = 0) -> bool:
    now = now_local()
    return (now.hour, now.minute) >= (hour, minute)
