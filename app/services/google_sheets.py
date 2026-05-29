from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from app.config import get_settings
from app.models.inventory import InventoryItem
from app.services.google_auth import get_google_credentials
from app.utils.dates import now_local


SHEET_TABS = {
    "inventory": "库存清单",
    "events": "低库存记录",
    "history": "购买历史",
    "order_insights": "订单分析",
    "recommendations": "补货推荐",
    "send_log": "发送记录",
}

HEADERS = {
    "库存清单": [
        "商品ID",
        "商品名称",
        "分类",
        "偏好品牌",
        "偏好店铺",
        "存放位置",
        "常购规格",
        "补货阈值",
        "默认紧急度",
        "备注",
    ],
    "低库存记录": [
        "事件ID",
        "记录时间",
        "商品ID",
        "商品名称",
        "来源",
        "紧急度",
        "备注",
        "是否已处理",
    ],
    "购买历史": [
        "购买ID",
        "邮件ID",
        "商品ID",
        "商品名称",
        "购买日期",
        "店铺",
        "品牌",
        "商品标题",
        "规格",
        "价格",
        "收货地址",
        "地址分类",
        "订单链接",
        "满意度",
        "备注",
    ],
    "订单分析": [
        "分析ID",
        "邮件ID",
        "分析日期",
        "商品ID",
        "商品名称",
        "店铺",
        "商品标题",
        "价格",
        "收货地址",
        "地址分类",
        "价格判断",
        "补货预测",
        "健康/适用性提醒",
        "更好建议",
        "置信度",
        "备注",
    ],
    "补货推荐": [
        "推荐ID",
        "推荐日期",
        "商品ID",
        "商品名称",
        "推荐店铺",
        "推荐品牌",
        "推荐商品",
        "预估价格",
        "商品链接",
        "置信度",
        "紧急度",
        "推荐理由",
        "补货状态",
        "最后更新",
    ],
    "发送记录": [
        "日期",
        "处理时间",
        "状态",
        "是否发送邮件",
        "补货推荐数",
        "订单分析数",
        "备注",
    ],
}


@dataclass
class GoogleSheetsService:
    sheet_id: str | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.sheet_id = self.sheet_id or settings.google_sheet_id
        if not self.sheet_id:
            raise RuntimeError("缺少 GOOGLE_SHEET_ID，请在 .env 中配置 Google Sheet ID。")
        self.client = build("sheets", "v4", credentials=get_google_credentials())

    def read_rows(self, tab_name: str) -> list[dict[str, Any]]:
        values = (
            self.client.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=f"{tab_name}!A:Z")
            .execute()
            .get("values", [])
        )
        if not values:
            return []
        headers = values[0]
        return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:]]

    def read_values(self, tab_name: str) -> list[list[Any]]:
        return (
            self.client.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=f"{tab_name}!A:Z")
            .execute()
            .get("values", [])
        )

    def append_row(self, tab_name: str, row: list[Any]) -> None:
        self.client.spreadsheets().values().append(
            spreadsheetId=self.sheet_id,
            range=f"{tab_name}!A:Z",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def append_dict_row(self, tab_name: str, row: dict[str, Any]) -> None:
        values = self.read_values(tab_name)
        if not values:
            raise RuntimeError(f"{tab_name} 缺少表头，请先运行 ensure_tabs_and_headers。")
        headers = values[0]
        self.append_row(tab_name, [row.get(header, "") for header in headers])

    def update_cell(self, tab_name: str, row_number: int, column_letter: str, value: Any) -> None:
        self.client.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"{tab_name}!{column_letter}{row_number}",
            valueInputOption="USER_ENTERED",
            body={"values": [[value]]},
        ).execute()

    def update_row_by_headers(self, tab_name: str, row_number: int, updates: dict[str, Any]) -> None:
        values = self.read_values(tab_name)
        if not values:
            raise RuntimeError(f"{tab_name} 缺少表头。")
        headers = values[0]
        existing_row = values[row_number - 1] if len(values) >= row_number else []
        row = existing_row + [""] * (len(headers) - len(existing_row))
        for header, value in updates.items():
            if header in headers:
                row[headers.index(header)] = value
        self.client.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"{tab_name}!A{row_number}:{_column_name(len(headers))}{row_number}",
            valueInputOption="USER_ENTERED",
            body={"values": [row]},
        ).execute()

    def delete_rows(self, tab_name: str, row_numbers: list[int]) -> None:
        if not row_numbers:
            return
        spreadsheet = self.client.spreadsheets().get(spreadsheetId=self.sheet_id).execute()
        sheet_id = next(
            sheet["properties"]["sheetId"]
            for sheet in spreadsheet.get("sheets", [])
            if sheet["properties"]["title"] == tab_name
        )
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_number - 1,
                        "endIndex": row_number,
                    }
                }
            }
            for row_number in sorted(row_numbers, reverse=True)
        ]
        self.client.spreadsheets().batchUpdate(
            spreadsheetId=self.sheet_id, body={"requests": requests}
        ).execute()

    def ensure_tabs_and_headers(self) -> None:
        spreadsheet = self.client.spreadsheets().get(spreadsheetId=self.sheet_id).execute()
        existing_tabs = {
            sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
        }
        requests = [
            {"addSheet": {"properties": {"title": tab_name}}}
            for tab_name in HEADERS
            if tab_name not in existing_tabs
        ]
        if requests:
            self.client.spreadsheets().batchUpdate(
                spreadsheetId=self.sheet_id, body={"requests": requests}
            ).execute()

        for tab_name, headers in HEADERS.items():
            values = self.read_values(tab_name)
            if not values:
                self.append_row(tab_name, headers)
            else:
                existing_headers = values[0]
                missing_headers = [header for header in headers if header not in existing_headers]
                if missing_headers:
                    self.client.spreadsheets().values().update(
                        spreadsheetId=self.sheet_id,
                        range=f"{tab_name}!A1:{_column_name(len(existing_headers) + len(missing_headers))}1",
                        valueInputOption="USER_ENTERED",
                        body={"values": [existing_headers + missing_headers]},
                    ).execute()

    def get_inventory_items(self) -> list[InventoryItem]:
        rows = self.read_rows(SHEET_TABS["inventory"])
        items = []
        for row in rows:
            if not row.get("商品ID"):
                continue
            items.append(
                InventoryItem(
                    item_id=row.get("商品ID", ""),
                    item_name=row.get("商品名称", ""),
                    category=row.get("分类", ""),
                    preferred_brand=row.get("偏好品牌", ""),
                    preferred_retailer=row.get("偏好店铺", ""),
                    household_location=row.get("存放位置", ""),
                    typical_quantity=row.get("常购规格", ""),
                    reorder_threshold=row.get("补货阈值", ""),
                    urgency_default=row.get("默认紧急度", "中"),
                    notes=row.get("备注", ""),
                )
            )
        return items

    def find_inventory_item(self, item_id: str) -> InventoryItem | None:
        return next((item for item in self.get_inventory_items() if item.item_id == item_id), None)

    def append_low_stock_event(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["events"], row)

    def recent_low_stock_event(
        self,
        item_id: str,
        source: str,
        within_minutes: int,
    ) -> dict[str, Any] | None:
        cutoff = now_local().replace(tzinfo=None) - timedelta(minutes=within_minutes)
        for row in reversed(self.read_rows(SHEET_TABS["events"])):
            if row.get("商品ID") != item_id or row.get("来源") != source:
                continue
            recorded_at = _parse_local_datetime(row.get("记录时间", ""))
            if recorded_at and recorded_at >= cutoff:
                return row
        return None

    def append_recommendation(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["recommendations"], row)

    def unresolved_events(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.read_rows(SHEET_TABS["events"])
            if row.get("是否已处理", "").strip() not in {"是", "TRUE", "true", "已处理"}
        ]

    def purchase_history(self) -> list[dict[str, Any]]:
        return self.read_rows(SHEET_TABS["history"])

    def append_purchase_history(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["history"], row)

    def append_purchase_history_dict(self, row: dict[str, Any]) -> None:
        self.append_dict_row(SHEET_TABS["history"], row)

    def order_insights(self) -> list[dict[str, Any]]:
        return self.read_rows(SHEET_TABS["order_insights"])

    def append_order_insight(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["order_insights"], row)

    def append_order_insight_dict(self, row: dict[str, Any]) -> None:
        self.append_dict_row(SHEET_TABS["order_insights"], row)

    def recommendations(self) -> list[dict[str, Any]]:
        return self.read_rows(SHEET_TABS["recommendations"])

    def send_logs(self) -> list[dict[str, Any]]:
        return self.read_rows(SHEET_TABS["send_log"])

    def has_successful_daily_run(self, date_string: str) -> bool:
        return any(
            row.get("日期") == date_string and row.get("状态") == "完成"
            for row in self.send_logs()
        )

    def append_send_log(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["send_log"], row)

    def mark_event_resolved(self, event_id: str) -> None:
        rows = self.read_rows(SHEET_TABS["events"])
        for idx, row in enumerate(rows, start=2):
            if row.get("事件ID") == event_id:
                self.update_cell(SHEET_TABS["events"], idx, "H", "是")
                return

    def update_recommendation_status(self, recommendation_id: str, status: str) -> bool:
        rows = self.read_rows(SHEET_TABS["recommendations"])
        for idx, row in enumerate(rows, start=2):
            if row.get("推荐ID") == recommendation_id:
                self.update_cell(SHEET_TABS["recommendations"], idx, "M", status)
                return True
        return False


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _parse_local_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
