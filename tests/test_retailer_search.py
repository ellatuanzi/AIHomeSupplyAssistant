from app.models.inventory import InventoryItem
from app.services.retailer_search import RetailerSearchService


def test_retailer_search_prefers_configured_retailer():
    item = InventoryItem(
        item_id="toilet_paper",
        item_name="Toilet Paper",
        preferred_brand="Charmin",
        preferred_retailer="Costco",
        typical_quantity="30 rolls",
    )

    options = RetailerSearchService().search(item)

    assert options[0].retailer == "Costco"
    assert "Charmin" in options[0].product_title
