from app.api import routes
from app.models.inventory import InventoryItem


class FakeSheets:
    def __init__(self) -> None:
        self.low_stock_rows = []
        self.task_rows = []
        self.locations = []
        self.created_items = []
        self.completed = False
        self.fail_append_low_stock = False

    def get_inventory_items(self):
        return [
            InventoryItem(item_id="toilet_paper", item_name="Toilet Paper", urgency_default="中"),
            InventoryItem(item_id="paper_towels", item_name="Paper Towels", urgency_default="中"),
            InventoryItem(item_id="napkin", item_name="Napkin", urgency_default="中"),
            InventoryItem(item_id="wet_wipes", item_name="Wet Wipes", urgency_default="中"),
            InventoryItem(item_id="body_lotion", item_name="Body Lotion", urgency_default="中"),
            InventoryItem(item_id="kids_toothpaste", item_name="Kids Toothpaste", urgency_default="中"),
        ]

    def find_inventory_item(self, item_id):
        return next(
            (
                item
                for item in self.get_inventory_items() + self.created_items
                if item.item_id == item_id
            ),
            None,
        )

    def ensure_inventory_item(
        self,
        item_id,
        item_name,
        category="未分类",
        preferred_brand="",
        preferred_retailer="",
        household_location="",
        typical_quantity="",
        reorder_threshold="",
        urgency_default="中",
        notes="",
    ):
        item = InventoryItem(
            item_id=item_id,
            item_name=item_name,
            category=category,
            preferred_brand=preferred_brand,
            preferred_retailer=preferred_retailer,
            household_location=household_location,
            typical_quantity=typical_quantity,
            reorder_threshold=reorder_threshold,
            urgency_default=urgency_default,
            notes=notes,
        )
        self.created_items.append(item)
        return item

    def ensure_item_location(self, item_id, item_name, location, source="", note=""):
        if location:
            self.locations.append((item_id, item_name, location, source, note))

    def recent_low_stock_event(self, item_id, source, within_minutes, location=""):
        return None

    def append_low_stock_event(self, row):
        if self.fail_append_low_stock:
            raise RuntimeError("模拟写入失败")
        self.low_stock_rows.append(row)

    def append_task(self, row):
        self.task_rows.append(row)

    def complete_open_task(self, item_id, target_location="", task_type="搬运补货"):
        self.completed = True
        return {"商品ID": item_id, "目标位置": target_location, "任务类型": task_type}


def test_voice_command_records_low_stock(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("主卧洗手间手纸低库存")

    assert result["status"] == "已记录"
    assert result["action"] == "low_stock"
    assert result["item_id"] == "toilet_paper"
    assert fake.low_stock_rows[0][4] == "语音"
    assert fake.low_stock_rows[0][8] == "主卧洗手间"


def test_voice_command_handles_toilet_paper_mishearing(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("主卧洗手间手指低库存")

    assert result["status"] == "已记录"
    assert result["item_id"] == "toilet_paper"
    assert fake.low_stock_rows[0][3] == "Toilet Paper"


def test_voice_command_handles_common_english_aliases(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("Tangyuan room moisturizer is low")

    assert result["status"] == "已记录"
    assert result["item_id"] == "body_lotion"
    assert fake.low_stock_rows[0][3] == "Body Lotion"


def test_voice_command_handles_common_replacement_words(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("二层厨房 kitchen paper 快没了")

    assert result["status"] == "已记录"
    assert result["action"] == "empty_stock"
    assert result["item_id"] == "paper_towels"


def test_voice_command_handles_napkin_alias(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("餐巾纸低库存")

    assert result["status"] == "已记录"
    assert result["item_id"] == "napkin"
    assert fake.low_stock_rows[0][3] == "Napkin"


def test_voice_command_handles_wet_wipes_to_third_floor(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("把湿纸巾拿到3层")

    assert result["status"] == "已创建"
    assert result["action"] == "create_task"
    assert result["item_id"] == "wet_wipes"
    assert result["target_location"] == "三层收纳柜"
    assert fake.task_rows[0][7] == "三层收纳柜"


def test_voice_command_handles_brand_alias(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("Tom's 草莓牙膏低库存")

    assert result["status"] == "已记录"
    assert result["item_id"] == "kids_toothpaste"


def test_voice_command_creates_unknown_item_when_not_matched(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("主卧洗手间神秘东西低库存")

    assert result["ok"] is True
    assert result["updated_google_sheet"] is True
    assert result["created_unknown_item"] is True
    assert fake.created_items[0].item_name == "神秘东西"
    assert fake.low_stock_rows[0][2] == "custom_神秘东西"
    assert fake.low_stock_rows[0][3] == "神秘东西"


def test_voice_command_creates_unknown_task_without_location_in_name(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("把神秘布拿到3层")

    assert result["ok"] is True
    assert result["status"] == "已创建"
    assert result["created_unknown_item"] is True
    assert fake.created_items[0].item_name == "神秘布"
    assert fake.task_rows[0][4] == "神秘布"
    assert fake.task_rows[0][7] == "三层收纳柜"


def test_voice_command_warns_when_sheet_write_fails(monkeypatch):
    fake = FakeSheets()
    fake.fail_append_low_stock = True
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("主卧洗手间手纸低库存")

    assert result["ok"] is False
    assert result["updated_google_sheet"] is False
    assert result["status"] == "未更新"
    assert "写入 Google Sheet 失败" in result["message"]


def test_voice_command_creates_task(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("把车库的手纸拿到主卧洗手间")

    assert result["status"] == "已创建"
    assert result["action"] == "create_task"
    assert result["item_id"] == "toilet_paper"
    assert fake.task_rows[0][6] == "车库"
    assert fake.task_rows[0][7] == "主卧洗手间"
    assert fake.task_rows[0][9] == "语音"


def test_voice_command_completes_task(monkeypatch):
    fake = FakeSheets()
    monkeypatch.setattr(routes, "sheets_service", lambda: fake)

    result = routes._handle_voice_command("完成主卧洗手间手纸搬运任务")

    assert result["status"] == "已完成"
    assert result["action"] == "complete_task"
    assert fake.completed is True
