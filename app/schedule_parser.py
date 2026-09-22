import re
import unicodedata
from collections import Counter


WEEKDAY_ALIASES = {
    "周一": 1,
    "星期一": 1,
    "礼拜一": 1,
    "周二": 2,
    "星期二": 2,
    "礼拜二": 2,
    "周三": 3,
    "星期三": 3,
    "礼拜三": 3,
    "周四": 4,
    "星期四": 4,
    "礼拜四": 4,
    "周四": 4,
    "周五": 5,
    "星期五": 5,
    "礼拜五": 5,
    "周六": 6,
    "星期六": 6,
    "礼拜六": 6,
    "周日": 7,
    "周天": 7,
    "星期日": 7,
    "星期天": 7,
    "礼拜日": 7,
    "礼拜天": 7,
}
SINGLE_WEEKDAY_HEADERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7}
CHINESE_PERIOD_LABELS = {
    "一二": (1, 2),
    "第三四": (3, 4),
    "三四": (3, 4),
    "第五六": (5, 6),
    "五六": (5, 6),
    "第七八": (7, 8),
    "七八": (7, 8),
    "第九十十一": (9, 11),
    "第九十": (9, 10),
    "九十": (9, 10),
}
PERIOD_PATTERN = re.compile(
    r"(?:第\s*)?(\d{1,2})\s*(?:[-~—－至到]\s*(\d{1,2}))?\s*节"
)
ANY_PERIOD_PAIR_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})\s*[-~—－至到]\s*(\d{1,2})(?!\d)"
)
WEEK_PATTERN = re.compile(
    r"(\d{1,2}\s*(?:[-~—－至到]\s*\d{1,2})?"
    r"(?:\s*[,，、]\s*\d{1,2}\s*(?:[-~—－至到]\s*\d{1,2})?)*\s*周)"
)
GENERAL_WEEK_PATTERN = re.compile(
    r"[\d０-９]+(?:[\s,，、.．\-~—－至到]*[\d０-９]+)*"
    r"\s*[（(]?\s*周\s*[）)]?"
)
BRACKET_PATTERN = re.compile(r"[\[【][^\]】]*[\]】]")
LOCATION_PATTERN = re.compile(
    r"(?:教\d+[-－]\d+|教学楼|实验楼|实验室|双创大楼|智慧教室|"
    r"体育馆|体育场|乒乓球场|微机原理实验室)"
)
TIME_RANGE_PATTERN = re.compile(
    r"\d{1,2}\s*[:：]\s*\d{2}\s*[-~—－至到]\s*\d{1,2}\s*[:：]\s*\d{2}"
)
TIME_PATTERN = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})")

TIME_TO_PERIOD = {
    (8, 0): 1,
    (8, 55): 2,
    (10, 5): 3,
    (11, 0): 4,
    (14, 0): 5,
    (14, 55): 6,
    (16, 5): 7,
    (17, 0): 8,
    (18, 30): 9,
    (19, 20): 10,
    (20, 10): 11,
}


def normalize_text(value):
    return unicodedata.normalize("NFKC", str(value or "")).replace("\n", " ").strip()


def compact_text(value):
    return re.sub(r"\s+", "", normalize_text(value))


def detect_weekday(text):
    compact = compact_text(text)
    for alias, weekday in WEEKDAY_ALIASES.items():
        if alias in compact:
            return weekday
    return None


def parse_period_range(text, require_marker=True):
    compact = compact_text(text)
    match = PERIOD_PATTERN.search(compact)
    if match:
        start = int(match.group(1))
        end = int(match.group(2) or start)
        return _valid_period(start, end)

    match = ANY_PERIOD_PAIR_PATTERN.search(compact)
    if match and not WEEK_PATTERN.search(compact):
        return _valid_period(int(match.group(1)), int(match.group(2)))

    if compact.isdigit() and not require_marker:
        period = int(compact)
        return _valid_period(period, period)
    return None


def parse_chinese_period_range(text):
    compact = compact_text(text).replace("第", "").replace("节", "")
    for label, period in sorted(
        CHINESE_PERIOD_LABELS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if label in compact:
            return period
    return None


def parse_time_period(text):
    compact = compact_text(text)
    for hour_text, minute_text in TIME_PATTERN.findall(compact):
        hour, minute = int(hour_text), int(minute_text)
        if (hour, minute) in TIME_TO_PERIOD:
            return TIME_TO_PERIOD[(hour, minute)]
        nearest = min(
            TIME_TO_PERIOD,
            key=lambda value: abs(value[0] * 60 + value[1] - hour * 60 - minute),
        )
        difference = abs(nearest[0] * 60 + nearest[1] - hour * 60 - minute)
        if difference <= 12:
            return TIME_TO_PERIOD[nearest]
    return None


def parse_weeks(text):
    compact = compact_text(text)
    match = WEEK_PATTERN.search(compact)
    weeks = normalize_text(match.group(1)) if match else ""
    if not weeks:
        general_match = GENERAL_WEEK_PATTERN.search(compact)
        weeks = normalize_text(general_match.group(0)) if general_match else ""
    if "单周" in compact or "(单)" in compact:
        weeks = f"{weeks}（单周）" if weeks else "单周"
    elif "双周" in compact or "(双)" in compact:
        weeks = f"{weeks}（双周）" if weeks else "双周"
    return weeks


def clean_course_name(text):
    value = normalize_text(text)
    for alias in sorted(WEEKDAY_ALIASES, key=len, reverse=True):
        value = value.replace(alias, " ")
    value = WEEK_PATTERN.sub(" ", value)
    value = GENERAL_WEEK_PATTERN.sub(" ", value)
    value = PERIOD_PATTERN.sub(" ", value)
    value = ANY_PERIOD_PAIR_PATTERN.sub(" ", value)
    value = BRACKET_PATTERN.sub(" ", value)
    value = TIME_RANGE_PATTERN.sub(" ", value)
    value = TIME_PATTERN.sub(" ", value)
    value = re.sub(r"(?:第\s*)?\d{1,2}\s*节", " ", value)
    value = re.sub(r"[（(]\s*[单双]\s*[）)]", " ", value)
    value = re.sub(r"\b(?:单周|双周)\b", " ", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"^[\-—_:：,，、/|]+|[\-—_:：,，、/|]+$", "", value)
    return value.strip()


def parse_schedule(ocr_items):
    items = _valid_items(ocr_items)
    if not items:
        return [], ["未识别到文字，请手动添加课程。"]

    warnings = []
    weekday_anchors = _find_weekday_anchors(items)
    period_anchors = _find_period_anchors(items)

    if not weekday_anchors:
        warnings.append("未稳定识别星期表头，已按图片横向位置估算星期，请逐条核对。")
    if not period_anchors:
        warnings.append("未稳定识别节次行，已按图片纵向位置估算节次，请逐条核对。")

    table_items = items
    if len(weekday_anchors) >= 5:
        table_top = min(anchor["y"] for anchor in weekday_anchors) - 5
        table_items = [item for item in items if item["center_y"] >= table_top]
        if period_anchors:
            table_bottom = max(anchor["y"] for anchor in period_anchors) + 180
            table_items = [
                item for item in table_items if item["center_y"] <= table_bottom
            ]
        left_edge = min(anchor["x"] for anchor in weekday_anchors) - 70
        right_edge = max(anchor["x"] for anchor in weekday_anchors) + 70
        table_items = [
            item
            for item in table_items
            if left_edge <= item["center_x"] <= right_edge
        ]

    candidates = [
        item
        for item in table_items
        if not _is_anchor_only(item)
        and clean_course_name(item["text"])
        and not _looks_like_metadata(item["text"])
        and _is_probable_course_text(item["text"])
    ]
    if not candidates:
        return [], ["识别到文字，但未提取出课程，请在修正页手动添加。"]

    min_y = min(
        (item["center_y"] for item in table_items if item["center_y"]), default=0
    )
    max_y = max(
        (item["center_y"] for item in table_items if item["center_y"]), default=1
    )
    max_x = max(
        (item["center_x"] for item in table_items if item["center_x"]), default=1
    )

    courses = []
    for item in candidates:
        text = item["text"]
        weekday = detect_weekday(text)
        period = parse_period_range(text)
        weeks = parse_weeks(text)

        if weekday is None:
            weekday = _nearest_weekday(item, weekday_anchors)
        if weekday is None:
            weekday = _estimate_weekday(item["center_x"], max_x)

        if period is None:
            period = parse_time_period(text)
        if period is None:
            period = _nearest_period(item["center_y"], period_anchors)
        if period is None:
            period = _estimate_period(item["center_y"], min_y, max_y)

        start_period, end_period = period
        course_name = clean_course_name(text)
        if not course_name:
            continue

        courses.append(
            {
                "weekday": weekday,
                "start_period": start_period,
                "end_period": end_period,
                "course_name": course_name,
                "weeks": weeks,
                "location": "",
                "note": text,
                "confidence": item["confidence"],
                "source_text": text,
                "_center_x": item["center_x"],
                "_center_y": item["center_y"],
            }
        )

    courses = _deduplicate(courses)
    _enrich_courses(courses, table_items, weekday_anchors, period_anchors)
    courses = _merge_vertical_fragments(courses)
    if not courses:
        warnings.append("未能自动生成课程行，请手动添加。")
    for course in courses:
        course.pop("_center_x", None)
        course.pop("_center_y", None)
    return courses, warnings


def _valid_items(ocr_items):
    items = []
    for item in ocr_items or []:
        text = normalize_text(item.get("text"))
        if not text:
            continue
        items.append(
            {
                "text": text,
                "confidence": float(item.get("confidence") or 0),
                "center_x": float(item.get("center_x") or 0),
                "center_y": float(item.get("center_y") or 0),
                "box": item.get("box") or [],
            }
        )
    return items


def _find_weekday_anchors(items):
    anchors = []
    for item in items:
        text = compact_text(item["text"])
        if len(text) > 5:
            continue
        weekday = None
        for alias, value in WEEKDAY_ALIASES.items():
            if text == alias or text.startswith(alias):
                weekday = value
                break
        if weekday is None and text in SINGLE_WEEKDAY_HEADERS:
            weekday = SINGLE_WEEKDAY_HEADERS[text]
        if weekday is not None:
            anchors.append(
                {
                    "weekday": weekday,
                    "x": item["center_x"],
                    "y": item["center_y"],
                    "confidence": item.get("confidence") or 0,
                }
            )
    return _normalize_weekday_anchors(anchors)


def _find_period_anchors(items):
    anchors = []
    for item in items:
        text = item["text"]
        if WEEK_PATTERN.search(compact_text(text)):
            continue
        period = parse_period_range(text)
        if period is None:
            period = parse_chinese_period_range(text)
        if period is None:
            single_period = parse_time_period(text)
            if single_period is not None:
                period = (single_period, single_period)
        if period is not None:
            anchors.append(
                {
                    "start": period[0],
                    "end": period[1],
                    "y": item["center_y"],
                }
            )
    deduplicated = []
    seen = set()
    for anchor in sorted(anchors, key=lambda value: value["y"]):
        key = (anchor["start"], anchor["end"], round(anchor["y"] / 5))
        if key not in seen:
            deduplicated.append(anchor)
            seen.add(key)
    return deduplicated


def _normalize_weekday_anchors(anchors):
    if not anchors:
        return []

    clusters = []
    for anchor in sorted(anchors, key=lambda value: value["x"]):
        if clusters and abs(anchor["x"] - clusters[-1]["x"]) <= 18:
            cluster = clusters[-1]
            cluster["items"].append(anchor)
            total_weight = sum(max(item["confidence"], 0.1) for item in cluster["items"])
            cluster["x"] = sum(
                item["x"] * max(item["confidence"], 0.1)
                for item in cluster["items"]
            ) / total_weight
            cluster["y"] = sum(
                item["y"] * max(item["confidence"], 0.1)
                for item in cluster["items"]
            ) / total_weight
            continue
        clusters.append(
            {
                "x": anchor["x"],
                "y": anchor["y"],
                "items": [anchor],
            }
        )

    if len(clusters) == 1:
        anchor = clusters[0]
        weekday = max(
            Counter(item["weekday"] for item in anchor["items"]).items(),
            key=lambda value: value[1],
        )[0]
        return [{"weekday": weekday, "x": anchor["x"], "y": anchor["y"]}]

    observed_days = [
        max(
            Counter(item["weekday"] for item in cluster["items"]).items(),
            key=lambda value: value[1],
        )[0]
        for cluster in clusters
    ]
    has_duplicate_days = len(set(observed_days)) != len(observed_days)
    labels_are_sorted = observed_days == sorted(observed_days)

    assigned_days = []
    used_days = set()
    next_day = 1
    for observed_day in observed_days:
        if (
            not has_duplicate_days
            and labels_are_sorted
            and observed_day not in used_days
        ):
            day = observed_day
        else:
            while next_day in used_days:
                next_day += 1
            day = next_day
        day = min(7, max(1, day))
        while day in used_days and day < 7:
            day += 1
        assigned_days.append(day)
        used_days.add(day)
        next_day = day + 1

    normalized = [
        {"weekday": day, "x": cluster["x"], "y": cluster["y"]}
        for day, cluster in zip(assigned_days, clusters)
    ]
    by_day = {anchor["weekday"]: anchor for anchor in normalized}
    if len(by_day) >= 3:
        normalized = _fill_missing_weekday_anchors(by_day)
    return sorted(normalized, key=lambda value: value["x"])


def _fill_missing_weekday_anchors(by_day):
    known_days = sorted(by_day)
    spacings = [
        (by_day[right]["x"] - by_day[left]["x"]) / (right - left)
        for left, right in zip(known_days, known_days[1:])
        if right > left
    ]
    fallback_spacing = (
        sorted(spacings)[len(spacings) // 2] if spacings else 100.0
    )

    complete = []
    for day in range(1, 8):
        if day in by_day:
            complete.append(by_day[day])
            continue

        previous_days = [value for value in known_days if value < day]
        next_days = [value for value in known_days if value > day]
        if previous_days and next_days:
            left_day = max(previous_days)
            right_day = min(next_days)
            ratio = (day - left_day) / (right_day - left_day)
            x = by_day[left_day]["x"] + (
                by_day[right_day]["x"] - by_day[left_day]["x"]
            ) * ratio
            y = by_day[left_day]["y"] + (
                by_day[right_day]["y"] - by_day[left_day]["y"]
            ) * ratio
        elif previous_days:
            left_day = max(previous_days)
            x = by_day[left_day]["x"] + fallback_spacing * (day - left_day)
            y = by_day[left_day]["y"]
        else:
            right_day = min(next_days)
            x = by_day[right_day]["x"] - fallback_spacing * (right_day - day)
            y = by_day[right_day]["y"]
        complete.append({"weekday": day, "x": x, "y": y})
    return complete


def _nearest_weekday(item, anchors):
    if not anchors:
        return None
    ordered = sorted(anchors, key=lambda anchor: anchor["x"])
    if len(ordered) == 1:
        return ordered[0]["weekday"]

    left, right = _item_horizontal_span(item)
    boundaries = [
        (ordered[index]["x"] + ordered[index + 1]["x"]) / 2
        for index in range(len(ordered) - 1)
    ]
    best_anchor = None
    best_overlap = -1.0
    for index, anchor in enumerate(ordered):
        column_left = boundaries[index - 1] if index > 0 else float("-inf")
        column_right = (
            boundaries[index] if index < len(boundaries) else float("inf")
        )
        overlap = max(
            0.0, min(right, column_right) - max(left, column_left)
        )
        if overlap > best_overlap:
            best_anchor = anchor
            best_overlap = overlap
    if best_anchor is not None and best_overlap > 0:
        return best_anchor["weekday"]
    center_x = (left + right) / 2
    return min(ordered, key=lambda anchor: abs(anchor["x"] - center_x))["weekday"]


def _item_horizontal_span(item):
    points = item.get("box") or []
    if points:
        x_values = [float(point[0]) for point in points if len(point) >= 2]
        if x_values:
            return min(x_values), max(x_values)
    center_x = item["center_x"]
    return center_x, center_x


def _nearest_period(center_y, anchors):
    if not anchors:
        return None
    anchor = min(anchors, key=lambda value: abs(value["y"] - center_y))
    return anchor["start"], anchor["end"]


def _estimate_weekday(center_x, max_x):
    if max_x <= 0:
        return 1
    return min(7, max(1, int(center_x / max_x * 7) + 1))


def _estimate_period(center_y, min_y, max_y):
    if max_y <= min_y:
        return 1, 2
    ratio = (center_y - min_y) / (max_y - min_y)
    row = min(4, max(0, int(ratio * 5)))
    return row * 2 + 1, row * 2 + 2


def _is_anchor_only(item):
    text = compact_text(item["text"])
    if len(text) > 8:
        return False
    if text in SINGLE_WEEKDAY_HEADERS:
        return True
    if any(text == alias for alias in WEEKDAY_ALIASES):
        return True
    if PERIOD_PATTERN.fullmatch(text):
        return True
    if parse_chinese_period_range(text):
        return True
    return bool(TIME_RANGE_PATTERN.fullmatch(text))


def _looks_like_metadata(text):
    compact = compact_text(text)
    metadata_words = {
        "课程表",
        "课表",
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
        "上午",
        "下午",
        "晚上",
        "午休",
        "节次",
        "时间",
    }
    if compact in metadata_words:
        return True
    if "星期" in compact and len(compact) <= 4:
        return True
    return False


def _is_probable_course_text(text):
    course_name = clean_course_name(text)
    compact = compact_text(course_name)
    if len(compact) < 2:
        return False
    if re.fullmatch(r"[\d\W_]+", compact):
        return False
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    if chinese_count <= 3 and not re.search(r"[A-Za-z]{2,}\d*|\d{2,}", compact):
        return False
    if compact.startswith(("(", "（")) or (
        compact.endswith((")", "）")) and len(compact) <= 8
    ):
        return False
    if compact in {"男", "女", "打印", "备注：", "备注", "教学评价", "实践环节"}:
        return False
    if re.fullmatch(r"[\[【]?\d{1,2}[-~—－至到]\d{1,2}节[\]】]?", compact):
        return False
    if re.match(
        r"^(?:教\d|教室|实验楼|实验室|双创大楼|智慧教室|体育馆|"
        r"体育场|乒乓球场|微机原理实验室)",
        compact,
    ):
        return False
    navigation_words = {
        "我的桌面",
        "个人中心",
        "学籍成绩",
        "培养管理",
        "考试报名",
        "教学评价",
        "实践环节",
        "消息通知",
        "学期理论课表",
    }
    if any(word in compact for word in navigation_words):
        return False
    return True


def _deduplicate(courses):
    seen = set()
    result = []
    for course in courses:
        key = (
            course["weekday"],
            course["start_period"],
            course["end_period"],
            compact_text(course["course_name"]),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(course)
    return result


def _enrich_courses(courses, items, weekday_anchors, period_anchors):
    max_x = max((item["center_x"] for item in items), default=1)
    for item in items:
        text = item["text"]
        weeks = parse_weeks(text)
        location_match = LOCATION_PATTERN.search(compact_text(text))
        if not weeks and not location_match:
            continue

        weekday = detect_weekday(text)
        if weekday is None:
            weekday = _nearest_weekday(item, weekday_anchors)
        if weekday is None:
            weekday = _estimate_weekday(item["center_x"], max_x)

        period = parse_period_range(text)
        if period is None:
            period = _nearest_period(item["center_y"], period_anchors)

        candidates = [course for course in courses if course["weekday"] == weekday]
        if period:
            same_period = [
                course
                for course in candidates
                if max(period[0], course["start_period"])
                <= min(period[1], course["end_period"])
            ]
            candidates = same_period or candidates
        if not candidates:
            continue

        target = min(
            candidates,
            key=lambda course: abs(course.get("_center_y", 0) - item["center_y"]),
        )
        if abs(target.get("_center_y", 0) - item["center_y"]) > 140:
            continue
        if weeks and not target["weeks"]:
            target["weeks"] = weeks
        if location_match and not target["location"]:
            target["location"] = location_match.group(0)


def _merge_vertical_fragments(courses):
    ordered = sorted(
        courses,
        key=lambda course: (
            course["weekday"],
            course.get("_center_y", 0),
            course["start_period"],
        ),
    )
    merged = []
    for course in ordered:
        if merged:
            previous = merged[-1]
            same_column = previous["weekday"] == course["weekday"]
            nearby = abs(previous.get("_center_y", 0) - course.get("_center_y", 0)) <= 45
            same_row = (
                abs(previous["start_period"] - course["start_period"]) <= 1
                and abs(previous["end_period"] - course["end_period"]) <= 1
            )
            if same_column and nearby and same_row:
                combined_name = f"{previous['course_name']}{course['course_name']}"
                if len(combined_name) <= 150:
                    previous["course_name"] = combined_name
                    previous["start_period"] = min(
                        previous["start_period"], course["start_period"]
                    )
                    previous["end_period"] = max(
                        previous["end_period"], course["end_period"]
                    )
                    previous["weeks"] = previous["weeks"] or course["weeks"]
                    previous["location"] = previous["location"] or course["location"]
                    previous["note"] = f"{previous['note']} | {course['note']}"
                    previous["_center_y"] = (
                        previous.get("_center_y", 0) + course.get("_center_y", 0)
                    ) / 2
                    continue
        merged.append(course)
    return merged


def summarize_periods(items):
    counter = Counter()
    for item in items:
        period = parse_period_range(item.get("text", ""), require_marker=False)
        if period:
            counter[period] += 1
    return counter


def _valid_period(start, end):
    if not 1 <= start <= 12 or not 1 <= end <= 12:
        return None
    if start > end:
        start, end = end, start
    return start, end
