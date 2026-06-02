from html import escape

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse

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


def sheets_service() -> GoogleSheetsService:
    try:
        return GoogleSheetsService()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    safe_location = escape(location)
    locations = sheets.item_locations(item_id)
    location_options = "\n".join(
        f'<option value="{escape(value)}">{escape(value)}</option>' for value in locations
    )
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
            <label for="location">位置</label>
            <input id="location" name="location" list="locations" value="{safe_location}" placeholder="例如：主卧洗手间">
            <datalist id="locations">
              {location_options}
            </datalist>
            <label for="source_location">搬运来源</label>
            <input id="source_location" name="source_location" list="locations" value="车库" placeholder="例如：车库">
            <label for="target_location">搬运目标</label>
            <input id="target_location" name="target_location" list="locations" value="{safe_location}" placeholder="例如：主卧洗手间">
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
