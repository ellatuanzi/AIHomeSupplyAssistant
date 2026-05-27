from __future__ import annotations

from typing import Any

from app.agents.daily_replenishment_agent import DailyReplenishmentAgent
from app.services.google_sheets import GoogleSheetsService
from app.utils.dates import is_at_or_after_local_time, now_local_string, today_local_string


class DailySendGuard:
    def __init__(
        self,
        hour: int = 7,
        minute: int = 0,
        sheets: GoogleSheetsService | None = None,
    ) -> None:
        self.hour = hour
        self.minute = minute
        self.sheets = sheets or GoogleSheetsService()

    def run_if_due(self) -> dict[str, Any]:
        self.sheets.ensure_tabs_and_headers()
        today = today_local_string()

        if not is_at_or_after_local_time(self.hour, self.minute):
            return {
                "status": "跳过",
                "reason": f"未到 {self.hour:02d}:{self.minute:02d}",
                "date": today,
                "email_sent": False,
            }

        if self.sheets.has_successful_daily_run(today):
            return {
                "status": "跳过",
                "reason": "今天已经完成过每日检查",
                "date": today,
                "email_sent": False,
            }

        try:
            result = DailyReplenishmentAgent(sheets=self.sheets).run(send_email=True)
            self.sheets.append_send_log(
                [
                    today,
                    now_local_string(),
                    "完成",
                    "是" if result.get("email_sent") else "否",
                    result.get("recommendations_created", 0),
                    result.get("order_insights_created", 0),
                    "已检查并按需发送；当天不再重复发送。",
                ]
            )
            return {"date": today, **result}
        except Exception as exc:
            self.sheets.append_send_log(
                [
                    today,
                    now_local_string(),
                    "失败",
                    "否",
                    0,
                    0,
                    str(exc)[:400],
                ]
            )
            raise
