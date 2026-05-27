from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.google_sheets import SHEET_TABS, GoogleSheetsService


SUBJECT_PREFIXES = (
    "ordered:",
    "your order",
    "order received",
    "order confirmation",
)


def looks_like_email_subject(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(SUBJECT_PREFIXES) or " and ⁦" in lowered or " more item" in lowered


def append_subject_note(note: str, subject: str) -> str:
    marker = f"邮件标题: {subject}"
    if marker in note:
        return note
    return "; ".join(part for part in [note, marker] if part)


def fix_tab(sheets: GoogleSheetsService, tab_name: str) -> int:
    rows = sheets.read_rows(tab_name)
    fixed = 0
    for row_number, row in enumerate(rows, start=2):
        product_title = row.get("商品标题", "")
        if not looks_like_email_subject(product_title):
            continue
        sheets.update_row_by_headers(
            tab_name,
            row_number,
            {
                "商品标题": "待识别",
                "备注": append_subject_note(row.get("备注", ""), product_title),
            },
        )
        fixed += 1
    return fixed


def main() -> None:
    sheets = GoogleSheetsService()
    sheets.ensure_tabs_and_headers()
    result = {
        "purchase_history_fixed": fix_tab(sheets, SHEET_TABS["history"]),
        "order_insights_fixed": fix_tab(sheets, SHEET_TABS["order_insights"]),
    }
    print(result)


if __name__ == "__main__":
    main()
