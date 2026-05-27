from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAIError

from app.models.inventory import InventoryItem
from app.services.gmail import GmailService
from app.services.google_sheets import GoogleSheetsService
from app.services.hsa_tracker import HsaTrackerService
from app.services.openai_client import OpenAIRecommendationService
from app.utils.dates import today_local_string
from app.utils.ids import new_id


class OrderAnalysisAgent:
    def __init__(
        self,
        sheets: GoogleSheetsService | None = None,
        gmail: GmailService | None = None,
        recommender: OpenAIRecommendationService | None = None,
        hsa_tracker: HsaTrackerService | None = None,
    ) -> None:
        self.sheets = sheets or GoogleSheetsService()
        self.gmail = gmail or GmailService()
        self.recommender = recommender or OpenAIRecommendationService()
        self.hsa_tracker = hsa_tracker
        self.default_shipping_address = self.gmail.settings.default_shipping_address

    def run(self) -> list[dict[str, Any]]:
        self.sheets.ensure_tabs_and_headers()
        settings = self.gmail.settings
        inventory = self.sheets.get_inventory_items()
        processed_ids = self._processed_message_ids()
        messages = self.gmail.search_messages(
            settings.order_email_query, settings.max_order_emails
        )

        insights = []
        for message in messages:
            message_id = message["id"]
            if any(existing_id == message_id or existing_id.startswith(f"{message_id}#") for existing_id in processed_ids):
                continue
            email = self.gmail.get_message_text(message_id)
            if not is_order_received_email(email):
                continue
            extracted_orders = self._extract_orders(email, inventory)
            if not extracted_orders:
                continue

            for index, extracted in enumerate(extracted_orders, start=1):
                item = self._match_inventory_item(extracted, inventory)
                extracted["address_category"] = self._address_category(
                    extracted.get("shipping_address", "")
                )
                insight = self._analyze_order(email, extracted, item)
                source_id = f"{message_id}#{index}"
                self._write_purchase_history(source_id, email, extracted, item, insight)
                self._write_order_insight(source_id, extracted, item, insight)
                self._write_hsa_candidate(source_id, extracted, email.get("subject", ""))
                insights.append(insight)

        return insights

    def process_message_ids(self, message_ids: list[str]) -> list[dict[str, Any]]:
        self.sheets.ensure_tabs_and_headers()
        inventory = self.sheets.get_inventory_items()
        insights = []
        for message_id in message_ids:
            email = self.gmail.get_message_text(message_id)
            if not is_order_received_email(email):
                continue
            extracted_orders = self._extract_orders(email, inventory)
            for index, extracted in enumerate(extracted_orders, start=1):
                source_id = f"{message_id}#{index}"
                item = self._match_inventory_item(extracted, inventory)
                extracted["address_category"] = self._address_category(
                    extracted.get("shipping_address", "")
                )
                insight = self._analyze_order(email, extracted, item)
                self._write_purchase_history(source_id, email, extracted, item, insight)
                self._write_order_insight(source_id, extracted, item, insight)
                self._write_hsa_candidate(source_id, extracted, email.get("subject", ""))
                insights.append(insight)
        return insights

    def _processed_message_ids(self) -> set[str]:
        rows = self.sheets.purchase_history() + self.sheets.order_insights()
        return {row.get("邮件ID", "") for row in rows if row.get("邮件ID")}

    def _extract_orders(
        self, email: dict[str, str], inventory: list[InventoryItem]
    ) -> list[dict[str, Any]]:
        client = self.recommender.client
        if not client:
            return self._heuristic_extract_orders(email, inventory)

        prompt = {
            "instruction": "只从 order received、ordered、order confirmation 这类下单确认邮件正文中提取实际商品行。邮件标题不是商品标题；商品信息通常在正文中，可能包含商品链接文本、Quantity 和价格。发货、送达、促销、广告、deal、sale 邮件必须返回空数组。每件商品输出一条。",
            "email": {
                "subject": email["subject"],
                "from": email["from"],
                "date": email["date"],
                "snippet": email["snippet"],
                "body": email["body"][:8000],
            },
            "inventory_items": [item.model_dump() for item in inventory],
            "schema": [
                {
                    "retailer": "Amazon/Costco/Walmart/Target/Other",
                    "item_name": "string",
                    "item_id": "string if matched else empty",
                    "brand": "string",
                    "product_title": "actual product title from email body, not email subject",
                    "quantity": "string",
                    "price": "string",
                    "shipping_address": "string",
                    "address_category": "默认地址/其他地址/未识别",
                    "order_link": "string",
                }
            ],
        }
        try:
            response = client.chat.completions.create(
                model=self.recommender.model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                temperature=0.1,
            )
            parsed = json.loads(response.choices[0].message.content or "[]")
            if isinstance(parsed, dict):
                return [parsed] if parsed.get("is_order", True) else []
            return [item for item in parsed if item]
        except (OpenAIError, json.JSONDecodeError):
            return self._heuristic_extract_orders(email, inventory)

    def _analyze_order(
        self,
        email: dict[str, str],
        order: dict[str, Any],
        item: InventoryItem | None,
    ) -> dict[str, Any]:
        client = self.recommender.client
        if not client:
            return self._heuristic_analysis(order, item)

        matching_history = [
            row
            for row in self.sheets.purchase_history()
            if item and row.get("商品ID") == item.item_id
        ]
        prompt = {
            "instruction": "分析这次家庭日用品下单是否买贵、是否可能需要未来补货、是否有健康/适用性提醒，以及更好建议。不要建议自动购买。",
            "order": order,
            "inventory_item": item.model_dump() if item else {},
            "purchase_history": matching_history[-10:],
            "email_excerpt": email["body"][:4000],
            "schema": {
                "item_id": "string",
                "item_name": "string",
                "retailer": "string",
                "product_title": "string",
                "price": "string",
                "shipping_address": "string",
                "address_category": "默认地址/其他地址/未识别",
                "price_judgment": "中文一句话",
                "restock_prediction": "中文一句话",
                "health_or_fit_note": "中文一句话",
                "better_suggestion": "中文一句话",
                "confidence": "integer 0-100",
                "summary": "中文一句话",
            },
        }
        try:
            response = client.chat.completions.create(
                model=self.recommender.model,
                messages=[
                    {"role": "system", "content": "只输出 JSON，不要 Markdown。"},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            return json.loads(response.choices[0].message.content or "{}")
        except (OpenAIError, json.JSONDecodeError):
            return self._heuristic_analysis(order, item)

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

    def _write_purchase_history(
        self,
        message_id: str,
        email: dict[str, str],
        order: dict[str, Any],
        item: InventoryItem | None,
        insight: dict[str, Any],
    ) -> None:
        self.sheets.append_purchase_history_dict(
            _purchase_history_row(
                purchase_id=new_id("pur"),
                source_id=message_id,
                item_id=item.item_id if item else order.get("item_id", ""),
                item_name=item.item_name if item else order.get("item_name", ""),
                purchase_date=today_local_string(),
                retailer=order.get("retailer", ""),
                brand=order.get("brand", ""),
                product_title=order.get("product_title", ""),
                quantity=order.get("quantity", ""),
                price=order.get("price", ""),
                shipping_address=order.get("shipping_address", ""),
                address_category=order.get(
                    "address_category",
                    self._address_category(order.get("shipping_address", "")),
                ),
                order_link=order.get("order_link", ""),
                satisfaction="",
                note=_join_note(
                    f"来自 Gmail: {email.get('subject', '')}",
                    f"邮件标题: {order.get('email_subject', '')}",
                    insight.get("summary", ""),
                ),
            )
        )

    def _write_order_insight(
        self,
        message_id: str,
        order: dict[str, Any],
        item: InventoryItem | None,
        insight: dict[str, Any],
    ) -> None:
        self.sheets.append_order_insight_dict(
            _order_insight_row(
                analysis_id=new_id("ord"),
                source_id=message_id,
                analysis_date=today_local_string(),
                item_id=item.item_id if item else insight.get("item_id", ""),
                item_name=item.item_name
                if item
                else insight.get("item_name", order.get("item_name", "")),
                retailer=insight.get("retailer", order.get("retailer", "")),
                product_title=insight.get("product_title", order.get("product_title", "")),
                price=insight.get("price", order.get("price", "")),
                shipping_address=insight.get("shipping_address", order.get("shipping_address", "")),
                address_category=insight.get(
                    "address_category",
                    order.get(
                        "address_category",
                        self._address_category(order.get("shipping_address", "")),
                    ),
                ),
                price_judgment=insight.get("price_judgment", ""),
                restock_prediction=insight.get("restock_prediction", ""),
                health_note=insight.get("health_or_fit_note", ""),
                better_suggestion=insight.get("better_suggestion", ""),
                confidence=insight.get("confidence", 60),
                note=insight.get("summary", ""),
            )
        )

    def _heuristic_extract_orders(
        self, email: dict[str, str], inventory: list[InventoryItem]
    ) -> list[dict[str, Any]]:
        text = " ".join([email["subject"], email["from"], email["snippet"], email["body"]])
        lower = text.lower()
        if not is_order_received_email(email):
            return []
        retailer = "Other"
        for name in ["Amazon", "Costco", "Walmart", "Target"]:
            if name.lower() in lower:
                retailer = name
                break
        shipping_address = self._extract_shipping_address(text)
        product_blocks = extract_product_blocks_from_order_body(email["body"])
        if not product_blocks:
            product_blocks = [{"product_title": "待识别", "quantity": "", "price": "待确认"}]

        orders = []
        for block in product_blocks:
            product_title = clean_product_title(block.get("product_title", "待识别"))
            matched = self._match_inventory_item(block, inventory)
            orders.append(
                {
                    "is_order": True,
                    "retailer": retailer,
                    "item_id": matched.item_id if matched else "",
                    "item_name": matched.item_name if matched else product_title,
                    "brand": matched.preferred_brand if matched else "",
                    "product_title": product_title,
                    "email_subject": email["subject"],
                    "quantity": block.get("quantity", ""),
                    "price": block.get("price", "待确认"),
                    "shipping_address": shipping_address,
                    "address_category": self._address_category(shipping_address),
                    "order_link": "",
                }
            )
        return orders

    def _heuristic_analysis(
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
            "address_category": order.get(
                "address_category",
                self._address_category(order.get("shipping_address", "")),
            ),
            "price_judgment": "尚未配置 OpenAI API Key，无法做细致价格比较；已记录本次价格用于后续对比。",
            "restock_prediction": f"已把 {item_name} 写入购买历史，后续可结合低库存记录判断补货周期。",
            "health_or_fit_note": "尚未做成分或适用性判断；建议人工确认是否符合家庭偏好。",
            "better_suggestion": "后续可比较单位价格、规格和历史满意度后给出更好建议。",
            "confidence": 55,
            "summary": f"已从 Gmail 订单邮件记录 {item_name} 的购买信息。",
        }

    def _address_category(self, address: str) -> str:
        if not address:
            return "未识别"
        normalized_address = _normalize_address(address)
        normalized_default = _normalize_address(self.default_shipping_address)
        return "默认地址" if normalized_default in normalized_address else "其他地址"

    def _extract_shipping_address(self, text: str) -> str:
        match = re.search(
            r"(ship(?:ping|ped)? to|deliver(?:y|ed)? to|address)[:\\s]+(.{0,180})",
            text,
            flags=re.I,
        )
        if match:
            return " ".join(match.group(2).split())[:180]
        amazon_match = extract_amazon_delivery_location(text)
        if amazon_match:
            return amazon_match
        if _normalize_address(self.default_shipping_address) in _normalize_address(text):
            return self.default_shipping_address
        return ""

    def _write_hsa_candidate(self, source_id: str, order: dict[str, Any], subject: str) -> None:
        try:
            tracker = self.hsa_tracker or HsaTrackerService()
            tracker.append_if_candidate(
                source="Gmail订单",
                source_id=source_id,
                order=order,
                note=f"来自邮件: {subject}",
            )
        except Exception:
            return


def _normalize_address(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _join_note(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def extract_amazon_delivery_location(text: str) -> str:
    lines = [_clean_order_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    for line in lines:
        if re.search(r"^[A-Za-z][A-Za-z .'-]{0,40}\s+-\s+[A-Z][A-Z .'-]+,\s*[A-Z]{2}$", line):
            return line
    return ""


def extract_product_blocks_from_order_body(body: str) -> list[dict[str, str]]:
    lines = [_clean_order_line(line) for line in body.splitlines()]
    lines = [line for line in lines if line]
    blocks = []

    for idx, line in enumerate(lines):
        quantity_match = re.search(r"\bquantity\s*:\s*(\d+)", line, flags=re.I)
        if not quantity_match:
            continue

        title = clean_product_title(_previous_product_title(lines, idx))
        if not title:
            continue

        price = _next_price(lines, idx + 1)
        blocks.append(
            {
                "product_title": title,
                "item_name": title,
                "quantity": quantity_match.group(1),
                "price": price or "待确认",
            }
        )

    return _dedupe_product_blocks(blocks)


def _clean_order_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _previous_product_title(lines: list[str], quantity_index: int) -> str:
    for idx in range(quantity_index - 1, max(-1, quantity_index - 6), -1):
        candidate = lines[idx].strip()
        if _looks_like_product_title(candidate):
            return candidate
    return ""


def _next_price(lines: list[str], start_index: int) -> str:
    for idx in range(start_index, min(len(lines), start_index + 5)):
        match = re.search(
            r"(?:\$\s?\d+(?:[\.,]\d{2})?|\d+(?:[\.,]\d{1,2})?\s*USD)",
            lines[idx],
            flags=re.I,
        )
        if match:
            return match.group(0).replace(" ", "").replace(",", ".")
    return ""


def _looks_like_product_title(value: str) -> bool:
    lowered = value.lower()
    if len(value) < 4:
        return False
    bad_fragments = [
        "quantity",
        "order",
        "subtotal",
        "total",
        "shipping",
        "payment",
        "address",
        "view order",
        "track",
        "amazon.com",
        "$",
    ]
    if any(fragment in lowered for fragment in bad_fragments):
        return False
    return bool(re.search(r"[a-zA-Z]", value))


def _dedupe_product_blocks(blocks: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for block in blocks:
        key = (
            block.get("product_title", "").lower(),
            block.get("quantity", ""),
            block.get("price", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(block)
    return result


def clean_product_title(value: str) -> str:
    value = re.sub(r"^\s*[*•-]\s*", "", value.strip())
    return re.sub(r"\s+", " ", value)


def is_order_received_email(email: dict[str, str]) -> bool:
    subject = email.get("subject", "").lower()
    combined = " ".join(
        [
            email.get("subject", ""),
            email.get("from", ""),
            email.get("snippet", ""),
            email.get("body", "")[:2000],
        ]
    ).lower()

    if subject.startswith("ordered:"):
        return True

    negative_terms = [
        "shipped",
        "shipping update",
        "delivered",
        "out for delivery",
        "promotion",
        "promotional",
        "promo",
        "deal",
        "deals",
        "sale",
        "warehouse insider",
        "memorial day",
        "coupon",
        "save up to",
        "subscribe",
        "recommended for you",
        "picked for you",
        "refund",
        "refunded",
        "advance refund",
        "return",
        "dropoff",
        "drop-off",
        "canceled",
        "cancelled",
        "package from order",
        "did your recent",
    ]
    if any(term in combined for term in negative_terms):
        return False

    positive_subject_terms = [
        "order received",
        "order confirmation",
        "your order",
        "ordered",
        "order placed",
        "thanks for your order",
        "thank you for your order",
    ]
    if any(term in subject for term in positive_subject_terms):
        return True

    positive_body_terms = [
        "order number",
        "order total",
        "order date",
        "payment method",
    ]
    return "order" in subject and any(term in combined for term in positive_body_terms)


def _purchase_history_row(
    purchase_id: str,
    source_id: str,
    item_id: str,
    item_name: str,
    purchase_date: str,
    retailer: str,
    brand: str,
    product_title: str,
    quantity: str,
    price: str,
    shipping_address: str,
    address_category: str,
    order_link: str,
    satisfaction: str,
    note: str,
) -> dict[str, Any]:
    return {
        "购买ID": purchase_id,
        "邮件ID": source_id,
        "商品ID": item_id,
        "商品名称": item_name,
        "购买日期": purchase_date,
        "店铺": retailer,
        "品牌": brand,
        "商品标题": product_title,
        "规格": quantity,
        "价格": price,
        "收货地址": shipping_address,
        "地址分类": address_category,
        "订单链接": order_link,
        "满意度": satisfaction,
        "备注": note,
    }


def _order_insight_row(
    analysis_id: str,
    source_id: str,
    analysis_date: str,
    item_id: str,
    item_name: str,
    retailer: str,
    product_title: str,
    price: str,
    shipping_address: str,
    address_category: str,
    price_judgment: str,
    restock_prediction: str,
    health_note: str,
    better_suggestion: str,
    confidence: int,
    note: str,
) -> dict[str, Any]:
    return {
        "分析ID": analysis_id,
        "邮件ID": source_id,
        "分析日期": analysis_date,
        "商品ID": item_id,
        "商品名称": item_name,
        "店铺": retailer,
        "商品标题": product_title,
        "价格": price,
        "收货地址": shipping_address,
        "地址分类": address_category,
        "价格判断": price_judgment,
        "补货预测": restock_prediction,
        "健康/适用性提醒": health_note,
        "更好建议": better_suggestion,
        "置信度": confidence,
        "备注": note,
    }
