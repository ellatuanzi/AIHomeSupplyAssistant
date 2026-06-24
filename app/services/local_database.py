from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from app.config import get_settings
from app.models.inventory import InventoryItem
from app.services.sheet_schema import DEFAULT_INVENTORY_ROWS, HEADERS, SHEET_TABS
from app.utils.dates import now_local


@dataclass
class LocalDatabaseService:
    sheet_id: str | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        self.database_path = Path(settings.database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_tabs_and_headers()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tabs_and_headers(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sheet_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tab_name TEXT NOT NULL,
                    row_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sheet_rows_tab ON sheet_rows(tab_name, id)"
            )
        if not self.read_rows(SHEET_TABS["inventory"]):
            for row in DEFAULT_INVENTORY_ROWS:
                self.append_row(SHEET_TABS["inventory"], row)

    def read_rows(self, tab_name: str) -> list[dict[str, Any]]:
        self._ensure_known_tab(tab_name)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT row_json FROM sheet_rows WHERE tab_name = ? ORDER BY id",
                (tab_name,),
            ).fetchall()
        return [json.loads(row["row_json"]) for row in rows]

    def read_values(self, tab_name: str) -> list[list[Any]]:
        headers = self._headers(tab_name)
        values = [headers]
        for row in self.read_rows(tab_name):
            values.append([row.get(header, "") for header in headers])
        return values

    def append_row(self, tab_name: str, row: list[Any]) -> None:
        headers = self._headers(tab_name)
        row_dict = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
        }
        self.append_dict_row(tab_name, row_dict)

    def append_dict_row(self, tab_name: str, row: dict[str, Any]) -> None:
        self._ensure_known_tab(tab_name)
        now = now_local().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sheet_rows (tab_name, row_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (tab_name, json.dumps(row, ensure_ascii=False), now, now),
            )

    def update_cell(self, tab_name: str, row_number: int, column_letter: str, value: Any) -> None:
        headers = self._headers(tab_name)
        index = _column_index(column_letter)
        if index >= len(headers):
            return
        self.update_row_by_headers(tab_name, row_number, {headers[index]: value})

    def update_row_by_headers(self, tab_name: str, row_number: int, updates: dict[str, Any]) -> None:
        db_id = self._db_id_for_sheet_row(tab_name, row_number)
        if db_id is None:
            return
        now = now_local().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            current = conn.execute(
                "SELECT row_json FROM sheet_rows WHERE id = ?", (db_id,)
            ).fetchone()
            if not current:
                return
            row = json.loads(current["row_json"])
            row.update(updates)
            conn.execute(
                "UPDATE sheet_rows SET row_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(row, ensure_ascii=False), now, db_id),
            )

    def delete_rows(self, tab_name: str, row_numbers: list[int]) -> None:
        ids = [
            db_id
            for row_number in row_numbers
            if (db_id := self._db_id_for_sheet_row(tab_name, row_number)) is not None
        ]
        if not ids:
            return
        with self._connect() as conn:
            conn.executemany("DELETE FROM sheet_rows WHERE id = ?", [(db_id,) for db_id in ids])

    def get_inventory_items(self) -> list[InventoryItem]:
        items = []
        for row in self.read_rows(SHEET_TABS["inventory"]):
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

    def ensure_inventory_item(
        self,
        item_id: str,
        item_name: str,
        category: str = "未分类",
        preferred_brand: str = "",
        preferred_retailer: str = "",
        household_location: str = "",
        typical_quantity: str = "",
        reorder_threshold: str = "",
        urgency_default: str = "中",
        notes: str = "",
    ) -> InventoryItem:
        existing = self.find_inventory_item(item_id)
        if existing:
            return existing
        self.append_row(
            SHEET_TABS["inventory"],
            [
                item_id,
                item_name,
                category,
                preferred_brand,
                preferred_retailer,
                household_location,
                typical_quantity,
                reorder_threshold,
                urgency_default,
                notes,
            ],
        )
        return InventoryItem(
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

    def append_low_stock_event(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["events"], row)

    def recent_low_stock_event(
        self,
        item_id: str,
        source: str,
        within_minutes: int,
        location: str = "",
    ) -> dict[str, Any] | None:
        cutoff = now_local().replace(tzinfo=None) - timedelta(minutes=within_minutes)
        for row in reversed(self.read_rows(SHEET_TABS["events"])):
            if row.get("商品ID") != item_id or row.get("来源") != source:
                continue
            if location and row.get("位置", "") != location:
                continue
            recorded_at = _parse_local_datetime(row.get("记录时间", ""))
            if recorded_at and recorded_at >= cutoff:
                return row
        return None

    def item_locations(self, item_id: str) -> list[str]:
        rows = self.read_rows(SHEET_TABS["item_locations"])
        locations = [
            row.get("位置", "").strip()
            for row in rows
            if row.get("商品ID") == item_id and row.get("位置", "").strip()
        ]
        if locations:
            return _dedupe_strings(locations)

        item = self.find_inventory_item(item_id)
        if not item or not item.household_location:
            return []
        return _dedupe_strings(_split_locations(item.household_location))

    def ensure_item_location(
        self,
        item_id: str,
        item_name: str,
        location: str,
        source: str = "",
        note: str = "",
    ) -> None:
        if not location.strip():
            return
        normalized_location = location.strip().lower()
        for row in self.read_rows(SHEET_TABS["item_locations"]):
            if (
                row.get("商品ID") == item_id
                and row.get("位置", "").strip().lower() == normalized_location
            ):
                return
        self.append_row(
            SHEET_TABS["item_locations"],
            [
                f"loc_{item_id}_{len(self.item_locations(item_id)) + 1}",
                item_id,
                item_name,
                location.strip(),
                source,
                "已记录",
                note,
            ],
        )

    def append_task(self, row: list[Any]) -> None:
        self.append_row(SHEET_TABS["tasks"], row)

    def complete_open_task(
        self,
        item_id: str,
        target_location: str = "",
        task_type: str = "搬运补货",
    ) -> dict[str, Any] | None:
        rows = self.read_rows(SHEET_TABS["tasks"])
        for idx, row in reversed(list(enumerate(rows, start=2))):
            if row.get("商品ID") != item_id:
                continue
            if task_type and row.get("任务类型") != task_type:
                continue
            if target_location and row.get("目标位置") != target_location:
                continue
            if row.get("状态", "").strip() in {"完成", "已完成"}:
                continue
            self.update_cell(SHEET_TABS["tasks"], idx, "C", now_local().strftime("%Y-%m-%d %H:%M:%S"))
            self.update_cell(SHEET_TABS["tasks"], idx, "I", "完成")
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

    def tasks(self) -> list[dict[str, Any]]:
        return self.read_rows(SHEET_TABS["tasks"])

    def pending_tasks(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.tasks()
            if row.get("状态", "").strip() not in {"完成", "已完成"}
        ]

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

    def _headers(self, tab_name: str) -> list[str]:
        self._ensure_known_tab(tab_name)
        return HEADERS[tab_name]

    def _ensure_known_tab(self, tab_name: str) -> None:
        if tab_name not in HEADERS:
            raise RuntimeError(f"未知数据表：{tab_name}")

    def _db_id_for_sheet_row(self, tab_name: str, row_number: int) -> int | None:
        if row_number < 2:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM sheet_rows WHERE tab_name = ? ORDER BY id",
                (tab_name,),
            ).fetchall()
        index = row_number - 2
        if index >= len(rows):
            return None
        return int(rows[index]["id"])


def _column_index(column_letter: str) -> int:
    result = 0
    for char in column_letter.upper():
        if not char.isalpha():
            continue
        result = result * 26 + (ord(char) - ord("A") + 1)
    return max(result - 1, 0)


def _parse_local_datetime(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _split_locations(value: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"[,，、/;；\n]+", value) if part.strip()]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
