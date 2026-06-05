from html import escape
import json
import re
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.agents.daily_replenishment_agent import DailyReplenishmentAgent
from app.agents.daily_send_guard import DailySendGuard
from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.agents.receipt_analysis_agent import ReceiptAnalysisAgent
from app.models.events import LowStockEventCreate
from app.models.recommendations import RecommendationStatusUpdate
from app.config import get_settings
from app.services.google_sheets import GoogleSheetsService
from app.utils.dates import now_local_string
from app.utils.ids import new_id

router = APIRouter()


COMMON_ITEM_ALIASES = {
    "toilet_paper": [
        "手纸",
        "手指",
        "卫生纸",
        "卫生只",
        "卫生巾",
        "厕纸",
        "厕只",
        "卷纸",
        "纸巾卷",
        "bath tissue",
        "toilet paper",
        "tp",
    ],
    "paper_towels": [
        "厨房纸",
        "厨房纸巾",
        "厨纸",
        "擦手纸",
        "paper towel",
        "paper towels",
        "kitchen paper",
        "bounty",
    ],
    "napkin": [
        "napkin",
        "napkins",
        "餐巾",
        "餐巾纸",
        "饭巾",
        "饭巾纸",
        "餐纸",
        "paper napkin",
        "paper napkins",
    ],
    "wet_wipes": [
        "湿纸巾",
        "湿巾",
        "擦手湿巾",
        "婴儿湿巾",
        "baby wipes",
        "wet wipes",
        "wipe",
        "wipes",
        "flushable wipes",
    ],
    "trash_bags": [
        "垃圾袋",
        "垃圾带",
        "垃圾桶袋",
        "trash bag",
        "trash bags",
        "garbage bag",
        "garbage bags",
        "glad bag",
    ],
    "detergent": [
        "洗衣液",
        "洗衣粉",
        "洗衣剂",
        "洗衣精",
        "laundry detergent",
        "detergent",
        "tide",
        "persil",
    ],
    "pet_food": [
        "宠物粮",
        "狗粮",
        "猫粮",
        "宠物食物",
        "pet food",
        "dog food",
        "cat food",
        "kibble",
    ],
    "body_lotion": [
        "身体乳",
        "身体露",
        "润肤乳",
        "润肤露",
        "润肤霜",
        "body lotion",
        "lotion",
        "moisturizer",
        "moisturiser",
        "cream",
        "cerave",
        "cetaphil",
    ],
    "swiffer_wet_cloth": [
        "swiffer",
        "湿拖布",
        "湿拖把布",
        "拖地湿巾",
        "拖把湿巾",
        "wet cloth",
        "wet jet",
        "wetjet",
        "mopping cloth",
        "floor wipes",
    ],
    "pencil": ["铅笔", "自动铅笔", "pencil", "pencils", "mechanical pencil", "ticonderoga"],
    "eraser": ["橡皮", "像皮", "橡皮擦", "eraser", "erasers"],
    "kids_toothpaste": [
        "儿童牙膏",
        "小孩牙膏",
        "孩子牙膏",
        "牙膏",
        "tom's",
        "toms",
        "tom's of maine",
        "tom's maine",
        "strawberry toothpaste",
        "kid toothpaste",
        "kids toothpaste",
        "children toothpaste",
    ],
    "kids_electric_toothbrush": [
        "儿童牙刷",
        "小孩牙刷",
        "孩子牙刷",
        "电动牙刷",
        "儿童电动牙刷",
        "electric toothbrush",
        "kids electric toothbrush",
        "children electric toothbrush",
        "sonic toothbrush",
        "oral b kids",
        "oral-b kids",
    ],
}


COMMON_ITEM_NAMES = {
    "toilet_paper": "Toilet Paper",
    "paper_towels": "Paper Towels",
    "napkin": "Napkin",
    "wet_wipes": "Wet Wipes",
    "trash_bags": "Trash Bags",
    "detergent": "Laundry Detergent",
    "pet_food": "Pet Food",
    "body_lotion": "Body Lotion",
    "swiffer_wet_cloth": "Swiffer Wet Cloth",
    "pencil": "Pencil",
    "eraser": "Eraser",
    "kids_toothpaste": "Kids Toothpaste",
    "kids_electric_toothbrush": "Kids Electric Toothbrush",
}


LOCATION_DETAIL_OPTIONS = {
    "车库": ["货架", "收纳柜", "门口备用区"],
    "一层": ["玄关柜", "客厅柜", "储物柜"],
    "二层餐厅": ["餐边柜", "抽屉", "台面"],
    "二层厨房": ["水槽下", " pantry", "橱柜", "岛台抽屉"],
    "二层客卧": ["衣柜", "床头柜", "收纳箱"],
    "二层洗手间": ["洗手台下", "镜柜", "马桶旁"],
    "主卧": ["收纳柜", "电视柜", "床头柜", "衣柜"],
    "主卧洗手间": ["洗手台下", "镜柜", "马桶旁", "淋浴间旁"],
    "汤圆房间": ["书桌", "衣柜", "床头柜", "收纳柜"],
    "汤圆洗手间": ["洗手台下", "镜柜", "马桶旁"],
    "三层收纳柜": ["上层", "中层", "下层"],
}


LOCATION_ALIASES = {
    "车库": ["garage"],
    "二层餐厅": ["餐厅", "二楼餐厅", "2层餐厅", "2楼餐厅"],
    "二层厨房": ["厨房", "二楼厨房", "2层厨房", "2楼厨房"],
    "二层洗手间": ["二楼洗手间", "2层洗手间", "2楼洗手间", "二楼厕所", "二楼卫生间"],
    "主卧": ["master bedroom", "主卧室"],
    "主卧洗手间": ["主卧厕所", "主卧卫生间", "主卫", "master bathroom"],
    "汤圆房间": ["汤圆屋", "汤圆卧室", "tangyuan room"],
    "汤圆洗手间": ["汤圆厕所", "汤圆卫生间", "tangyuan bathroom"],
    "三层收纳柜": ["3层", "三层", "3楼", "三楼", "顶楼", "三层柜", "三层收纳"],
}


class VoiceCommandRequest(BaseModel):
    text: str
    dry_run: bool = False


class ChatMessageRequest(BaseModel):
    message: str
    dry_run: bool = False


def sheets_service() -> GoogleSheetsService:
    try:
        return GoogleSheetsService()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _location_options(item_locations: list[str]) -> list[str]:
    options = _split_location_string(get_settings().household_locations) + item_locations
    seen = set()
    result = []
    for option in options:
        key = option.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(option.strip())
    return result


def _select_options(options: list[str], selected: str = "") -> str:
    selected = selected.strip()
    has_selected = selected and any(option == selected for option in options)
    rows = []
    if selected and not has_selected:
        rows.append(f'<option value="__manual__" selected>其他/新增位置</option>')
    for option in options:
        selected_attr = " selected" if option == selected else ""
        rows.append(f'<option value="{escape(option)}"{selected_attr}>{escape(option)}</option>')
    if not selected or has_selected:
        rows.append('<option value="__manual__">其他/新增位置</option>')
    return "\n".join(rows)


def _area_options(selected_area: str = "") -> str:
    options = _location_options([])
    selected = selected_area.strip()
    has_selected = selected and any(option == selected for option in options)
    rows = []
    if selected and not has_selected:
        rows.append('<option value="__manual__" selected>其他/新增区域</option>')
    for option in options:
        selected_attr = " selected" if option == selected else ""
        rows.append(f'<option value="{escape(option)}"{selected_attr}>{escape(option)}</option>')
    if not selected or has_selected:
        rows.append('<option value="__manual__">其他/新增区域</option>')
    return "\n".join(rows)


def _detail_options(area: str, selected_detail: str = "") -> str:
    options = LOCATION_DETAIL_OPTIONS.get(area, [])
    selected = selected_detail.strip()
    has_selected = selected and any(option == selected for option in options)
    rows = ['<option value="">不指定具体位置</option>']
    if selected and not has_selected:
        rows.append('<option value="__manual__" selected>其他/新增具体位置</option>')
    for option in options:
        selected_attr = " selected" if option == selected else ""
        rows.append(f'<option value="{escape(option)}"{selected_attr}>{escape(option)}</option>')
    if not selected or has_selected:
        rows.append('<option value="__manual__">其他/新增具体位置</option>')
    return "\n".join(rows)


def _location_picker_html(base_id: str, label: str, selected_location: str = "") -> str:
    area, detail = _split_location_parts(selected_location)
    safe_selected = escape(selected_location)
    safe_area_manual = escape(area if area and area not in _location_options([]) else "")
    safe_detail_manual = escape(detail if detail and detail not in LOCATION_DETAIL_OPTIONS.get(area, []) else "")
    return f"""
            <label>{escape(label)}</label>
            <div class="location-picker" data-location-picker="{escape(base_id)}">
              <select id="{escape(base_id)}_area_select" onchange="syncLocation('{escape(base_id)}')">
                {_area_options(area)}
              </select>
              <input class="manual-location" id="{escape(base_id)}_area_manual" value="{safe_area_manual}" placeholder="输入新区域" oninput="syncLocation('{escape(base_id)}')">
              <select id="{escape(base_id)}_detail_select" onchange="syncLocation('{escape(base_id)}')">
                {_detail_options(area, detail)}
              </select>
              <input class="manual-location" id="{escape(base_id)}_detail_manual" value="{safe_detail_manual}" placeholder="输入具体位置，例如：收纳柜、电视柜" oninput="syncLocation('{escape(base_id)}')">
              <input type="hidden" id="{escape(base_id)}" name="{escape(base_id)}" value="{safe_selected}">
            </div>
    """


def _split_location_parts(location: str) -> tuple[str, str]:
    if " - " in location:
        area, detail = location.split(" - ", 1)
        return area.strip(), detail.strip()
    return location.strip(), ""


def _split_location_string(value: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"[,，、/;；\n]+", value) if part.strip()]


def _known_location_names() -> list[str]:
    names = [alias for alias, _canonical in _location_lookup()]
    return sorted({name.strip() for name in names if name.strip()}, key=len, reverse=True)


def _location_lookup() -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    for location in _location_options([]):
        names.append((location, location))
    for area, details in LOCATION_DETAIL_OPTIONS.items():
        names.append((area, area))
        for detail in details:
            names.append((f"{area} - {detail}", f"{area} - {detail}"))
            names.append((detail, detail))
    for canonical, aliases in LOCATION_ALIASES.items():
        names.append((canonical, canonical))
        for alias in aliases:
            names.append((alias, canonical))

    deduped: dict[str, str] = {}
    for alias, canonical in names:
        alias = alias.strip()
        canonical = canonical.strip()
        if alias:
            deduped[alias.lower()] = canonical
    return sorted(
        [(alias, canonical) for alias, canonical in deduped.items()],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )


def _find_location_in_text(text: str) -> str:
    normalized = text.lower()
    for alias, canonical in _location_lookup():
        if alias.lower() in normalized:
            return canonical
    return ""


def _locations_in_text(text: str) -> list[str]:
    normalized = text.lower()
    matches = []
    for alias, canonical in _location_lookup():
        start = normalized.find(alias.lower())
        if start >= 0:
            matches.append((start, -len(alias), canonical))
    by_start = {}
    for start, negative_length, location_name in sorted(matches):
        if start not in by_start:
            by_start[start] = (negative_length, location_name)
    result = []
    seen = set()
    for _, value in sorted(by_start.items()):
        location = value[1]
        if location not in seen:
            seen.add(location)
            result.append(location)
    return result


def _find_source_target_locations(text: str) -> tuple[str, str]:
    source = ""
    target = ""
    ba_match = re.search(r"把(.+?)的.+?(?:拿|搬|移|放|补|带)?到(.+)", text)
    if ba_match:
        source = _find_location_in_text(ba_match.group(1))
        target = _find_location_in_text(ba_match.group(2))
    from_to_match = re.search(r"从(.+?)(?:拿|搬|移|放|补|带)?到(.+)", text)
    if from_to_match and not (source and target):
        source = _find_location_in_text(from_to_match.group(1))
        target = _find_location_in_text(from_to_match.group(2))
    if not source:
        source_match = re.search(r"(?:从|来源|源位置)(.+?)(?:到|去|拿|搬|移|补|$)", text)
        if source_match:
            source = _find_location_in_text(source_match.group(1))
    if not target:
        target_match = re.search(r"(?:到|去|目标|放到|拿到)(.+)", text)
        if target_match:
            target = _find_location_in_text(target_match.group(1))
    locations = _locations_in_text(text)
    if not source and len(locations) >= 2:
        source = locations[0]
    if not target:
        target = locations[-1] if locations else _find_location_in_text(text)
    return source, target


def _match_voice_item(text: str, inventory: list[Any]) -> Any | None:
    normalized = text.lower().replace(" ", "").replace("_", "")
    best = None
    best_score = 0
    for item in inventory:
        candidates = [
            item.item_id,
            item.item_name,
            item.category,
            item.preferred_brand,
            item.typical_quantity,
        ] + COMMON_ITEM_ALIASES.get(item.item_id, [])
        score = 0
        for candidate in candidates:
            candidate_key = str(candidate).lower().replace(" ", "").replace("_", "")
            if candidate_key and candidate_key in normalized:
                score = max(score, len(candidate_key))
        if score > best_score:
            best = item
            best_score = score
    return best


def _match_common_alias_item_id(text: str) -> str:
    normalized = text.lower().replace(" ", "").replace("_", "")
    best_item_id = ""
    best_score = 0
    for item_id, aliases in COMMON_ITEM_ALIASES.items():
        candidates = [item_id, COMMON_ITEM_NAMES.get(item_id, item_id)] + aliases
        for candidate in candidates:
            candidate_key = str(candidate).lower().replace(" ", "").replace("_", "")
            if candidate_key and candidate_key in normalized and len(candidate_key) > best_score:
                best_item_id = item_id
                best_score = len(candidate_key)
    return best_item_id


def _create_common_alias_inventory_item(
    sheets: Any,
    item_id: str,
    command: str,
    location: str = "",
    dry_run: bool = False,
) -> Any | None:
    if not item_id:
        return None
    item_name = COMMON_ITEM_NAMES.get(item_id, item_id.replace("_", " ").title())
    if dry_run:
        return SimpleNamespace(
            item_id=item_id,
            item_name=item_name,
            category="未分类",
            preferred_brand="",
            preferred_retailer="",
            household_location=location,
            typical_quantity="",
            reorder_threshold="",
            urgency_default="中",
            notes=f"自动从常用别名创建，原始指令：{command}",
        )
    if not hasattr(sheets, "ensure_inventory_item"):
        return None
    return sheets.ensure_inventory_item(
        item_id=item_id,
        item_name=item_name,
        category="未分类",
        household_location=location,
        urgency_default="中",
        notes=f"自动从常用别名创建，原始指令：{command}",
    )


def _slugify_item_name(name: str) -> str:
    cleaned = name.strip().lower()
    cleaned = re.sub(r"['’]", "", cleaned)
    cleaned = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "unknown_item"
    return f"custom_{cleaned}"[:80]


def _extract_unknown_item_name(text: str) -> str:
    candidate = text.strip()
    for location in _known_location_names():
        candidate = candidate.replace(location, " ")
    candidate = re.sub(
        r"(低库存|没了|没有了|没有|空了|用完了|用完|快没了|快用完了|"
        r"out of stock|out of|empty|low stock|low|"
        r"创建|完成|任务|待办|todo|to do|把|从|拿到|搬到|移到|放到|补到|到)",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip(" ，。,.")
    if "的" in candidate:
        parts = [part.strip() for part in candidate.split("的") if part.strip()]
        if parts:
            candidate = parts[-1]
    return candidate[:80].strip()


def _create_unknown_inventory_item(
    sheets: Any,
    command: str,
    location: str = "",
) -> Any | None:
    item_name = _extract_unknown_item_name(command)
    if not item_name:
        return None
    item_id = _slugify_item_name(item_name)
    if hasattr(sheets, "ensure_inventory_item"):
        return sheets.ensure_inventory_item(
            item_id=item_id,
            item_name=item_name,
            category="未分类",
            household_location=location,
            urgency_default="中",
            notes=f"自动从语音/Chat 创建，原始指令：{command}",
        )
    return None


def _voice_action(text: str) -> str:
    lowered = text.lower()
    if any(
        token in lowered
        for token in [
            "完成",
            "做好",
            "做完",
            "已拿到",
            "已经拿到",
            "已搬到",
            "已经搬到",
            "已放到",
            "已经放到",
            "已移到",
            "已经移到",
            "已补到",
            "已经补到",
            "done",
            "finish",
            "finished",
        ]
    ):
        return "complete_task"
    if any(token in lowered for token in ["任务", "todo", "to do", "待办", "拿到", "搬到", "移到", "补到"]):
        return "create_task"
    if any(token in lowered for token in ["没有", "没了", "空了", "用完", "out of", "empty"]):
        return "empty_stock"
    return "low_stock"


def _voice_failure_result(message: str, command: str = "", action: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "updated_google_sheet": False,
        "status": "未更新",
        "action": action,
        "item_id": "",
        "item_name": "",
        "location": "",
        "source_location": "",
        "target_location": "",
        "message": message,
        "recognized_text": command,
    }


def _mark_voice_success(result: dict[str, Any], updated: bool = True) -> dict[str, Any]:
    result["ok"] = True
    result["updated_google_sheet"] = updated
    return result


def _handle_voice_command(text: str, dry_run: bool = False) -> dict[str, Any]:
    command = text.strip()
    if not command:
        return _voice_failure_result("没有收到语音文字，所以没有更新 Google Sheet。")

    try:
        sheets = sheets_service()
        inventory = sheets.get_inventory_items()
    except Exception as exc:
        return _voice_failure_result(f"无法读取 Google Sheet，所以没有更新：{exc}", command)

    action = _voice_action(command)
    source_location, target_location = _find_source_target_locations(command)
    location = target_location or source_location or _find_location_in_text(command)
    note = f"语音指令：{command}"
    alias_item_id = _match_common_alias_item_id(command)
    item = _match_voice_item(command, inventory)
    created_unknown_item = False
    should_prefer_common_alias = bool(
        alias_item_id and (not item or item.item_id == alias_item_id or str(item.item_id).startswith("custom_"))
    )
    if should_prefer_common_alias:
        existing_alias_item = (
            sheets.find_inventory_item(alias_item_id)
            if hasattr(sheets, "find_inventory_item")
            else None
        )
        if existing_alias_item:
            item = existing_alias_item
        elif not item or str(item.item_id).startswith("custom_"):
            try:
                item = _create_common_alias_inventory_item(
                    sheets,
                    alias_item_id,
                    command,
                    location,
                    dry_run=dry_run,
                )
                created_unknown_item = bool(item) and not dry_run
            except Exception as exc:
                return _voice_failure_result(f"无法自动创建常用商品，所以没有更新：{exc}", command, action)
    if not item:
        try:
            item = (
                SimpleNamespace(
                    item_id=_slugify_item_name(_extract_unknown_item_name(command)),
                    item_name=_extract_unknown_item_name(command),
                    urgency_default="中",
                )
                if dry_run
                else _create_unknown_inventory_item(sheets, command, location)
            )
            created_unknown_item = bool(item) and not dry_run
        except Exception as exc:
            return _voice_failure_result(f"无法自动创建未知商品，所以没有更新：{exc}", command, action)
    if not item:
        return _voice_failure_result(
            f"没有从语音中识别到商品，也无法抽取新商品名，所以没有更新 Google Sheet。听到的是：{command}",
            command,
            action,
        )

    if dry_run:
        return {
            "ok": True,
            "updated_google_sheet": False,
            "status": "预览",
            "action": action,
            "item_id": item.item_id,
            "item_name": item.item_name,
            "location": location,
            "source_location": source_location,
            "target_location": target_location,
            "message": "这是预览，没有更新 Google Sheet。",
            "recognized_text": command,
            "created_unknown_item": created_unknown_item,
        }

    try:
        if action in {"low_stock", "empty_stock"}:
            status = "empty" if action == "empty_stock" else "low"
            urgency = "紧急" if status == "empty" else item.urgency_default or "中"
            status_note = "已经没有库存" if status == "empty" else "低库存"
            combined_note = "。".join(part for part in [status_note, f"位置：{location}" if location else "", note] if part)
            payload = LowStockEventCreate(
                item_id=item.item_id,
                source="语音",
                urgency=urgency,
                note=combined_note,
                location=location,
            )
            result = create_low_stock_event(payload)
            result.update(
                {
                    "action": action,
                    "location": location,
                    "source_location": source_location,
                    "target_location": target_location,
                    "recognized_text": command,
                    "created_unknown_item": created_unknown_item,
                }
            )
            if created_unknown_item:
                result["message"] = f"{result.get('message', '')} 已自动加入库存清单，分类为未分类。"
            return _mark_voice_success(result, updated=result.get("status") != "已存在")

        sheets.ensure_item_location(item.item_id, item.item_name, source_location, "语音")
        sheets.ensure_item_location(item.item_id, item.item_name, target_location or location, "语音")
    except Exception as exc:
        return _voice_failure_result(f"写入 Google Sheet 失败，所以没有更新：{exc}", command, action)

    if action == "complete_task":
        try:
            completed = sheets.complete_open_task(item.item_id, target_location=target_location or location)
        except Exception as exc:
            return _voice_failure_result(f"更新待办任务失败，所以没有更新：{exc}", command, action)
        result = {
            "ok": bool(completed),
            "updated_google_sheet": bool(completed),
            "status": "已完成" if completed else "未找到",
            "action": action,
            "item_id": item.item_id,
            "item_name": item.item_name,
            "location": target_location or location,
            "source_location": source_location,
            "target_location": target_location,
            "message": (
                f"{item.item_name} 的待办任务已完成。"
                if completed
                else f"没有找到 {item.item_name} 的待完成任务，所以没有更新。"
            ),
            "recognized_text": command,
            "created_unknown_item": created_unknown_item,
        }
        if created_unknown_item:
            result["message"] = f"{result['message']} 已自动加入库存清单，分类为未分类。"
        return result

    task_id = new_id("task")
    try:
        sheets.append_task(
            [
                task_id,
                now_local_string(),
                "",
                item.item_id,
                item.item_name,
                "搬运补货",
                source_location,
                target_location or location,
                "待办",
                "语音",
                note,
            ]
        )
    except Exception as exc:
        return _voice_failure_result(f"创建待办任务失败，所以没有更新：{exc}", command, action)
    result = {
        "status": "已创建",
        "action": action,
        "task_id": task_id,
        "item_id": item.item_id,
        "item_name": item.item_name,
        "location": target_location or location,
        "source_location": source_location,
        "target_location": target_location,
        "message": f"已创建任务：把 {item.item_name} 从 {source_location or '未指定位置'} 拿到 {target_location or location or '未指定位置'}。",
        "recognized_text": command,
        "created_unknown_item": created_unknown_item,
    }
    if created_unknown_item:
        result["message"] = f"{result['message']} 已自动加入库存清单，分类为未分类。"
    return _mark_voice_success(result)


def _task_summary(tasks: list[dict[str, Any]], limit: int = 8) -> str:
    if not tasks:
        return "当前没有待办任务。"
    lines = []
    for task in tasks[:limit]:
        item_name = task.get("商品名称", "未命名商品")
        task_type = task.get("任务类型", "待办")
        source = task.get("来源位置", "")
        target = task.get("目标位置", "")
        route = f"{source} -> {target}" if source or target else ""
        lines.append(" - ".join(part for part in [task_type, item_name, route] if part))
    if len(tasks) > limit:
        lines.append(f"还有 {len(tasks) - limit} 个待办未显示。")
    return "\n".join(lines)


def _event_summary(events: list[dict[str, Any]], limit: int = 8) -> str:
    if not events:
        return "当前没有未处理的低库存记录。"
    lines = []
    for event in events[:limit]:
        item_name = event.get("商品名称", "未命名商品")
        location = event.get("位置", "")
        urgency = event.get("紧急度", "")
        lines.append(" - ".join(part for part in [item_name, location, urgency] if part))
    if len(events) > limit:
        lines.append(f"还有 {len(events) - limit} 条低库存记录未显示。")
    return "\n".join(lines)


def _recommendation_summary(recommendations: list[dict[str, Any]], limit: int = 8) -> str:
    pending = [
        row
        for row in recommendations
        if row.get("补货状态", "").strip() not in {"已下单", "已购买", "已处理", "跳过"}
    ]
    if not pending:
        return "当前没有待确认的补货推荐。"
    lines = []
    for rec in pending[:limit]:
        item_name = rec.get("商品名称", "未命名商品")
        product = rec.get("推荐商品", "")
        retailer = rec.get("推荐店铺", "")
        price = rec.get("预估价格", "")
        lines.append(" - ".join(part for part in [item_name, product, retailer, price] if part))
    if len(pending) > limit:
        lines.append(f"还有 {len(pending) - limit} 条推荐未显示。")
    return "\n".join(lines)


def _inventory_answer(message: str, sheets: GoogleSheetsService) -> str | None:
    item = _match_voice_item(message, sheets.get_inventory_items())
    if not item:
        return None
    lowered = message.lower()
    if any(token in message for token in ["哪里", "位置", "放哪", "放在"]) or "where" in lowered:
        locations = sheets.item_locations(item.item_id)
        if locations:
            return f"{item.item_name} 记录的位置：{', '.join(locations)}。"
        return f"{item.item_name} 暂时没有记录具体位置。"
    if any(token in message for token in ["偏好", "品牌", "店铺", "规格", "阈值"]) or any(
        token in lowered for token in ["brand", "store", "retailer", "threshold", "size"]
    ):
        details = [
            f"商品：{item.item_name}",
            f"分类：{item.category or '未填'}",
            f"偏好品牌：{item.preferred_brand or '未填'}",
            f"偏好店铺：{item.preferred_retailer or '未填'}",
            f"常购规格：{item.typical_quantity or '未填'}",
            f"补货阈值：{item.reorder_threshold or '未填'}",
            f"默认紧急度：{item.urgency_default or '中'}",
        ]
        return "\n".join(details)
    return None


def _is_update_message(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in [
            "低库存",
            "没了",
            "没有",
            "空了",
            "用完",
            "out of",
            "empty",
            "low stock",
            "任务",
            "todo",
            "to do",
            "待办",
            "拿到",
            "搬到",
            "移到",
            "完成",
            "done",
            "finished",
        ]
    )


def _is_read_query(message: str) -> bool:
    lowered = message.lower()
    return any(token in message for token in ["哪些", "什么", "现在", "当前", "查看", "查询", "列出"]) or any(
        token in lowered for token in ["what", "which", "show", "list", "where", "?"]
    )


def _handle_chat_message(message: str, dry_run: bool = False) -> dict[str, Any]:
    text = message.strip()
    if not text:
        return {"ok": False, "message": "请输入问题或指令。", "updated_google_sheet": False}

    try:
        sheets = sheets_service()
        if any(token in text.lower() for token in ["todo", "to do", "task"]) or any(
            token in text for token in ["待办", "任务", "要做"]
        ) and _is_read_query(text):
            return {
                "ok": True,
                "message": _task_summary(sheets.pending_tasks()),
                "updated_google_sheet": False,
            }
        if (
            any(token in text for token in ["低库存", "缺货", "没处理"])
            or "low stock" in text.lower()
        ) and _is_read_query(text):
            return {
                "ok": True,
                "message": _event_summary(sheets.unresolved_events()),
                "updated_google_sheet": False,
            }
        if (
            any(token in text for token in ["推荐", "要买", "补货"])
            or any(
            token in text.lower() for token in ["recommend", "buy", "restock"]
            )
        ) and _is_read_query(text):
            return {
                "ok": True,
                "message": _recommendation_summary(sheets.recommendations()),
                "updated_google_sheet": False,
            }
        inventory_answer = _inventory_answer(text, sheets)
        if inventory_answer:
            return {"ok": True, "message": inventory_answer, "updated_google_sheet": False}
        if _is_update_message(text):
            result = _handle_voice_command(text, dry_run=dry_run)
            return {
                "ok": result.get("ok", False),
                "message": result.get("message", "已处理。"),
                "updated_google_sheet": result.get("updated_google_sheet", False),
                "action": result.get("action", ""),
                "item_name": result.get("item_name", ""),
                "location": result.get("location", ""),
            }
        return {
            "ok": True,
            "message": (
                "我可以回答：待办列表、低库存记录、补货推荐、商品位置/偏好；"
                "也可以执行：记录低库存、创建待办、完成待办。"
            ),
            "updated_google_sheet": False,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"无法读取 Google Sheet：{exc}",
            "updated_google_sheet": False,
        }


def _chat_state() -> dict[str, Any]:
    sheets = sheets_service()
    tasks = sheets.pending_tasks()
    events = sheets.unresolved_events()
    recommendations = [
        row
        for row in sheets.recommendations()
        if row.get("补货状态", "").strip() not in {"已下单", "已购买", "已处理", "跳过"}
    ]
    return {
        "pending_tasks": tasks,
        "unresolved_events": events,
        "pending_recommendations": recommendations,
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/items")
def list_items() -> list[dict[str, str]]:
    sheets = sheets_service()
    return [item.model_dump() for item in sheets.get_inventory_items()]


@router.get("/items/{item_id}/locations")
def list_item_locations(item_id: str) -> dict[str, object]:
    sheets = sheets_service()
    item = sheets.find_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{item_id}")
    return {"item_id": item.item_id, "item_name": item.item_name, "locations": sheets.item_locations(item_id)}


@router.post("/items/{item_id}/locations")
def add_item_location(
    item_id: str,
    location: str = Query(...),
    note: str = Query(default=""),
) -> dict[str, str]:
    sheets = sheets_service()
    item = sheets.find_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{item_id}")
    sheets.ensure_item_location(item.item_id, item.item_name, location, "API", note)
    return {"status": "已记录", "item_id": item.item_id, "location": location}


@router.get("/chat", response_class=HTMLResponse)
def chat_entry() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>家庭补货 Chat</title>
            <style>
              :root { color-scheme: light; }
              body {
                margin: 0;
                background: #f5f5f1;
                color: #1f2933;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }
              main {
                max-width: 760px;
                margin: 0 auto;
                padding: 20px;
              }
              h1 {
                font-size: 28px;
                margin: 10px 0 4px;
              }
              .subtle {
                margin: 0 0 18px;
                color: #667085;
                line-height: 1.45;
              }
              .panel {
                background: #ffffff;
                border: 1px solid #d7d8d2;
                border-radius: 8px;
                padding: 14px;
                margin-bottom: 14px;
              }
              .panel h2 {
                margin: 0 0 10px;
                font-size: 18px;
              }
              .task {
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 8px;
                padding: 10px 0;
                border-top: 1px solid #ecece7;
              }
              .task:first-of-type { border-top: 0; }
              .task-title { font-weight: 650; }
              .task-meta { color: #667085; font-size: 14px; margin-top: 2px; }
              .badge {
                align-self: start;
                border: 1px solid #c8d1ea;
                background: #eef4ff;
                border-radius: 999px;
                padding: 3px 9px;
                font-size: 13px;
                color: #344054;
              }
              #messages {
                min-height: 220px;
                max-height: 48vh;
                overflow: auto;
                display: grid;
                gap: 10px;
              }
              .msg {
                white-space: pre-wrap;
                line-height: 1.45;
                padding: 10px 12px;
                border-radius: 8px;
                max-width: 88%;
              }
              .user {
                justify-self: end;
                background: #2563eb;
                color: white;
              }
              .assistant {
                justify-self: start;
                background: #f1f5f9;
                color: #1f2933;
              }
              form {
                display: grid;
                grid-template-columns: 1fr auto;
                gap: 8px;
                margin-top: 12px;
              }
              input {
                min-height: 46px;
                border: 1px solid #cbd2d9;
                border-radius: 8px;
                padding: 0 12px;
                font: inherit;
              }
              input[type=file] {
                box-sizing: border-box;
                width: 100%;
                min-height: 0;
                padding: 14px;
                border-style: dashed;
                background: #fbfbf8;
              }
              button {
                min-height: 46px;
                border: 0;
                border-radius: 8px;
                background: #111827;
                color: white;
                font-weight: 700;
                padding: 0 16px;
              }
              .quick {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 10px;
              }
              .quick button {
                min-height: 34px;
                background: #e5e7eb;
                color: #111827;
                font-size: 14px;
              }
              .upload-form {
                display: grid;
                grid-template-columns: 1fr;
                gap: 10px;
              }
              .upload-result {
                margin-top: 10px;
                color: #344054;
                line-height: 1.45;
                white-space: pre-wrap;
              }
            </style>
          </head>
          <body>
            <main>
              <h1>家庭补货 Chat</h1>
              <p class="subtle">可以查询 Google Sheet，也可以直接更新低库存和待办。系统不会自动购买。</p>
              <section class="panel">
                <h2>待办列表</h2>
                <div id="tasks">加载中...</div>
              </section>
              <section class="panel">
                <h2>Chat</h2>
                <div id="messages">
                  <div class="msg assistant">可以问：“现在有哪些待办？”、“身体乳放在哪里？”；也可以说：“主卧洗手间手纸低库存”、“把车库的手纸拿到主卧洗手间”。</div>
                </div>
                <div class="quick">
                  <button type="button" data-text="现在有哪些待办？">待办</button>
                  <button type="button" data-text="现在有哪些低库存？">低库存</button>
                  <button type="button" data-text="现在有什么要买？">要买什么</button>
                </div>
                <form id="chat-form">
                  <input id="message" name="message" autocomplete="off" placeholder="输入问题或指令">
                  <button type="submit">发送</button>
                </form>
              </section>
              <section class="panel">
                <h2>拍照补录</h2>
                <p class="subtle">邮件没读准或 delivered 订单漏掉时，可以在这里拍小票、订单截图或 delivered 页面截图。</p>
                <form id="receipt-form" class="upload-form">
                  <input id="receipt-file" name="file" type="file" accept="image/*,.pdf,.txt" capture="environment" required>
                  <button id="receipt-submit" type="submit">上传并写入 Google Sheet</button>
                </form>
                <div id="receipt-result" class="upload-result"></div>
              </section>
            </main>
            <script>
              const tasksEl = document.getElementById('tasks');
              const messagesEl = document.getElementById('messages');
              const form = document.getElementById('chat-form');
              const input = document.getElementById('message');
              const receiptForm = document.getElementById('receipt-form');
              const receiptFile = document.getElementById('receipt-file');
              const receiptSubmit = document.getElementById('receipt-submit');
              const receiptResult = document.getElementById('receipt-result');

              function addMessage(role, text) {
                const div = document.createElement('div');
                div.className = `msg ${role}`;
                div.textContent = text;
                messagesEl.appendChild(div);
                messagesEl.scrollTop = messagesEl.scrollHeight;
              }

              function renderTasks(tasks) {
                if (!tasks.length) {
                  tasksEl.textContent = '当前没有待办任务。';
                  return;
                }
                tasksEl.innerHTML = tasks.slice(0, 8).map((task) => {
                  const item = task['商品名称'] || '未命名商品';
                  const type = task['任务类型'] || '待办';
                  const source = task['来源位置'] || '';
                  const target = task['目标位置'] || '';
                  const route = [source, target].filter(Boolean).join(' -> ');
                  return `<div class="task"><div><div class="task-title">${item}</div><div class="task-meta">${route || '未指定位置'}</div></div><div class="badge">${type}</div></div>`;
                }).join('');
              }

              async function refreshState() {
                try {
                  const response = await fetch('/chat/state');
                  const data = await response.json();
                  renderTasks(data.pending_tasks || []);
                } catch (error) {
                  tasksEl.textContent = `无法读取待办：${error}`;
                }
              }

              async function sendMessage(text) {
                if (!text.trim()) return;
                addMessage('user', text);
                input.value = '';
                const response = await fetch('/chat/message', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({message: text})
                });
                const data = await response.json();
                addMessage('assistant', data.message || '没有返回内容。');
                if (data.updated_google_sheet) await refreshState();
              }

              form.addEventListener('submit', (event) => {
                event.preventDefault();
                sendMessage(input.value);
              });
              document.querySelectorAll('.quick button').forEach((button) => {
                button.addEventListener('click', () => sendMessage(button.dataset.text));
              });
              receiptForm.addEventListener('submit', async (event) => {
                event.preventDefault();
                const file = receiptFile.files[0];
                if (!file) return;
                receiptSubmit.disabled = true;
                receiptSubmit.textContent = '正在识别...';
                receiptResult.textContent = '上传中，请稍等。';
                try {
                  const body = new FormData();
                  body.append('file', file);
                  const response = await fetch('/receipts/upload', { method: 'POST', body });
                  const data = await response.json();
                  if (!response.ok) throw new Error(data.detail || '上传失败');
                  receiptResult.textContent = `完成：已写入 ${data.receipt_items_created} 条记录。\\n文件：${data.filename || file.name}`;
                  await refreshState();
                } catch (error) {
                  receiptResult.textContent = `没有成功写入。${error.message || error}`;
                } finally {
                  receiptSubmit.disabled = false;
                  receiptSubmit.textContent = '上传并写入 Google Sheet';
                }
              });
              refreshState();
            </script>
          </body>
        </html>
        """
    )


@router.get("/chat/state")
def chat_state() -> dict[str, Any]:
    return _chat_state()


@router.post("/chat/message")
def chat_message(payload: ChatMessageRequest) -> dict[str, Any]:
    return _handle_chat_message(payload.message, dry_run=payload.dry_run)


@router.get("/voice", response_class=HTMLResponse)
def voice_entry() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>语音入口</title>
        <style>
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 28px;
            background: #f7f7f4;
            color: #1f2933;
          }
          main {
            max-width: 520px;
            margin: 0 auto;
          }
          h1 {
            font-size: 32px;
            margin: 20px 0 8px;
          }
          p {
            color: #52606d;
            font-size: 17px;
            line-height: 1.5;
          }
          label {
            display: block;
            margin: 20px 0 8px;
            font-weight: 650;
          }
          textarea {
            width: 100%;
            min-height: 132px;
            border: 1px solid #cbd2d9;
            border-radius: 8px;
            padding: 12px;
            font: inherit;
            box-sizing: border-box;
          }
          button {
            width: 100%;
            min-height: 52px;
            margin-top: 16px;
            border: 0;
            border-radius: 8px;
            background: #2563eb;
            color: white;
            font-size: 18px;
            font-weight: 700;
          }
        </style>
      </head>
      <body>
        <main>
          <h1>语音入口</h1>
          <p>把手机听写出来的指令贴在这里，系统会更新 Google Sheet 和待办任务，不会自动购买。</p>
          <form method="get" action="/voice/command">
            <label for="text">语音指令</label>
            <textarea id="text" name="text" placeholder="例如：主卧洗手间手纸低库存。或者：把车库的手纸拿到主卧洗手间。"></textarea>
            <button type="submit">提交</button>
          </form>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/voice/command", response_class=HTMLResponse)
def voice_command_get(
    text: str = Query(default=""),
    dry_run: bool = Query(default=False),
) -> HTMLResponse:
    result = _handle_voice_command(text, dry_run=dry_run)
    safe_message = escape(result.get("message", "已处理"))
    safe_item = escape(result.get("item_name", ""))
    safe_status = escape(result.get("status", "已处理"))
    safe_action = escape(result.get("action", ""))
    safe_update_note = (
        "已更新 Google Sheet。" if result.get("updated_google_sheet") else "没有更新 Google Sheet。"
    )
    safe_recognized_text = escape(result.get("recognized_text", text))
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{safe_status}</title>
            <style>
              body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 28px; background: #f7f7f4; color: #1f2933; }}
              main {{ max-width: 520px; margin: 0 auto; padding-top: 36px; }}
              h1 {{ font-size: 32px; margin: 0 0 12px; }}
              p {{ color: #52606d; font-size: 17px; line-height: 1.5; }}
              a {{ display: inline-block; margin-top: 20px; padding: 14px 18px; border-radius: 8px; background: #2563eb; color: white; font-weight: 700; text-decoration: none; }}
            </style>
          </head>
          <body>
            <main>
              <h1>{safe_status}</h1>
              <p>{safe_message}</p>
              <p>商品：{safe_item}</p>
              <p>分类动作：{safe_action}</p>
              <p>{safe_update_note}</p>
              <p>听到：{safe_recognized_text}</p>
              <p>系统不会自动购买。</p>
              <a href="/voice">返回</a>
            </main>
          </body>
        </html>
        """
    )


@router.post("/voice/command")
def voice_command_post(payload: VoiceCommandRequest) -> dict[str, Any]:
    return _handle_voice_command(payload.text, dry_run=payload.dry_run)


@router.post("/events/low-stock")
def create_low_stock_event(payload: LowStockEventCreate) -> dict[str, str]:
    sheets = sheets_service()
    item = sheets.find_inventory_item(payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{payload.item_id}")

    sheets.ensure_item_location(item.item_id, item.item_name, payload.location, payload.source)
    existing_event = sheets.recent_low_stock_event(
        item.item_id,
        payload.source,
        get_settings().duplicate_event_window_minutes,
        payload.location,
    )
    if existing_event:
        return {
            "status": "已存在",
            "event_id": existing_event.get("事件ID", ""),
            "item_id": item.item_id,
            "message": f"{item.item_name} 最近已经记录过低库存，本次没有重复添加。",
        }

    event_id = new_id("evt")
    sheets.append_low_stock_event(
        [
            event_id,
            now_local_string(),
            item.item_id,
            item.item_name,
            payload.source,
            payload.urgency,
            payload.note,
            "否",
            payload.location,
        ]
    )
    return {
        "status": "已记录",
        "event_id": event_id,
        "item_id": item.item_id,
        "message": f"{item.item_name} 已标记为低库存。",
    }


@router.get("/nfc/{item_id}", response_class=HTMLResponse)
def nfc_low_stock(
    item_id: str,
    note: str = Query(default=""),
    location: str = Query(default=""),
) -> HTMLResponse:
    sheets = sheets_service()
    item = sheets.find_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{item_id}")

    safe_item_id = escape(item_id)
    safe_item_name = escape(item.item_name)
    safe_note = escape(note)
    location_picker = _location_picker_html("location", "位置", location)
    source_location_picker = _location_picker_html("source_location", "搬运来源", "车库")
    target_location_picker = _location_picker_html("target_location", "搬运目标", location)
    detail_options_json = json.dumps(LOCATION_DETAIL_OPTIONS, ensure_ascii=False)
    html = f"""
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{safe_item_name}</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 28px;
            background: #f7f7f4;
            color: #1f2933;
          }}
          main {{
            max-width: 520px;
            margin: 0 auto;
          }}
          h1 {{
            font-size: 32px;
            margin: 20px 0 8px;
          }}
          p {{
            color: #52606d;
            font-size: 17px;
            line-height: 1.5;
          }}
          label {{
            display: block;
            margin: 20px 0 8px;
            font-weight: 650;
          }}
          textarea {{
            width: 100%;
            min-height: 88px;
            border: 1px solid #cbd2d9;
            border-radius: 8px;
            padding: 12px;
            font: inherit;
            box-sizing: border-box;
          }}
          input, select {{
            width: 100%;
            min-height: 48px;
            border: 1px solid #cbd2d9;
            border-radius: 8px;
            padding: 10px 12px;
            font: inherit;
            box-sizing: border-box;
          }}
          .location-picker {{
            display: grid;
            gap: 8px;
          }}
          .manual-location {{
            display: none;
          }}
          .actions {{
            display: grid;
            gap: 12px;
            margin-top: 20px;
          }}
          button {{
            min-height: 52px;
            border: 0;
            border-radius: 8px;
            font-size: 18px;
            font-weight: 700;
          }}
          .low {{ background: #2563eb; color: white; }}
          .empty {{ background: #b91c1c; color: white; }}
          .task {{ background: #047857; color: white; }}
          .done {{ background: #7c3aed; color: white; }}
          .cancel {{ background: #e5e7eb; color: #111827; }}
        </style>
      </head>
      <body>
        <main>
          <h1>{safe_item_name}</h1>
          <p>选择这次扫描要记录什么。系统只会更新 Google Sheet，不会自动购买。</p>
          <form method="get" action="/nfc/{safe_item_id}/record">
            {location_picker}
            {source_location_picker}
            {target_location_picker}
            <label for="note">备注</label>
            <textarea id="note" name="note" placeholder="例如：只剩最后一卷">{safe_note}</textarea>
            <div class="actions">
              <button class="low" type="submit" name="status" value="low">低库存</button>
              <button class="empty" type="submit" name="status" value="empty">已经没有库存</button>
              <button class="task" type="submit" formaction="/nfc/{safe_item_id}/task" name="task_action" value="create">创建搬运任务</button>
              <button class="done" type="submit" formaction="/nfc/{safe_item_id}/task" name="task_action" value="complete">完成搬运任务</button>
              <button class="cancel" type="button" onclick="history.back()">取消</button>
            </div>
          </form>
          <script>
            const locationDetails = {detail_options_json};
            function option(value, label, selected) {{
              const selectedAttr = selected ? ' selected' : '';
              return `<option value="${{value}}"${{selectedAttr}}>${{label}}</option>`;
            }}
            function setDetailOptions(baseId, area, previousValue) {{
              const detailSelect = document.getElementById(baseId + '_detail_select');
              const details = locationDetails[area] || [];
              let html = option('', '不指定具体位置', previousValue === '');
              const hasPrevious = details.includes(previousValue);
              if (previousValue && !hasPrevious && previousValue !== '__manual__') {{
                html += option('__manual__', '其他/新增具体位置', true);
              }}
              details.forEach((detail) => {{
                html += option(detail, detail, detail === previousValue);
              }});
              if (!previousValue || hasPrevious || previousValue === '__manual__') {{
                html += option('__manual__', '其他/新增具体位置', previousValue === '__manual__');
              }}
              detailSelect.innerHTML = html;
            }}
            function syncLocation(baseId) {{
              const areaSelect = document.getElementById(baseId + '_area_select');
              const areaManual = document.getElementById(baseId + '_area_manual');
              const detailSelect = document.getElementById(baseId + '_detail_select');
              const detailManual = document.getElementById(baseId + '_detail_manual');
              const hidden = document.getElementById(baseId);
              const isManualArea = areaSelect.value === '__manual__';
              const area = isManualArea ? areaManual.value.trim() : areaSelect.value;
              areaManual.style.display = isManualArea ? 'block' : 'none';
              if (detailSelect.dataset.area !== area) {{
                const previousDetail = detailSelect.value === '__manual__' ? '__manual__' : '';
                setDetailOptions(baseId, area, previousDetail);
                detailSelect.dataset.area = area;
              }}
              const isManualDetail = detailSelect.value === '__manual__';
              detailManual.style.display = isManualDetail ? 'block' : 'none';
              const detail = isManualDetail ? detailManual.value.trim() : detailSelect.value;
              hidden.value = detail ? `${{area}} - ${{detail}}` : area;
            }}
            ['location', 'source_location', 'target_location'].forEach(syncLocation);
          </script>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/nfc/{item_id}/record", response_class=HTMLResponse)
def record_nfc_low_stock(
    item_id: str,
    status: str = Query(default="low"),
    note: str = Query(default=""),
    location: str = Query(default=""),
) -> HTMLResponse:
    urgency = "紧急" if status == "empty" else "中"
    status_note = "已经没有库存" if status == "empty" else "低库存"
    location_note = f"位置：{location}" if location else ""
    combined_note = "。".join(part for part in [status_note, location_note, note] if part)
    payload = LowStockEventCreate(
        item_id=item_id, source="NFC", urgency=urgency, note=combined_note, location=location
    )
    result = create_low_stock_event(payload)
    safe_message = escape(result["message"])
    safe_item_id = escape(item_id)
    safe_status_note = escape(status_note)
    html = f"""
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>已记录</title>
        <style>
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            margin: 0;
            padding: 28px;
            background: #f7f7f4;
            color: #1f2933;
          }}
          main {{
            max-width: 520px;
            margin: 0 auto;
            padding-top: 36px;
          }}
          h1 {{
            font-size: 32px;
            margin: 0 0 12px;
          }}
          p {{
            color: #52606d;
            font-size: 17px;
            line-height: 1.5;
          }}
          a {{
            display: inline-block;
            margin-top: 20px;
            padding: 14px 18px;
            border-radius: 8px;
            background: #2563eb;
            color: white;
            font-weight: 700;
            text-decoration: none;
          }}
        </style>
      </head>
      <body>
        <main>
          <h1>已记录</h1>
          <p>{safe_message}</p>
          <p>状态：{safe_status_note}</p>
          <p>系统只更新了 Google Sheet，不会自动购买。</p>
          <a href="/nfc/{safe_item_id}">返回</a>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/nfc/{item_id}/task", response_class=HTMLResponse)
def record_nfc_task(
    item_id: str,
    task_action: str = Query(default="create"),
    location: str = Query(default=""),
    note: str = Query(default=""),
    source_location: str = Query(default="车库"),
    target_location: str = Query(default=""),
) -> HTMLResponse:
    sheets = sheets_service()
    item = sheets.find_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{item_id}")

    target = target_location or location
    sheets.ensure_item_location(item.item_id, item.item_name, source_location, "NFC")
    sheets.ensure_item_location(item.item_id, item.item_name, target, "NFC")
    if task_action == "complete":
        completed = sheets.complete_open_task(item.item_id, target_location=target)
        message = (
            f"{item.item_name} 的搬运任务已完成。"
            if completed
            else f"没有找到 {item.item_name} 在该位置的待完成搬运任务。"
        )
        status = "已完成" if completed else "未找到"
    else:
        task_id = new_id("task")
        sheets.append_task(
            [
                task_id,
                now_local_string(),
                "",
                item.item_id,
                item.item_name,
                "搬运补货",
                source_location,
                target,
                "待办",
                "NFC",
                note,
            ]
        )
        message = f"已创建任务：把 {item.item_name} 从 {source_location or '未指定位置'} 拿到 {target or '未指定位置'}。"
        status = "已创建"

    safe_message = escape(message)
    safe_item_id = escape(item_id)
    safe_status = escape(status)
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{safe_status}</title>
            <style>
              body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 28px; background: #f7f7f4; color: #1f2933; }}
              main {{ max-width: 520px; margin: 0 auto; padding-top: 36px; }}
              h1 {{ font-size: 32px; margin: 0 0 12px; }}
              p {{ color: #52606d; font-size: 17px; line-height: 1.5; }}
              a {{ display: inline-block; margin-top: 20px; padding: 14px 18px; border-radius: 8px; background: #2563eb; color: white; font-weight: 700; text-decoration: none; }}
            </style>
          </head>
          <body>
            <main>
              <h1>{safe_status}</h1>
              <p>{safe_message}</p>
              <p>系统只更新了 Google Sheet，不会自动购买。</p>
              <a href="/nfc/{safe_item_id}">返回</a>
            </main>
          </body>
        </html>
        """
    )


@router.post("/agent/daily-run")
def run_daily_agent() -> dict[str, object]:
    result = DailyReplenishmentAgent().run()
    return result


@router.post("/agent/daily-run-if-due")
def run_daily_agent_if_due() -> dict[str, object]:
    return DailySendGuard(hour=7, minute=0).run_if_due()


@router.post("/agent/order-analysis")
def run_order_analysis_agent() -> dict[str, object]:
    insights = OrderAnalysisAgent().run()
    return {"status": "完成", "order_insights_created": len(insights)}


@router.get("/receipts", response_class=HTMLResponse)
def receipt_upload_entry() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="zh-CN">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>上传小票/订单截图</title>
            <style>
              :root { color-scheme: light; }
              body {
                margin: 0;
                background: #f6f6f2;
                color: #1f2933;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
              }
              main {
                max-width: 560px;
                margin: 0 auto;
                padding: 22px;
              }
              h1 {
                font-size: 28px;
                margin: 14px 0 8px;
              }
              p {
                color: #52606d;
                line-height: 1.5;
              }
              .panel {
                background: white;
                border: 1px solid #d8dad4;
                border-radius: 8px;
                padding: 16px;
                margin-top: 16px;
              }
              label {
                display: block;
                font-weight: 700;
                margin-bottom: 8px;
              }
              input[type=file] {
                width: 100%;
                box-sizing: border-box;
                padding: 14px;
                border: 1px dashed #9aa4b2;
                border-radius: 8px;
                background: #fbfbf8;
              }
              button {
                width: 100%;
                min-height: 48px;
                margin-top: 14px;
                border: 0;
                border-radius: 8px;
                background: #111827;
                color: white;
                font-size: 16px;
                font-weight: 750;
              }
              button:disabled {
                background: #9aa4b2;
              }
              #result {
                margin-top: 14px;
                white-space: pre-wrap;
                line-height: 1.45;
                color: #1f2933;
              }
              .ok {
                border-left: 4px solid #16a34a;
                padding-left: 12px;
              }
              .error {
                border-left: 4px solid #dc2626;
                padding-left: 12px;
              }
            </style>
          </head>
          <body>
            <main>
              <h1>上传小票/订单截图</h1>
              <p>适合邮件没读准、delivered 订单漏掉、Whole Foods/Target/Costco 小票等情况。拍照后系统会提取商品、价格、店铺和地址，并更新 Google Sheet。</p>
              <section class="panel">
                <form id="receipt-form">
                  <label for="file">拍照或选择图片</label>
                  <input id="file" name="file" type="file" accept="image/*,.pdf,.txt" capture="environment" required>
                  <button id="submit" type="submit">上传并记录</button>
                </form>
                <div id="result"></div>
              </section>
            </main>
            <script>
              const form = document.getElementById('receipt-form');
              const button = document.getElementById('submit');
              const result = document.getElementById('result');
              form.addEventListener('submit', async (event) => {
                event.preventDefault();
                const file = document.getElementById('file').files[0];
                if (!file) return;
                button.disabled = true;
                button.textContent = '正在识别...';
                result.className = '';
                result.textContent = '上传中，请稍等。';
                try {
                  const body = new FormData();
                  body.append('file', file);
                  const response = await fetch('/receipts/upload', { method: 'POST', body });
                  const data = await response.json();
                  if (!response.ok) {
                    throw new Error(data.detail || '上传失败');
                  }
                  result.className = 'ok';
                  result.textContent = `完成：已写入 ${data.receipt_items_created} 条记录。\\n文件：${data.filename || file.name}`;
                } catch (error) {
                  result.className = 'error';
                  result.textContent = `没有成功写入。${error.message || error}`;
                } finally {
                  button.disabled = false;
                  button.textContent = '上传并记录';
                }
              });
            </script>
          </body>
        </html>
        """
    )


@router.post("/receipts/upload")
async def upload_receipt(file: UploadFile = File(...)) -> dict[str, object]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的小票文件为空。")
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="小票文件太大，请控制在 8MB 以内。")

    insights = ReceiptAnalysisAgent().process_upload(
        file.filename or "receipt", file.content_type or "application/octet-stream", data
    )
    return {
        "status": "完成",
        "filename": file.filename,
        "receipt_items_created": len(insights),
    }


@router.post("/recommendations/{recommendation_id}/status")
def update_recommendation_status(
    recommendation_id: str, payload: RecommendationStatusUpdate
) -> dict[str, str]:
    updated = sheets_service().update_recommendation_status(
        recommendation_id, payload.reorder_status
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"找不到推荐ID：{recommendation_id}")
    return {"status": "已更新", "recommendation_id": recommendation_id}
