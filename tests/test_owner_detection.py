from app.owner_detection import extract_owner_name


def test_owner_name_is_extracted_from_bottom_right():
    items = [
        {"text": "高等数学", "center_x": 120, "center_y": 400, "confidence": 0.98},
        {"text": "王越", "center_x": 720, "center_y": 455, "confidence": 0.97},
    ]

    result = extract_owner_name(items, image_width=800, image_height=500)

    assert result is not None
    assert result["name"] == "王越"
    assert result["source_text"] == "王越"


def test_owner_name_marker_and_generic_text_are_handled():
    marked = extract_owner_name(
        [
            {
                "text": "学生姓名：张三",
                "center_x": 680,
                "center_y": 440,
                "confidence": 0.96,
            }
        ],
        image_width=800,
        image_height=500,
    )
    assert marked["name"] == "张三"

    generic = extract_owner_name(
        [
            {
                "text": "课程表",
                "center_x": 700,
                "center_y": 450,
                "confidence": 0.99,
            }
        ],
        image_width=800,
        image_height=500,
    )
    assert generic is None
