from app.api import course_occurs_in_week
from app.schedule_parser import (
    clean_course_name,
    parse_period_range,
    parse_schedule,
    parse_weeks,
)


def test_parser_extracts_explicit_course_fields():
    text = "周一第3-4节 数据结构 1-16周(单)"

    assert parse_period_range(text) == (3, 4)
    assert parse_weeks(text) == "1-16周（单周）"
    assert clean_course_name(text) == "数据结构"


def test_course_week_rules_handle_ranges_and_parity():
    assert course_occurs_in_week("1-16周", 8)
    assert not course_occurs_in_week("1-16周", 17)
    assert course_occurs_in_week("1-16周（单周）", 3)
    assert not course_occurs_in_week("1-16周（单周）", 4)
    assert course_occurs_in_week("1-16周（双周）", 4)
    assert not course_occurs_in_week("1-16周（双周）", 5)


def test_unknown_week_text_is_treated_conservatively():
    assert course_occurs_in_week("", 1)
    assert course_occurs_in_week("详见教务系统", 10)


def test_weekday_columns_survive_duplicate_header_ocr():
    items = [
        {"text": "周一", "center_x": 100, "center_y": 50, "confidence": 0.99},
        {"text": "周二", "center_x": 200, "center_y": 50, "confidence": 0.99},
        {"text": "周三", "center_x": 300, "center_y": 50, "confidence": 0.98},
        {"text": "周三", "center_x": 400, "center_y": 50, "confidence": 0.72},
        {"text": "周五", "center_x": 500, "center_y": 50, "confidence": 0.99},
        {"text": "周六", "center_x": 600, "center_y": 50, "confidence": 0.99},
        {"text": "周日", "center_x": 700, "center_y": 50, "confidence": 0.99},
        {"text": "第1-2节", "center_x": 50, "center_y": 120, "confidence": 0.99},
        {
            "text": "高等数学 1-16周",
            "center_x": 400,
            "center_y": 120,
            "confidence": 0.95,
            "box": [[370, 105], [430, 105], [430, 135], [370, 135]],
        },
    ]

    courses, _warnings = parse_schedule(items)

    assert len(courses) == 1
    assert courses[0]["weekday"] == 4
    assert courses[0]["start_period"] == 1
    assert courses[0]["end_period"] == 2
