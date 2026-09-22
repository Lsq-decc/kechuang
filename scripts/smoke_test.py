"""Run the main HTTP flow against a locally started Flask service."""

import argparse
import io
import sys
import uuid

import requests
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin123!")
    args = parser.parse_args()

    session = requests.Session()
    login = session.post(
        f"{args.base_url}/api/auth/login",
        json={"username": args.username, "password": args.password},
        timeout=20,
    )
    login.raise_for_status()
    login_data = login.json()
    if not login_data.get("ok"):
        raise SystemExit(login_data.get("message", "login failed"))
    session.headers["X-CSRF-Token"] = login_data["csrf_token"]

    users_response = session.get(f"{args.base_url}/api/users", timeout=20)
    users_response.raise_for_status()
    users = users_response.json().get("users", [])
    target_user = next((user for user in users if user["role"] != "admin"), None)
    created_user_id = None
    if not target_user:
        create_user = session.post(
            f"{args.base_url}/api/users",
            json={
                "username": f"smoke_{uuid.uuid4().hex[:10]}",
                "name": "HTTP冒烟测试成员",
                "student_id": f"smoke_{uuid.uuid4().hex[:10]}",
                "department": "测试部门",
                "role": "member",
            },
            timeout=20,
        )
        create_user.raise_for_status()
        target_user = create_user.json()["user"]
        created_user_id = target_user["id"]

    image = io.BytesIO()
    Image.new("RGB", (320, 200), "white").save(image, format="PNG")
    image.seek(0)
    upload = session.post(
        f"{args.base_url}/api/schedules/upload",
        data={"target_user_id": str(target_user["id"])},
        files={"file": ("smoke.png", image, "image/png")},
        timeout=60,
    )
    upload.raise_for_status()
    upload_data = upload.json()

    save = session.post(
        f"{args.base_url}/api/schedules/save",
        json={
            "upload_id": upload_data["upload"]["id"],
            "replace_existing": True,
            "courses": [
                {
                    "weekday": 1,
                    "start_period": 1,
                    "end_period": 2,
                    "course_name": "HTTP smoke course",
                    "weeks": "1-16周",
                    "location": "test",
                    "note": "created by smoke test",
                }
            ],
        },
        timeout=20,
    )
    save.raise_for_status()
    saved_courses = save.json().get("courses", [])

    query = session.get(
        f"{args.base_url}/api/availability",
        params={
            "weekday": 1,
            "start_period": 1,
            "end_period": 2,
            "week_number": 1,
        },
        timeout=20,
    )
    query.raise_for_status()
    query_data = query.json()

    summary = session.get(
        f"{args.base_url}/api/availability-summary",
        params={
            "department": target_user["department"],
            "week_number": 1,
        },
        timeout=20,
    )
    summary.raise_for_status()
    summary_data = summary.json()

    export = session.get(
        f"{args.base_url}/api/availability-summary/export",
        params={
            "department": target_user["department"],
            "week_number": 1,
        },
        timeout=20,
    )
    export.raise_for_status()

    cleanup_ok = True
    for course in saved_courses:
        response = session.delete(
            f"{args.base_url}/api/schedules/courses/{course['id']}", timeout=20
        )
        cleanup_ok = cleanup_ok and response.ok and response.json().get("ok", False)
    if created_user_id:
        response = session.delete(
            f"{args.base_url}/api/users/{created_user_id}", timeout=20
        )
        cleanup_ok = cleanup_ok and response.ok and response.json().get("ok", False)

    result = {
        "login": login.json().get("ok"),
        "upload": upload_data.get("ok"),
        "ocr_warning_count": len(upload_data.get("warnings", [])),
        "saved": save.json().get("saved_count"),
        "available": query_data.get("available_count"),
        "busy": query_data.get("busy_count"),
        "summary_members": summary_data.get("summary", {}).get("member_count"),
        "export": export.content.startswith(b"PK"),
        "cleanup": cleanup_ok,
    }
    print(result)
    if not all(
        [
            result["login"],
            result["upload"],
            result["saved"] == 1,
            result["summary_members"] is not None,
            result["export"],
            result["cleanup"],
        ]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
