from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.agents.email_summary_agent import EmailSummaryAgent
from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.models.recommendations import Recommendation
from app.services.gmail import GmailService
from app.services.google_sheets import GoogleSheetsService
from app.services.openai_client import OpenAIRecommendationService
from app.services.retailer_search import RetailerSearchService
from app.utils.dates import now_local_string, today_local_string
from app.utils.ids import new_id


class DailyReplenishmentAgent:
    def __init__(
        self,
        sheets: GoogleSheetsService | None = None,
        retailer_search: RetailerSearchService | None = None,
        recommender: OpenAIRecommendationService | None = None,
        gmail: GmailService | None = None,
    ) -> None:
        self.sheets = sheets or GoogleSheetsService()
        self.retailer_search = retailer_search or RetailerSearchService()
        self.recommender = recommender or OpenAIRecommendationService()
        self.gmail = gmail

    def run(self, send_email: bool = True) -> dict[str, Any]:
        self.sheets.ensure_tabs_and_headers()
        inventory = {item.item_id: item for item in self.sheets.get_inventory_items()}
        unresolved_events = self.sheets.unresolved_events()
        history = self.sheets.purchase_history()

        events_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in unresolved_events:
            if event.get("商品ID") in inventory:
                events_by_item[event["商品ID"]].append(event)

        created_recommendations: list[Recommendation] = []
        for item_id, events in events_by_item.items():
            item = inventory[item_id]
            item_history = [row for row in history if row.get("商品ID") == item_id]
            options = self.retailer_search.search(item)
            choice = self.recommender.choose_best_option(item, events, item_history, options)

            recommendation = Recommendation(
                recommendation_id=new_id("rec"),
                date=today_local_string(),
                item_id=item.item_id,
                item_name=item.item_name,
                recommended_retailer=choice.get("recommended_retailer", ""),
                recommended_brand=choice.get("recommended_brand", ""),
                product_title=choice.get("product_title", ""),
                estimated_price=choice.get("estimated_price", "待查看"),
                product_url=choice.get("product_url", ""),
                confidence=int(choice.get("confidence", 70)),
                urgency=choice.get("urgency", item.urgency_default),
                reasoning=choice.get("reasoning", ""),
                reorder_status="待确认",
                last_updated=now_local_string(),
            )
            self.sheets.append_recommendation(
                [
                    recommendation.recommendation_id,
                    recommendation.date,
                    recommendation.item_id,
                    recommendation.item_name,
                    recommendation.recommended_retailer,
                    recommendation.recommended_brand,
                    recommendation.product_title,
                    recommendation.estimated_price,
                    recommendation.product_url,
                    recommendation.confidence,
                    recommendation.urgency,
                    recommendation.reasoning,
                    recommendation.reorder_status,
                    recommendation.last_updated,
                ]
            )
            created_recommendations.append(recommendation)

            for event in events:
                self.sheets.mark_event_resolved(event.get("事件ID", ""))

        email_sent = False
        order_insights = []
        if send_email:
            order_insights = OrderAnalysisAgent(
                sheets=self.sheets,
                gmail=self.gmail,
                recommender=self.recommender,
            ).run()

        if send_email:
            pending_recommendations = self.sheets.recommendations()
            email_agent = EmailSummaryAgent()
            if email_agent.should_send(
                created_recommendations, pending_recommendations, order_insights
            ):
                subject, body = email_agent.build(
                    created_recommendations, pending_recommendations, order_insights
                )
                gmail = self.gmail or GmailService()
                gmail.send_email(subject, body)
                email_sent = True

        return {
            "status": "完成",
            "items_reviewed": len(events_by_item),
            "recommendations_created": len(created_recommendations),
            "order_insights_created": len(order_insights),
            "email_sent": email_sent,
        }
