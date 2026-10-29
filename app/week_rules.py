import re


def course_occurs_in_week(weeks_text, week_number):
    text = (weeks_text or "").strip()
    if not text:
        return True

    odd_only = "单周" in text or "(单)" in text or "（单）" in text
    even_only = "双周" in text or "(双)" in text or "（双）" in text
    if odd_only and week_number % 2 == 0:
        return False
    if even_only and week_number % 2 != 0:
        return False

    ranges = re.findall(
        r"(\d{1,2})\s*[-~—－至到]\s*(\d{1,2})",
        text,
    )
    if ranges:
        return any(
            int(start) <= week_number <= int(end)
            for start, end in ranges
        )

    singles = re.findall(
        r"(?<!\d)(\d{1,2})(?!\s*[-~—－至到]\d)",
        text,
    )
    if singles:
        return week_number in {int(value) for value in singles}

    # Unknown week text is treated conservatively as occupying every week.
    return True
