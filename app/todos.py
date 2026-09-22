from datetime import datetime

from flask import Blueprint, g, jsonify, request
from sqlalchemy import case

from .decorators import roles_required
from .extensions import db
from .models import TodoItem, User


todos_api_bp = Blueprint("todos_api", __name__)


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


def _todo_or_404(todo_id):
    return TodoItem.query.filter_by(
        id=todo_id, user_id=g.current_user.id
    ).first_or_404()


@todos_api_bp.get("")
@roles_required(User.ROLE_ADMIN)
def list_todos():
    status = (request.args.get("status") or "all").strip()
    sort = (request.args.get("sort") or "priority").strip()
    if status not in {"all", "pending", "completed"}:
        return _error("待办状态筛选不正确")
    if sort not in {"priority", "newest", "oldest"}:
        return _error("待办排序方式不正确")

    query = TodoItem.query.filter_by(user_id=g.current_user.id)
    if status == "pending":
        query = query.filter(TodoItem.is_completed.is_(False))
    elif status == "completed":
        query = query.filter(TodoItem.is_completed.is_(True))

    completed_order = TodoItem.is_completed.asc()
    if sort == "priority":
        priority_order = case(
            (TodoItem.priority == TodoItem.PRIORITY_HIGH, 3),
            (TodoItem.priority == TodoItem.PRIORITY_MEDIUM, 2),
            (TodoItem.priority == TodoItem.PRIORITY_LOW, 1),
            else_=0,
        ).desc()
        query = query.order_by(
            completed_order, priority_order, TodoItem.created_at.desc()
        )
    elif sort == "oldest":
        query = query.order_by(completed_order, TodoItem.created_at.asc())
    else:
        query = query.order_by(completed_order, TodoItem.created_at.desc())

    todos = query.all()
    base_query = TodoItem.query.filter_by(user_id=g.current_user.id)
    pending_count = base_query.filter(TodoItem.is_completed.is_(False)).count()
    completed_count = base_query.filter(TodoItem.is_completed.is_(True)).count()
    return _ok(
        {
            "todos": [todo.to_dict() for todo in todos],
            "counts": {
                "total": pending_count + completed_count,
                "pending": pending_count,
                "completed": completed_count,
            },
            "status": status,
            "sort": sort,
        }
    )


@todos_api_bp.post("")
@roles_required(User.ROLE_ADMIN)
def create_todo():
    data = _json_body()
    title = str(data.get("title") or "").strip()
    note = str(data.get("note") or "").strip()
    priority = str(data.get("priority") or TodoItem.PRIORITY_MEDIUM).strip()

    if not title:
        return _error("待办内容不能为空")
    if len(title) > 200:
        return _error("待办内容不能超过 200 个字符")
    if len(note) > 500:
        return _error("备注不能超过 500 个字符")
    if priority not in TodoItem.PRIORITIES:
        return _error("重要程度不正确")

    todo = TodoItem(
        user_id=g.current_user.id,
        title=title,
        note=note,
        priority=priority,
    )
    db.session.add(todo)
    db.session.commit()
    return _ok({"todo": todo.to_dict()}, "待办已添加", 201)


@todos_api_bp.patch("/<int:todo_id>")
@roles_required(User.ROLE_ADMIN)
def update_todo(todo_id):
    todo = _todo_or_404(todo_id)
    data = _json_body()

    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            return _error("待办内容不能为空")
        if len(title) > 200:
            return _error("待办内容不能超过 200 个字符")
        todo.title = title
    if "note" in data:
        note = str(data.get("note") or "").strip()
        if len(note) > 500:
            return _error("备注不能超过 500 个字符")
        todo.note = note
    if "priority" in data:
        priority = str(data.get("priority") or "").strip()
        if priority not in TodoItem.PRIORITIES:
            return _error("重要程度不正确")
        todo.priority = priority
    if "is_completed" in data:
        is_completed = data.get("is_completed")
        if not isinstance(is_completed, bool):
            return _error("完成状态不正确")
        todo.is_completed = is_completed
        todo.completed_at = datetime.utcnow() if is_completed else None

    db.session.commit()
    return _ok({"todo": todo.to_dict()}, "待办已更新")


@todos_api_bp.delete("/<int:todo_id>")
@roles_required(User.ROLE_ADMIN)
def delete_todo(todo_id):
    todo = _todo_or_404(todo_id)
    db.session.delete(todo)
    db.session.commit()
    return _ok(message="待办已删除")
