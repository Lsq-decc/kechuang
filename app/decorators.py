from functools import wraps

from flask import abort, g, jsonify, redirect, request, session, url_for

from .models import User


def load_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    from .extensions import db

    return db.session.get(User, user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = load_current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "请先登录"}), 401
            return redirect(url_for("views.login", next=request.full_path))
        g.current_user = user
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user.role not in roles:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "message": "没有权限执行此操作"}), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
