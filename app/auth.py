from flask import Blueprint, jsonify, request, session

from .decorators import load_current_user, login_required
from .models import User
from .security import ensure_csrf_token


auth_bp = Blueprint("auth", __name__)


def _error(message, status=400):
    return jsonify({"ok": False, "message": message}), status


def _payload():
    return request.get_json(silent=True) or request.form


@auth_bp.post("/register")
def register():
    return _error("系统仅供管理员使用，成员资料由管理员统一创建", 403)


@auth_bp.post("/login")
def login():
    data = _payload()
    account = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = User.query.filter(
        (User.username == account) | (User.student_id == account)
    ).first()
    if not user or not user.check_password(password):
        return _error("用户名或密码错误", 401)
    if user.role != User.ROLE_ADMIN:
        return _error("系统仅限管理员登录", 403)

    session.clear()
    session["user_id"] = user.id
    return jsonify(
        {
            "ok": True,
            "message": "登录成功",
            "user": user.to_dict(),
            "csrf_token": ensure_csrf_token(),
        }
    )


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True, "message": "已退出登录"})


@auth_bp.get("/me")
@login_required
def me():
    user = load_current_user()
    return jsonify({"ok": True, "user": user.to_dict()})
