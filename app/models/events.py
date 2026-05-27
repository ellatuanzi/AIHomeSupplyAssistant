from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Source = Literal["NFC", "语音", "手动", "API"]
Urgency = Literal["低", "中", "高", "紧急"]


class LowStockEventCreate(BaseModel):
    item_id: str = Field(..., examples=["toilet_paper"])
    source: Source = "API"
    urgency: Urgency = "中"
    note: str = ""


class LowStockEvent(BaseModel):
    event_id: str
    timestamp: datetime
    item_id: str
    item_name: str
    source: Source
    urgency: Urgency
    note: str = ""
    resolved: bool = False

