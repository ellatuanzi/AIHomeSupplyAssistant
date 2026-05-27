from html import escape

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse

from app.agents.daily_replenishment_agent import DailyReplenishmentAgent
from app.agents.daily_send_guard import DailySendGuard
from app.agents.order_analysis_agent import OrderAnalysisAgent
from app.agents.receipt_analysis_agent import ReceiptAnalysisAgent
from app.models.events import LowStockEventCreate
from app.models.recommendations import RecommendationStatusUpdate
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


@router.post("/events/low-stock")
def create_low_stock_event(payload: LowStockEventCreate) -> dict[str, str]:
    sheets = sheets_service()
    item = sheets.find_inventory_item(payload.item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{payload.item_id}")

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
) -> HTMLResponse:
    sheets = sheets_service()
    item = sheets.find_inventory_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到商品ID：{item_id}")

    safe_item_id = escape(item_id)
    safe_item_name = escape(item.item_name)
    safe_note = escape(note)
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
          .cancel {{ background: #e5e7eb; color: #111827; }}
        </style>
      </head>
      <body>
        <main>
          <h1>{safe_item_name}</h1>
          <p>要记录这个物品的库存状态吗？系统只会更新 Google Sheet，不会自动购买。</p>
          <form method="get" action="/nfc/{safe_item_id}/record">
            <label for="note">备注</label>
            <textarea id="note" name="note" placeholder="例如：只剩最后一卷">{safe_note}</textarea>
            <div class="actions">
              <button class="low" type="submit" name="status" value="low">低库存</button>
              <button class="empty" type="submit" name="status" value="empty">已经没有库存</button>
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
) -> HTMLResponse:
    urgency = "紧急" if status == "empty" else "中"
    status_note = "已经没有库存" if status == "empty" else "低库存"
    combined_note = f"{status_note}。{note}".strip("。")
    payload = LowStockEventCreate(
        item_id=item_id, source="NFC", urgency=urgency, note=combined_note
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
