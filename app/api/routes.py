from html import escape
import json
import re
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
    "toilet_paper": ["手纸", "卫生纸", "厕纸", "toilet paper"],
    "paper_towels": ["厨房纸", "paper towel", "paper towels"],
    "trash_bags": ["垃圾袋", "trash bag", "trash bags"],
    "detergent": ["洗衣液", "洗衣粉", "detergent"],
    "pet_food": ["宠物粮", "狗粮", "猫粮", "pet food"],
    "body_lotion": ["身体乳", "润肤乳", "body lotion", "lotion"],
    "swiffer_wet_cloth": ["swiffer", "湿拖布", "拖地湿巾", "wet cloth"],
    "pencil": ["铅笔", "pencil", "pencils"],
    "eraser": ["橡皮", "eraser", "erasers"],
    "kids_toothpaste": ["儿童牙膏", "牙膏", "kid toothpaste", "kids toothpaste"],
    "kids_electric_toothbrush": ["儿童牙刷", "电动牙刷", "electric toothbrush"],
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


class VoiceCommandRequest(BaseModel):
    text: str
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
    names = _location_options([])
    for area, details in LOCATION_DETAIL_OPTIONS.items():
        for detail in details:
            names.append(f"{area} - {detail}")
            names.append(detail)
    return sorted({name.strip() for name in names if name.strip()}, key=len, reverse=True)


def _find_location_in_text(text: str) -> str:
    normalized = text.lower()
    for location_name in _known_location_names():
        if location_name.lower() in normalized:
            return location_name
    return ""


def _locations_in_text(text: str) -> list[str]:
    normalized = text.lower()
    matches = []
    for location_name in _known_location_names():
        start = normalized.find(location_name.lower())
        if start >= 0:
            matches.append((start, -len(location_name), location_name))
    by_start = {}
    for start, negative_length, location_name in sorted(matches):
        if start not in by_start:
            by_start[start] = (negative_length, location_name)
    return [value[1] for _, value in sorted(by_start.items())]


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


def _voice_action(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["完成", "做好", "做完", "done", "finish", "finished"]):
        return "complete_task"
    if any(token in lowered for token in ["任务", "todo", "to do", "待办", "拿到", "搬到", "移到", "补到"]):
        return "create_task"
    if any(token in lowered for token in ["没有", "没了", "空了", "用完", "out of", "empty"]):
        return "empty_stock"
    return "low_stock"


def _handle_voice_command(text: str, dry_run: bool = False) -> dict[str, Any]:
    command = text.strip()
    if not command:
        raise HTTPException(status_code=400, detail="语音文字为空。")
    sheets = sheets_service()
    item = _match_voice_item(command, sheets.get_inventory_items())
    if not item:
        raise HTTPException(status_code=404, detail=f"没有从语音中识别到商品：{command}")

    action = _voice_action(command)
    source_location, target_location = _find_source_target_locations(command)
    location = target_location or source_location or _find_location_in_text(command)
    note = f"语音指令：{command}"

    if dry_run:
        return {
            "status": "预览",
            "action": action,
            "item_id": item.item_id,
            "item_name": item.item_name,
            "location": location,
            "source_location": source_location,
            "target_location": target_location,
            "message": "这是预览，没有更新 Google Sheet。",
        }

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
            }
        )
        return result

    sheets.ensure_item_location(item.item_id, item.item_name, source_location, "语音")
    sheets.ensure_item_location(item.item_id, item.item_name, target_location or location, "语音")
    if action == "complete_task":
        completed = sheets.complete_open_task(item.item_id, target_location=target_location or location)
        return {
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
                else f"没有找到 {item.item_name} 的待完成任务。"
            ),
        }

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
            target_location or location,
            "待办",
            "语音",
            note,
        ]
    )
    return {
        "status": "已创建",
        "action": action,
        "task_id": task_id,
        "item_id": item.item_id,
        "item_name": item.item_name,
        "location": target_location or location,
        "source_location": source_location,
        "target_location": target_location,
        "message": f"已创建任务：把 {item.item_name} 从 {source_location or '未指定位置'} 拿到 {target_location or location or '未指定位置'}。",
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
              <p>系统只更新了 Google Sheet，不会自动购买。</p>
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
