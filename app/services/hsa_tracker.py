from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from googleapiclient.discovery import build

from app.config import get_settings
from app.services.google_auth import BASE_SCOPES, DRIVE_SCOPES, get_google_credentials
from app.services.google_drive import GoogleDriveService
from app.utils.dates import today_local_string
from app.utils.ids import new_id


HSA_TAB_NAME = "HSA候选"
HSA_HEADERS = [
    "记录ID",
    "日期",
    "来源",
    "来源ID",
    "商品名称",
    "商品标题",
    "店铺",
    "价格",
    "数量",
    "收货地址",
    "地址分类",
    "HSA判断",
    "判断理由",
    "置信度",
    "收据链接",
    "备注",
]


@dataclass
class HsaCandidate:
    is_candidate: bool
    reason: str
    confidence: int


@dataclass
class HsaTrackerService:
    drive: GoogleDriveService | None = None
    sheet_id: str | None = None

    def __post_init__(self) -> None:
        self.settings = get_settings()
        self.drive = self.drive or GoogleDriveService()
        self.sheet_id = self.sheet_id or self.settings.hsa_sheet_id or ""
        self.client = build(
            "sheets",
            "v4",
            credentials=get_google_credentials(BASE_SCOPES + DRIVE_SCOPES),
        )

    def classify_order(self, order: dict[str, Any]) -> HsaCandidate:
        return classify_hsa_candidate(order, self.settings.hsa_keywords)

    def has_hsa_candidate(self, orders: list[dict[str, Any]]) -> bool:
        return any(self.classify_order(order).is_candidate for order in orders)

    def upload_receipt_to_hsa_folder(
        self, filename: str, content_type: str, data: bytes
    ) -> str:
        parent_folder_id = self._hsa_parent_folder_id()
        return self.drive.upload_receipt(filename, content_type, data, parent_folder_id)

    def append_if_candidate(
        self,
        *,
        source: str,
        source_id: str,
        order: dict[str, Any],
        receipt_link: str = "",
        note: str = "",
    ) -> bool:
        candidate = self.classify_order(order)
        if not candidate.is_candidate:
            return False
        self.ensure_hsa_sheet()
        if self._source_exists(source_id):
            return False
        self._append_row(
            [
                new_id("hsa"),
                today_local_string(),
                source,
                source_id,
                order.get("item_name", ""),
                order.get("product_title", ""),
                order.get("retailer", ""),
                order.get("price", ""),
                order.get("quantity", ""),
                order.get("shipping_address", ""),
                order.get("address_category", ""),
                "可能 HSA/FSA，需人工确认",
                candidate.reason,
                candidate.confidence,
                receipt_link,
                note,
            ]
        )
        return True

    def ensure_hsa_sheet(self) -> str:
        if not self.sheet_id:
            parent_folder_id = self._main_sheet_parent_folder_id()
            self.sheet_id = self.drive.find_or_create_spreadsheet(
                self.settings.hsa_sheet_name, parent_folder_id
            )
        spreadsheet = self.client.spreadsheets().get(spreadsheetId=self.sheet_id).execute()
        sheets = spreadsheet.get("sheets", [])
        existing_tabs = {sheet["properties"]["title"] for sheet in sheets}
        requests = []
        if HSA_TAB_NAME not in existing_tabs:
            if len(sheets) == 1 and sheets[0]["properties"]["title"] == "Sheet1":
                requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheets[0]["properties"]["sheetId"],
                                "title": HSA_TAB_NAME,
                            },
                            "fields": "title",
                        }
                    }
                )
            else:
                requests.append({"addSheet": {"properties": {"title": HSA_TAB_NAME}}})
        if requests:
            self.client.spreadsheets().batchUpdate(
                spreadsheetId=self.sheet_id, body={"requests": requests}
            ).execute()

        values = self._read_values()
        if not values:
            self._append_row(HSA_HEADERS)
        else:
            existing_headers = values[0]
            missing_headers = [header for header in HSA_HEADERS if header not in existing_headers]
            if missing_headers:
                headers = existing_headers + missing_headers
                self.client.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=f"{HSA_TAB_NAME}!A1:{_column_name(len(headers))}1",
                    valueInputOption="USER_ENTERED",
                    body={"values": [headers]},
                ).execute()
        return self.sheet_id

    def _hsa_parent_folder_id(self) -> str:
        if self.sheet_id or self.settings.hsa_sheet_id:
            return self.drive.get_parent_folder_id(self.sheet_id or self.settings.hsa_sheet_id)
        return self._main_sheet_parent_folder_id()

    def _main_sheet_parent_folder_id(self) -> str:
        if not self.settings.google_sheet_id:
            return ""
        return self.drive.get_parent_folder_id(self.settings.google_sheet_id)

    def _read_values(self) -> list[list[Any]]:
        return (
            self.client.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=f"{HSA_TAB_NAME}!A:Z")
            .execute()
            .get("values", [])
        )

    def _append_row(self, row: list[Any]) -> None:
        self.client.spreadsheets().values().append(
            spreadsheetId=self.sheet_id,
            range=f"{HSA_TAB_NAME}!A:Z",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def _source_exists(self, source_id: str) -> bool:
        rows = self._read_values()
        if not rows:
            return False
        headers = rows[0]
        if "来源ID" not in headers:
            return False
        source_index = headers.index("来源ID")
        return any(len(row) > source_index and row[source_index] == source_id for row in rows[1:])


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def classify_hsa_candidate(order: dict[str, Any], keywords_value: str) -> HsaCandidate:
    text = " ".join(
        str(order.get(key, "")) for key in ["item_name", "product_title", "brand", "category", "note"]
    ).lower()
    keywords = [
        keyword.strip().lower()
        for keyword in keywords_value.split(",")
        if keyword.strip()
    ]
    matches = [keyword for keyword in keywords if keyword in text]
    if not matches:
        return HsaCandidate(False, "", 0)
    confidence = 80 if len(matches) >= 2 else 68
    return HsaCandidate(
        True,
        f"命中关键词：{', '.join(matches[:5])}。需要人工确认是否符合 HSA/FSA 报销规则。",
        confidence,
    )
