from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI, OpenAIError
import requests

from app.config import get_settings
from app.models.inventory import InventoryItem
from app.services.retailer_search import RetailOption


class OpenAIRecommendationService:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openai_model
        self.gemini_api_key = settings.gemini_api_key
        self.gemini_model = settings.gemini_model
        self.gemini_timeout_seconds = settings.gemini_timeout_seconds
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
        if self.gemini_api_key:
            try:
                return self._choose_with_gemini(prompt)
            except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError):
                pass

        if not self.client:
            return self._fallback_choice(item, events, options)

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

    def generate_json(
        self,
        prompt: dict[str, Any],
        fallback: Any,
        temperature: float = 0.2,
    ) -> Any:
        if self.gemini_api_key:
            try:
                return self._generate_json_with_gemini(prompt, temperature=temperature)
            except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError):
                pass

        if not self.client:
            return fallback

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                temperature=temperature,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except (OpenAIError, json.JSONDecodeError):
            return fallback

    def _choose_with_gemini(self, prompt: dict[str, Any]) -> dict[str, Any]:
        parsed = self._generate_json_with_gemini(prompt, temperature=0.2)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini response was not a JSON object.")
        return parsed

    def _generate_json_with_gemini(self, prompt: dict[str, Any], temperature: float = 0.2) -> Any:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.gemini_model}:generateContent"
        )
        response = requests.post(
            url,
            params={"key": self.gemini_api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "只输出 JSON，不要 Markdown。\n"
                                    + json.dumps(prompt, ensure_ascii=False)
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json",
                },
            },
            timeout=self.gemini_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json(text)

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


def _parse_json(content: str) -> Any:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _parse_json_object(content: str) -> dict[str, Any]:
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("Gemini response was not a JSON object.")
    return parsed
