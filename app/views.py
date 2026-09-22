from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from .decorators import load_current_user, roles_required
from .models import DEPARTMENTS, ScheduleUpload, User
from .security import ensure_csrf_token


views_bp = Blueprint("views", __name__)


@views_bp.app_context_processor
def inject_navigation():
    user = load_current_user()
    return {
        "current_user": user,
        "csrf_token": ensure_csrf_token() if user else "",
        "User": User,
    }


@views_bp.get("/")
def index():
    user = load_current_user()
    if not user or user.role != User.ROLE_ADMIN:
        session.clear()
        return redirect(url_for("views.login"))
    return redirect(url_for("views.dashboard"))


@views_bp.get("/login")
def login():
    user = load_current_user()
    if user and user.role == User.ROLE_ADMIN:
        return redirect(url_for("views.dashboard"))
    if user:
        session.clear()
    return render_template("login.html")


@views_bp.get("/register")
def register():
    return redirect(url_for("views.login"))


@views_bp.get("/dashboard")
@roles_required(User.ROLE_ADMIN)
def dashboard():
    return render_template("dashboard.html")


@views_bp.get("/upload")
@roles_required(User.ROLE_ADMIN)
def upload():
    target_user = None
    target_user_id = (request.args.get("user_id") or "").strip()
    if target_user_id:
        try:
            target_user_id = int(target_user_id)
        except ValueError:
            abort(400)
        target_user = User.query.get_or_404(target_user_id)
    return render_template("upload.html", target_user=target_user)


@views_bp.get("/batch-upload")
@roles_required(User.ROLE_ADMIN)
def batch_upload():
    return render_template("batch_upload.html")


@views_bp.get("/review/<int:upload_id>")
@roles_required(User.ROLE_ADMIN)
def review(upload_id):
    upload_record = ScheduleUpload.query.get_or_404(upload_id)
    is_owner = upload_record.user_id == g.current_user.id
    can_save = True
    return_url = (
        url_for("views.my_schedule")
        if is_owner
        else url_for("views.admin_user_schedule", user_id=upload_record.user_id)
    )
    next_url = (request.args.get("next") or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return_url = next_url
    return render_template(
        "review.html",
        upload_id=upload_id,
        target_user=upload_record.user,
        can_save=can_save,
        return_url=return_url,
    )


@views_bp.get("/my-schedule")
@roles_required(User.ROLE_ADMIN)
def my_schedule():
    return render_template("my_schedule.html")


@views_bp.get("/query")
@roles_required(User.ROLE_ADMIN)
def query():
    return render_template("query.html")


@views_bp.get("/users")
@roles_required(User.ROLE_ADMIN)
def users():
    return render_template("users.html")


@views_bp.get("/summary")
@roles_required(User.ROLE_ADMIN)
def summary():
    return render_template("summary.html")


@views_bp.get("/materials")
@roles_required(User.ROLE_ADMIN)
def materials():
    return render_template("materials.html", departments=DEPARTMENTS)


@views_bp.get("/todos")
@roles_required(User.ROLE_ADMIN)
def todos():
    return render_template("todos.html")


@views_bp.get("/admin/users/<int:user_id>/schedule")
@roles_required(User.ROLE_ADMIN)
def admin_user_schedule(user_id):
    target_user = User.query.get_or_404(user_id)
    return render_template("admin_user_schedule.html", target_user=target_user)


@views_bp.get("/uploads/<path:filename>")
@roles_required(User.ROLE_ADMIN)
def uploaded_file(filename):
    upload_record = ScheduleUpload.query.filter_by(stored_filename=filename).first_or_404()
    if (
        upload_record.user_id != g.current_user.id
        and not g.current_user.can_manage_all
    ):
        abort(403)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        filename,
    )


@views_bp.get("/health")
def health():
    return {"ok": True, "service": "kechuang-schedule"}
