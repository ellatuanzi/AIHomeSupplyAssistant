from app.services.hsa_tracker import classify_hsa_candidate


KEYWORDS = "hsa,fsa,hydrocortisone,anti-itch,first aid,bandage,medicine,spf"


def test_hsa_candidate_detects_medical_purchase():
    result = classify_hsa_candidate(
        {
            "item_name": "Amazon Basic Care Maximum Strength Anti-Itch Cream",
            "product_title": "Amazon Basic Care Maximum Strength Anti-Itch Cream, 1 oz",
        },
        KEYWORDS,
    )

    assert result.is_candidate is True
    assert result.confidence >= 68
    assert "anti-itch" in result.reason


def test_hsa_candidate_ignores_non_medical_purchase():
    result = classify_hsa_candidate(
        {
            "item_name": "Transon Flat Paint Brush Set",
            "product_title": "Transon Flat Paint Brush Set 7pcs",
        },
        KEYWORDS,
    )

    assert result.is_candidate is False
