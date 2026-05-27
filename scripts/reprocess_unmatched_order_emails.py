from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.services.google_sheets import SHEET_TABS, GoogleSheetsService


def base_message_id(value: str) -> str:
    return value.split("#", 1)[0]


def is_low_quality_row(row: dict[str, str]) -> bool:
    text = " ".join(str(value) for value in row.values() if value)
    return (
        row.get("商品名称", "") in {"未匹配商品", "未匹配小票商品"}
        or row.get("商品标题", "") in {"待识别", "test_receipt.txt", "Order Receipt"}
        or bool(re.search(r"\bOrdered:\s*\"", row.get("备注", "") + " " + row.get("商品标题", ""), re.I))
    )


def main() -> None:
    sheets = GoogleSheetsService()
    sheets.ensure_tabs_and_headers()

    low_quality_message_ids = set()
    purchase_delete_rows = []
    for idx, row in enumerate(sheets.purchase_history(), start=2):
        if is_low_quality_row(row) and row.get("邮件ID", "").startswith("receipt_") is False:
            purchase_delete_rows.append(idx)
            if row.get("邮件ID"):
                low_quality_message_ids.add(base_message_id(row["邮件ID"]))

    insight_delete_rows = []
    for idx, row in enumerate(sheets.order_insights(), start=2):
        if is_low_quality_row(row) and row.get("邮件ID", "").startswith("receipt_") is False:
            insight_delete_rows.append(idx)
            if row.get("邮件ID"):
                low_quality_message_ids.add(base_message_id(row["邮件ID"]))

    sheets.delete_rows(SHEET_TABS["history"], purchase_delete_rows)
    sheets.delete_rows(SHEET_TABS["order_insights"], insight_delete_rows)

    insights = OrderAnalysisAgent(sheets=sheets).run()
    print(
        {
            "low_quality_message_ids_unblocked": len(low_quality_message_ids),
            "purchase_history_deleted": len(purchase_delete_rows),
            "order_insights_deleted": len(insight_delete_rows),
            "new_order_insights_created": len(insights),
        }
    )


if __name__ == "__main__":
    main()
