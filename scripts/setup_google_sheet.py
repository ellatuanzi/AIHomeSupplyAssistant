from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.google_sheets import GoogleSheetsService


SAMPLE_INVENTORY = [
    [
        "toilet_paper",
        "Toilet Paper",
        "纸品",
        "Charmin",
        "Costco",
        "卫生间",
        "30 rolls",
        "只剩一周",
        "中",
        "偏好 septic-safe",
    ],
    [
        "trash_bags",
        "Trash Bags",
        "清洁用品",
        "Glad",
        "Amazon",
        "厨房",
        "120 count",
        "少于 10 个",
        "高",
        "Tall kitchen, drawstring",
    ],
    [
        "detergent",
        "Laundry Detergent",
        "清洁用品",
        "Tide",
        "Target",
        "洗衣房",
        "92 fl oz",
        "少于 20%",
        "中",
        "尽量买 unscented",
    ],
]


def main() -> None:
    sheets = GoogleSheetsService()
    sheets.ensure_tabs_and_headers()

    existing_ids = {row.get("商品ID") for row in sheets.read_rows("库存清单")}
    for row in SAMPLE_INVENTORY:
        if row[0] not in existing_ids:
            sheets.append_row("库存清单", row)

    print("Google Sheet 初始化完成。")


if __name__ == "__main__":
    main()
