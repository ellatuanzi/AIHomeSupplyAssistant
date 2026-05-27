from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.daily_send_guard import DailySendGuard


if __name__ == "__main__":
    result = DailySendGuard(hour=7, minute=0).run_if_due()
    print(result)
