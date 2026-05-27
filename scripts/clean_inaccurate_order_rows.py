from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.google_sheets import SHEET_TABS, GoogleSheetsService


BAD_TERMS = [
    "new deals",
    "refund",
    "advance refund",
    "shipped",
    "delivered",
    "dropoff",
    "drop-off",
    "canceled",
    "cancelled",
    "weekly warehouse insider",
    "memorial day offers",
    "promo",
    "promotion",
    "save up to",
    "final day",
    "package from order",
    "did your recent",
]


def row_text(row: dict[str, str]) -> str:
    return " ".join(str(value) for value in row.values() if value)


def should_delete_purchase_history(row: dict[str, str]) -> bool:
    note = row.get("备注", "")
    if "来自上传小票" in note:
        return False
    text = row_text(row).lower()
    return any(term in text for term in BAD_TERMS)


def should_delete_order_insight(row: dict[str, str]) -> bool:
    note = row.get("备注", "")
    text = row_text(row)
    if "上传小票" in note or "上传小票" in text:
        return False
    return any(term in text.lower() for term in BAD_TERMS)


def main() -> None:
    sheets = GoogleSheetsService()
    sheets.ensure_tabs_and_headers()

    purchase_rows = sheets.purchase_history()
    purchase_delete_rows = [
        idx
        for idx, row in enumerate(purchase_rows, start=2)
        if should_delete_purchase_history(row)
    ]
    sheets.delete_rows(SHEET_TABS["history"], purchase_delete_rows)

    insight_rows = sheets.order_insights()
    insight_delete_rows = [
        idx
        for idx, row in enumerate(insight_rows, start=2)
        if should_delete_order_insight(row)
    ]
    sheets.delete_rows(SHEET_TABS["order_insights"], insight_delete_rows)

    print(
        {
            "purchase_history_deleted": len(purchase_delete_rows),
            "order_insights_deleted": len(insight_delete_rows),
        }
    )


if __name__ == "__main__":
    main()
