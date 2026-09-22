from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from PIL import Image

from app.extensions import db
from app.models import Course, QueryLog, ScheduleUpload, User


def make_png():
    buffer = BytesIO()
    Image.new("RGB", (800, 500), "white").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def create_user(
    app,
    username,
    name,
    student_id,
    department="项目办公室",
    role=User.ROLE_MEMBER,
    password="password123",
):
    with app.app_context():
        user = User(
            username=username,
            name=name,
            student_id=student_id,
            department=department,
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.to_dict()


def create_admin(app, username="admin01", student_id="admin001"):
    return create_user(
        app,
        username=username,
        name="系统管理员",
        student_id=student_id,
        department="大学生科创实践中心",
        role=User.ROLE_ADMIN,
    )


def login_admin(client, username="admin01"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 200
    return response.get_json()["user"]


def create_course(app, user_id, course_name, weekday=1, start_period=1, end_period=1):
    with app.app_context():
        course = Course(
            user_id=user_id,
            weekday=weekday,
            start_period=start_period,
            end_period=end_period,
            course_name=course_name,
            weeks="1-16周",
            location="测试教室",
            note="",
        )
        db.session.add(course)
        db.session.commit()
        return course.id


def test_only_admin_can_login(client, app):
    member = create_user(app, "member01", "张同学", "20260001")
    register_response = client.post(
        "/api/auth/register",
        json={
            "username": "member02",
            "password": "password123",
            "name": "李同学",
            "student_id": "20260002",
            "department": "项目办公室",
        },
    )
    assert register_response.status_code == 403

    member_login = client.post(
        "/api/auth/login",
        json={"username": member["username"], "password": "password123"},
    )
    assert member_login.status_code == 403

    create_admin(app)
    assert login_admin(client)["role"] == User.ROLE_ADMIN


def test_admin_upload_fix_save_query_and_delete_file(monkeypatch, app, client):
    from app import api

    monkeypatch.setattr(
        api,
        "recognize_image",
        lambda _path: (
            [
                {
                    "text": "周一第1-2节 高等数学 1-16周",
                    "confidence": 0.96,
                    "box": [],
                    "center_x": 120,
                    "center_y": 120,
                }
            ],
            "周一第1-2节 高等数学 1-16周",
        ),
    )
    member = create_user(app, "member03", "王同学", "20260003")
    create_admin(app)
    login_admin(client)

    missing_target = client.post(
        "/api/schedules/upload",
        data={"file": (make_png(), "schedule.png")},
        content_type="multipart/form-data",
    )
    assert missing_target.status_code == 400

    upload_response = client.post(
        "/api/schedules/upload",
        data={
            "file": (make_png(), "schedule.png"),
            "target_user_id": str(member["id"]),
        },
        content_type="multipart/form-data",
    )
    assert upload_response.status_code == 201
    upload_data = upload_response.get_json()
    assert upload_data["draft_courses"][0]["course_name"] == "高等数学"

    save_response = client.post(
        "/api/schedules/save",
        json={
            "upload_id": upload_data["upload"]["id"],
            "replace_existing": True,
            "courses": [
                {
                    "weekday": 1,
                    "start_period": 1,
                    "end_period": 2,
                    "course_name": "高等数学",
                    "weeks": "1-16周",
                    "location": "教3-101",
                    "note": "OCR修正后",
                }
            ],
        },
    )
    assert save_response.status_code == 200
    assert save_response.get_json()["user"]["id"] == member["id"]

    with app.app_context():
        assert Course.query.filter_by(user_id=member["id"]).count() == 1
        stored_upload = db.session.get(ScheduleUpload, upload_data["upload"]["id"])
        image_path = stored_upload.image_path
        assert Path(image_path).exists()

    busy_response = client.get(
        "/api/availability?weekday=1&start_period=1&end_period=2&week_number=1"
    )
    busy_data = busy_response.get_json()
    assert busy_response.status_code == 200
    assert busy_data["busy_count"] == 1
    assert busy_data["busy_users"][0]["name"] == "王同学"

    stats = client.get("/api/admin/stats").get_json()["stats"]
    assert stats["total_members"] == 1
    assert stats["total_courses"] == 1
    assert stats["covered_members"] == 1

    delete_response = client.delete(f"/api/users/{member['id']}")
    assert delete_response.status_code == 200
    assert not Path(image_path).exists()


def test_upload_can_auto_create_member_from_owner_name(monkeypatch, app, client):
    from app import api

    monkeypatch.setattr(
        api,
        "recognize_image",
        lambda _path: (
            [
                {
                    "text": "王越",
                    "confidence": 0.98,
                    "box": [[700, 440], [760, 440], [760, 470], [700, 470]],
                    "center_x": 730,
                    "center_y": 455,
                }
            ],
            "王越",
        ),
    )
    create_admin(app, username="owner_admin", student_id="owner_admin")
    login_admin(client, username="owner_admin")

    response = client.post(
        "/api/schedules/upload",
        data={
            "file": (make_png(), "schedule.png"),
            "auto_owner": "1",
            "auto_department": "自动识别部门",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload["owner_detection"]["name"] == "王越"
    assert payload["member_created"] is True
    assert payload["user"]["name"] == "王越"
    assert payload["user"]["department"] == "自动识别部门"

    with app.app_context():
        user = User.query.filter_by(name="王越").one()
        upload = db.session.get(ScheduleUpload, payload["upload"]["id"])
        assert upload.user_id == user.id


def test_admin_can_manage_other_schedule_and_delete_account(app, client):
    member = create_user(app, "member10", "赵同学", "20260100")
    create_admin(app)
    login_admin(client)

    save_response = client.post(
        "/api/schedules/save",
        json={
            "user_id": member["id"],
            "replace_existing": True,
            "courses": [
                {
                    "weekday": 3,
                    "start_period": 3,
                    "end_period": 4,
                    "course_name": "数据结构",
                    "weeks": "1-16周",
                    "location": "教2-201",
                    "note": "",
                }
            ],
        },
    )
    assert save_response.status_code == 200
    assert save_response.get_json()["saved_count"] == 1

    append_response = client.post(
        "/api/schedules/save",
        json={
            "user_id": member["id"],
            "replace_existing": False,
            "courses": [
                {
                    "weekday": 5,
                    "start_period": 5,
                    "end_period": 6,
                    "course_name": "大学英语",
                    "weeks": "2-15周",
                    "location": "外语楼",
                    "note": "",
                }
            ],
        },
    )
    assert append_response.status_code == 200
    schedule = client.get(f"/api/schedules/users/{member['id']}").get_json()
    assert len(schedule["courses"]) == 2

    course_id = schedule["courses"][0]["id"]
    assert client.delete(f"/api/schedules/courses/{course_id}").status_code == 200

    users = client.get("/api/users").get_json()["users"]
    member_row = next(user for user in users if user["id"] == member["id"])
    assert member_row["course_count"] == 1

    update_response = client.patch(
        f"/api/users/{member['id']}",
        json={
            "username": "member10_updated",
            "name": "赵同学（已更新）",
            "student_id": "20260100",
            "department": "竞赛部",
            "role": User.ROLE_MEMBER,
        },
    )
    assert update_response.status_code == 200
    assert update_response.get_json()["user"]["username"] == "member10_updated"

    with app.app_context():
        query_log = QueryLog(
            operator_id=member["id"],
            weekday=1,
            start_period=1,
            end_period=2,
            department="竞赛部",
            result_count=0,
            criteria={},
        )
        db.session.add(query_log)
        db.session.commit()
        query_log_id = query_log.id

    delete_user_response = client.delete(f"/api/users/{member['id']}")
    assert delete_user_response.status_code == 200
    with app.app_context():
        assert db.session.get(User, member["id"]) is None
        assert Course.query.filter_by(user_id=member["id"]).count() == 0
        assert db.session.get(QueryLog, query_log_id).operator_id is None


def test_summary_preview_and_xlsx_export(app, client):
    first = create_user(app, "member20", "刘同学", "20260200")
    second = create_user(app, "member21", "陈同学", "20260201")
    third = create_user(
        app, "member22", "郑同学", "20260202", department="竞赛部"
    )
    create_course(app, first["id"], "高等数学", weekday=1, start_period=1, end_period=2)
    create_course(app, second["id"], "大学英语", weekday=1, start_period=1, end_period=1)
    create_course(app, third["id"], "程序设计", weekday=2, start_period=1, end_period=2)
    create_admin(app)
    login_admin(client)

    response = client.get(
        "/api/availability-summary",
        query_string={"department": "项目办公室", "week_number": "1"},
    )
    assert response.status_code == 200
    summary = response.get_json()["summary"]
    assert summary["periods"] == ["1-2", "3-4", "5-6", "7-8", "9-10"]
    assert len(summary["time_slots"]) == 35
    assert summary["member_count"] == 2
    assert summary["scheduled_count"] == 2
    assert summary["members"][0]["cells"][0]["free"] is False
    assert summary["members"][0]["cells"][1]["free"] is True
    assert summary["all_free"][0] is False
    assert summary["all_free"][1] is True
    assert summary["free_students_by_slot"][0]["free_count"] == 0
    assert summary["free_students_by_slot"][1]["free_count"] == 2
    assert {
        member["name"]
        for member in summary["free_students_by_slot"][1]["free_students"]
    } == {"刘同学", "陈同学"}
    assert summary["free_students_by_slot"][1]["time_range"] == "09:55-11:35"
    assert len(summary["free_table_rows"]) == 5
    assert len(summary["free_table_rows"][0]["cells"]) == 7
    assert summary["free_table_rows"][1]["cells"][0]["free_count"] == 2

    override_response = client.post(
        "/api/availability-overrides",
        json={
            "user_id": first["id"],
            "week_number": 1,
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "is_free": True,
        },
    )
    assert override_response.status_code == 200
    assert override_response.get_json()["override"]["is_free"] is True

    overridden_summary = client.get(
        "/api/availability-summary",
        query_string={"department": "项目办公室", "week_number": "1"},
    ).get_json()["summary"]
    assert overridden_summary["free_students_by_slot"][0]["free_count"] == 1
    assert (
        overridden_summary["free_students_by_slot"][0]["free_students"][0]["id"]
        == first["id"]
    )
    first_summary_member = next(
        member
        for member in overridden_summary["members"]
        if member["id"] == first["id"]
    )
    assert first_summary_member["cells"][0]["manual_override"]["is_free"] is True
    assert any(
        override["user_id"] == first["id"]
        for override in overridden_summary["free_table_rows"][0]["cells"][0][
            "manual_overrides"
        ]
    )

    reset_response = client.delete(
        f"/api/availability-overrides?user_id={first['id']}&week_number=1"
    )
    assert reset_response.status_code == 200
    reset_summary = client.get(
        "/api/availability-summary",
        query_string={"department": "项目办公室", "week_number": "1"},
    ).get_json()["summary"]
    assert reset_summary["free_students_by_slot"][0]["free_count"] == 0

    all_departments_response = client.get(
        "/api/availability-summary",
        query_string={"department": "", "week_number": "1"},
    )
    assert all_departments_response.status_code == 200
    all_departments = all_departments_response.get_json()["summary"]
    assert all_departments["department_label"] == "全部部门"
    assert all_departments["member_count"] == 3

    export_response = client.get(
        "/api/availability-summary/export",
        query_string={"department": "", "week_number": "1"},
    )
    assert export_response.status_code == 200
    assert export_response.data.startswith(b"PK")
    assert "spreadsheetml.sheet" in export_response.content_type

    with ZipFile(BytesIO(export_response.data)) as archive:
        assert archive.testzip() is None
        for filename in [
            "[Content_Types].xml",
            "xl/workbook.xml",
            "xl/styles.xml",
            "xl/worksheets/sheet1.xml",
        ]:
            ElementTree.fromstring(archive.read(filename))
        assert "xl/worksheets/sheet2.xml" not in archive.namelist()
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles_xml = archive.read("xl/styles.xml").decode("utf-8")
        assert "总无课表" in sheet_xml
        assert "节次" in sheet_xml
        assert "时间" in sheet_xml
        assert "周一" in sheet_xml
        assert "周二" in sheet_xml
        assert "1-2节" in sheet_xml
        assert "刘同学" in sheet_xml
        assert "09:55-11:35" in sheet_xml
        assert 'width="28"' in sheet_xml
        assert 'vertical="top"' in styles_xml
        assert 'wrapText="1"' in styles_xml
        assert 'xml:space="preserve"' in sheet_xml
        assert "刘同学\n陈同学" in sheet_xml


def test_admin_can_render_management_pages(app, client):
    member = create_user(app, "member30", "周同学", "20260300")
    create_admin(app)
    login_admin(client)

    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    dashboard_html = dashboard.get_data(as_text=True)
    assert "data-nav-group" in dashboard_html
    assert "课表管理" in dashboard_html
    assert "批量上传" in dashboard_html
    assert client.get("/users").status_code == 200
    assert client.get("/upload").status_code == 200
    assert client.get("/batch-upload").status_code == 200
    assert client.get(f"/upload?user_id={member['id']}").status_code == 200
    assert client.get("/query").status_code == 200
    assert client.get("/summary").status_code == 200
    assert client.get(f"/admin/users/{member['id']}/schedule").status_code == 200


def test_member_session_cannot_access_admin_features(app, client):
    member = create_user(app, "member40", "吴同学", "20260400")
    with client.session_transaction() as session:
        session["user_id"] = member["id"]

    assert client.get("/api/users").status_code == 403
    assert client.get("/api/admin/stats").status_code == 403
    assert client.get("/dashboard").status_code == 403


def test_admin_cannot_delete_or_demote_self(app, client):
    admin = create_admin(app, username="admin50", student_id="admin050")
    login_admin(client, username="admin50")

    demote_response = client.patch(
        f"/api/users/{admin['id']}",
        json={"role": User.ROLE_MEMBER},
    )
    assert demote_response.status_code == 400

    delete_response = client.delete(f"/api/users/{admin['id']}")
    assert delete_response.status_code == 400
