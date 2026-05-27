from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.daily_replenishment_agent import DailyReplenishmentAgent


if __name__ == "__main__":
    result = DailyReplenishmentAgent().run(send_email=True)
    print(result)
