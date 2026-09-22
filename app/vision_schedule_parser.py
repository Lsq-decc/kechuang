import base64
import json
from io import BytesIO

import requests
from flask import current_app
from PIL import Image

from .ai_schedule_parser import (
    AIParserError,
    AIParserUnavailable,
    _extract_json_object,
    normalize_course_fields,
)


VISION_SYSTEM_PROMPT = """你是高校课表图片识别专家。

请直接查看用户提供的课表图片，按课表网格理解每一门课程所在的小格。
不要识别或输出边框、页码、水印、星期表头、节次表头和无关文字。

只输出一个 JSON 对象，不要输出 Markdown、解释或代码块：
{
  "owner_name": "课表主人姓名，无法判断时为空字符串",
  "courses": [
    {
      "weekday": 1,
      "start_period": 1,
      "end_period": 2,
      "course_name": "课程名称",
      "weeks": "1-16周",
      "location": "地点",
      "note": "教师或其他备注",
      "confidence": 0.95
    }
  ]
}

规则：
1. weekday 使用 1-7，分别代表周一至周日；节次使用 1-12。
2. 每一门课程必须填写 weeks。若图片中确实没有周数，填写“每周”。
3. 周数只保留“1-16周”“1-8周”“单周”“双周”等有效信息。
4. 课程名称必须是该课程的主标题，不要把教师姓名识别成课程名称。
5. 地点通常包含“教”“楼”“室”“馆”“区”等字样。
6. 教师姓名以及其他有效说明放入 note。
7. 合并单元格中的课程要跨正确的节次范围。
8. 不确定时降低 confidence，不要虚构课程。
9. 最多输出 200 条课程。
10. 优先从图片右下角、姓名栏或“学生姓名/姓名”附近读取课表主人。
"""


def is_enabled():
    return bool(
        current_app.config.get("VISION_PARSER_ENABLED")
        and current_app.config.get("VISION_API_KEY")
        and current_app.config.get("VISION_MODEL")
    )


def _image_data_url(image_path):
    max_width = max(int(current_app.config.get("VISION_MAX_IMAGE_WIDTH", 2000)), 800)
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            height = round(image.height * max_width / image.width)
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _request_completion(payload):
    config = current_app.config
    url = f"{config['VISION_BASE_URL'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['VISION_API_KEY']}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=config["VISION_TIMEOUT"],
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
            timeout=config["VISION_TIMEOUT"],
        )
    if response.status_code >= 400:
        raise AIParserError(
            f"视觉模型请求失败（{response.status_code}）：{response.text[:300]}"
        )
    return response.json()


def parse_schedule_with_vision(image_path):
    if not is_enabled():
        raise AIParserUnavailable("视觉模型解析未启用")

    image_url = _image_data_url(image_path)
    payload = {
        "model": current_app.config["VISION_MODEL"],
        "temperature": 0.1,
        "max_tokens": current_app.config["VISION_MAX_TOKENS"],
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "识别这张课表并严格按照 JSON 格式输出全部课程。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ],
    }
    response_data = _request_completion(payload)
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIParserError("视觉模型响应缺少 choices.message.content") from exc

    parsed = _extract_json_object(content)
    if isinstance(parsed, list):
        courses = parsed
        owner_name = ""
    elif isinstance(parsed, dict):
        courses = parsed.get("courses")
        owner_name = str(parsed.get("owner_name") or "").strip()
    else:
        courses = None
        owner_name = ""
    if not isinstance(courses, list):
        raise AIParserError("视觉模型 JSON 中缺少 courses 数组")

    courses = [normalize_course_fields(course) for course in courses[:200]]
    metadata = {
        "provider": "vision",
        "model": current_app.config["VISION_MODEL"],
        "usage": response_data.get("usage") or {},
        "owner_name": owner_name,
        "raw_content": content,
    }
    return courses, metadata
