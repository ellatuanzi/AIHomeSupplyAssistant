from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agents.daily_replenishment_agent import DailyReplenishmentAgent
from app.config import get_settings


def build_daily_scheduler(hour: int = 8, minute: int = 0) -> BackgroundScheduler:
    settings = get_settings()
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        lambda: DailyReplenishmentAgent().run(send_email=True),
        CronTrigger(hour=hour, minute=minute, timezone=settings.timezone),
        id="daily_replenishment_agent",
        replace_existing=True,
    )
    return scheduler

