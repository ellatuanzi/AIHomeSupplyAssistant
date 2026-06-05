from app.services.google_sheets import GoogleSheetsService, SHEET_TABS


class FakeGoogleSheetsService(GoogleSheetsService):
    def __post_init__(self):
        self.rows = []

    def get_inventory_items(self):
        return []

    def append_row(self, tab_name, row):
        self.rows.append((tab_name, row))


def test_ensure_inventory_item_appends_inventory_row():
    sheets = FakeGoogleSheetsService()

    item = sheets.ensure_inventory_item(
        item_id="custom_神秘东西",
        item_name="神秘东西",
        household_location="主卧洗手间",
        notes="自动创建",
    )

    assert item.item_id == "custom_神秘东西"
    assert item.item_name == "神秘东西"
    assert sheets.rows == [
        (
            SHEET_TABS["inventory"],
            ["custom_神秘东西", "神秘东西", "未分类", "", "", "主卧洗手间", "", "", "中", "自动创建"],
        )
    ]
