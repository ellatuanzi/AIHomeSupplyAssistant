from pathlib import Path
from datetime import timedelta
import os
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.dates import now_local

# Nightly cron should be boring and bounded: Gmail + Sheets first, AI polish only
# when explicitly enabled. This prevents one slow provider call from hanging Render.
os.environ.setdefault("MAX_ORDER_EMAILS", "5")
today = now_local().date()
tomorrow = today + timedelta(days=1)
os.environ["ORDER_EMAIL_QUERY"] = os.environ.get(
    "ORDER_ANALYSIS_QUERY",
    (
        '(subject:"order received" OR subject:"order confirmation" OR '
        'subject:"your order" OR subject:ordered) '
        f'-subject:shipped -subject:delivered -category:promotions '
        f'after:{today:%Y/%m/%d} before:{tomorrow:%Y/%m/%d}'
    ),
)
os.environ.setdefault("ORDER_ANALYSIS_USE_OPENAI", "false")
if os.environ.get("ORDER_ANALYSIS_USE_OPENAI", "").lower() not in {"1", "true", "yes"}:
    os.environ["OPENAI_API_KEY"] = ""

from app.agents.order_analysis_agent import OrderAnalysisAgent


def _stop_cleanly_on_timeout(signum, frame) -> None:
    print({"status": "跳过", "reason": "订单分析超过时间上限，已停止以避免 Render 长时间挂起。"})
    raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _stop_cleanly_on_timeout)
    signal.alarm(int(os.environ.get("ORDER_ANALYSIS_TIMEOUT_SECONDS", "600")))
    print({"status": "开始", "query": os.environ["ORDER_EMAIL_QUERY"]})
    insights = OrderAnalysisAgent().run()
    signal.alarm(0)
    print({"status": "完成", "order_insights_created": len(insights)})
