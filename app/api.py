import os
import re
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from .ai_schedule_parser import (
    AIParserError,
    AIParserUnavailable,
    is_enabled as is_ai_parser_enabled,
    normalize_course_fields,
    parse_schedule_with_deepseek,
)
from .decorators import roles_required
from .extensions import db
from .models import (
    AvailabilityOverride,
    Course,
    QueryLog,
    ScheduleUpload,
    User,
    format_period_range,
)
from .ocr_service import OCRUnavailable, recognize_image
from .owner_detection import extract_owner_name
from .schedule_parser import parse_schedule
from .summary_export import build_total_free_xlsx
from .table_layout import extract_table_layout
from .vision_schedule_parser import (
    is_enabled as is_vision_parser_enabled,
    parse_schedule_with_vision,
)


api_bp = Blueprint("api", __name__)


def _ok(data=None, message=None, status=200):
    payload = {"ok": True}
    if message:
        payload["message"] = message
    if data:
        payload.update(data)
    return jsonify(payload), status


def _error(message, status=400):
    return jsonify({"ok": False, "message": message}), status


def _json_body():
    return request.get_json(silent=True) or {}


def _normalize_ai_courses(raw_courses):
    normalized_courses = []
    skipped_count = 0
    seen_courses = set()
    for index, raw_course in enumerate(raw_courses, start=1):
        prepared_course = normalize_course_fields(raw_course)
        diagnostic_flags = list(
            prepared_course.pop("_diagnostic_flags", []) or []
        )
        confidence = prepared_course.get("confidence")
        normalized_course, validation_error = _validate_course(
            prepared_course, index
        )
        if validation_error:
            skipped_count += 1
            continue
        normalized_course = _annotate_course_issues(
            normalized_course,
            diagnostic_flags,
            confidence,
        )
        course_key = (
            normalized_course["weekday"],
            normalized_course["start_period"],
            normalized_course["end_period"],
            normalized_course["course_name"],
            normalized_course["weeks"],
            normalized_course["location"],
            normalized_course["note"],
        )
        if course_key in seen_courses:
            continue
        seen_courses.add(course_key)
        normalized_courses.append(normalized_course)
    normalized_courses.sort(
        key=lambda course: (
            course["weekday"],
            course["start_period"],
            course["end_period"],
        )
    )
    return normalized_courses, skipped_count


def _annotate_course_issues(course, reasons=None, confidence=None):
    annotated = dict(course)
    issue_reasons = list(reasons or [])
    if annotated.get("weeks") in {"", "每周"}:
        issue_reasons.append("未识别具体周数，已按每周处理")
    if not annotated.get("location"):
        issue_reasons.append("未识别地点")
    try:
        confidence_value = float(confidence)
        annotated["confidence"] = round(confidence_value, 4)
        if confidence_value < 0.85:
            issue_reasons.append("识别置信度较低")
    except (TypeError, ValueError):
        pass
    if not (
        1
        <= int(annotated.get("start_period") or 0)
        <= int(annotated.get("end_period") or 0)
        <= 10
    ):
        issue_reasons.append("节次不在1-10范围内")
    unique_reasons = list(dict.fromkeys(issue_reasons))
    annotated["issue_reasons"] = unique_reasons
    annotated["has_issue"] = bool(unique_reasons)
    return annotated


def _allowed_file(filename):
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]


SUMMARY_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
SUMMARY_PERIOD_GROUPS = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]
SUMMARY_PERIOD_LABELS = [
    f"{start_period}-{end_period}"
    for start_period, end_period in SUMMARY_PERIOD_GROUPS
]
SUMMARY_PERIOD_TIMES = {
    "1-2": "08:00-09:40",
    "3-4": "09:55-11:35",
    "5-6": "14:30-16:10",
    "7-8": "16:25-18:05",
    "9-10": "19:00-21:35",
}
COURSE_FIELDS = (
    "weekday",
    "start_period",
    "end_period",
    "course_name",
    "weeks",
    "location",
    "note",
)


def _remove_uploaded_files(file_paths):
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    for image_path in file_paths:
        try:
            file_path = Path(image_path).resolve()
            file_path.relative_to(upload_root)
        except (OSError, ValueError):
            continue
        try:
            file_path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            current_app.logger.warning("Failed to remove uploaded file: %s", file_path)


def _remove_saved_file(file_path):
    try:
        os.remove(file_path)
    except OSError:
        pass


def _form_enabled(name):
    return (request.form.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_auto_owner(owner_detection, default_department):
    owner_name = owner_detection["name"]
    matches = (
        User.query.filter(
            User.name == owner_name,
            User.role != User.ROLE_ADMIN,
        )
        .order_by(User.id.asc())
        .all()
    )
    if len(matches) > 1:
        raise ValueError(f"识别到“{owner_name}”，但成员中存在同名记录，请手工选择")
    if matches:
        return matches[0], False

    username = f"member_{uuid.uuid4().hex[:10]}"
    while User.query.filter_by(username=username).first():
        username = f"member_{uuid.uuid4().hex[:10]}"
    user = User(
        username=username,
        name=owner_name,
        student_id=None,
        department=default_department or "待设置",
        role=User.ROLE_MEMBER,
    )
    user.set_password(uuid.uuid4().hex)
    db.session.add(user)
    db.session.flush()
    return user, True


def _owner_detection_from_vision(ai_metadata):
    name = str((ai_metadata or {}).get("owner_name") or "").strip()
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,6}", name):
        return None
    return {
        "name": name,
        "confidence": 0.95,
        "source_text": "Qwen 视觉模型识别",
        "score": 120.0,
    }


@api_bp.get("/users")
@roles_required(User.ROLE_ADMIN)
def list_users():
    keyword = (request.args.get("keyword") or "").strip()
    query = User.query
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                User.name.like(pattern),
                User.username.like(pattern),
                User.student_id.like(pattern),
                User.department.like(pattern),
            )
        )
    users = query.order_by(User.department.asc(), User.name.asc()).all()
    user_ids = [user.id for user in users]
    course_counts = {}
    if user_ids:
        course_counts = dict(
            db.session.query(Course.user_id, func.count(Course.id))
            .filter(Course.user_id.in_(user_ids))
            .group_by(Course.user_id)
            .all()
        )

    result = []
    for user in users:
        item = user.to_dict()
        item["course_count"] = course_counts.get(user.id, 0)
        result.append(item)
    return _ok({"users": result})


@api_bp.post("/users")
@roles_required(User.ROLE_ADMIN)
def create_user():
    data = _json_body()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip()
    student_id = (data.get("student_id") or "").strip() or None
    department = (data.get("department") or "").strip() or "未设置"
    role = (data.get("role") or User.ROLE_MEMBER).strip()

    if role == User.ROLE_ADMIN and not username:
        return _error("管理员用户名不能为空")
    if username and not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
        return _error("用户名格式不正确")
    if role == User.ROLE_ADMIN and len(password) < 6:
        return _error("密码至少 6 位")
    if not name:
        return _error("姓名不能为空")
    if role not in User.ROLES:
        return _error("角色不正确")
    if username and User.query.filter_by(username=username).first():
        return _error("用户名已存在")
    if student_id and User.query.filter_by(student_id=student_id).first():
        return _error("学号/工号已存在")

    if not username:
        username = f"member_{uuid.uuid4().hex[:10]}"
        while User.query.filter_by(username=username).first():
            username = f"member_{uuid.uuid4().hex[:10]}"

    user = User(
        username=username,
        name=name,
        student_id=student_id,
        department=department,
        role=role,
    )
    user.set_password(password if role == User.ROLE_ADMIN else uuid.uuid4().hex)
    db.session.add(user)
    db.session.commit()
    return _ok({"user": user.to_dict()}, "成员创建成功", 201)


@api_bp.patch("/users/<int:user_id>")
@roles_required(User.ROLE_ADMIN)
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = _json_body()

    if "username" in data:
        username = (data.get("username") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
            return _error("用户名格式不正确")
        existing = User.query.filter_by(username=username).first()
        if existing and existing.id != user.id:
            return _error("用户名已存在")
        user.username = username
    if "name" in data:
        user.name = (data.get("name") or "").strip()
        if not user.name:
            return _error("姓名不能为空")
    if "student_id" in data:
        student_id = (data.get("student_id") or "").strip() or None
        existing = User.query.filter_by(student_id=student_id).first()
        if student_id and existing and existing.id != user.id:
            return _error("学号/工号已存在")
        user.student_id = student_id
    if "department" in data:
        user.department = (data.get("department") or "").strip() or "未设置"
    if "role" in data:
        role = (data.get("role") or "").strip()
        if role not in User.ROLES:
            return _error("角色不正确")
        if user.id == g.current_user.id and role != User.ROLE_ADMIN:
            return _error("不能取消当前登录账号的管理员角色")
        user.role = role
    if data.get("password"):
        if len(data["password"]) < 6:
            return _error("密码至少 6 位")
        user.set_password(data["password"])

    db.session.commit()
    return _ok({"user": user.to_dict()}, "成员信息已更新")


@api_bp.delete("/users/<int:user_id>")
@roles_required(User.ROLE_ADMIN)
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == g.current_user.id:
        return _error("不能删除当前登录账号")

    upload_paths = [upload.image_path for upload in user.uploads]
    QueryLog.query.filter_by(operator_id=user.id).update(
        {"operator_id": None}, synchronize_session=False
    )
    db.session.delete(user)
    db.session.commit()
    _remove_uploaded_files(upload_paths)
    return _ok(message="账号及其课表已删除")


@api_bp.post("/schedules/upload")
@roles_required(User.ROLE_ADMIN)
def upload_schedule_image():
    upload_file = request.files.get("file")
    if not upload_file or not upload_file.filename:
        return _error("请选择要上传的课表图片")
    if not _allowed_file(upload_file.filename):
        allowed = ", ".join(sorted(current_app.config["ALLOWED_EXTENSIONS"]))
        return _error(f"仅支持这些图片格式：{allowed}")

    auto_owner = _form_enabled("auto_owner")
    auto_department = (
        request.form.get("auto_department") or "待设置"
    ).strip() or "待设置"
    target_user_id = (request.form.get("target_user_id") or "").strip()
    target_user = None
    if target_user_id:
        try:
            target_user_id = int(target_user_id)
        except ValueError:
            return _error("目标账号不正确")
        target_user = db.session.get(User, target_user_id)
        if not target_user:
            return _error("目标账号不存在", 404)
    elif not auto_owner:
        return _error("请选择课表所属成员，或启用在图片中自动识别姓名")

    original_filename = secure_filename(upload_file.filename) or "schedule.png"
    extension = original_filename.rsplit(".", 1)[1].lower()
    stored_filename = f"{uuid.uuid4().hex}.{extension}"
    file_path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_filename)
    upload_file.save(file_path)

    try:
        with Image.open(file_path) as image:
            image_width, image_height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError):
        _remove_saved_file(file_path)
        return _error("文件不是有效图片")

    warnings = []
    raw_items = []
    ocr_text = ""
    parser_used = "rules"
    ai_metadata = None
    ai_error = None
    layout_metadata = None
    courses = []
    ai_errors = []
    try:
        # Send the original image to Qwen VL first. This path does not require
        # PaddleOCR or any local OCR model.
        if is_vision_parser_enabled():
            try:
                vision_courses, ai_metadata = parse_schedule_with_vision(
                    file_path
                )
                normalized_vision_courses, skipped_vision_courses = (
                    _normalize_ai_courses(vision_courses)
                )
                if normalized_vision_courses:
                    courses = normalized_vision_courses
                    parser_used = "vision"
                    warning_message = (
                        "已使用 Qwen 视觉模型直接读取原图并整理课程，"
                        "请重点核对课程名称、周数、节次和地点。"
                    )
                    if skipped_vision_courses:
                        warning_message += (
                            f" 另有 {skipped_vision_courses} 条候选"
                            "因内容不足未生成课程。"
                        )
                    warnings = [warning_message]
                    ocr_text = str((ai_metadata or {}).get("raw_content") or "")
                else:
                    ai_errors.append("Qwen 视觉模型：未返回有效课程")
            except AIParserUnavailable:
                pass
            except Exception as exc:
                ai_errors.append(f"Qwen 视觉模型：{exc}")
                current_app.logger.exception(
                    "Qwen vision schedule parsing failed for upload %s",
                    stored_filename,
                )

        # Local OCR is only a fallback when Qwen did not return usable courses.
        if parser_used != "vision":
            raw_items, ocr_text = recognize_image(file_path)
            courses, parse_warnings = parse_schedule(raw_items)
            courses = [
                _annotate_course_issues(normalize_course_fields(course))
                for course in courses
            ]
            warnings.extend(parse_warnings)

            if is_ai_parser_enabled():
                try:
                    cell_layout = extract_table_layout(file_path, raw_items)
                    layout_metadata = (
                        {
                            "method": cell_layout.get("method", "grid-lines"),
                            "grid": cell_layout.get("grid"),
                            "content_cell_count": len(
                                cell_layout.get("content_cells") or []
                            ),
                        }
                        if cell_layout
                        else None
                    )
                    deepseek_courses, ai_metadata = (
                        parse_schedule_with_deepseek(raw_items, cell_layout)
                    )
                    normalized_deepseek_courses, skipped_deepseek_courses = (
                        _normalize_ai_courses(deepseek_courses)
                    )
                    if normalized_deepseek_courses:
                        courses = normalized_deepseek_courses
                        parser_used = "deepseek"
                        warning_message = (
                            "已按课表单元格切分并交给 DeepSeek 解析，"
                            "请重点核对课程名称、周数和地点。"
                        )
                        if skipped_deepseek_courses:
                            warning_message += (
                                f" 另有 {skipped_deepseek_courses} 个单元格"
                                "因内容不足未生成课程。"
                            )
                        warnings = [warning_message]
                    else:
                        ai_errors.append("DeepSeek：未返回有效课程")
                except AIParserUnavailable:
                    pass
                except Exception as exc:
                    ai_errors.append(f"DeepSeek：{exc}")
                    current_app.logger.exception(
                        "DeepSeek schedule parsing failed for upload %s",
                        stored_filename,
                    )

            if parser_used == "rules" and ai_errors:
                ai_error = " | ".join(ai_errors)
                warnings.append("AI 识别失败，已使用规则解析结果。")
    except OCRUnavailable as exc:
        courses = []
        warnings.append(str(exc))
        warnings.append("OCR 不可用，已进入手动录入模式。")
    except Exception as exc:
        current_app.logger.exception("OCR failed for upload %s", stored_filename)
        courses = []
        warnings.append(f"OCR 识别失败：{exc}")
        warnings.append("可以继续在修正页手动添加课程。")

    owner_detection = _owner_detection_from_vision(ai_metadata)
    if not owner_detection:
        owner_detection = extract_owner_name(raw_items, image_width, image_height)
    member_created = False
    if auto_owner:
        if not owner_detection:
            _remove_saved_file(file_path)
            return _error(
                "未能在图片右下角稳定识别课表主人姓名，请手工选择成员后重试",
                422,
            )
        try:
            target_user, member_created = _resolve_auto_owner(
                owner_detection, auto_department
            )
        except ValueError as exc:
            _remove_saved_file(file_path)
            db.session.rollback()
            return _error(str(exc), 409)
        owner_detection["matched_existing"] = not member_created
        owner_detection["member_created"] = member_created

    upload = ScheduleUpload(
        user_id=target_user.id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        image_path=file_path,
        status=ScheduleUpload.STATUS_PENDING,
    )
    db.session.add(upload)
    db.session.flush()

    upload.ocr_text = ocr_text
    upload.ocr_result = {
        "items": raw_items,
        "courses": courses,
        "warnings": warnings,
        "owner_detection": owner_detection,
        "member_created": member_created,
        "auto_owner": auto_owner,
        "parser": parser_used,
        "ai_metadata": ai_metadata,
        "ai_error": ai_error,
        "layout_metadata": layout_metadata,
    }
    db.session.commit()

    return _ok(
        {
            "upload": upload.to_dict(),
            "user": target_user.to_dict(),
            "draft_courses": courses,
            "warnings": warnings,
            "owner_detection": owner_detection,
            "member_created": member_created,
            "auto_owner": auto_owner,
            "parser": parser_used,
            "ai_metadata": ai_metadata,
            "layout_metadata": layout_metadata,
            "review_url": f"/review/{upload.id}",
        },
        "图片已上传，请核对识别结果",
        201,
    )


@api_bp.get("/schedules/uploads/<int:upload_id>")
@roles_required(User.ROLE_ADMIN)
def get_schedule_draft(upload_id):
    upload = ScheduleUpload.query.get_or_404(upload_id)

    result = upload.ocr_result or {}
    return _ok(
        {
            "upload": upload.to_dict(),
            "user": upload.user.to_dict(),
            "draft_courses": result.get("courses", []),
            "ocr_items": result.get("items", []),
            "warnings": result.get("warnings", []),
            "owner_detection": result.get("owner_detection"),
            "member_created": result.get("member_created", False),
            "auto_owner": result.get("auto_owner", False),
            "parser": result.get("parser", "rules"),
            "ai_metadata": result.get("ai_metadata"),
            "layout_metadata": result.get("layout_metadata"),
        }
    )


@api_bp.post("/schedules/save")
@roles_required(User.ROLE_ADMIN)
def save_schedule():
    data = _json_body()
    raw_courses = data.get("courses")
    if not isinstance(raw_courses, list):
        return _error("courses 必须是课程数组")
    if len(raw_courses) > 200:
        return _error("单次最多保存 200 条课程")

    upload = None
    upload_id = data.get("upload_id")
    if upload_id:
        try:
            upload = db.session.get(ScheduleUpload, int(upload_id))
        except (TypeError, ValueError):
            return _error("上传记录 ID 不正确")
        if not upload:
            return _error("上传记录不存在", 404)
    target_user = upload.user if upload else g.current_user
    requested_user_id = data.get("user_id")
    if requested_user_id not in (None, ""):
        try:
            requested_user_id = int(requested_user_id)
        except (TypeError, ValueError):
            return _error("账号 ID 不正确")
        target_user = db.session.get(User, requested_user_id)
        if not target_user:
            return _error("账号不存在", 404)
        if upload and upload.user_id != target_user.id:
            return _error("上传记录与目标账号不一致")

    normalized_courses = []
    for index, course in enumerate(raw_courses, start=1):
        normalized, validation_error = _validate_course(course, index)
        if validation_error:
            return _error(validation_error)
        normalized_courses.append(normalized)

    replace_existing = data.get("replace_existing", True)
    try:
        if replace_existing:
            Course.query.filter_by(user_id=target_user.id).delete(
                synchronize_session=False
            )

        for course_data in normalized_courses:
            course_values = {
                field: course_data[field] for field in COURSE_FIELDS
            }
            db.session.add(
                Course(
                    user_id=target_user.id,
                    upload_id=upload.id if upload else None,
                    **course_values,
                )
            )
        if upload:
            upload.status = ScheduleUpload.STATUS_CONFIRMED
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save schedule")
        return _error("保存课表失败，请稍后重试", 500)

    courses = (
        Course.query.filter_by(user_id=target_user.id)
        .order_by(Course.weekday, Course.start_period)
        .all()
    )
    return _ok(
        {
            "saved_count": len(normalized_courses),
            "user": target_user.to_dict(),
            "courses": [course.to_dict() for course in courses],
        },
        "课表保存成功",
    )


@api_bp.get("/schedules/me")
@roles_required(User.ROLE_ADMIN)
def my_schedule():
    courses = (
        Course.query.filter_by(user_id=g.current_user.id)
        .order_by(Course.weekday, Course.start_period)
        .all()
    )
    return _ok(
        {
            "user": g.current_user.to_dict(),
            "courses": [course.to_dict() for course in courses],
        }
    )


@api_bp.get("/schedules/users/<int:user_id>")
@roles_required(User.ROLE_ADMIN)
def user_schedule(user_id):
    user = User.query.get_or_404(user_id)
    courses = (
        Course.query.filter_by(user_id=user.id)
        .order_by(Course.weekday, Course.start_period)
        .all()
    )
    return _ok(
        {"user": user.to_dict(), "courses": [course.to_dict() for course in courses]}
    )


@api_bp.delete("/schedules/courses/<int:course_id>")
@roles_required(User.ROLE_ADMIN)
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    return _ok(message="课程已删除")


@api_bp.get("/availability")
@roles_required(User.ROLE_ADMIN)
def query_availability():
    try:
        weekday = int(request.args.get("weekday", ""))
        start_period = int(request.args.get("start_period", ""))
        end_period = int(request.args.get("end_period", ""))
    except ValueError:
        return _error("星期和节次不能为空，且必须为数字")

    week_number_raw = (request.args.get("week_number") or "").strip()
    try:
        week_number = int(week_number_raw) if week_number_raw else None
    except ValueError:
        return _error("周次必须为数字")

    if not 1 <= weekday <= 7:
        return _error("星期必须在 1-7 之间")
    if not 1 <= start_period <= 12 or not 1 <= end_period <= 12:
        return _error("节次必须在 1-12 之间")
    if start_period > end_period:
        return _error("开始节次不能晚于结束节次")
    if week_number is not None and not 1 <= week_number <= 30:
        return _error("周次必须在 1-30 之间")

    department = (request.args.get("department") or "").strip()
    query = User.query.filter(User.role != User.ROLE_ADMIN)
    if department:
        query = query.filter(User.department == department)
    users = query.order_by(User.department.asc(), User.name.asc()).all()

    available_users = []
    busy_users = []
    for user in users:
        conflicting_courses = []
        same_day_courses = []
        for course in user.courses:
            if course.weekday != weekday:
                continue
            same_day_courses.append(course)
            time_conflict = _periods_overlap(
                start_period, end_period, course.start_period, course.end_period
            )
            week_conflict = week_number is None or course_occurs_in_week(
                course.weeks, week_number
            )
            if time_conflict and week_conflict:
                conflicting_courses.append(course)

        item = user.to_dict()
        item.update(
            {
                "has_class": bool(conflicting_courses),
                "courses": [
                    {
                        **course.to_dict(),
                        "conflicts": course in conflicting_courses,
                    }
                    for course in same_day_courses
                ],
            }
        )
        if conflicting_courses:
            busy_users.append(item)
        else:
            available_users.append(item)

    criteria = {
        "weekday": weekday,
        "start_period": start_period,
        "end_period": end_period,
        "week_number": week_number,
        "department": department,
    }
    log = QueryLog(
        operator_id=g.current_user.id,
        weekday=weekday,
        start_period=start_period,
        end_period=end_period,
        week_number=week_number,
        department=department,
        result_count=len(available_users),
        criteria=criteria,
    )
    db.session.add(log)
    db.session.commit()

    return _ok(
        {
            "criteria": criteria,
            "total": len(users),
            "available_count": len(available_users),
            "busy_count": len(busy_users),
            "available_users": available_users,
            "busy_users": busy_users,
            "members": available_users + busy_users,
        }
    )


@api_bp.get("/departments")
@roles_required(User.ROLE_ADMIN)
def list_departments():
    rows = (
        db.session.query(User.department)
        .filter(
            User.role != User.ROLE_ADMIN,
            User.department.isnot(None),
            User.department != "",
        )
        .distinct()
        .order_by(User.department.asc())
        .all()
    )
    return _ok({"departments": [row[0] for row in rows]})


@api_bp.get("/admin/stats")
@roles_required(User.ROLE_ADMIN)
def admin_stats():
    member_query = User.query.filter(User.role != User.ROLE_ADMIN)
    total_members = member_query.count()
    total_courses = Course.query.count()
    covered_members = (
        db.session.query(func.count(func.distinct(Course.user_id)))
        .join(User, Course.user_id == User.id)
        .filter(User.role != User.ROLE_ADMIN)
        .scalar()
        or 0
    )
    department_count = (
        db.session.query(func.count(func.distinct(User.department)))
        .filter(
            User.role != User.ROLE_ADMIN,
            User.department.isnot(None),
            User.department != "",
        )
        .scalar()
        or 0
    )
    return _ok(
        {
            "stats": {
                "total_members": total_members,
                "total_courses": total_courses,
                "covered_members": covered_members,
                "department_count": department_count,
            }
        }
    )


def _summary_filters():
    department = (request.args.get("department") or "").strip()
    week_number_raw = (request.args.get("week_number") or "").strip()
    try:
        week_number = int(week_number_raw)
    except ValueError:
        raise ValueError("请选择教学周")
    if not 1 <= week_number <= 30:
        raise ValueError("教学周必须在 1-30 之间")
    return department, week_number


def _build_availability_summary(department, week_number):
    query = User.query.filter(User.role != User.ROLE_ADMIN).options(
        selectinload(User.courses),
        selectinload(User.availability_overrides),
    )
    if department:
        query = query.filter(User.department == department)
    users = query.order_by(User.department.asc(), User.name.asc()).all()

    time_slots = [
        {
            "key": f"{weekday}-{start_period}-{end_period}",
            "weekday": weekday,
            "weekday_label": SUMMARY_WEEKDAYS[weekday - 1],
            "start_period": start_period,
            "end_period": end_period,
            "label": SUMMARY_PERIOD_LABELS[index],
            "time_range": SUMMARY_PERIOD_TIMES.get(
                SUMMARY_PERIOD_LABELS[index], ""
            ),
        }
        for weekday in range(1, 8)
        for index, (start_period, end_period) in enumerate(SUMMARY_PERIOD_GROUPS)
    ]
    members = []
    for user in users:
        manual_overrides = {
            (
                override.weekday,
                override.start_period,
                override.end_period,
            ): override
            for override in user.availability_overrides
            if override.week_number == week_number
        }
        busy_slots = {}
        for course in user.courses:
            if course.weekday < 1 or course.weekday > 7:
                continue
            if not course_occurs_in_week(course.weeks, week_number):
                continue
            for slot in time_slots:
                if slot["weekday"] != course.weekday:
                    continue
                if not _periods_overlap(
                    course.start_period,
                    course.end_period,
                    slot["start_period"],
                    slot["end_period"],
                ):
                    continue
                busy_slots.setdefault(slot["key"], [])
                if course.course_name not in busy_slots[slot["key"]]:
                    busy_slots[slot["key"]].append(course.course_name)

        cells = []
        for slot in time_slots:
            course_names = busy_slots.get(slot["key"], [])
            manual_override = manual_overrides.get(
                (
                    slot["weekday"],
                    slot["start_period"],
                    slot["end_period"],
                )
            )
            if manual_override:
                is_free = bool(manual_override.is_free)
                if not is_free and not course_names:
                    course_names = ["手动标记有课"]
            else:
                is_free = not course_names
            cells.append(
                {
                    "key": slot["key"],
                    "free": is_free,
                    "courses": course_names,
                    "manual_override": (
                        manual_override.to_dict() if manual_override else None
                    ),
                }
            )
        members.append(
            {
                **user.to_dict(),
                "cells": cells,
                "free_count": sum(1 for cell in cells if cell["free"]),
            }
        )

    all_free = [
        bool(members) and all(member["cells"][index]["free"] for member in members)
        for index in range(len(time_slots))
    ]
    free_students_by_slot = []
    for index, slot in enumerate(time_slots):
        free_students = [
            {
                "id": member["id"],
                "name": member["name"],
                "student_id": member["student_id"],
                "department": member["department"],
            }
            for member in members
            if member["cells"][index]["free"]
        ]
        free_students_by_slot.append(
            {
                **slot,
                "free_students": free_students,
                "free_count": len(free_students),
                "all_free": all_free[index],
            }
        )
    slot_lookup = {
        (slot["weekday"], slot["label"]): slot for slot in free_students_by_slot
    }
    slot_index_lookup = {
        (slot["weekday"], slot["label"]): index
        for index, slot in enumerate(time_slots)
    }
    manual_overrides_by_slot = {}
    for member in members:
        for index, cell in enumerate(member["cells"]):
            if cell["manual_override"]:
                manual_overrides_by_slot.setdefault(index, []).append(
                    cell["manual_override"]
                )
    free_table_rows = []
    for period_label in SUMMARY_PERIOD_LABELS:
        cells = []
        for weekday in range(1, 8):
            slot = slot_lookup[(weekday, period_label)]
            cells.append(
                {
                    "weekday": weekday,
                    "weekday_label": slot["weekday_label"],
                    "free_students": slot["free_students"],
                    "free_count": slot["free_count"],
                    "all_free": slot["all_free"],
                    "start_period": slot["start_period"],
                    "end_period": slot["end_period"],
                    "manual_overrides": manual_overrides_by_slot.get(
                        slot_index_lookup[(slot["weekday"], slot["label"])], []
                    ),
                }
            )
        free_table_rows.append(
            {
                "label": period_label,
                "time_range": SUMMARY_PERIOD_TIMES.get(period_label, ""),
                "cells": cells,
            }
        )
    return {
        "department": department,
        "department_label": department or "全部部门",
        "week_number": week_number,
        "weekdays": SUMMARY_WEEKDAYS,
        "periods": SUMMARY_PERIOD_LABELS,
        "period_groups": [
            {
                "start_period": start_period,
                "end_period": end_period,
                "label": SUMMARY_PERIOD_LABELS[index],
                "time_range": SUMMARY_PERIOD_TIMES.get(
                    SUMMARY_PERIOD_LABELS[index], ""
                ),
            }
            for index, (start_period, end_period) in enumerate(SUMMARY_PERIOD_GROUPS)
        ],
        "time_slots": time_slots,
        "members": members,
        "member_count": len(members),
        "scheduled_count": sum(
            1 for member in members if member["free_count"] < len(time_slots)
        ),
        "all_free": all_free,
        "all_free_count": sum(1 for is_free in all_free if is_free),
        "free_students_by_slot": free_students_by_slot,
        "free_table_rows": free_table_rows,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


@api_bp.get("/availability-summary")
@roles_required(User.ROLE_ADMIN)
def availability_summary():
    try:
        department, week_number = _summary_filters()
    except ValueError as exc:
        return _error(str(exc))
    return _ok(
        {"summary": _build_availability_summary(department, week_number)}
    )


@api_bp.post("/availability-overrides")
@roles_required(User.ROLE_ADMIN)
def set_availability_override():
    data = _json_body()
    try:
        user_id = int(data.get("user_id"))
        week_number = int(data.get("week_number"))
        weekday = int(data.get("weekday"))
        start_period = int(data.get("start_period"))
        end_period = int(data.get("end_period"))
    except (TypeError, ValueError):
        return _error("成员、周次、星期或节次参数不正确")

    user = db.session.get(User, user_id)
    if not user or user.role == User.ROLE_ADMIN:
        return _error("成员不存在", 404)
    if not 1 <= week_number <= 30:
        return _error("周次必须在 1-30 之间")
    if not 1 <= weekday <= 7:
        return _error("星期必须在 1-7 之间")
    if not 1 <= start_period <= end_period <= 12:
        return _error("节次必须在 1-12 之间且顺序正确")

    is_free = data.get("is_free")
    if not isinstance(is_free, bool):
        return _error("无课状态必须是布尔值")
    note = str(data.get("note") or "").strip()[:255]

    override = AvailabilityOverride.query.filter_by(
        user_id=user.id,
        week_number=week_number,
        weekday=weekday,
        start_period=start_period,
        end_period=end_period,
    ).first()
    if override is None:
        override = AvailabilityOverride(
            user_id=user.id,
            week_number=week_number,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
        )
        db.session.add(override)

    override.is_free = is_free
    override.note = note
    override.created_by_id = g.current_user.id
    db.session.commit()
    action = "设为无课" if is_free else "设为有课"
    return _ok(
        {
            "override": override.to_dict(),
            "user": user.to_dict(),
        },
        f"{user.name}第{week_number}周{SUMMARY_WEEKDAYS[weekday - 1]}"
        f"{format_period_range(start_period, end_period)}已{action}",
    )


@api_bp.delete("/availability-overrides")
@roles_required(User.ROLE_ADMIN)
def reset_availability_overrides():
    user_id = request.args.get("user_id", type=int)
    week_number = request.args.get("week_number", type=int)
    if not user_id or not week_number:
        return _error("成员和周次不能为空")

    user = db.session.get(User, user_id)
    if not user or user.role == User.ROLE_ADMIN:
        return _error("成员不存在", 404)
    deleted = AvailabilityOverride.query.filter_by(
        user_id=user.id, week_number=week_number
    ).delete(synchronize_session=False)
    db.session.commit()
    return _ok(
        {"deleted_count": deleted},
        f"已恢复 {user.name} 第{week_number}周的课表判断",
    )


@api_bp.get("/availability-summary/export")
@roles_required(User.ROLE_ADMIN)
def export_availability_summary():
    try:
        department, week_number = _summary_filters()
    except ValueError as exc:
        return _error(str(exc))
    summary = _build_availability_summary(department, week_number)
    content = build_total_free_xlsx(summary)
    safe_department = re.sub(
        r'[\\/:*?"<>|]+', "_", summary["department_label"]
    ).strip(" .") or "全部部门"
    return send_file(
        BytesIO(content),
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        as_attachment=True,
        download_name=f"总无课表_{safe_department}_第{week_number}周.xlsx",
    )


def _validate_course(raw, index):
    if not isinstance(raw, dict):
        return None, f"第 {index} 条课程格式不正确"
    try:
        weekday = int(raw.get("weekday"))
        start_period = int(raw.get("start_period"))
        end_period = int(raw.get("end_period"))
    except (TypeError, ValueError):
        return None, f"第 {index} 条课程的星期或节次不正确"

    course_name = (raw.get("course_name") or "").strip()
    if not course_name:
        return None, f"第 {index} 条课程缺少课程名称"
    if not 1 <= weekday <= 7:
        return None, f"第 {index} 条课程的星期必须在 1-7 之间"
    if not 1 <= start_period <= 10 or not 1 <= end_period <= 10:
        return None, f"第 {index} 条课程的节次必须在 1-10 之间"
    if start_period > end_period:
        return None, f"第 {index} 条课程的开始节次不能晚于结束节次"
    if len(course_name) > 150:
        return None, f"第 {index} 条课程名称过长"

    return (
        {
            "weekday": weekday,
            "start_period": start_period,
            "end_period": end_period,
            "course_name": course_name,
            "weeks": (raw.get("weeks") or "").strip()[:255],
            "location": (raw.get("location") or "").strip()[:150],
            "note": (raw.get("note") or "").strip()[:255],
        },
        None,
    )


def _periods_overlap(query_start, query_end, course_start, course_end):
    return max(query_start, course_start) <= min(query_end, course_end)


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

    ranges = re.findall(r"(\d{1,2})\s*[-~—－至到]\s*(\d{1,2})", text)
    if ranges:
        return any(int(start) <= week_number <= int(end) for start, end in ranges)

    singles = re.findall(r"(?<!\d)(\d{1,2})(?!\s*[-~—－至到]\d)", text)
    if singles:
        return week_number in {int(value) for value in singles}

    # With no parseable week range, a recorded course is treated conservatively
    # as occupying every week.
    return True
