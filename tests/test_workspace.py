from io import BytesIO
from pathlib import Path

from app.extensions import db
from app.models import MaterialFile, MaterialFolder, TodoItem, User


def create_admin(
    app,
    username="workspace_admin",
    student_id="workspace_admin",
    name="资料管理员",
):
    with app.app_context():
        user = User(
            username=username,
            name=name,
            student_id=student_id,
            department="大学生科创实践中心",
            role=User.ROLE_ADMIN,
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.to_dict()


def login_admin(client, username="workspace_admin"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": "password123"},
    )
    assert response.status_code == 200


def test_material_spaces_support_nested_folders_and_multiple_files(app, client):
    create_admin(app)
    login_admin(client)

    page = client.get("/materials")
    assert page.status_code == 200
    assert "部门资料库".encode("utf-8") in page.data

    root_response = client.post(
        "/api/materials/folders",
        json={
            "department": "综合事务部",
            "parent_id": None,
            "name": "活动资料",
        },
    )
    assert root_response.status_code == 201
    root_folder = root_response.get_json()["folder"]

    nested_response = client.post(
        "/api/materials/folders",
        json={
            "department": "综合事务部",
            "parent_id": root_folder["id"],
            "name": "照片",
        },
    )
    assert nested_response.status_code == 201
    nested_folder = nested_response.get_json()["folder"]

    duplicate = client.post(
        "/api/materials/folders",
        json={
            "department": "综合事务部",
            "parent_id": root_folder["id"],
            "name": "照片",
        },
    )
    assert duplicate.status_code == 409

    upload = client.post(
        "/api/materials/files",
        data={
            "department": "综合事务部",
            "folder_id": str(nested_folder["id"]),
            "files": [
                (BytesIO("会议记录".encode("utf-8")), "会议记录.txt"),
                (BytesIO(b"\x89PNG\r\n\x1a\n"), "活动照片.png"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    uploaded_files = upload.get_json()["files"]
    assert len(uploaded_files) == 2

    listing = client.get(
        "/api/materials",
        query_string={
            "department": "综合事务部",
            "folder_id": nested_folder["id"],
        },
    )
    assert listing.status_code == 200
    payload = listing.get_json()
    assert payload["current_folder"]["name"] == "照片"
    assert [crumb["name"] for crumb in payload["breadcrumbs"]] == [
        "活动资料",
        "照片",
    ]
    assert {item["original_filename"] for item in payload["files"]} == {
        "会议记录.txt",
        "活动照片.png",
    }

    text_file = next(
        item for item in uploaded_files if item["original_filename"].endswith(".txt")
    )
    download = client.get(f"{text_file['content_url']}?download=1")
    assert download.status_code == 200
    assert download.data == "会议记录".encode("utf-8")
    download.close()

    with app.app_context():
        stored_file = db.session.get(MaterialFile, text_file["id"])
        stored_path = (
            Path(app.config["MATERIAL_STORAGE_FOLDER"]) / stored_file.storage_key
        )
        assert stored_path.exists()

    delete_response = client.delete(
        f"/api/materials/folders/{root_folder['id']}"
    )
    assert delete_response.status_code == 200
    assert delete_response.get_json()["deleted_folder_count"] == 2
    assert delete_response.get_json()["deleted_file_count"] == 2
    assert not stored_path.exists()

    with app.app_context():
        assert MaterialFolder.query.count() == 0
        assert MaterialFile.query.count() == 0


def test_todos_are_private_sorted_by_priority_and_filterable(app, client):
    create_admin(app)
    login_admin(client)

    assert client.get("/todos").status_code == 200
    high = client.post(
        "/api/todos",
        json={"title": "准备重要材料", "priority": "high"},
    )
    completed = client.post(
        "/api/todos",
        json={"title": "已完成的旧事项", "priority": "low"},
    )
    medium = client.post(
        "/api/todos",
        json={"title": "整理一般资料", "priority": "medium", "note": "本周内"},
    )
    assert high.status_code == 201
    assert completed.status_code == 201
    assert medium.status_code == 201

    completed_id = completed.get_json()["todo"]["id"]
    update = client.patch(
        f"/api/todos/{completed_id}", json={"is_completed": True}
    )
    assert update.status_code == 200
    assert update.get_json()["todo"]["is_completed"] is True

    listing = client.get("/api/todos?status=all&sort=priority").get_json()
    assert [todo["title"] for todo in listing["todos"]] == [
        "准备重要材料",
        "整理一般资料",
        "已完成的旧事项",
    ]
    assert listing["counts"] == {"total": 3, "pending": 2, "completed": 1}

    pending = client.get("/api/todos?status=pending&sort=priority").get_json()
    assert [todo["title"] for todo in pending["todos"]] == [
        "准备重要材料",
        "整理一般资料",
    ]

    priority_update = client.patch(
        f"/api/todos/{medium.get_json()['todo']['id']}",
        json={"priority": "high"},
    )
    assert priority_update.status_code == 200
    reordered = client.get("/api/todos?status=pending&sort=priority").get_json()
    assert {todo["priority"] for todo in reordered["todos"]} == {"high"}

    create_admin(
        app,
        username="second_admin",
        student_id="second_admin",
        name="第二管理员",
    )
    login_admin(client, username="second_admin")
    private_listing = client.get("/api/todos").get_json()
    assert private_listing["todos"] == []
    assert private_listing["counts"]["total"] == 0

    with app.app_context():
        assert TodoItem.query.count() == 3
