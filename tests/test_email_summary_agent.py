from app.agents.email_summary_agent import EmailSummaryAgent
from app.models.recommendations import Recommendation


def test_email_summary_is_chinese_and_mentions_no_auto_purchase():
    rec = Recommendation(
        recommendation_id="rec_1",
        date="2026-05-22",
        item_id="toilet_paper",
        item_name="Toilet Paper",
        recommended_retailer="Costco",
        recommended_brand="Charmin",
        product_title="Charmin Ultra Soft 30-roll pack",
        estimated_price="$29.99",
        product_url="https://example.com",
        confidence=88,
        urgency="中",
        reasoning="符合偏好品牌和店铺。",
        reorder_status="待确认",
        last_updated="2026-05-22 08:00:00",
    )

    subject, body = EmailSummaryAgent().build([rec], [])

    assert "今日家庭补货提醒" in subject
    assert "Toilet Paper" in body
    assert "Google Sheet" in body
    assert "系统不会自动购买任何商品" in body


def test_email_summary_should_not_send_when_nothing_needs_attention():
    assert EmailSummaryAgent.should_send([], []) is False
    assert EmailSummaryAgent.should_send([], [{"补货状态": "已下单"}]) is False


def test_email_summary_should_send_for_pending_items():
    assert EmailSummaryAgent.should_send([], [{"补货状态": "待确认"}]) is True
