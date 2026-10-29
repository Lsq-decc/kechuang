from app.free_periods import build_free_period_schedule


def _busy(weekday, start_period, end_period, weeks):
    return {
        "weekday": weekday,
        "start_period": start_period,
        "end_period": end_period,
        "weeks": weeks,
    }


def test_lsq_schedule_matches_expected_free_periods():
    courses = [
        _busy(1, 1, 2, "1-16周"),
        _busy(1, 3, 4, "1-16周"),
        _busy(1, 7, 8, "1-16周"),
        _busy(1, 9, 10, "1-16周"),
        _busy(2, 1, 2, "1-16周"),
        _busy(2, 3, 4, "5-8周"),
        _busy(2, 5, 6, "1-16周"),
        _busy(2, 9, 10, "2,4,6,8,10,12,14,16周"),
        _busy(3, 1, 2, "1-12周"),
        _busy(3, 3, 4, "1-16周"),
        _busy(3, 9, 10, "1-16周"),
        _busy(4, 1, 2, "1-12周"),
        _busy(4, 3, 4, "1-16周"),
        _busy(4, 5, 6, "1-16周"),
        _busy(4, 7, 8, "1-16周"),
        _busy(5, 1, 2, "1-16周"),
        _busy(5, 7, 8, "1-8周"),
        _busy(5, 9, 10, "1-8周"),
    ]

    schedule = build_free_period_schedule(courses)
    actual = {
        day["weekday_label"]: [
            (slot["period_label"], slot["availability_label"])
            for slot in day["slots"]
        ]
        for day in schedule["days"]
    }

    assert actual == {
        "周一": [("5-6节", "全周空")],
        "周二": [
            ("7-8节", "全周空"),
            ("3-4节", "1-4、9-16周空"),
            ("9-10节", "单周空"),
        ],
        "周三": [
            ("5-6节", "全周空"),
            ("7-8节", "全周空"),
            ("1-2节", "13-16周空"),
        ],
        "周四": [
            ("9-10节", "全周空"),
            ("1-2节", "13-16周空"),
        ],
        "周五": [
            ("3-4节", "全周空"),
            ("5-6节", "全周空"),
            ("7-8节", "9-16周空"),
            ("9-10节", "9-16周空"),
        ],
    }
    assert schedule["total_free_slots"] == 13


def test_free_period_schedule_ignores_invalid_course_values():
    schedule = build_free_period_schedule(
        [
            {"weekday": 0, "start_period": 1, "end_period": 2},
            {"weekday": "invalid", "start_period": 1, "end_period": 2},
            {"weekday": 1, "start_period": 99, "end_period": 100},
        ]
    )

    assert schedule["total_free_slots"] == 0

