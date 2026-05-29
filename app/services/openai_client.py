from __future__ import annotations

import json
from typing import Any

from openai import OpenAI, OpenAIError

from app.config import get_settings
from app.models.inventory import InventoryItem
from app.services.retailer_search import RetailOption


class OpenAIRecommendationService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openai_model
        self.client = (
            OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
                max_retries=0,
            )
            if settings.openai_api_key
            else None
        )

    def choose_best_option(
        self,
        item: InventoryItem,
        events: list[dict[str, Any]],
        purchase_history: list[dict[str, Any]],
        options: list[RetailOption],
    ) -> dict[str, Any]:
        if not self.client:
            return self._fallback_choice(item, events, options)

        prompt = {
            "instruction": "你是家庭补货助手。请用中文推荐一个最实用的补货选项，不要自动下单。",
            "item": item.model_dump(),
            "low_stock_events": events,
            "purchase_history": purchase_history,
            "candidate_options": [option.__dict__ for option in options],
            "output_schema": {
                "recommended_retailer": "string",
                "recommended_brand": "string",
                "product_title": "string",
                "estimated_price": "string",
                "product_url": "string",
                "confidence": "integer 0-100",
                "urgency": "低/中/高/紧急",
                "reasoning": "中文，一句话",
            },
        }
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except (OpenAIError, json.JSONDecodeError):
            return self._fallback_choice(item, events, options)

    def _fallback_choice(
        self,
        item: InventoryItem,
        events: list[dict[str, Any]],
        options: list[RetailOption],
    ) -> dict[str, Any]:
        first = options[0]
        return {
            "recommended_retailer": first.retailer,
            "recommended_brand": first.brand,
            "product_title": first.product_title,
            "estimated_price": first.estimated_price,
            "product_url": first.product_url,
            "confidence": 70,
            "urgency": self._max_urgency(events) or item.urgency_default,
            "reasoning": "已根据偏好品牌、偏好店铺和常购规格生成基础推荐；AI 细化分析不可用时会自动使用此结果。",
        }

    @staticmethod
    def _max_urgency(events: list[dict[str, Any]]) -> str:
        order = {"低": 1, "中": 2, "高": 3, "紧急": 4}
        urgencies = [event.get("紧急度", "中") for event in events]
        return max(urgencies, key=lambda value: order.get(value, 0), default="中")
