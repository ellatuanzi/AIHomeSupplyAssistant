from app.agents.order_analysis_agent import _normalize_address, extract_amazon_delivery_location


def address_category(address: str, default_address: str = "102 Montelena Ct") -> str:
    if not address:
        return "未识别"
    return (
        "默认地址"
        if _normalize_address(default_address) in _normalize_address(address)
        else "其他地址"
    )


def test_default_shipping_address_is_classified():
    assert address_category("Ship to: 102 Montelena Ct, Mountain View, CA") == "默认地址"


def test_other_shipping_address_is_classified():
    assert address_category("500 Castro St, Mountain View, CA") == "其他地址"


def test_missing_shipping_address_is_unknown():
    assert address_category("") == "未识别"


def test_extracts_amazon_delivery_location():
    text = """
    Arriving tomorrow

    Ella - GILBERT, AZ

    Order #
    113-2600182-4521823
    """

    assert extract_amazon_delivery_location(text) == "Ella - GILBERT, AZ"
