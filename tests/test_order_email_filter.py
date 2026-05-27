from app.agents.order_analysis_agent import is_order_received_email


def test_order_received_email_is_allowed():
    assert is_order_received_email(
        {
            "subject": "Your order received",
            "from": "store@example.com",
            "snippet": "Order total $24.99",
            "body": "Order number 123",
        }
    )


def test_shipped_email_is_filtered():
    assert not is_order_received_email(
        {
            "subject": "Your order shipped",
            "from": "store@example.com",
            "snippet": "Track your package",
            "body": "Shipping update",
        }
    )


def test_promotion_email_is_filtered():
    assert not is_order_received_email(
        {
            "subject": "Order now and save 20%",
            "from": "promo@example.com",
            "snippet": "Sale ends today",
            "body": "Recommended for you",
        }
    )


def test_amazon_ordered_subject_is_allowed():
    assert is_order_received_email(
        {
            "subject": 'Ordered: "GRANOTONE Clear Coat..." and ⁦1⁩ more item',
            "from": "Amazon.com",
            "snippet": "Quantity: 1",
            "body": "Transon Flat Paint Brush Set 7pcs\nQuantity: 1\n$6.99",
        }
    )
