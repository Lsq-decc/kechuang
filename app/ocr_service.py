import logging
import os
import threading
from pathlib import Path

from flask import current_app


logger = logging.getLogger(__name__)
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()
_engine = None
_engine_key = None


class OCRUnavailable(RuntimeError):
    pass


def _create_paddle_engine():
    runtime_home = Path(current_app.config["PADDLE_RUNTIME_HOME"]).resolve()
    runtime_home.mkdir(parents=True, exist_ok=True)
    # PaddlePaddle and PaddleOCR both call expanduser("~") during import.
    # Point that cache at the project directory, which is writable in this app.
    os.environ["USERPROFILE"] = str(runtime_home)
    os.environ["HOME"] = str(runtime_home)

    try:
        from paddleocr import PaddleOCR
    except Exception as exc:
        raise OCRUnavailable(
            "未安装 PaddleOCR。请执行 pip install -r requirements-ocr.txt"
        ) from exc

    attempts = (
        {
            "use_angle_cls": True,
            "lang": "ch",
            "show_log": False,
            "use_gpu": False,
        },
        {"use_textline_orientation": True, "lang": "ch"},
        {"lang": "ch"},
    )
    last_error = None
    for kwargs in attempts:
        try:
            logger.info("Initializing PaddleOCR with options: %s", kwargs)
            return PaddleOCR(**kwargs)
        except (TypeError, ValueError) as exc:
            last_error = exc
    raise OCRUnavailable(f"PaddleOCR 初始化失败：{last_error}")


def get_engine():
    global _engine, _engine_key

    if current_app.config.get("OCR_ENGINE") != "paddle":
        raise OCRUnavailable("当前 OCR_ENGINE 未配置为 paddle")

    key = (current_app.config.get("OCR_ENGINE"), os.getenv("PADDLE_OCR_LANG", "ch"))
    with _engine_lock:
        if _engine is None or _engine_key != key:
            _engine = _create_paddle_engine()
            _engine_key = key
    return _engine


def recognize_image(image_path):
    """Run PaddleOCR and return normalized text boxes plus plain text."""
    engine = get_engine()
    with _inference_lock:
        try:
            raw_result = engine.ocr(str(image_path), cls=True)
        except TypeError:
            raw_result = engine.ocr(str(image_path))

    items = _normalize_result(raw_result)
    text = "\n".join(item["text"] for item in items if item["text"])
    return items, text


def _normalize_result(raw_result):
    if raw_result is None:
        return []

    if isinstance(raw_result, dict):
        raw_result = [raw_result]

    items = []
    for page in raw_result or []:
        if isinstance(page, dict):
            items.extend(_normalize_v3_page(page))
            continue
        if not page:
            continue
        for line in page:
            try:
                box, recognition = line
                text, confidence = recognition
            except (TypeError, ValueError):
                continue
            normalized_box = _normalize_box(box)
            if not text:
                continue
            items.append(
                {
                    "text": str(text).strip(),
                    "confidence": round(float(confidence or 0), 4),
                    "box": normalized_box,
                    "center_x": _box_center(normalized_box, 0),
                    "center_y": _box_center(normalized_box, 1),
                }
            )
    return items


def _normalize_v3_page(page):
    texts = page.get("rec_texts") or []
    scores = page.get("rec_scores") or []
    boxes = page.get("rec_polys")
    if boxes is None:
        boxes = page.get("dt_polys") or []

    items = []
    for index, text in enumerate(texts):
        box = boxes[index] if index < len(boxes) else []
        normalized_box = _normalize_box(box)
        confidence = scores[index] if index < len(scores) else 0
        items.append(
            {
                "text": str(text).strip(),
                "confidence": round(float(confidence or 0), 4),
                "box": normalized_box,
                "center_x": _box_center(normalized_box, 0),
                "center_y": _box_center(normalized_box, 1),
            }
        )
    return items


def _normalize_box(box):
    if box is None:
        return []
    if hasattr(box, "tolist"):
        box = box.tolist()
    normalized = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        try:
            normalized.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError, IndexError):
            continue
    return normalized


def _box_center(box, axis):
    if not box:
        return 0.0
    return round(sum(point[axis] for point in box) / len(box), 2)
