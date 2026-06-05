from types import SimpleNamespace

from app.agents import receipt_analysis_agent
from app.agents.receipt_analysis_agent import ReceiptAnalysisAgent
from app.api import routes


def test_receipt_upload_page_has_camera_input():
    response = routes.receipt_upload_entry()
    html = response.body.decode("utf-8")

    assert "上传小票/订单截图" in html
    assert "本地上传 / 相册选择" in html
    assert 'accept="image/*,.pdf,.txt"' in html
    assert 'capture="environment"' in html
    assert "multiple" in html


def test_chat_page_includes_receipt_upload():
    response = routes.chat_entry()
    html = response.body.decode("utf-8")

    assert "拍照补录" in html
    assert "本地上传 / 相册选择" in html
    assert "receipt-form" in html
    assert "fetch('/receipts/upload'" in html


def test_receipt_image_extracts_with_gemini(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '[{"retailer":"Amazon","item_name":"Wet Wipes",'
                                        '"item_id":"wet_wipes","brand":"Amazon Basics",'
                                        '"product_title":"Amazon Basics Wet Wipes",'
                                        '"quantity":"1","price":"$12.99",'
                                        '"shipping_address":"102 Montelena Ct",'
                                        '"order_link":""}]'
                                    )
                                }
                            ]
                        }
                    }
                ]
            }

    captured = {}

    def fake_post(url, params, json, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr(receipt_analysis_agent.requests, "post", fake_post)

    recommender = SimpleNamespace(
        gemini_api_key="gemini-key",
        gemini_model="gemini-2.0-flash",
        client=None,
    )
    agent = ReceiptAnalysisAgent(sheets=SimpleNamespace(), recommender=recommender)

    result = agent._extract_receipt_items(
        "receipt.jpg",
        "image/jpeg",
        b"fake-image",
        [],
    )

    assert result[0]["item_id"] == "wet_wipes"
    assert result[0]["price"] == "$12.99"
    assert captured["params"]["key"] == "gemini-key"
    assert captured["json"]["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/jpeg"
    prompt_text = captured["json"]["contents"][0]["parts"][0]["text"]
    assert "所有可见的已购买商品" in prompt_text
    assert "不要只提取家庭日用品" in prompt_text
    assert "Sponsored" in prompt_text
    assert "Replacement for" in prompt_text


def test_receipt_image_does_not_fallback_to_openai_when_gemini_fails(monkeypatch):
    class FakeOpenAIClient:
        class Chat:
            class Completions:
                def create(self, *args, **kwargs):
                    raise AssertionError("receipt image upload should not call OpenAI fallback")

            completions = Completions()

        chat = Chat()

    class FakeResponse:
        def raise_for_status(self):
            raise receipt_analysis_agent.requests.RequestException("gemini temporarily unavailable")

    def fake_post(url, params, json, timeout):
        return FakeResponse()

    monkeypatch.setattr(receipt_analysis_agent.requests, "post", fake_post)

    recommender = SimpleNamespace(
        gemini_api_key="gemini-key",
        gemini_model="gemini-2.0-flash",
        client=FakeOpenAIClient(),
    )
    agent = ReceiptAnalysisAgent(sheets=SimpleNamespace(), recommender=recommender)

    result = agent._extract_receipt_items(
        "target_receipt.jpg",
        "image/jpeg",
        b"fake-image",
        [],
    )

    assert result[0]["item_name"] == "未匹配小票商品"
    assert result[0]["product_title"] == "target_receipt.jpg"


def test_receipt_upload_api_returns_extraction_status(monkeypatch):
    class FakeAgent:
        def process_uploads_with_status(self, uploads):
            return {
                "insights": [],
                "extraction_status": {
                    "method": "gemini",
                    "model": "gemini-2.5-flash",
                    "message": "Gemini 返回了空结果或缺少商品名称。",
                },
            }

    monkeypatch.setattr(routes, "ReceiptAnalysisAgent", lambda: FakeAgent())

    import anyio

    class FakeUpload:
        filename = "receipt.jpg"
        content_type = "image/jpeg"

        async def read(self):
            return b"image"

    result = anyio.run(routes.upload_receipt, FakeUpload())

    assert result["receipt_items_created"] == 0
    assert result["files_uploaded"] == 1
    assert result["extraction_status"]["model"] == "gemini-2.5-flash"
    assert "Gemini" in result["message"]


def test_receipt_batch_upload_dedupes_across_pictures():
    class FakeSheets:
        def __init__(self):
            self.purchase_rows = []
            self.insight_rows = []

        def ensure_tabs_and_headers(self):
            return None

        def get_inventory_items(self):
            return []

        def append_purchase_history_dict(self, row):
            self.purchase_rows.append(row)

        def append_order_insight_dict(self, row):
            self.insight_rows.append(row)

    class FakeHsaTracker:
        def has_hsa_candidate(self, orders):
            return False

        def append_if_candidate(self, **kwargs):
            return None

    class FakeAgent(ReceiptAnalysisAgent):
        def _extract_receipt_items(self, filename, content_type, data, inventory):
            return [
                {
                    "retailer": "Amazon",
                    "item_name": "Wet Wipes",
                    "item_id": "wet_wipes",
                    "brand": "Amazon Basics",
                    "product_title": "Amazon Basics Wet Wipes",
                    "quantity": "1",
                    "price": "$12.99",
                    "shipping_address": "102 Montelena Ct",
                    "order_link": "",
                }
            ]

    sheets = FakeSheets()
    agent = FakeAgent(
        sheets=sheets,
        recommender=SimpleNamespace(client=None, gemini_api_key="", gemini_model=""),
        hsa_tracker=FakeHsaTracker(),
    )

    result = agent.process_uploads_with_status(
        [
            ("order-page-1.jpg", "image/jpeg", b"one"),
            ("order-page-2.jpg", "image/jpeg", b"two"),
        ]
    )

    assert len(result["insights"]) == 1
    assert len(sheets.purchase_rows) == 1
    assert result["extraction_status"]["files"] == 2
    assert result["extraction_status"]["duplicates_removed"] == 1
