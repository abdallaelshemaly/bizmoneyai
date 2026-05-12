from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.admin_auth as admin_auth_module
import app.api.admin as admin_module
import app.api.auth as auth_module
from app.api.admin import router as admin_router
from app.api.admin_auth import protected_router as admin_protected_router
from app.api.admin_auth import router as admin_auth_router
from app.api.auth import router as auth_router
from app.core.config import settings
from app.db.session import get_db
from app.models.admin import Admin
from app.models.user import User


def create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_auth_router)
    app.include_router(admin_protected_router)
    app.include_router(admin_router)
    app.include_router(auth_router)
    return app


def test_public_registration_is_disabled(db_session):
    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/auth/register",
            json={"name": "Public User", "email": "public@example.com", "password": "secret1"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Public registration is disabled. Please contact the administrator."
        assert db_session.query(User).filter(User.email == "public@example.com").first() is None
    finally:
        app.dependency_overrides.clear()


def test_admin_can_create_user_and_manage_login_lifecycle(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth_module, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(admin_module, "get_password_hash", lambda password: password)
    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: plain == hashed)

    admin = Admin(name="Admin User", email="admin@example.com", password_hash="admin-secret")
    db_session.add(admin)
    db_session.commit()

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        unauthorized_response = client.post(
            "/admin/users",
            json={"name": "Managed User", "email": "managed@example.com", "password": "secret1"},
        )
        assert unauthorized_response.status_code == 401

        admin_login_response = client.post(
            "/admin/auth/login",
            json={"email": "admin@example.com", "password": "admin-secret"},
        )
        assert admin_login_response.status_code == 200

        missing_password_response = client.post(
            "/admin/users",
            json={"name": "Missing Password", "email": "missing-password@example.com"},
        )
        assert missing_password_response.status_code == 422
        assert "password" in str(missing_password_response.json()["detail"])

        invalid_email_response = client.post(
            "/admin/users",
            json={"name": "Invalid Email", "email": "not-an-email", "password": "secret1"},
        )
        assert invalid_email_response.status_code == 422
        assert "email" in str(invalid_email_response.json()["detail"])

        create_response = client.post(
            "/admin/users",
            json={"name": "Managed User", "email": "MixedCase@Example.com", "password": "secret1", "is_active": True},
        )
        assert create_response.status_code == 201
        body = create_response.json()
        assert body["email"] == "mixedcase@example.com"
        assert body["is_active"] is True
        assert "password_hash" not in body

        duplicate_response = client.post(
            "/admin/users",
            json={"name": "Duplicate User", "email": "mixedcase@example.com", "password": "secret1"},
        )
        assert duplicate_response.status_code == 400
        assert duplicate_response.json()["detail"] == "Email already registered"

        users_response = client.get("/admin/users", params={"search": "mixedcase"})
        assert users_response.status_code == 200
        assert users_response.json()["total"] == 1

        login_response = client.post(
            "/auth/login",
            json={"email": "MIXEDCASE@example.com", "password": "secret1"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["email"] == "mixedcase@example.com"
        assert "access_token" in client.cookies

        stored_user = db_session.query(User).filter(User.email == "mixedcase@example.com").one()
        assert stored_user.email == "mixedcase@example.com"
        assert stored_user.password_hash == "secret1"

        deactivate_response = client.patch(
            f"/admin/users/{stored_user.user_id}/status",
            json={"is_active": False},
        )
        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False

        blocked_login_response = client.post(
            "/auth/login",
            json={"email": "mixedcase@example.com", "password": "secret1"},
        )
        assert blocked_login_response.status_code == 403
        assert blocked_login_response.json()["detail"] == "Your account is inactive. Please contact the administrator."

        reactivate_response = client.patch(
            f"/admin/users/{stored_user.user_id}/status",
            json={"is_active": True},
        )
        assert reactivate_response.status_code == 200
        assert reactivate_response.json()["is_active"] is True

        reactivated_login_response = client.post(
            "/auth/login",
            json={"email": "mixedcase@example.com", "password": "secret1"},
        )
        assert reactivated_login_response.status_code == 200
        assert reactivated_login_response.json()["email"] == "mixedcase@example.com"
    finally:
        app.dependency_overrides.clear()


def test_auth_cookies_use_secure_flag_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr(admin_auth_module, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(auth_module, "verify_password", lambda plain, hashed: plain == hashed)
    monkeypatch.setattr(settings, "cookie_secure", True, raising=False)

    admin = Admin(name="Admin User", email="admin@example.com", password_hash="secret123")
    user = User(name="Cookie User", email="cookie@example.com", password_hash="secret123")
    db_session.add_all([admin, user])
    db_session.commit()

    app = create_test_app()
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        user_login_response = client.post(
            "/auth/login",
            json={"email": "cookie@example.com", "password": "secret123"},
        )
        assert user_login_response.status_code == 200
        assert "secure" in user_login_response.headers.get("set-cookie", "").lower()

        admin_login_response = client.post(
            "/admin/auth/login",
            json={"email": "admin@example.com", "password": "secret123"},
        )
        assert admin_login_response.status_code == 200
        assert "secure" in admin_login_response.headers.get("set-cookie", "").lower()
    finally:
        app.dependency_overrides.clear()
