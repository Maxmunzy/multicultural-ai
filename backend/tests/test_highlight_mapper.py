from app.services.highlight_mapper import (
    build_highlights_from_cards,
    normalize_highlight_text,
)


def test_normalize_highlight_text_removes_spacing_and_symbols():
    assert normalize_highlight_text("4월 28일(화) 까지 제출") == "4월28일화까지제출"


def test_build_highlights_from_mlkit_flat_layout():
    layout = [
        {
            "page": 1,
            "source": "mlkit_line",
            "text": "참가 동의서는 4월 28일(화)까지 담임선생님께 제출 바랍니다",
            "bbox": {"x": 120, "y": 340, "width": 380, "height": 28},
            "page_size": {"width": 1000, "height": 1414},
        }
    ]
    cards = [
        {
            "value_ko": "4월 28일(화)까지 담임선생님께 제출 바랍니다",
            "chip": "제출",
            "importance": 0.92,
            "value_translated": "Vui lòng gửi đến giáo viên chủ nhiệm trước ngày 28/4 (Thứ Ba)",
            "value_easy_ko": "4월 28일까지 담임선생님께 내세요.",
        }
    ]

    highlights = build_highlights_from_cards(cards, layout)

    assert len(highlights) == 1
    assert highlights[0]["highlight_id"] == "h_001"
    assert highlights[0]["source"] == "mlkit_line"
    assert highlights[0]["category"] == "제출"
    assert highlights[0]["bbox"]["x"] == 120
    assert highlights[0]["page_size"]["height"] == 1414


def test_build_highlights_from_pdf_probe_pages_layout():
    layout = {
        "pages": [
            {
                "page": 1,
                "width": 595.28,
                "height": 841.89,
                "lines": [
                    {
                        "page": 1,
                        "source": "pdfplumber_line",
                        "text": "준비물: 간편한 복장, 물",
                        "bbox": {"x": 80.0, "y": 240.0, "width": 220.0, "height": 14.0},
                    }
                ],
            }
        ]
    }
    cards = [
        {
            "value_ko": "간편한 복장, 물",
            "chip": "준비물",
            "importance": 0.85,
            "value_translated": "quần áo thoải mái, nước uống",
            "value_easy_ko": "편한 옷과 물을 준비하세요.",
        }
    ]

    highlights = build_highlights_from_cards(cards, layout)

    assert len(highlights) == 1
    assert highlights[0]["source"] == "pdfplumber_line"
    assert highlights[0]["category"] == "준비물"
    assert highlights[0]["page_size"]["width"] == 595.28


def test_build_highlights_returns_empty_when_score_too_low():
    layout = [
        {
            "page": 1,
            "source": "mlkit_line",
            "text": "전혀 다른 문장입니다",
            "bbox": {"x": 0, "y": 0, "width": 100, "height": 20},
            "page_size": {"width": 1000, "height": 1414},
        }
    ]
    cards = [{"value_ko": "4월 28일까지 제출", "chip": "제출"}]

    assert build_highlights_from_cards(cards, layout, min_score=0.8) == []
