import json
from io import BytesIO

from PIL import Image

from app.extensions import db
from app.models import User


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self.payload


def make_png():
    buffer = BytesIO()
    Image.new("RGB", (800, 500), "white").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def create_admin(app, username="ai_admin", student_id="ai_admin"):
    with app.app_context():
        admin = User(
            username=username,
            name="AI测试管理员",
            student_id=student_id,
            department="测试中心",
            role=User.ROLE_ADMIN,
        )
        admin.set_password("password123")
        db.session.add(admin)
        db.session.commit()


def enable_ai(app):
    app.config.update(
        {
            "AI_PARSER_ENABLED": True,
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_MODEL": "deepseek-chat",
            "DEEPSEEK_TIMEOUT": 10,
            "DEEPSEEK_MAX_TOKENS": 2048,
            "AI_PARSER_MAX_ITEMS": 400,
        }
    )


def test_deepseek_parser_uses_compact_ocr_layout(app, monkeypatch):
    from app import ai_schedule_parser

    enable_ai(app)
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"courses":[{"weekday":1,"start_period":1,'
                                '"end_period":2,"course_name":"高等数学",'
                                '"weeks":"1-16周","location":"教3-101",'
                                '"note":"","confidence":0.95}]}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

    monkeypatch.setattr(ai_schedule_parser.requests, "post", fake_post)
    with app.app_context():
        courses, metadata = ai_schedule_parser.parse_schedule_with_deepseek(
            [
                {
                    "text": "高等数学",
                    "confidence": 0.98,
                    "box": [[400, 190], [520, 190], [520, 220], [400, 220]],
                    "center_x": 460,
                    "center_y": 205,
                },
                {
                    "text": "1-16周",
                    "confidence": 0.96,
                    "box": [[410, 225], [500, 225], [500, 250], [410, 250]],
                    "center_x": 455,
                    "center_y": 237,
                },
            ]
        )

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    user_content = json.loads(captured["payload"]["messages"][1]["content"])
    assert "ocr_text" not in user_content
    assert isinstance(user_content["ocr_layout"]["items"][0], list)
    assert user_content["ocr_layout"]["items"][0][0] == "高等数学"
    assert courses[0]["course_name"] == "高等数学"
    assert metadata["provider"] == "deepseek"
    assert metadata["usage"]["prompt_tokens"] == 100


def test_deepseek_parser_uses_detected_cells(app, monkeypatch):
    from app import ai_schedule_parser

    enable_ai(app)
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["payload"] = json
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"courses":[{"weekday":3,"start_period":5,'
                                '"end_period":6,"course_name":"大学物理",'
                                '"weeks":"1-16周","location":"教4-201",'
                                '"note":"王老师"}]}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 90, "completion_tokens": 45},
            }
        )

    monkeypatch.setattr(ai_schedule_parser.requests, "post", fake_post)
    with app.app_context():
        courses, metadata = ai_schedule_parser.parse_schedule_with_deepseek(
            [],
            cell_layout={
                "method": "ocr-anchors",
                "grid": {"row_count": 1, "column_count": 1},
                "content_cells": [
                    {
                        "weekday": 3,
                        "start_period": 5,
                        "end_period": 6,
                        "texts": ["大学物理", "王老师", "1-16周", "教4-201"],
                    }
                ],
            },
        )

    user_content = json.loads(captured["payload"]["messages"][1]["content"])
    assert "table_cells" in user_content
    assert "ocr_layout" not in user_content
    assert courses[0]["course_name"] == "大学物理"
    assert metadata["parser_mode"] == "cell-layout"
    assert metadata["layout_method"] == "ocr-anchors"


def test_ensure_course_weeks_never_leaves_blank(app):
    from app.ai_schedule_parser import (
        ensure_course_weeks,
        normalize_course_fields,
    )

    course = ensure_course_weeks(
        {
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "course_name": "高等数学",
            "weeks": "",
            "source_texts": ["1-14(周）[01-02节]"],
        }
    )
    assert course["weeks"] == "1-14周"
    assert ensure_course_weeks({"weeks": ""})["weeks"] == "每周"
    corrected = normalize_course_fields(
        {
            "weekday": 3,
            "start_period": 11,
            "end_period": 11,
            "course_name": "大学茶文化",
            "weeks": "1-8(周)",
            "note": "董茜 [09-10节]",
        }
    )
    assert corrected["start_period"] == 9
    assert corrected["end_period"] == 10
    assert corrected["weeks"] == "1-8周"


def test_vision_parser_sends_image_and_requires_weeks(app, monkeypatch, tmp_path):
    from app import vision_schedule_parser

    app.config.update(
        {
            "VISION_PARSER_ENABLED": True,
            "VISION_API_KEY": "vision-test-key",
            "VISION_BASE_URL": "https://vision.example.com/v1",
            "VISION_MODEL": "qwen-vl-max",
            "VISION_TIMEOUT": 30,
            "VISION_MAX_TOKENS": 2048,
            "VISION_MAX_IMAGE_WIDTH": 1200,
        }
    )
    image_path = tmp_path / "schedule.png"
    image_path.write_bytes(make_png().getvalue())
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"courses":[{"weekday":1,"start_period":1,'
                                '"end_period":2,"course_name":"高等数学",'
                                '"weeks":"","location":"教3-101","note":""}]}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 200, "completion_tokens": 50},
            }
        )

    monkeypatch.setattr(vision_schedule_parser.requests, "post", fake_post)
    with app.app_context():
        courses, metadata = vision_schedule_parser.parse_schedule_with_vision(
            image_path
        )

    assert captured["url"] == "https://vision.example.com/v1/chat/completions"
    user_content = captured["payload"]["messages"][1]["content"]
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert courses[0]["weeks"] == "每周"
    assert metadata["provider"] == "vision"


def test_upload_uses_deepseek_parser_when_enabled(app, client, monkeypatch):
    from app import ai_schedule_parser, api

    enable_ai(app)
    create_admin(app)
    monkeypatch.setattr(
        api,
        "recognize_image",
        lambda _path: (
            [
                {
                    "text": "课程块",
                    "confidence": 0.95,
                    "box": [[400, 190], [520, 190], [520, 220], [400, 220]],
                    "center_x": 460,
                    "center_y": 205,
                }
            ],
            "课程块",
        ),
    )
    monkeypatch.setattr(
        api,
        "extract_table_layout",
        lambda _path, _items: {
            "method": "ocr-anchors",
            "grid": {"row_count": 1, "column_count": 1},
            "content_cells": [
                {
                    "weekday": 2,
                    "start_period": 3,
                    "end_period": 4,
                    "texts": ["线性代数", "1-8周", "教1-101"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        ai_schedule_parser.requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"courses":[{"weekday":2,"start_period":1,'
                                '"end_period":2,"course_name":"",'
                                '"weeks":"","location":"","note":""},'
                                '{"weekday":2,"start_period":3,'
                                '"end_period":4,"course_name":"线性代数",'
                                '"weeks":"1-8周","location":"教1-101",'
                                '"note":"AI解析"}]}'
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 40},
            }
        ),
    )
    login_response = client.post(
        "/api/auth/login",
        json={"username": "ai_admin", "password": "password123"},
    )
    assert login_response.status_code == 200

    member_response = client.post(
        "/api/users",
        json={
            "name": "AI测试成员",
            "student_id": "ai_member",
            "department": "测试中心",
            "role": "member",
        },
    )
    assert member_response.status_code == 201
    member_id = member_response.get_json()["user"]["id"]

    upload_response = client.post(
        "/api/schedules/upload",
        data={
            "file": (make_png(), "schedule.png"),
            "target_user_id": str(member_id),
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 201
    payload = upload_response.get_json()
    assert payload["parser"] == "deepseek"
    assert payload["draft_courses"][0]["course_name"] == "线性代数"
    assert len(payload["draft_courses"]) == 1
    assert payload["ai_metadata"]["parser_mode"] == "cell-layout"
    assert "1 个单元格" in payload["warnings"][0]


def test_upload_prefers_vision_parser(app, client, monkeypatch):
    from app import api

    enable_ai(app)
    app.config.update(
        {
            "VISION_PARSER_ENABLED": True,
            "VISION_API_KEY": "vision-test-key",
            "VISION_MODEL": "qwen-vl-max",
        }
    )
    create_admin(app, username="vision_admin", student_id="vision_admin")
    monkeypatch.setattr(
        api,
        "recognize_image",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("PaddleOCR must not run when Qwen succeeds")
        ),
    )
    monkeypatch.setattr(
        api,
        "parse_schedule_with_vision",
        lambda _path: (
            [
                {
                    "weekday": 4,
                    "start_period": 7,
                    "end_period": 8,
                    "course_name": "计算机网络",
                    "weeks": "1-16周",
                    "location": "教5-201",
                    "note": "",
                },
                {
                    "weekday": 5,
                    "start_period": 9,
                    "end_period": 10,
                    "course_name": "待确认课程",
                    "weeks": "",
                    "location": "",
                    "note": "",
                    "confidence": 0.5,
                }
            ],
            {
                "provider": "vision",
                "model": "qwen-vl-max",
                "usage": {},
                "owner_name": "视觉测试成员",
                "raw_content": '{"courses":[]}',
            },
        ),
    )
    monkeypatch.setattr(
        api,
        "parse_schedule_with_deepseek",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("DeepSeek should not be called")
        ),
    )
    login_response = client.post(
        "/api/auth/login",
        json={"username": "vision_admin", "password": "password123"},
    )
    assert login_response.status_code == 200
    member_response = client.post(
        "/api/users",
        json={
            "name": "视觉测试成员",
            "student_id": "vision_member",
            "department": "测试中心",
            "role": "member",
        },
    )
    member_id = member_response.get_json()["user"]["id"]
    upload_response = client.post(
        "/api/schedules/upload",
        data={
            "file": (make_png(), "schedule.png"),
            "target_user_id": str(member_id),
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 201
    payload = upload_response.get_json()
    assert payload["parser"] == "vision"
    assert payload["draft_courses"][0]["course_name"] == "计算机网络"
    suspect = next(
        course
        for course in payload["draft_courses"]
        if course["course_name"] == "待确认课程"
    )
    assert suspect["has_issue"] is True
    assert suspect["weeks"] == "每周"
    assert "识别置信度较低" in suspect["issue_reasons"]
