from pydantic import BaseModel


class InventoryItem(BaseModel):
    item_id: str
    item_name: str
    category: str = ""
    preferred_brand: str = ""
    preferred_retailer: str = ""
    household_location: str = ""
    typical_quantity: str = ""
    reorder_threshold: str = ""
    urgency_default: str = "中"
    notes: str = ""

