import re

import cv2
import numpy as np


WEEKDAY_PATTERN = re.compile(r"(?:周|星期)([一二三四五六日天])")
PERIOD_PATTERN = re.compile(
    r"(?<!\d)(\d{1,2})(?:\s*[-~—－至到]\s*(\d{1,2}))?\s*节?"
)
WEEKDAY_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
}


def extract_table_layout(image_path, ocr_items=None):
    try:
        image_data = np.fromfile(str(image_path), dtype=np.uint8)
    except OSError:
        return None
    image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
    if image is None:
        return None

    original_height, original_width = image.shape[:2]
    max_width = 1800
    scale = min(1.0, max_width / max(original_width, 1))
    if scale < 1.0:
        image = cv2.resize(
            image,
            (max(1, int(original_width * scale)), max(1, int(original_height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    row_positions, column_positions = _detect_grid_lines(gray)
    if len(row_positions) < 3 or len(column_positions) < 3:
        return None

    if scale < 1.0:
        row_positions = [round(position / scale, 1) for position in row_positions]
        column_positions = [
            round(position / scale, 1) for position in column_positions
        ]

    anchor_layout = _layout_from_ocr_anchors(
        row_positions,
        original_width,
        original_height,
        ocr_items or [],
    )
    if anchor_layout:
        return anchor_layout

    cells = _build_cells(column_positions, row_positions, ocr_items or [])
    rows = [
        {
            "index": index,
            "y1": row_positions[index],
            "y2": row_positions[index + 1],
            "texts": _row_texts(cells, index),
        }
        for index in range(len(row_positions) - 1)
    ]
    columns = [
        {
            "index": index,
            "x1": column_positions[index],
            "x2": column_positions[index + 1],
            "texts": _column_texts(cells, index),
        }
        for index in range(len(column_positions) - 1)
    ]

    header_row_index = _find_header_row(rows)
    label_column_indexes = _find_period_label_columns(
        columns, cells, rows, header_row_index
    )
    weekday_columns = _map_weekday_columns(
        columns, cells, header_row_index, label_column_indexes
    )
    period_rows = _map_period_rows(
        rows,
        cells,
        header_row_index,
        label_column_indexes,
    )
    content_cells = _content_cells(
        cells,
        weekday_columns,
        period_rows,
        header_row_index,
        label_column_indexes,
    )
    if not content_cells:
        return None

    return {
        "detected": True,
        "grid": {
            "row_count": len(rows),
            "column_count": len(columns),
        },
        "header_row_index": header_row_index,
        "label_column_indexes": sorted(label_column_indexes),
        "weekday_columns": weekday_columns,
        "period_rows": period_rows,
        "content_cells": content_cells,
        "source_ocr_item_count": len(ocr_items or []),
    }


def _detect_grid_lines(gray):
    edges = cv2.Canny(gray, 40, 120)
    height, width = gray.shape
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=70,
        minLineLength=max(30, int(width * 0.12)),
        maxLineGap=12,
    )
    horizontal_segments = []
    vertical_segments = []
    for line in lines if lines is not None else []:
        x1, y1, x2, y2 = [int(value) for value in line[0]]
        delta_x = abs(x2 - x1)
        delta_y = abs(y2 - y1)
        if delta_y <= 4 and delta_x >= width * 0.18:
            horizontal_segments.append((round((y1 + y2) / 2), delta_x))
        elif delta_x <= 4 and delta_y >= height * 0.18:
            vertical_segments.append((round((x1 + x2) / 2), delta_y))
    return (
        _cluster_line_segments(horizontal_segments),
        _cluster_line_segments(vertical_segments),
    )


def _cluster_line_segments(segments, max_gap=20):
    if not segments:
        return []
    ordered_segments = sorted(segments)
    clusters = []
    current = [ordered_segments[0]]
    for segment in ordered_segments[1:]:
        if segment[0] - current[-1][0] <= max_gap:
            current.append(segment)
        else:
            clusters.append(_weighted_segment_position(current))
            current = [segment]
    clusters.append(_weighted_segment_position(current))
    return clusters


def _weighted_segment_position(segments):
    total_weight = sum(weight for _position, weight in segments)
    if not total_weight:
        return round(sum(position for position, _weight in segments) / len(segments))
    return round(
        sum(position * weight for position, weight in segments) / total_weight
    )


def _layout_from_ocr_anchors(row_positions, image_width, image_height, ocr_items):
    weekday_items = []
    for item in ocr_items:
        match = WEEKDAY_PATTERN.search(str(item.get("text") or ""))
        if not match:
            continue
        weekday = WEEKDAY_MAP.get(match.group(1))
        if not weekday:
            continue
        weekday_items.append(
            {
                "weekday": weekday,
                "x": _number(item.get("center_x")),
                "y": _number(item.get("center_y")),
            }
        )
    if len(weekday_items) < 4:
        return None

    top_weekday_items = [
        item
        for item in weekday_items
        if item["y"] <= max(80.0, image_height * 0.18)
    ]
    if len(top_weekday_items) >= 4:
        weekday_items = top_weekday_items
    by_weekday = {}
    for item in weekday_items:
        current = by_weekday.get(item["weekday"])
        if current is None or (item["y"], item["x"]) < (
            current["y"],
            current["x"],
        ):
            by_weekday[item["weekday"]] = item
    weekday_items = [
        by_weekday[weekday] for weekday in sorted(by_weekday)
    ]
    if len(weekday_items) < 4:
        return None
    weekday_items.sort(key=lambda item: item["x"])
    spacings = [
        weekday_items[index + 1]["x"] - weekday_items[index]["x"]
        for index in range(len(weekday_items) - 1)
        if weekday_items[index + 1]["x"] > weekday_items[index]["x"]
    ]
    if not spacings:
        return None
    spacing = sorted(spacings)[len(spacings) // 2]
    first_left = max(0.0, weekday_items[0]["x"] - spacing / 2)
    last_right = min(
        float(image_width),
        weekday_items[-1]["x"] + spacing / 2,
    )

    weekday_columns = []
    for index, item in enumerate(weekday_items):
        if index == 0:
            x1 = first_left
        else:
            x1 = (
                weekday_items[index - 1]["x"] + item["x"]
            ) / 2
        if index == len(weekday_items) - 1:
            x2 = last_right
        else:
            x2 = (
                item["x"] + weekday_items[index + 1]["x"]
            ) / 2
        weekday_columns.append(
            {
                "column": index,
                "weekday": item["weekday"],
                "label": _weekday_label(item["weekday"]),
                "x1": round(x1, 1),
                "x2": round(x2, 1),
            }
        )

    header_y = sorted(item["y"] for item in weekday_items)[
        len(weekday_items) // 2
    ]
    header_bottom = next(
        (position for position in row_positions if position > header_y + 4),
        header_y + max(30.0, image_height * 0.03),
    )
    table_bottom = max(row_positions[-1], header_bottom + 1) if row_positions else image_height
    period_anchors = _period_anchors(
        ocr_items,
        header_bottom,
        first_left + max(8.0, spacing * 0.08),
    )
    if len(period_anchors) >= 2:
        row_boundaries = [header_bottom]
        for index in range(len(period_anchors) - 1):
            row_boundaries.append(
                round(
                    (
                        period_anchors[index]["y"]
                        + period_anchors[index + 1]["y"]
                    )
                    / 2,
                    1,
                )
            )
        row_boundaries.append(round(table_bottom, 1))
    else:
        row_boundaries = [
            position for position in row_positions if position >= header_bottom
        ]
        if row_boundaries and row_boundaries[-1] < table_bottom:
            row_boundaries.append(round(table_bottom, 1))
    if len(row_boundaries) < 2:
        return None

    period_rows = []
    for index in range(len(row_boundaries) - 1):
        y1 = row_boundaries[index]
        y2 = row_boundaries[index + 1]
        anchor = next(
            (
                item
                for item in period_anchors
                if y1 <= item["y"] <= y2
            ),
            None,
        )
        if anchor:
            start_period, end_period = anchor["period"]
        else:
            start_period = end_period = index + 1
        period_rows.append(
            {
                "row": index,
                "start_period": start_period,
                "end_period": end_period,
                "label": anchor["text"] if anchor else "",
                "y1": round(y1, 1),
                "y2": round(y2, 1),
            }
        )

    content_cells = []
    for row in period_rows:
        for column in weekday_columns:
            texts = []
            items = []
            for item in ocr_items:
                center_x = _number(item.get("center_x"))
                center_y = _number(item.get("center_y"))
                if (
                    column["x1"] + 3 <= center_x <= column["x2"] - 3
                    and row["y1"] + 3 <= center_y <= row["y2"] - 3
                ):
                    text = str(item.get("text") or "").strip()
                    if text:
                        texts.append(text)
                        items.append(item)
            if not texts:
                continue
            content_cells.append(
                {
                    "row": row["row"],
                    "column": column["column"],
                    "weekday": column["weekday"],
                    "start_period": row["start_period"],
                    "end_period": row["end_period"],
                    "period_label": row["label"],
                    "texts": texts,
                    "confidence": round(
                        min(
                            [_number(item.get("confidence"), 1.0) for item in items]
                        ),
                        4,
                    ),
                }
            )
    if not content_cells:
        return None
    return {
        "detected": True,
        "method": "ocr-anchors",
        "grid": {
            "row_count": len(period_rows),
            "column_count": len(weekday_columns),
        },
        "header_row_index": 0,
        "label_column_indexes": [0],
        "weekday_columns": [
            {
                "column": column["column"],
                "weekday": column["weekday"],
                "label": column["label"],
            }
            for column in weekday_columns
        ],
        "period_rows": period_rows,
        "content_cells": content_cells,
        "source_ocr_item_count": len(ocr_items),
    }


def _period_anchors(ocr_items, header_bottom, label_column_right):
    anchors = []
    for item in ocr_items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        x = _number(item.get("center_x"))
        y = _number(item.get("center_y"))
        if x > label_column_right or y < header_bottom - 8:
            continue
        period = _parse_chinese_period(text)
        if not period:
            continue
        anchors.append({"text": text, "x": x, "y": y, "period": period})
    anchors.sort(key=lambda item: item["y"])
    deduplicated = []
    for anchor in anchors:
        if (
            deduplicated
            and anchor["period"] == deduplicated[-1]["period"]
            and abs(anchor["y"] - deduplicated[-1]["y"]) < 40
        ):
            continue
        deduplicated.append(anchor)
    return deduplicated


def _parse_chinese_period(text):
    match = re.search(r"第([一二三四五六七八九十]+)", text)
    if not match:
        return None
    sequence = match.group(1)
    values = []
    for character in sequence:
        value = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }.get(character)
        if value:
            values.append(value)
    if not values:
        return None
    return min(values), max(values)


def _weekday_label(weekday):
    return f"周{'一二三四五六日'[weekday - 1]}"


def _build_cells(column_positions, row_positions, ocr_items):
    cells = []
    for row_index in range(len(row_positions) - 1):
        y1 = row_positions[row_index]
        y2 = row_positions[row_index + 1]
        for column_index in range(len(column_positions) - 1):
            x1 = column_positions[column_index]
            x2 = column_positions[column_index + 1]
            inset_x = min(max(3.0, (x2 - x1) * 0.04), 10.0)
            inset_y = min(max(3.0, (y2 - y1) * 0.04), 10.0)
            items = []
            for item in ocr_items:
                center_x = _number(item.get("center_x"))
                center_y = _number(item.get("center_y"))
                if (
                    x1 + inset_x <= center_x <= x2 - inset_x
                    and y1 + inset_y <= center_y <= y2 - inset_y
                ):
                    items.append(item)
            items.sort(key=lambda item: (_number(item.get("center_y")), _number(item.get("center_x"))))
            cells.append(
                {
                    "row": row_index,
                    "column": column_index,
                    "x1": round(x1, 1),
                    "y1": round(y1, 1),
                    "x2": round(x2, 1),
                    "y2": round(y2, 1),
                    "items": items,
                    "texts": [
                        str(item.get("text") or "").strip()
                        for item in items
                        if str(item.get("text") or "").strip()
                    ],
                }
            )
    return cells


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_texts(cells, row_index):
    return [
        text
        for cell in cells
        if cell["row"] == row_index
        for text in cell["texts"]
    ]


def _column_texts(cells, column_index):
    return [
        text
        for cell in cells
        if cell["column"] == column_index
        for text in cell["texts"]
    ]


def _find_header_row(rows):
    best_index = 0
    best_score = 0
    for row in rows[: min(3, len(rows))]:
        score = sum(1 for text in row["texts"] if WEEKDAY_PATTERN.search(text))
        if score > best_score:
            best_score = score
            best_index = row["index"]

    if best_score >= 2:
        return min(best_index + 1, len(rows))
    return 1 if rows else 0


def _parse_period(text):
    matches = PERIOD_PATTERN.findall(text)
    if not matches:
        return None
    start_values = []
    end_values = []
    for start, end in matches:
        start_value = int(start)
        end_value = int(end or start)
        if 1 <= start_value <= 12 and 1 <= end_value <= 12:
            start_values.append(min(start_value, end_value))
            end_values.append(max(start_value, end_value))
    if not start_values:
        return None
    return min(start_values), max(end_values)


def _find_period_label_columns(columns, cells, rows, header_row_index):
    period_column_candidates = []
    for column_index in range(min(3, len(columns))):
        count = 0
        for row_index in range(header_row_index, len(rows)):
            text = _cell_text(cells, column_index, row_index)
            if _parse_period(text):
                count += 1
        if count >= 2:
            period_column_candidates.append(column_index)
    return period_column_candidates or [0]


def _cell_text(cells, column_index, row_index):
    for cell in cells:
        if cell["row"] == row_index and cell["column"] == column_index:
            return " ".join(cell["texts"])
    return ""


def _map_weekday_columns(columns, cells, header_row_index, label_columns):
    mapped = {}
    for column in columns:
        if column["index"] in label_columns:
            continue
        header_texts = []
        start = max(0, header_row_index - 2)
        for row_index in range(start, header_row_index):
            for cell in cells:
                if (
                    cell["row"] == row_index
                    and cell["column"] == column["index"]
                ):
                    header_texts.extend(cell["texts"])
        for text in header_texts:
            match = WEEKDAY_PATTERN.search(text)
            if match:
                mapped[column["index"]] = WEEKDAY_MAP[match.group(1)]
                break
    if not mapped:
        content_columns = [
            column["index"]
            for column in columns
            if column["index"] not in label_columns
        ]
        for weekday, column_index in enumerate(content_columns[:7], start=1):
            mapped[column_index] = weekday
    elif mapped:
        known_columns = sorted(mapped)
        for column in columns:
            column_index = column["index"]
            if column_index in label_columns or column_index in mapped:
                continue
            nearest = min(
                known_columns,
                key=lambda known: abs(known - column_index),
            )
            mapped[column_index] = mapped[nearest]
    return [
        {
            "column": column["index"],
            "weekday": mapped.get(column["index"]),
            "label": " ".join(column["texts"][:3]),
        }
        for column in columns
        if column["index"] not in label_columns
    ]


def _map_period_rows(rows, cells, header_row_index, label_columns):
    mapped = []
    for row_index in range(header_row_index, len(rows)):
        texts = [
            text
            for column_index in label_columns
            for text in _cell_text(cells, column_index, row_index).split()
        ]
        parsed = _parse_period(" ".join(texts))
        fallback_period = row_index - header_row_index + 1
        start_period = parsed[0] if parsed else fallback_period
        end_period = parsed[1] if parsed else fallback_period
        mapped.append(
            {
                "row": row_index,
                "start_period": start_period,
                "end_period": end_period,
                "label": " ".join(texts),
            }
        )
    return mapped


def _content_cells(
    cells,
    weekday_columns,
    period_rows,
    header_row_index,
    label_columns,
):
    weekday_by_column = {
        item["column"]: item["weekday"]
        for item in weekday_columns
        if item.get("weekday")
    }
    period_by_row = {
        item["row"]: (item["start_period"], item["end_period"], item["label"])
        for item in period_rows
    }
    content = []
    for cell in cells:
        if cell["row"] < header_row_index or cell["column"] in label_columns:
            continue
        texts = [text for text in cell["texts"] if text]
        if not texts:
            continue
        period = period_by_row.get(cell["row"], (None, None, ""))
        content.append(
            {
                "row": cell["row"],
                "column": cell["column"],
                "weekday": weekday_by_column.get(cell["column"]),
                "start_period": period[0],
                "end_period": period[1],
                "period_label": period[2],
                "texts": texts,
                "confidence": round(
                    min(
                        [
                            _number(item.get("confidence"), 1.0)
                            for item in cell["items"]
                        ]
                        or [1.0]
                    ),
                    4,
                ),
            }
        )
    return content
