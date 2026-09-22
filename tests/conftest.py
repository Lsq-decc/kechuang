import pytest

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "MATERIAL_STORAGE_FOLDER": str(tmp_path / "materials"),
            "AUTO_CREATE_DB": False,
            "OCR_ENGINE": "paddle",
            "CSRF_ENABLED": False,
            "AI_PARSER_ENABLED": False,
            "DEEPSEEK_API_KEY": "",
            "VISION_PARSER_ENABLED": False,
            "VISION_API_KEY": "",
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
