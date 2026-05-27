from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.services.gmail import GmailService
from app.services.google_sheets import SHEET_TABS, GoogleSheetsService


def base_message_id(value: str) -> str:
    return value.split("#", 1)[0]


def backfill_tab(
    sheets: GoogleSheetsService,
    gmail: GmailService,
    agent: OrderAnalysisAgent,
    tab_name: str,
) -> int:
    rows = sheets.read_rows(tab_name)
    fixed = 0
    cache: dict[str, str] = {}
    for row_number, row in enumerate(rows, start=2):
        if row.get("收货地址"):
            continue
        message_id = base_message_id(row.get("邮件ID", ""))
        if not message_id or message_id.startswith("receipt_"):
            continue
        if message_id not in cache:
            email = gmail.get_message_text(message_id)
            text = " ".join([email["subject"], email["from"], email["snippet"], email["body"]])
            cache[message_id] = agent._extract_shipping_address(text)
        address = cache[message_id]
        if not address:
            continue
        sheets.update_row_by_headers(
            tab_name,
            row_number,
            {
                "收货地址": address,
                "地址分类": agent._address_category(address),
            },
        )
        fixed += 1
    return fixed


def main() -> None:
    sheets = GoogleSheetsService()
    gmail = GmailService()
    agent = OrderAnalysisAgent(sheets=sheets, gmail=gmail)
    sheets.ensure_tabs_and_headers()
    result = {
        "purchase_history_fixed": backfill_tab(sheets, gmail, agent, SHEET_TABS["history"]),
        "order_insights_fixed": backfill_tab(sheets, gmail, agent, SHEET_TABS["order_insights"]),
    }
    print(result)


if __name__ == "__main__":
    main()
