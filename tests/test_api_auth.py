"""Tests for authentication API routes in app.py."""

from __future__ import annotations

import pytest


class TestLogin:
    def test_login_success(self, app_client):
        resp = app_client.post("/api/login", json={
            "username": "admin",
            "password": "changeme123",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    def test_login_wrong_password(self, app_client):
        resp = app_client.post("/api/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401
        assert "Invalid" in resp.get_json()["error"]

    def test_login_missing_fields(self, app_client):
        resp = app_client.post("/api/login", json={"username": "admin"})
        assert resp.status_code == 400
        assert "required" in resp.get_json()["error"].lower()

    def test_login_empty_body(self, app_client):
        resp = app_client.post("/api/login", json={})
        assert resp.status_code == 400


class TestRateLimit:
    def test_rate_limiting(self, app_client):
        """After 10 failed attempts within the window, the 11th should get 429."""
        import app as app_module
        app_module._login_attempts.clear()

        for i in range(10):
            resp = app_client.post("/api/login", json={
                "username": "admin",
                "password": "wrongpassword",
            })
            assert resp.status_code == 401, f"Attempt {i+1} expected 401"

        # 11th attempt should be rate limited
        resp = app_client.post("/api/login", json={
            "username": "admin",
            "password": "wrongpassword",
        })
        assert resp.status_code == 429
        assert "Too many" in resp.get_json()["error"]


class TestLogout:
    def test_logout_clears_session(self, app_client):
        # Log in first
        app_client.post("/api/login", json={
            "username": "admin",
            "password": "changeme123",
        })
        # Verify authenticated
        resp = app_client.get("/api/me")
        assert resp.status_code == 200

        # Log out
        resp = app_client.post("/api/logout")
        assert resp.status_code == 200

        # Should be unauthenticated now
        resp = app_client.get("/api/me")
        assert resp.status_code == 401


class TestMe:
    def test_authenticated(self, admin_client):
        resp = admin_client.get("/api/me")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "admin"
        assert data["role"] == "admin"

    def test_unauthenticated(self, app_client):
        resp = app_client.get("/api/me")
        assert resp.status_code == 401
        assert "error" in resp.get_json()
