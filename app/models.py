from datetime import datetime, timezone

from sqlalchemy.dialects.mysql import INTEGER as MySQLInteger
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


UNSIGNED_INTEGER = db.Integer().with_variant(MySQLInteger(unsigned=True), "mysql")
DEPARTMENTS = ("综合事务部", "项目培育部", "宣传推广部")


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    ROLE_MEMBER = "member"
    ROLE_LEADER = "leader"
    ROLE_ADMIN = "admin"
    ROLES = {ROLE_MEMBER, ROLE_LEADER, ROLE_ADMIN}
    ROLE_LABELS = {
        ROLE_MEMBER: "普通成员",
        ROLE_LEADER: "负责人",
        ROLE_ADMIN: "管理员",
    }

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False, index=True)
    student_id = db.Column(db.String(50), unique=True, nullable=True, index=True)
    department = db.Column(db.String(100), nullable=False, default="未设置")
    role = db.Column(db.String(20), nullable=False, default=ROLE_MEMBER, index=True)

    uploads = db.relationship(
        "ScheduleUpload", backref="user", lazy=True, cascade="all, delete-orphan"
    )
    courses = db.relationship(
        "Course", backref="user", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def can_manage_all(self):
        return self.role in {self.ROLE_LEADER, self.ROLE_ADMIN}

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "student_id": self.student_id or "",
            "department": self.department,
            "role": self.role,
            "role_label": self.ROLE_LABELS.get(self.role, self.role),
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }


class ScheduleUpload(TimestampMixin, db.Model):
    __tablename__ = "schedule_uploads"

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_FAILED = "failed"

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    user_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    image_path = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING)
    ocr_text = db.Column(db.Text, nullable=True)
    ocr_result = db.Column(db.JSON, nullable=True)

    courses = db.relationship("Course", backref="upload", lazy=True)

    def to_dict(self, include_courses=False):
        payload = {
            "id": self.id,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "status": self.status,
            "ocr_text": self.ocr_text or "",
            "image_url": f"/uploads/{self.stored_filename}",
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }
        if include_courses:
            payload["courses"] = [
                course.to_dict(include_id=False) for course in self.courses
            ]
        return payload


class Course(TimestampMixin, db.Model):
    __tablename__ = "courses"
    __table_args__ = (
        db.Index("ix_courses_time_lookup", "weekday", "start_period", "end_period"),
    )

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    user_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    upload_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("schedule_uploads.id", ondelete="SET NULL"),
        nullable=True,
    )
    weekday = db.Column(db.SmallInteger, nullable=False)
    start_period = db.Column(db.SmallInteger, nullable=False)
    end_period = db.Column(db.SmallInteger, nullable=False)
    course_name = db.Column(db.String(150), nullable=False)
    weeks = db.Column(db.String(255), nullable=False, default="")
    location = db.Column(db.String(150), nullable=False, default="")
    note = db.Column(db.String(255), nullable=False, default="")

    def to_dict(self, include_id=True):
        payload = {
            "weekday": self.weekday,
            "weekday_label": f"周{'一二三四五六日'[self.weekday - 1]}",
            "start_period": self.start_period,
            "end_period": self.end_period,
            "period_label": format_period_range(
                self.start_period, self.end_period
            ),
            "course_name": self.course_name,
            "weeks": self.weeks or "",
            "location": self.location or "",
            "note": self.note or "",
        }
        if include_id:
            payload["id"] = self.id
        return payload


class AvailabilityOverride(TimestampMixin, db.Model):
    __tablename__ = "availability_overrides"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "week_number",
            "weekday",
            "start_period",
            "end_period",
            name="uq_availability_override_slot",
        ),
        db.Index(
            "ix_availability_override_lookup",
            "week_number",
            "weekday",
            "start_period",
            "end_period",
        ),
    )

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    user_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    week_number = db.Column(db.SmallInteger, nullable=False)
    weekday = db.Column(db.SmallInteger, nullable=False)
    start_period = db.Column(db.SmallInteger, nullable=False)
    end_period = db.Column(db.SmallInteger, nullable=False)
    is_free = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.String(255), nullable=False, default="")
    created_by_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref(
            "availability_overrides",
            lazy=True,
            cascade="all, delete-orphan",
        ),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "week_number": self.week_number,
            "weekday": self.weekday,
            "start_period": self.start_period,
            "end_period": self.end_period,
            "is_free": self.is_free,
            "note": self.note or "",
            "created_by_id": self.created_by_id,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }


class QueryLog(db.Model):
    __tablename__ = "query_logs"

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    operator_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    weekday = db.Column(db.SmallInteger, nullable=False)
    start_period = db.Column(db.SmallInteger, nullable=False)
    end_period = db.Column(db.SmallInteger, nullable=False)
    week_number = db.Column(db.SmallInteger, nullable=True)
    department = db.Column(db.String(100), nullable=False, default="")
    result_count = db.Column(db.Integer, nullable=False, default=0)
    criteria = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    operator = db.relationship("User")


class MaterialFolder(TimestampMixin, db.Model):
    __tablename__ = "material_folders"
    __table_args__ = (
        db.UniqueConstraint(
            "department",
            "parent_id",
            "name",
            name="uq_material_folder_name",
        ),
        db.Index("ix_material_folders_parent", "department", "parent_id"),
    )

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    department = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    parent_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("material_folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    parent = db.relationship(
        "MaterialFolder",
        remote_side=[id],
        backref=db.backref(
            "children",
            lazy=True,
            cascade="all, delete-orphan",
        ),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "department": self.department,
            "name": self.name,
            "parent_id": self.parent_id,
            "created_by_id": self.created_by_id,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }


class MaterialFile(TimestampMixin, db.Model):
    __tablename__ = "material_files"
    __table_args__ = (
        db.Index("ix_material_files_folder", "department", "folder_id"),
    )

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    department = db.Column(db.String(100), nullable=False, index=True)
    folder_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("material_folders.id", ondelete="CASCADE"),
        nullable=True,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    storage_key = db.Column(db.String(500), nullable=False, unique=True)
    content_type = db.Column(db.String(150), nullable=False, default="")
    file_size = db.Column(db.BigInteger, nullable=False, default=0)
    created_by_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    folder = db.relationship(
        "MaterialFolder",
        backref=db.backref("files", lazy=True, cascade="all, delete-orphan"),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])

    def to_dict(self):
        extension = self.original_filename.rsplit(".", 1)
        extension = extension[1].lower() if len(extension) == 2 else ""
        return {
            "id": self.id,
            "department": self.department,
            "folder_id": self.folder_id,
            "original_filename": self.original_filename,
            "content_type": self.content_type or "",
            "file_size": self.file_size,
            "extension": extension,
            "is_image": (self.content_type or "").startswith("image/"),
            "content_url": f"/api/materials/files/{self.id}/content",
            "created_by_id": self.created_by_id,
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }


class TodoItem(TimestampMixin, db.Model):
    __tablename__ = "todo_items"
    __table_args__ = (
        db.Index("ix_todo_items_user_status", "user_id", "is_completed"),
        db.Index("ix_todo_items_user_priority", "user_id", "priority"),
    )

    PRIORITY_HIGH = "high"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_LOW = "low"
    PRIORITIES = (PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW)
    PRIORITY_LABELS = {
        PRIORITY_HIGH: "重要",
        PRIORITY_MEDIUM: "一般",
        PRIORITY_LOW: "次要",
    }

    id = db.Column(UNSIGNED_INTEGER, primary_key=True)
    user_id = db.Column(
        UNSIGNED_INTEGER,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = db.Column(db.String(200), nullable=False)
    note = db.Column(db.String(500), nullable=False, default="")
    priority = db.Column(
        db.String(10), nullable=False, default=PRIORITY_MEDIUM, index=True
    )
    is_completed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note or "",
            "priority": self.priority,
            "priority_label": self.PRIORITY_LABELS.get(
                self.priority, self.priority
            ),
            "is_completed": self.is_completed,
            "completed_at": (
                self.completed_at.isoformat(timespec="seconds")
                if self.completed_at
                else None
            ),
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }


def format_period_range(start_period, end_period):
    if start_period == end_period:
        return f"第{start_period}节"
    return f"第{start_period}-{end_period}节"
