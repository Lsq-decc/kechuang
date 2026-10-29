from .week_rules import course_occurs_in_week


WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
PERIOD_GROUPS = ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10))
DEFAULT_WEEK_COUNT = 16


def _format_weeks(weeks, week_count):
    ordered = sorted(set(weeks))
    if ordered == list(range(1, week_count + 1)):
        return "全周空"
    if ordered == list(range(1, week_count + 1, 2)):
        return "单周空"
    if ordered == list(range(2, week_count + 1, 2)):
        return "双周空"

    ranges = []
    start = previous = ordered[0]
    for week in ordered[1:]:
        if week == previous + 1:
            previous = week
            continue
        ranges.append(
            str(start) if start == previous else f"{start}-{previous}"
        )
        start = previous = week
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return f"{'、'.join(ranges)}周空"


def build_free_period_schedule(courses, week_count=DEFAULT_WEEK_COUNT):
    """Return free two-period blocks for each week of the semester."""
    week_numbers = list(range(1, week_count + 1))
    active_weekdays = set(range(1, 6))
    has_course = False
    for course in courses or []:
        try:
            weekday = int(course.get("weekday"))
            start_period = int(course.get("start_period"))
            end_period = int(course.get("end_period"))
        except (AttributeError, TypeError, ValueError):
            continue
        if (
            1 <= weekday <= 7
            and max(start_period, 1) <= min(end_period, 10)
        ):
            active_weekdays.add(weekday)
            has_course = True
    if not has_course:
        active_weekdays = set()

    days = []
    free_slots = []
    for weekday, weekday_label in enumerate(WEEKDAY_LABELS, start=1):
        if weekday not in active_weekdays:
            continue
        slots = []
        for start_period, end_period in PERIOD_GROUPS:
            busy_weeks = set()
            for course in courses or []:
                try:
                    course_weekday = int(course.get("weekday"))
                    course_start = int(course.get("start_period"))
                    course_end = int(course.get("end_period"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if course_weekday != weekday:
                    continue
                if max(start_period, course_start) > min(
                    end_period,
                    course_end,
                ):
                    continue
                busy_weeks.update(
                    week
                    for week in week_numbers
                    if course_occurs_in_week(course.get("weeks"), week)
                )

            free_weeks = [
                week for week in week_numbers if week not in busy_weeks
            ]
            if not free_weeks:
                continue
            availability_label = _format_weeks(free_weeks, week_count)
            period_label = f"{start_period}-{end_period}节"
            slot = {
                "weekday": weekday,
                "weekday_label": weekday_label,
                "start_period": start_period,
                "end_period": end_period,
                "period_label": period_label,
                "free_weeks": free_weeks,
                "availability_label": availability_label,
                "label": f"{weekday_label}{period_label}{availability_label}",
            }
            slots.append(slot)
            free_slots.append(slot)
        slots.sort(
            key=lambda slot: (
                slot["availability_label"] != "全周空",
                slot["start_period"],
            )
        )
        if slots:
            days.append(
                {
                    "weekday": weekday,
                    "weekday_label": weekday_label,
                    "slots": slots,
                }
            )

    return {
        "week_count": week_count,
        "period_groups": [
            {
                "start_period": start_period,
                "end_period": end_period,
                "label": f"{start_period}-{end_period}节",
            }
            for start_period, end_period in PERIOD_GROUPS
        ],
        "basis": "week-specific-overlap",
        "days": days,
        "free_slots": free_slots,
        "total_free_slots": len(free_slots),
    }
