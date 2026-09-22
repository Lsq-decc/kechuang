import os
import secrets
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, jsonify, request, session
from sqlalchemy import inspect, text

from .config import Config
from .extensions import db


def create_app(config_override=None):
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)

    if config_override:
        app.config.update(config_override)

    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["MATERIAL_STORAGE_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["PADDLE_RUNTIME_HOME"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from .api import api_bp
    from .auth import auth_bp
    from .materials import materials_api_bp
    from .todos import todos_api_bp
    from .views import views_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(materials_api_bp, url_prefix="/api/materials")
    app.register_blueprint(todos_api_bp, url_prefix="/api/todos")

    register_cli(app)
    register_error_handlers(app)
    register_csrf_protection(app)

    if app.config.get("AUTO_CREATE_DB"):
        with app.app_context():
            init_database()

    return app


def init_database():
    from .models import User

    db.create_all()
    _ensure_mysql_collation()
    _ensure_admin()


def _ensure_mysql_collation():
    """Keep a newly created Flask-SQLAlchemy schema consistent on MySQL."""
    from .extensions import db

    if db.engine.dialect.name != "mysql":
        return

    inspector = inspect(db.engine)
    for table_name in inspector.get_table_names():
        try:
            db.session.execute(
                text(
                    f"ALTER TABLE `{table_name}` "
                    "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
        except Exception:
            db.session.rollback()
    db.session.commit()


def _ensure_admin():
    from .models import User

    username = os.getenv("ADMIN_USERNAME", "admin").strip()
    if not username:
        return

    admin = User.query.filter_by(username=username).first()
    if admin:
        return

    admin = User(
        username=username,
        name=os.getenv("ADMIN_NAME", "系统管理员").strip() or "系统管理员",
        student_id=os.getenv("ADMIN_STUDENT_ID", "admin").strip() or "admin",
        department=os.getenv("ADMIN_DEPARTMENT", "大学生科创实践中心").strip()
        or "大学生科创实践中心",
        role=User.ROLE_ADMIN,
    )
    admin.set_password(os.getenv("ADMIN_PASSWORD", "Admin123!"))
    db.session.add(admin)
    db.session.commit()


def register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and the initial administrator."""
        init_database()
        click.echo("Database initialized.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    @click.option("--name", prompt=True)
    @click.option("--student-id", default="")
    @click.option("--department", default="大学生科创实践中心")
    def create_admin_command(username, password, name, student_id, department):
        """Create or update an administrator account."""
        from .models import User

        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username)
            db.session.add(user)
        user.name = name
        user.student_id = student_id or None
        user.department = department
        user.role = User.ROLE_ADMIN
        user.set_password(password)
        db.session.commit()
        click.echo(f"Administrator {username} is ready.")


def register_error_handlers(app):
    @app.errorhandler(413)
    def file_too_large(_error):
        if request.path.startswith("/api/"):
            limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
            return jsonify({"ok": False, "message": f"文件不能超过 {limit_mb} MB"}), 413
        return "上传文件过大", 413

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "接口或资源不存在"}), 404
        return "页面不存在", 404


def register_csrf_protection(app):
    @app.before_request
    def protect_mutating_api_requests():
        if not app.config.get("CSRF_ENABLED"):
            return None
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        if not request.path.startswith("/api/"):
            return None
        if request.endpoint in {"auth.login", "auth.register"}:
            return None

        expected = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            return (
                jsonify({"ok": False, "message": "请求安全校验失败，请刷新页面重试"}),
                403,
            )
        return None
