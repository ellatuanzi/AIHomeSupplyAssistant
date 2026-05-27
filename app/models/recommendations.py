from pydantic import BaseModel


class Recommendation(BaseModel):
    recommendation_id: str
    date: str
    item_id: str
    item_name: str
    recommended_retailer: str
    recommended_brand: str
    product_title: str
    estimated_price: str
    product_url: str
    confidence: int
    urgency: str
    reasoning: str
    reorder_status: str = "待确认"
    last_updated: str


class RecommendationStatusUpdate(BaseModel):
    reorder_status: str
