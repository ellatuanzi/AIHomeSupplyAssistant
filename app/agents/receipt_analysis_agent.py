from __future__ import annotations

import base64
import json
import re
from typing import Any

import requests

from app.models.inventory import InventoryItem
from app.agents.order_analysis_agent import _order_insight_row, _purchase_history_row
from app.config import get_settings
from app.services.google_sheets import GoogleSheetsService
from app.services.hsa_tracker import HsaTrackerService
from app.services.openai_client import OpenAIRecommendationService
from app.utils.dates import today_local_string
from app.utils.ids import new_id


class ReceiptAnalysisAgent:
    def __init__(
        self,
        sheets: GoogleSheetsService | None = None,
        recommender: OpenAIRecommendationService | None = None,
        hsa_tracker: HsaTrackerService | None = None,
    ) -> None:
        self.sheets = sheets or GoogleSheetsService()
        self.recommender = recommender or OpenAIRecommendationService()
        self.hsa_tracker = hsa_tracker
        self.default_shipping_address = self.recommender.client and ""
        self.last_extraction_status: dict[str, Any] = {}

    def process_upload(
        self, filename: str, content_type: str, data: bytes
    ) -> list[dict[str, Any]]:
        return self.process_uploads([(filename, content_type, data)])

    def process_uploads(
        self, uploads: list[tuple[str, str, bytes]]
    ) -> list[dict[str, Any]]:
        self.sheets.ensure_tabs_and_headers()
        inventory = self.sheets.get_inventory_items()
        receipt_id = new_id("receipt")
        extracted_items: list[dict[str, Any]] = []
        file_statuses = []

        for filename, content_type, data in uploads:
            file_items = self._valid_receipt_items(
                self._extract_receipt_items(filename, content_type, data, inventory)
            )
            status = dict(self.last_extraction_status)
            status["filename"] = filename
            status["valid_items"] = len(file_items)
            file_statuses.append(status)
            receipt_link = self._upload_hsa_receipt_if_needed(filename, content_type, data, file_items)
            for order in file_items:
                order["_source_filename"] = filename
                order["_receipt_link"] = receipt_link
            extracted_items.extend(file_items)

        deduped_items = _dedupe_receipt_items(extracted_items)
        duplicates_removed = len(extracted_items) - len(deduped_items)
        insights = []

        for index, order in enumerate(deduped_items, start=1):
            filename = order.get("_source_filename", "receipt")
            item = self._match_inventory_item(order, inventory)
            order["address_category"] = _address_category(
                order.get("shipping_address", ""), self._default_shipping_address()
            )
            insight = self._analyze_receipt_item(order, item)
            self._write_purchase_history(receipt_id, filename, order, item, insight)
            self._write_order_insight(receipt_id, order, item, insight)
            self._write_hsa_candidate(
                source_id=f"{receipt_id}#{index}",
                order=order,
                receipt_link=order.get("_receipt_link", ""),
                filename=filename,
            )
            insights.append(insight)

        self.last_extraction_status = {
            "method": "batch",
            "files": len(uploads),
            "raw_items": len(extracted_items),
            "valid_items": len(deduped_items),
            "duplicates_removed": duplicates_removed,
            "file_statuses": file_statuses,
            "message": (
                f"已处理 {len(uploads)} 个文件，识别 {len(deduped_items)} 条记录，去掉 {duplicates_removed} 条重复。"
            ),
        }
        return insights

    def process_upload_with_status(
        self, filename: str, content_type: str, data: bytes
    ) -> dict[str, Any]:
        return self.process_uploads_with_status([(filename, content_type, data)])

    def process_uploads_with_status(
        self, uploads: list[tuple[str, str, bytes]]
    ) -> dict[str, Any]:
        insights = self.process_uploads(uploads)
        return {
            "insights": insights,
            "extraction_status": self.last_extraction_status,
        }

    def _extract_receipt_items(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        inventory: list[InventoryItem],
    ) -> list[dict[str, Any]]:
        text = _decode_text(data)
        if content_type.startswith("image/") and self.recommender.gemini_api_key:
            try:
                items = self._extract_with_gemini(filename, content_type, data, inventory)
                valid_items = self._valid_receipt_items(items)
                self.last_extraction_status = {
                    "method": "gemini",
                    "gemini_configured": True,
                    "model": self.recommender.gemini_model,
                    "raw_items": len(items),
                    "valid_items": len(valid_items),
                    "message": "Gemini 已返回识别结果。" if valid_items else "Gemini 返回了空结果或缺少商品名称。",
                }
                return valid_items
            except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.last_extraction_status = {
                    "method": "heuristic",
                    "gemini_configured": True,
                    "model": self.recommender.gemini_model,
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    "message": "Gemini 图片识别失败，已改用本地基础解析。",
                }

        if not content_type.startswith("image/") and self.recommender.gemini_api_key:
            fallback = [self._heuristic_receipt_item(filename, text, inventory)]
            prompt = self._receipt_extraction_prompt(filename, content_type, inventory)
            prompt["text"] = text[:12000]
            result = self.recommender.generate_json(prompt, fallback=fallback, temperature=0.1)
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                return [result]
            return fallback

        self.last_extraction_status = {
            "method": "heuristic",
            "gemini_configured": bool(self.recommender.gemini_api_key),
            "model": getattr(self.recommender, "gemini_model", ""),
            "message": "未使用 Gemini 图片识别；已改用本地基础解析。",
        }
        return [self._heuristic_receipt_item(filename, text, inventory)]

    @staticmethod
    def _valid_receipt_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        valid_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_name = str(item.get("item_name", "")).strip()
            product_title = str(item.get("product_title", "")).strip()
            if item_name or product_title:
                valid_items.append(item)
        return valid_items

    def _receipt_extraction_prompt(
        self,
        filename: str,
        content_type: str,
        inventory: list[InventoryItem],
    ) -> dict[str, Any]:
        return {
            "instruction": "从购物小票中提取家庭日用品购买记录。商品名/品牌/店铺可保留英文，分析字段用中文。若有多件日用品，输出多条。",
            "filename": filename,
            "content_type": content_type,
            "inventory_items": [item.model_dump() for item in inventory],
            "schema": [
                {
                    "retailer": "string",
                    "item_name": "string",
                    "item_id": "string if matched else empty",
                    "brand": "string",
                    "product_title": "string",
                    "quantity": "string",
                    "price": "string",
                    "shipping_address": "string, usually empty for in-store receipt",
                    "order_link": "",
                }
            ],
        }

    def _extract_with_openai(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        inventory: list[InventoryItem],
    ) -> list[dict[str, Any]]:
        prompt = self._receipt_extraction_prompt(filename, content_type, inventory)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": json.dumps(prompt, ensure_ascii=False)}
        ]
        if content_type.startswith("image/"):
            encoded = base64.b64encode(data).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                }
            )
        else:
            content.append({"type": "text", "text": _decode_text(data)[:12000]})

        response = self.recommender.client.chat.completions.create(
            model=self.recommender.model,
            messages=[
                {"role": "system", "content": "只输出 JSON array，不要 Markdown。"},
                {"role": "user", "content": content},
            ],
            temperature=0.1,
        )
        parsed = json.loads(response.choices[0].message.content or "[]")
        return parsed if isinstance(parsed, list) else [parsed]

    def _extract_with_gemini(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        inventory: list[InventoryItem],
    ) -> list[dict[str, Any]]:
        prompt = {
            "instruction": (
                "从手机拍摄的购物小票、订单截图、delivery/order 页面截图中提取家庭日用品购买记录。"
                "商品名/品牌/店铺可保留英文，分析字段用中文。若有多件日用品，输出多条。"
                "忽略广告、推荐商品、shipping/delivered 状态文字本身，只提取真正购买的商品。"
            ),
            "filename": filename,
            "content_type": content_type,
            "inventory_items": [item.model_dump() for item in inventory],
            "schema": [
                {
                    "retailer": "string",
                    "item_name": "string",
                    "item_id": "string if matched else empty",
                    "brand": "string",
                    "product_title": "string",
                    "quantity": "string",
                    "price": "string",
                    "shipping_address": "string if visible",
                    "order_link": "",
                }
            ],
        }
        encoded = base64.b64encode(data).decode("utf-8")
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.recommender.gemini_model}:generateContent"
        )
        response = requests.post(
            url,
            params={"key": self.recommender.gemini_api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "只输出 JSON array，不要 Markdown。\n"
                                    + json.dumps(prompt, ensure_ascii=False)
                                )
                            },
                            {
                                "inlineData": {
                                    "mimeType": content_type,
                                    "data": encoded,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            },
            timeout=get_settings().gemini_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        parsed = _parse_json(text)
        return parsed if isinstance(parsed, list) else [parsed]

    def _analyze_receipt_item(
        self, order: dict[str, Any], item: InventoryItem | None
    ) -> dict[str, Any]:
        item_name = item.item_name if item else order.get("item_name", "未匹配商品")
        return {
            "item_id": item.item_id if item else order.get("item_id", ""),
            "item_name": item_name,
            "retailer": order.get("retailer", ""),
            "product_title": order.get("product_title", item_name),
            "price": order.get("price", "待确认"),
            "shipping_address": order.get("shipping_address", ""),
            "address_category": order.get("address_category", "未识别"),
            "price_judgment": "来自上传小票；已记录价格，可用于后续和历史价格比较。",
            "restock_prediction": f"已记录 {item_name} 的购买信息，后续可结合低库存记录推测补货周期。",
            "health_or_fit_note": "上传小票通常缺少成分信息；如需健康分析，建议后续补充商品详情链接或包装照片。",
            "better_suggestion": "后续可按单位价格、品牌偏好和历史满意度比较更好选择。",
            "confidence": 70 if item else 45,
            "summary": f"已从上传小票记录 {item_name}。",
        }

    def _write_purchase_history(
        self,
        receipt_id: str,
        filename: str,
        order: dict[str, Any],
        item: InventoryItem | None,
        insight: dict[str, Any],
    ) -> None:
        self.sheets.append_purchase_history_dict(
            _purchase_history_row(
                purchase_id=new_id("pur"),
                source_id=receipt_id,
                item_id=item.item_id if item else order.get("item_id", ""),
                item_name=item.item_name if item else order.get("item_name", ""),
                purchase_date=today_local_string(),
                retailer=order.get("retailer", ""),
                brand=order.get("brand", ""),
                product_title=order.get("product_title", ""),
                quantity=order.get("quantity", ""),
                price=order.get("price", ""),
                shipping_address=order.get("shipping_address", ""),
                address_category=order.get("address_category", "未识别"),
                order_link=order.get("order_link", ""),
                satisfaction="",
                note=f"来自上传小票: {filename}; {insight.get('summary', '')}",
            )
        )

    def _write_order_insight(
        self,
        receipt_id: str,
        order: dict[str, Any],
        item: InventoryItem | None,
        insight: dict[str, Any],
    ) -> None:
        self.sheets.append_order_insight_dict(
            _order_insight_row(
                analysis_id=new_id("ord"),
                source_id=receipt_id,
                analysis_date=today_local_string(),
                item_id=item.item_id if item else insight.get("item_id", ""),
                item_name=item.item_name
                if item
                else insight.get("item_name", order.get("item_name", "")),
                retailer=insight.get("retailer", order.get("retailer", "")),
                product_title=insight.get("product_title", order.get("product_title", "")),
                price=insight.get("price", order.get("price", "")),
                shipping_address=insight.get("shipping_address", order.get("shipping_address", "")),
                address_category=insight.get("address_category", order.get("address_category", "未识别")),
                price_judgment=insight.get("price_judgment", ""),
                restock_prediction=insight.get("restock_prediction", ""),
                health_note=insight.get("health_or_fit_note", ""),
                better_suggestion=insight.get("better_suggestion", ""),
                confidence=insight.get("confidence", 60),
                note=insight.get("summary", ""),
            )
        )

    def _match_inventory_item(
        self, order: dict[str, Any], inventory: list[InventoryItem]
    ) -> InventoryItem | None:
        if order.get("item_id"):
            return next((item for item in inventory if item.item_id == order["item_id"]), None)
        title = " ".join(
            [order.get("item_name", ""), order.get("product_title", ""), order.get("brand", "")]
        ).lower()
        return next(
            (
                item
                for item in inventory
                if item.item_name.lower() in title
                or item.item_id.replace("_", " ") in title
                or (item.preferred_brand and item.preferred_brand.lower() in title)
            ),
            None,
        )

    def _heuristic_receipt_item(
        self, filename: str, text: str, inventory: list[InventoryItem]
    ) -> dict[str, Any]:
        price_match = re.search(r"\$\s?\d+(?:\.\d{2})?", text)
        matched = self._match_inventory_item({"product_title": text[:500]}, inventory)
        return {
            "retailer": _guess_retailer(filename + " " + text),
            "item_id": matched.item_id if matched else "",
            "item_name": matched.item_name if matched else "未匹配小票商品",
            "brand": matched.preferred_brand if matched else "",
            "product_title": matched.item_name if matched else filename,
            "quantity": "",
            "price": price_match.group(0) if price_match else "待确认",
            "shipping_address": "",
            "address_category": "未识别",
            "order_link": "",
        }

    def _default_shipping_address(self) -> str:
        from app.config import get_settings

        return get_settings().default_shipping_address

    def _upload_hsa_receipt_if_needed(
        self, filename: str, content_type: str, data: bytes, orders: list[dict[str, Any]]
    ) -> str:
        try:
            tracker = self.hsa_tracker or HsaTrackerService()
            if not tracker.has_hsa_candidate(orders):
                return ""
            return tracker.upload_receipt_to_hsa_folder(filename, content_type, data)
        except Exception:
            return ""

    def _write_hsa_candidate(
        self, source_id: str, order: dict[str, Any], receipt_link: str, filename: str
    ) -> None:
        try:
            tracker = self.hsa_tracker or HsaTrackerService()
            tracker.append_if_candidate(
                source="上传小票",
                source_id=source_id,
                order=order,
                receipt_link=receipt_link,
                note=f"来自上传小票: {filename}",
            )
        except Exception:
            return


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")


def _parse_json(content: str) -> Any:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _dedupe_receipt_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = _receipt_item_dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _receipt_item_dedupe_key(item: dict[str, Any]) -> tuple[str, str, str]:
    identity = item.get("item_id") or item.get("product_title") or item.get("item_name") or ""
    retailer = item.get("retailer", "")
    price = item.get("price", "")
    return (_normalize_text_key(identity), _normalize_text_key(retailer), _normalize_price(price))


def _normalize_text_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).lower())


def _normalize_price(value: Any) -> str:
    match = re.search(r"\d+(?:\.\d{1,2})?", str(value))
    if not match:
        return ""
    dollars = float(match.group(0))
    return f"{dollars:.2f}"


def _normalize_address(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _address_category(address: str, default_address: str) -> str:
    if not address:
        return "未识别"
    return (
        "默认地址"
        if _normalize_address(default_address) in _normalize_address(address)
        else "其他地址"
    )


def _guess_retailer(text: str) -> str:
    lower = text.lower()
    for retailer in ["Amazon", "Costco", "Walmart", "Target"]:
        if retailer.lower() in lower:
            return retailer
    return "Other"
