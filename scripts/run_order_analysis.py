from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.order_analysis_agent import OrderAnalysisAgent


if __name__ == "__main__":
    insights = OrderAnalysisAgent().run()
    print({"status": "完成", "order_insights_created": len(insights)})
