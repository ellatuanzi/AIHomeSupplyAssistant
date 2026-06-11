from app.api import routes
from app.models.inventory import InventoryItem


class FakeSheets:
    def __init__(self) -> None:
        self.low_stock_rows = []

    def get_inventory_items(self):
        return [
            InventoryItem(
                item_id="toilet_paper",
                item_name="Toilet Paper",
                category="纸品",
                preferred_retailer="Costco",
                household_location="主卧洗手间",
                urgency_default="中",
            ),
            InventoryItem(item_id="body_lotion", item_name="Body Lotion", urgency_default="中"),
        ]

    def find_inventory_item(self, item_id):
        return next((item for item in self.get_inventory_items() if item.item_id == item_id), None)

    def pending_tasks(self):
        return [
            {
                "任务类型": "搬运补货",
                "商品名称": "Toilet Paper",
                "来源位置": "车库",
                "目标位置": "主卧洗手间",
                "状态": "待办",
            }
        ]

    def unresolved_events(self):
        return [
            {
                "商品名称": "Body Lotion",
                "位置": "汤圆房间",
                "紧急度": "中",
                "是否已处理": "否",
            }
        ]

    def recommendations(self):
        return [
            {
                "商品名称": "Body Lotion",
                "推荐商品": "CeraVe Daily Moisturizing Lotion",
                "推荐店铺": "Amazon",
                "预估价格": "$15.99",
                "补货状态": "待确认",
            }
        ]

    def item_locations(self, item_id):
        if item_id == "toilet_paper":
            return ["主卧洗手间", "车库"]
        return []

    def order_insights(self):
        return []

    def ensure_item_location(self, item_id, item_name, location, source="", note=""):
        pass

    def recent_low_stock_event(self, item_id, source, within_minutes, location=""):
        return None

    def append_low_stock_event(self, row):
        self.low_stock_rows.append(row)


def test_chat_lists_pending_tasks(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_chat_message("现在有哪些待办？")

    assert result["ok"] is True
    assert "Toilet Paper" in result["message"]
    assert "车库 -> 主卧洗手间" in result["message"]


def test_chat_answers_item_location(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_chat_message("手纸放在哪里？")

    assert result["ok"] is True
    assert "主卧洗手间" in result["message"]
    assert "车库" in result["message"]


def test_chat_can_update_low_stock(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_chat_message("主卧洗手间手纸低库存")

    assert result["ok"] is True
    assert result["updated_google_sheet"] is True
    assert result["action"] == "low_stock"
    assert fake.low_stock_rows[0][3] == "Toilet Paper"


def test_chat_state_includes_daily_summary(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    state = routes._chat_state()

    assert "daily_summary" in state
    assert "今日摘要" in state["daily_summary"]["text"]
    assert state["daily_summary"]["pending_tasks_count"] == 1


def test_order_analysis_endpoint_skips_when_gmail_disabled(monkeypatch):
    class ExplodingOrderAnalysisAgent:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Gmail order analysis should not be instantiated")

    monkeypatch.setattr(routes, "OrderAnalysisAgent", ExplodingOrderAnalysisAgent)

    result = routes.run_order_analysis_agent()

    assert result["status"] == "跳过"
    assert result["order_insights_created"] == 0
