import re
import unicodedata


NAME_MARKER_PATTERN = re.compile(
    r"(?:学生姓名|课表主人|姓名|学生)[:：\s]*([\u4e00-\u9fff·]{2,6})"
)
CHINESE_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fff·]{2,6}$")
BLOCKED_NAMES = {
    "课程表",
    "课表",
    "打印",
    "备注",
    "学生",
    "姓名",
    "星期",
    "节次",
    "时间",
    "教务",
    "系统",
}


def extract_owner_name(ocr_items, image_width, image_height):
    if not ocr_items or image_width <= 0 or image_height <= 0:
        return None

    candidates = []
    for item in ocr_items:
        center_x = float(item.get("center_x") or 0)
        center_y = float(item.get("center_y") or 0)
        if center_x < image_width * 0.55 or center_y < image_height * 0.65:
            continue

        name, marker_matched = _extract_name(item.get("text"))
        if not name:
            continue

        confidence = float(item.get("confidence") or 0)
        length_bonus = 18 if 2 <= len(name) <= 4 else 4
        marker_bonus = 28 if marker_matched else 0
        position_bonus = (
            (center_x / image_width) * 18
            + (center_y / image_height) * 24
        )
        score = confidence * 100 + length_bonus + marker_bonus + position_bonus
        candidates.append(
            {
                "name": name,
                "confidence": round(confidence, 4),
                "source_text": str(item.get("text") or "").strip(),
                "score": round(score, 2),
            }
        )

    if not candidates:
        return None
    best = max(candidates, key=lambda item: item["score"])
    if best["confidence"] < 0.65 and best["score"] < 88:
        return None
    return best


def _extract_name(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return None, False

    marker_match = NAME_MARKER_PATTERN.search(compact)
    if marker_match:
        name = marker_match.group(1).strip("·")
        name = re.sub(r"[的之]?课表$", "", name)
        if _is_plausible_name(name):
            return name, True

    compact = re.sub(r"[的之]?课表$", "", compact)
    compact = re.sub(r"^[（(【\[]|[）)】\]]$", "", compact)
    if _is_plausible_name(compact):
        return compact, False
    return None, False


def _is_plausible_name(value):
    return bool(
        value
        and CHINESE_NAME_PATTERN.fullmatch(value)
        and value not in BLOCKED_NAMES
    )
