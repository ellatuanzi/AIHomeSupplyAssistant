from app.agents.order_analysis_agent import extract_product_blocks_from_order_body


def test_extracts_multiple_products_from_order_body():
    body = """
    Transon Flat Paint Brush Set 7pcs...
    Quantity: 1
    6.99 USD

    GRANOTONE Clear Coat Acrylic Matt...
    Quantity: 1
    $15.00
    """

    products = extract_product_blocks_from_order_body(body)

    assert len(products) == 2
    assert products[0]["product_title"] == "Transon Flat Paint Brush Set 7pcs..."
    assert products[0]["quantity"] == "1"
    assert products[0]["price"] == "6.99USD"
    assert products[1]["product_title"] == "GRANOTONE Clear Coat Acrylic Matt..."
    assert products[1]["price"] == "$15.00"
