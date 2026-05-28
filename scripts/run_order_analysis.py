from pathlib import Path
import os
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Nightly cron should be boring and bounded: Gmail + Sheets first, AI polish only
# when explicitly enabled. This prevents one slow provider call from hanging Render.
os.environ.setdefault("MAX_ORDER_EMAILS", "5")
os.environ.setdefault("ORDER_ANALYSIS_USE_OPENAI", "false")
if os.environ.get("ORDER_ANALYSIS_USE_OPENAI", "").lower() not in {"1", "true", "yes"}:
    os.environ["OPENAI_API_KEY"] = ""

from app.agents.order_analysis_agent import OrderAnalysisAgent


if __name__ == "__main__":
    signal.alarm(int(os.environ.get("ORDER_ANALYSIS_TIMEOUT_SECONDS", "600")))
    insights = OrderAnalysisAgent().run()
    print({"status": "完成", "order_insights_created": len(insights)})
