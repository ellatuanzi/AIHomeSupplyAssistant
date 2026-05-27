from dataclasses import dataclass
from urllib.parse import quote_plus

from app.models.inventory import InventoryItem


@dataclass
class RetailOption:
    retailer: str
    brand: str
    product_title: str
    estimated_price: str
    product_url: str


class RetailerSearchService:
    """MVP search layer: create reliable retailer search links without scraping."""

    def search(self, item: InventoryItem) -> list[RetailOption]:
        query = " ".join(
            part
            for part in [item.preferred_brand, item.item_name, item.typical_quantity]
            if part
        )
        encoded = quote_plus(query or item.item_name)
        retailers = {
            "Amazon": f"https://www.amazon.com/s?k={encoded}",
            "Costco": f"https://www.costco.com/CatalogSearch?keyword={encoded}",
            "Walmart": f"https://www.walmart.com/search?q={encoded}",
            "Target": f"https://www.target.com/s?searchTerm={encoded}",
        }

        preferred = item.preferred_retailer.strip()
        ordered_retailers = [preferred] if preferred in retailers else []
        ordered_retailers.extend([name for name in retailers if name not in ordered_retailers])

        return [
            RetailOption(
                retailer=retailer,
                brand=item.preferred_brand or "",
                product_title=f"{item.preferred_brand} {item.item_name} {item.typical_quantity}".strip(),
                estimated_price="待查看",
                product_url=retailers[retailer],
            )
            for retailer in ordered_retailers[:4]
        ]

