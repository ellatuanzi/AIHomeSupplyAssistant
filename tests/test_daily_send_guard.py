from app.agents.daily_send_guard import DailySendGuard


class FakeSheets:
    def __init__(self, already_done: bool) -> None:
        self.already_done = already_done

    def ensure_tabs_and_headers(self) -> None:
        pass

    def has_successful_daily_run(self, date_string: str) -> bool:
        return self.already_done


def test_daily_send_guard_skips_when_already_done(monkeypatch):
    monkeypatch.setattr("app.agents.daily_send_guard.today_local_string", lambda: "2026-05-25")
    monkeypatch.setattr(
        "app.agents.daily_send_guard.is_at_or_after_local_time", lambda hour, minute: True
    )

    result = DailySendGuard(sheets=FakeSheets(already_done=True)).run_if_due()

    assert result["status"] == "跳过"
    assert result["reason"] == "今天已经完成过每日检查"


def test_daily_send_guard_skips_before_due_time(monkeypatch):
    monkeypatch.setattr("app.agents.daily_send_guard.today_local_string", lambda: "2026-05-25")
    monkeypatch.setattr(
        "app.agents.daily_send_guard.is_at_or_after_local_time", lambda hour, minute: False
    )

    result = DailySendGuard(sheets=FakeSheets(already_done=False)).run_if_due()

    assert result["status"] == "跳过"
    assert result["reason"] == "未到 07:00"
