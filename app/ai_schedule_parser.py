import json
import re

import requests
from flask import current_app


class AIParserUnavailable(RuntimeError):
    pass


class AIParserError(RuntimeError):
    pass


WEEK_RANGE_PATTERN = re.compile(
    r"(\d{1,2})\s*[-~—－至到]\s*(\d{1,2})\s*[（(]?\s*周"
)
WEEK_LIST_PATTERN = re.compile(
    r"((?:\d{1,2}\s*[,，、]\s*)+\d{1,2})\s*[（(]?\s*周"
)
PERIOD_TAG_PATTERN = re.compile(
    r"\[\s*(\d{1,2})\s*[-~—－至到]\s*(\d{1,2})\s*节\s*\]"
)
PERIOD_BLOCKS = ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10))


SYSTEM_PROMPT = """你是高校课表截图的结构化解析器。

你会收到 PaddleOCR 从课表图片中提取的文字片段。每个片段是紧凑数组：
[text, x, y, w, h, confidence]
- text：识别文字
- x、y：文字中心点坐标
- w、h：文字框宽高
- confidence：OCR 置信度

坐标原点在图片左上角，x 向右增大，y 向下增大。课表通常按横向排列星期，
按纵向排列节次；合并单元格中的课程可能跨多个节次。

请只输出一个 JSON 对象，不要输出 Markdown、解释或代码块：
{
  "courses": [
    {
      "weekday": 1,
      "start_period": 1,
      "end_period": 2,
      "course_name": "课程名称",
      "weeks": "1-16周",
      "location": "地点",
      "note": "",
      "confidence": 0.92,
      "source_texts": ["用于判断该课程的 OCR 原文"]
    }
  ]
}

解析规则：
1. weekday 使用 1-7，分别代表周一至周日；start_period 和 end_period 使用 1-12。
2. 文字中明确写明星期或节次时优先采用文字信息。
3. 文字不完整时，根据课程块与星期表头、节次标签的横纵坐标关系推断。
4. weeks 只保留“1-16周”“单周”“双周”等周数信息；无法判断时留空。
5. location 和 note 无法判断时留空，不要编造。
6. 一个课程块只输出一条课程，不要拆出重复行。
7. 忽略页面标题、页码、按钮、水印等与课程无关的文字。
8. 不确定的内容宁可降低 confidence，也不要虚构课程。
9. 最多输出 200 条课程。
"""

CELL_SYSTEM_PROMPT = """你是高校课表单元格解析器。

系统已经先检测课表网格，并把每个小格内部的 OCR 文字整理为：
{
  "weekday": 1,
  "start_period": 1,
  "end_period": 2,
  "texts": ["课程名称", "教师", "1-16周", "教3-101"]
}

其中 weekday、start_period、end_period 已经由单元格在课表中的位置确定。
你只需要分析 texts，不要重新判断课表边框、星期表头或节次表头。

只输出一个 JSON 对象：
{
  "courses": [
    {
      "weekday": 1,
      "start_period": 1,
      "end_period": 2,
      "course_name": "课程名称",
      "weeks": "1-16周",
      "location": "教3-101",
      "note": "教师或其他有效备注",
      "confidence": 0.95,
      "source_texts": ["单元格 OCR 原文"]
    }
  ]
}

规则：
1. 每个有有效课程内容的单元格最多输出一条课程。
2. 保留输入中的 weekday、start_period 和 end_period。
3. 忽略只有时间、节次标签、表头、边框、水印或页码的单元格。
4. 课程名称通常是单元格中最主要的课程标题，不要输出教师姓名作为课程名称。
5. 周数通常形如“1-16周”“1-16(周)[01-02节]”“单周”“双周”，请只保留周数部分。
6. 地点通常包含“教”“楼”“室”“馆”“区”等字样。
7. 教师姓名和无法归类的有效内容可以放入 note。
8. 不确定时降低 confidence，不要虚构。
9. 最多输出 200 条课程。
"""


def is_enabled():
    return bool(
        current_app.config.get("AI_PARSER_ENABLED")
        and current_app.config.get("DEEPSEEK_API_KEY")
        and current_app.config.get("DEEPSEEK_MODEL")
    )


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _box_center_and_size(item):
    box = item.get("box") or []
    points = []
    for point in box:
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if not points:
        x = _number(item.get("center_x"))
        y = _number(item.get("center_y"))
        return x, y, 0.0, 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        max(xs) - min(xs),
        max(ys) - min(ys),
    )


def _compact_ocr_items(raw_items):
    compact = []
    seen = set()
    for item in raw_items or []:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        center_x, center_y, width, height = _box_center_and_size(item)
        dedupe_key = (
            text,
            round(center_x / 4),
            round(center_y / 4),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        compact.append(
            {
                "text": text[:300],
                "x": round(center_x, 1),
                "y": round(center_y, 1),
                "w": round(width, 1),
                "h": round(height, 1),
                "confidence": round(
                    min(max(_number(item.get("confidence")), 0.0), 1.0), 3
                ),
            }
        )

    compact.sort(key=lambda item: (item["y"], item["x"]))
    max_items = max(
        int(current_app.config.get("AI_PARSER_MAX_ITEMS", 400)), 50
    )
    truncated = len(compact) > max_items
    if truncated:
        compact = compact[:max_items]

    image_width = max(
        (item["x"] + item["w"] / 2 for item in compact),
        default=0,
    )
    image_height = max(
        (item["y"] + item["h"] / 2 for item in compact),
        default=0,
    )
    return {
        "estimated_image_width": round(image_width, 1),
        "estimated_image_height": round(image_height, 1),
        "truncated": truncated,
        "items": [
            [
                item["text"],
                item["x"],
                item["y"],
                item["w"],
                item["h"],
                item["confidence"],
            ]
            for item in compact
        ],
    }


def _request_completion(payload):
    config = current_app.config
    url = f"{config['DEEPSEEK_BASE_URL']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['DEEPSEEK_API_KEY']}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=config["DEEPSEEK_TIMEOUT"],
    )
    if (
        response.status_code == 400
        and "response_format" in response.text.lower()
        and "response_format" in payload
    ):
        fallback_payload = dict(payload)
        fallback_payload.pop("response_format", None)
        response = requests.post(
            url,
            headers=headers,
            json=fallback_payload,
            timeout=config["DEEPSEEK_TIMEOUT"],
        )
    if response.status_code >= 400:
        raise AIParserError(
            f"DeepSeek 请求失败（{response.status_code}）：{response.text[:300]}"
        )
    return response.json()


def _extract_json_object(content):
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AIParserError("DeepSeek 未返回有效 JSON")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIParserError("DeepSeek 返回的 JSON 无法解析") from exc


def ensure_course_weeks(course):
    normalized = dict(course)
    weeks = str(normalized.get("weeks") or "").strip()
    if weeks:
        range_match = WEEK_RANGE_PATTERN.search(weeks)
        if range_match:
            normalized["weeks"] = (
                f"{int(range_match.group(1))}-{int(range_match.group(2))}周"
            )
            return normalized
        list_match = WEEK_LIST_PATTERN.search(weeks)
        if list_match:
            numbers = re.findall(r"\d{1,2}", list_match.group(1))
            normalized["weeks"] = (
                ",".join(str(int(number)) for number in numbers) + "周"
            )
            return normalized
        return normalized

    source_text = " ".join(
        str(value)
        for value in [
            *(normalized.get("source_texts") or []),
            normalized.get("note") or "",
        ]
    )
    range_match = WEEK_RANGE_PATTERN.search(source_text)
    if range_match:
        normalized["weeks"] = (
            f"{int(range_match.group(1))}-{int(range_match.group(2))}周"
        )
        return normalized

    list_match = WEEK_LIST_PATTERN.search(source_text)
    if list_match:
        numbers = re.findall(r"\d{1,2}", list_match.group(1))
        normalized["weeks"] = ",".join(str(int(number)) for number in numbers) + "周"
        return normalized
    if "单周" in source_text:
        normalized["weeks"] = "单周"
        return normalized
    if "双周" in source_text:
        normalized["weeks"] = "双周"
        return normalized
    normalized["weeks"] = "每周"
    return normalized


def normalize_course_fields(course):
    normalized = ensure_course_weeks(course)
    diagnostic_flags = []
    try:
        original_start = int(normalized.get("start_period"))
        original_end = int(normalized.get("end_period"))
    except (TypeError, ValueError):
        original_start = 0
        original_end = 0
    source_text = " ".join(
        str(value)
        for value in [
            normalized.get("note") or "",
            normalized.get("weeks") or "",
            *(normalized.get("source_texts") or []),
        ]
    )
    period_match = PERIOD_TAG_PATTERN.search(source_text)
    if period_match:
        start_period = int(period_match.group(1))
        end_period = int(period_match.group(2))
        if (
            1 <= start_period <= 12
            and 1 <= end_period <= 12
            and start_period <= end_period
        ):
            normalized["start_period"] = start_period
            normalized["end_period"] = end_period
    try:
        start_period = int(normalized.get("start_period"))
        end_period = int(normalized.get("end_period"))
    except (TypeError, ValueError):
        start_period = 0
        end_period = 0
    if original_start > 10 or original_end > 10:
        diagnostic_flags.append("节次超出1-10，已自动归入课程块")
    block = _period_block(start_period, end_period)
    if block:
        if (start_period, end_period) != block:
            diagnostic_flags.append("节次已按1-2、3-4、5-6、7-8、9-10归并")
        normalized["start_period"], normalized["end_period"] = block
    else:
        diagnostic_flags.append("节次无法确定，需要人工确认")
    normalized["_diagnostic_flags"] = diagnostic_flags
    return normalized


def _period_block(start_period, end_period):
    if start_period <= 0 or end_period <= 0:
        return None
    start_period = min(start_period, 10)
    end_period = min(max(end_period, start_period), 10)
    midpoint = (start_period + end_period) / 2
    for block_start, block_end in PERIOD_BLOCKS:
        if block_start <= start_period <= block_end:
            return block_start, block_end
        if block_start <= end_period <= block_end:
            return block_start, block_end
    for block_start, block_end in PERIOD_BLOCKS:
        if block_start <= midpoint <= block_end:
            return block_start, block_end
    return PERIOD_BLOCKS[-1]


def parse_schedule_with_deepseek(raw_items, cell_layout=None):
    if not is_enabled():
        raise AIParserUnavailable("DeepSeek 文本解析未启用")

    content_cells = (cell_layout or {}).get("content_cells") or []
    use_cell_layout = bool(content_cells)
    if use_cell_layout:
        user_payload = {
            "table_cells": [
                {
                    "weekday": cell.get("weekday"),
                    "start_period": cell.get("start_period"),
                    "end_period": cell.get("end_period"),
                    "texts": cell.get("texts") or [],
                }
                for cell in content_cells
            ]
        }
        system_prompt = CELL_SYSTEM_PROMPT
        prompt_metadata = {
            "layout_method": cell_layout.get("method") or "cells",
            "cell_count": len(content_cells),
        }
    else:
        compact = _compact_ocr_items(raw_items)
        if not compact["items"]:
            raise AIParserError("OCR 没有可交给 DeepSeek 解析的文字片段")
        user_payload = {"ocr_layout": compact}
        system_prompt = SYSTEM_PROMPT
        prompt_metadata = {
            "ocr_item_count": len(compact["items"]),
            "ocr_items_truncated": compact["truncated"],
        }

    payload = {
        "model": current_app.config["DEEPSEEK_MODEL"],
        "temperature": 0.1,
        "max_tokens": current_app.config["DEEPSEEK_MAX_TOKENS"],
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
    }
    response_data = _request_completion(payload)
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIParserError("DeepSeek 响应缺少 choices.message.content") from exc

    parsed = _extract_json_object(content)
    if isinstance(parsed, list):
        courses = parsed
    elif isinstance(parsed, dict):
        courses = parsed.get("courses")
    else:
        courses = None
    if not isinstance(courses, list):
        raise AIParserError("DeepSeek JSON 中缺少 courses 数组")

    courses = [normalize_course_fields(course) for course in courses[:200]]
    metadata = {
        "provider": "deepseek",
        "model": current_app.config["DEEPSEEK_MODEL"],
        "parser_mode": "cell-layout" if use_cell_layout else "raw-ocr",
        "usage": response_data.get("usage") or {},
        **prompt_metadata,
    }
    return courses, metadata
