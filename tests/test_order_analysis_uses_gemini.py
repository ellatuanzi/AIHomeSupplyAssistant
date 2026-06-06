from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.models.inventory import InventoryItem


class FakeSheets:
    def purchase_history(self):
        return []


class FakeSheetsWithHistory:
    def purchase_history(self):
        return [
            {"商品ID": "body_lotion", "价格": "$10.00"},
            {"商品ID": "body_lotion", "价格": "$12.00"},
        ]


class FakeRecommender:
    def __init__(self):
        self.calls = []

    def generate_json(self, prompt, fallback, temperature=0.2):
        self.calls.append((prompt, fallback, temperature))
        if "schema" in prompt and isinstance(prompt["schema"], dict):
            return {
                "item_id": "body_lotion",
                "item_name": "Body Lotion",
                "retailer": "Amazon",
                "product_title": "CeraVe Daily Moisturizing Lotion",
                "price": "$14.99",
                "shipping_address": "102 Montelena Ct",
                "address_category": "默认地址",
                "price_judgment": "价格接近常见区间。",
                "restock_prediction": "按低库存记录后续比较。",
                "health_or_fit_note": "适合干燥皮肤时仍需人工确认。",
                "better_suggestion": "可比较 Costco 单位价格。",
                "confidence": 80,
                "summary": "已分析订单。",
            }
        return [
            {
                "retailer": "Amazon",
                "item_name": "Body Lotion",
                "item_id": "body_lotion",
                "brand": "CeraVe",
                "product_title": "CeraVe Daily Moisturizing Lotion",
                "quantity": "1",
                "price": "$14.99",
                "shipping_address": "102 Montelena Ct",
                "address_category": "默认地址",
                "order_link": "",
            }
        ]


class FakeGmail:
    class Settings:
        default_shipping_address = "102 Montelena Ct"

    settings = Settings()


def test_order_analysis_uses_recommender_json_without_openai_client():
    recommender = FakeRecommender()
    agent = OrderAnalysisAgent(sheets=FakeSheets(), gmail=FakeGmail(), recommender=recommender)
    email = {
        "subject": "Your Order Confirmation - Details Inside",
        "from": "store@example.com",
        "date": "2026-06-04",
        "snippet": "CeraVe Daily Moisturizing Lotion",
        "body": "CeraVe Daily Moisturizing Lotion Qty 1 Price $14.99",
    }
    inventory = [InventoryItem(item_id="body_lotion", item_name="Body Lotion")]

    orders = agent._extract_orders(email, inventory)
    insight = agent._analyze_order(email, orders[0], inventory[0])

    assert orders[0]["item_id"] == "body_lotion"
    assert insight["price_judgment"] == "价格接近常见区间。"
    assert [call[2] for call in recommender.calls] == [0.1, 0.2]


class FallbackRecommender(FakeRecommender):
    def generate_json(self, prompt, fallback, temperature=0.2):
        self.calls.append((prompt, fallback, temperature))
        return fallback


def test_order_analysis_fallback_records_baseline_price_without_ai():
    recommender = FallbackRecommender()
    agent = OrderAnalysisAgent(sheets=FakeSheets(), gmail=FakeGmail(), recommender=recommender)
    order = {
        "item_id": "body_lotion",
        "item_name": "Body Lotion",
        "retailer": "Amazon",
        "product_title": "CeraVe Daily Moisturizing Lotion",
        "price": "$14.99",
    }

    insight = agent._analyze_order({"body": ""}, order, InventoryItem(item_id="body_lotion", item_name="Body Lotion"))

    assert "AI 价格分析暂不可用" not in insight["price_judgment"]
    assert "作为基准" in insight["price_judgment"]


def test_order_analysis_fallback_compares_against_history():
    recommender = FallbackRecommender()
    agent = OrderAnalysisAgent(
        sheets=FakeSheetsWithHistory(), gmail=FakeGmail(), recommender=recommender
    )
    order = {
        "item_id": "body_lotion",
        "item_name": "Body Lotion",
        "retailer": "Amazon",
        "product_title": "CeraVe Daily Moisturizing Lotion",
        "price": "$15.00",
    }

    insight = agent._analyze_order({"body": ""}, order, InventoryItem(item_id="body_lotion", item_name="Body Lotion"))

    assert "可能偏贵" in insight["price_judgment"]
    assert "$15.00" in insight["price_judgment"]
