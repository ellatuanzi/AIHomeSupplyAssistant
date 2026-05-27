from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.order_analysis_agent import clean_product_title
from app.services.google_sheets import SHEET_TABS, GoogleSheetsService


def should_delete_bad_legacy_row(row: dict[str, str]) -> bool:
    return (
        row.get("商品名称") == "未识别"
        and row.get("商品标题", "") == ""
        and row.get("价格", "") == ""
    )


def fix_tab(sheets: GoogleSheetsService, tab_name: str) -> tuple[int, int]:
    rows = sheets.read_rows(tab_name)
    fixed = 0
    delete_rows = []
    for row_number, row in enumerate(rows, start=2):
        if should_delete_bad_legacy_row(row):
            delete_rows.append(row_number)
            continue

        product_title = row.get("商品标题", "")
        cleaned_title = clean_product_title(product_title)
        updates = {}
        if cleaned_title != product_title:
            updates["商品标题"] = cleaned_title
        if row.get("商品名称") == "未匹配商品" and cleaned_title and cleaned_title != "待识别":
            updates["商品名称"] = cleaned_title
        if updates:
            sheets.update_row_by_headers(tab_name, row_number, updates)
            fixed += 1

    sheets.delete_rows(tab_name, delete_rows)
    return fixed, len(delete_rows)


def main() -> None:
    sheets = GoogleSheetsService()
    sheets.ensure_tabs_and_headers()
    history_fixed, history_deleted = fix_tab(sheets, SHEET_TABS["history"])
    insights_fixed, insights_deleted = fix_tab(sheets, SHEET_TABS["order_insights"])
    print(
        {
            "purchase_history_fixed": history_fixed,
            "purchase_history_deleted": history_deleted,
            "order_insights_fixed": insights_fixed,
            "order_insights_deleted": insights_deleted,
        }
    )


if __name__ == "__main__":
    main()
