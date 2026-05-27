from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.order_analysis_agent import OrderAnalysisAgent, is_order_received_email
from app.services.gmail import GmailService


def main() -> None:
    gmail = GmailService()
    messages = gmail.search_messages('from:amazon.com newer_than:2d subject:ordered', 10)
    order_ids = []
    skipped = []
    for message in messages:
        email = gmail.get_message_text(message["id"])
        if is_order_received_email(email):
            order_ids.append(message["id"])
        else:
            skipped.append(email["subject"])

    insights = OrderAnalysisAgent(gmail=gmail).process_message_ids(order_ids)
    print(
        {
            "amazon_ordered_messages": len(order_ids),
            "skipped": skipped,
            "order_insights_created": len(insights),
        }
    )


if __name__ == "__main__":
    main()
