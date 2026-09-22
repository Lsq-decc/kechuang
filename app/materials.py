import mimetypes
import os
import re
import uuid
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy import func

from .decorators import roles_required
from .extensions import db
from .models import DEPARTMENTS, MaterialFile, MaterialFolder, User


materials_api_bp = Blueprint("materials_api", __name__)

DEPARTMENT_SLUGS = {
    "综合事务部": "general-affairs",
    "项目培育部": "project-incubation",
    "宣传推广部": "publicity",
}
SAFE_INLINE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}


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


def _parse_department(value):
    department = str(value or "").strip()
    if department not in DEPARTMENTS:
        return None
    return department


def _storage_root():
    return Path(current_app.config["MATERIAL_STORAGE_FOLDER"]).resolve()


def _folder_or_error(folder_id, department):
    if not folder_id:
        return None, None
    try:
        folder_id = int(folder_id)
    except (TypeError, ValueError):
        return None, _error("文件夹参数不正确")
    folder = db.session.get(MaterialFolder, folder_id)
    if not folder or folder.department != department:
        return None, _error("文件夹不存在", 404)
    return folder, None


def _folder_duplicate(department, parent_id, name, exclude_id=None):
    query = MaterialFolder.query.filter_by(
        department=department, parent_id=parent_id, name=name
    )
    if exclude_id:
        query = query.filter(MaterialFolder.id != exclude_id)
    return query.first() is not None


def _valid_folder_name(value):
    name = str(value or "").strip()
    if not name:
        raise ValueError("文件夹名称不能为空")
    if len(name) > 100:
        raise ValueError("文件夹名称不能超过 100 个字符")
    if name in {".", ".."} or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
        raise ValueError("文件夹名称不能包含 \\ / : * ? \" < > |")
    return name


def _valid_filename(value):
    original = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not original:
        raise ValueError("文件名不能为空")
    original = re.sub(r"[\x00-\x1f]", "", original)
    if len(original) > 255:
        suffix = Path(original).suffix[:20]
        original = f"{Path(original).stem[: 255 - len(suffix)]}{suffix}"
    return original


def _stored_extension(filename):
    suffix = Path(filename).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,15}", suffix or ""):
        return ""
    return suffix.lower()


def _resolve_file_path(material_file):
    root = _storage_root()
    path = (root / material_file.storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _remove_paths(paths):
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            current_app.logger.warning("Failed to remove material file: %s", path)


@materials_api_bp.get("")
@roles_required(User.ROLE_ADMIN)
def list_materials():
    department = _parse_department(request.args.get("department"))
    if not department:
        return _error("请选择有效的部门空间")

    current_folder, error = _folder_or_error(
        request.args.get("folder_id"), department
    )
    if error:
        return error

    folder_filter = (
        MaterialFolder.parent_id == current_folder.id
        if current_folder
        else MaterialFolder.parent_id.is_(None)
    )
    folders = (
        MaterialFolder.query.filter(
            MaterialFolder.department == department, folder_filter
        )
        .order_by(MaterialFolder.name.asc())
        .all()
    )
    files = (
        MaterialFile.query.filter(
            MaterialFile.department == department,
            (
                MaterialFile.folder_id == current_folder.id
                if current_folder
                else MaterialFile.folder_id.is_(None)
            ),
        )
        .order_by(MaterialFile.created_at.desc())
        .all()
    )

    folder_ids = [folder.id for folder in folders]
    child_counts = {}
    file_counts = {}
    if folder_ids:
        child_counts = dict(
            db.session.query(
                MaterialFolder.parent_id, func.count(MaterialFolder.id)
            )
            .filter(MaterialFolder.parent_id.in_(folder_ids))
            .group_by(MaterialFolder.parent_id)
            .all()
        )
        file_counts = dict(
            db.session.query(MaterialFile.folder_id, func.count(MaterialFile.id))
            .filter(MaterialFile.folder_id.in_(folder_ids))
            .group_by(MaterialFile.folder_id)
            .all()
        )

    breadcrumbs = []
    cursor = current_folder
    visited = set()
    while cursor and cursor.id not in visited:
        visited.add(cursor.id)
        breadcrumbs.insert(0, cursor.to_dict())
        cursor = cursor.parent

    folder_payload = []
    for folder in folders:
        item = folder.to_dict()
        item["folder_count"] = child_counts.get(folder.id, 0)
        item["file_count"] = file_counts.get(folder.id, 0)
        folder_payload.append(item)

    return _ok(
        {
            "departments": list(DEPARTMENTS),
            "department": department,
            "current_folder": (
                current_folder.to_dict() if current_folder else None
            ),
            "breadcrumbs": breadcrumbs,
            "folders": folder_payload,
            "files": [material_file.to_dict() for material_file in files],
        }
    )


@materials_api_bp.post("/folders")
@roles_required(User.ROLE_ADMIN)
def create_material_folder():
    data = _json_body()
    department = _parse_department(data.get("department"))
    if not department:
        return _error("请选择有效的部门空间")

    parent_id = data.get("parent_id")
    if parent_id in {"", None}:
        parent_id = None
    parent, error = _folder_or_error(parent_id, department)
    if error:
        return error

    try:
        name = _valid_folder_name(data.get("name"))
    except ValueError as exc:
        return _error(str(exc))

    if _folder_duplicate(department, parent.id if parent else None, name):
        return _error("当前目录下已存在同名文件夹", 409)

    folder = MaterialFolder(
        department=department,
        name=name,
        parent_id=parent.id if parent else None,
        created_by_id=g.current_user.id,
    )
    db.session.add(folder)
    db.session.commit()
    return _ok({"folder": folder.to_dict()}, "文件夹已创建", 201)


@materials_api_bp.delete("/folders/<int:folder_id>")
@roles_required(User.ROLE_ADMIN)
def delete_material_folder(folder_id):
    folder = db.session.get(MaterialFolder, folder_id)
    if not folder:
        return _error("文件夹不存在", 404)

    folder_ids = [folder.id]
    pending_ids = [folder.id]
    while pending_ids:
        child_ids = [
            row[0]
            for row in db.session.query(MaterialFolder.id)
            .filter(MaterialFolder.parent_id.in_(pending_ids))
            .all()
        ]
        new_ids = [child_id for child_id in child_ids if child_id not in folder_ids]
        folder_ids.extend(new_ids)
        pending_ids = new_ids

    files = MaterialFile.query.filter(
        MaterialFile.folder_id.in_(folder_ids)
    ).all()
    paths = [
        path
        for path in (_resolve_file_path(material_file) for material_file in files)
        if path is not None
    ]

    MaterialFile.query.filter(MaterialFile.folder_id.in_(folder_ids)).delete(
        synchronize_session=False
    )
    MaterialFolder.query.filter(MaterialFolder.id.in_(folder_ids)).delete(
        synchronize_session=False
    )
    db.session.commit()
    _remove_paths(paths)
    return _ok(
        {"deleted_folder_count": len(folder_ids), "deleted_file_count": len(files)},
        "文件夹及其内容已删除",
    )


@materials_api_bp.post("/files")
@roles_required(User.ROLE_ADMIN)
def upload_material_files():
    department = _parse_department(request.form.get("department"))
    if not department:
        return _error("请选择有效的部门空间")

    folder, error = _folder_or_error(request.form.get("folder_id"), department)
    if error:
        return error

    uploads = request.files.getlist("files") or request.files.getlist("file")
    uploads = [upload for upload in uploads if upload and upload.filename]
    if not uploads:
        return _error("请选择要上传的文件")
    if len(uploads) > 50:
        return _error("单次最多上传 50 个文件")

    try:
        filenames = [_valid_filename(upload.filename) for upload in uploads]
    except ValueError as exc:
        return _error(str(exc))

    department_dir = _storage_root() / DEPARTMENT_SLUGS[department]
    department_dir.mkdir(parents=True, exist_ok=True)
    saved_paths = []
    material_files = []
    try:
        for upload, original_filename in zip(uploads, filenames):
            extension = _stored_extension(original_filename)
            stored_filename = f"{uuid.uuid4().hex}{extension}"
            destination = department_dir / stored_filename
            upload.save(destination)
            saved_paths.append(destination)

            content_type = (
                upload.mimetype
                or mimetypes.guess_type(original_filename)[0]
                or "application/octet-stream"
            )
            material_file = MaterialFile(
                department=department,
                folder_id=folder.id if folder else None,
                original_filename=original_filename,
                storage_key=str(
                    Path(DEPARTMENT_SLUGS[department]) / stored_filename
                ),
                content_type=content_type[:150],
                file_size=os.path.getsize(destination),
                created_by_id=g.current_user.id,
            )
            db.session.add(material_file)
            material_files.append(material_file)
        db.session.commit()
    except Exception:
        db.session.rollback()
        _remove_paths(saved_paths)
        current_app.logger.exception("Failed to upload department materials")
        return _error("文件上传失败，请稍后重试", 500)

    return _ok(
        {"files": [material_file.to_dict() for material_file in material_files]},
        f"已上传 {len(material_files)} 个文件",
        201,
    )


@materials_api_bp.get("/files/<int:file_id>/content")
@roles_required(User.ROLE_ADMIN)
def material_file_content(file_id):
    material_file = db.session.get(MaterialFile, file_id)
    if not material_file:
        return _error("文件不存在", 404)

    path = _resolve_file_path(material_file)
    if not path or not path.is_file():
        return _error("文件不存在或已被移除", 404)

    content_type = material_file.content_type or "application/octet-stream"
    inline = (
        request.args.get("inline") == "1"
        and content_type in SAFE_INLINE_TYPES
    )
    return send_file(
        path,
        mimetype=content_type,
        as_attachment=not inline,
        download_name=material_file.original_filename,
        conditional=True,
        max_age=0,
    )


@materials_api_bp.delete("/files/<int:file_id>")
@roles_required(User.ROLE_ADMIN)
def delete_material_file(file_id):
    material_file = db.session.get(MaterialFile, file_id)
    if not material_file:
        return _error("文件不存在", 404)

    path = _resolve_file_path(material_file)
    db.session.delete(material_file)
    db.session.commit()
    if path:
        _remove_paths([path])
    return _ok(message="文件已删除")
