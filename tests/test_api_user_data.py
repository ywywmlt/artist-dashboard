"""Tests for user-data and account management API routes."""

from __future__ import annotations

import pytest


class TestGetUserData:
    def test_default_empty_structure(self, authed_client):
        resp = authed_client.get("/api/user-data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["profiles"] == []
        assert data["watchlist"] == {}
        assert data["contacts"] == {}
        assert data["alerts"] == []


class TestSaveAndGetUserData:
    def test_roundtrip(self, authed_client):
        payload = {
            "profiles": [{"id": "p1", "name": "Test Artist"}],
            "watchlist": {"abc": "Target"},
            "contacts": {"xyz123": {"email": "test@example.com"}},
            "alerts": [{"id": "a1", "type": "test", "message": "hello", "generated_at": "2026-01-01"}],
        }
        resp = authed_client.post("/api/user-data", json=payload)
        assert resp.status_code == 200

        resp = authed_client.get("/api/user-data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["profiles"]) == 1
        assert data["profiles"][0]["name"] == "Test Artist"
        assert data["watchlist"]["abc"] is not None
        assert data["alerts"][0]["id"] == "a1"

    def test_only_safe_keys_persisted(self, authed_client):
        """Extra keys beyond profiles/watchlist/contacts/alerts should be dropped."""
        payload = {
            "profiles": [],
            "watchlist": {},
            "contacts": {},
            "alerts": [],
            "evil_key": "should not be saved",
            "password_hash": "definitely not",
        }
        resp = authed_client.post("/api/user-data", json=payload)
        assert resp.status_code == 200

        resp = authed_client.get("/api/user-data")
        data = resp.get_json()
        assert "evil_key" not in data
        assert "password_hash" not in data


class TestChangeUsername:
    def test_change_username(self, authed_client):
        resp = authed_client.post("/api/account/username", json={
            "username": "newname",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "newname"

        # Verify /api/me reflects the change
        resp = authed_client.get("/api/me")
        assert resp.get_json()["username"] == "newname"

    def test_change_username_invalid(self, authed_client):
        resp = authed_client.post("/api/account/username", json={
            "username": "bad name!@#",
        })
        assert resp.status_code == 400

    def test_change_username_empty(self, authed_client):
        resp = authed_client.post("/api/account/username", json={
            "username": "",
        })
        assert resp.status_code == 400

    def test_change_username_taken(self, authed_client):
        """Cannot change to a username that already exists (e.g. admin)."""
        resp = authed_client.post("/api/account/username", json={
            "username": "admin",
        })
        assert resp.status_code == 409


class TestChangePassword:
    def test_change_password(self, authed_client):
        resp = authed_client.post("/api/account/password", json={
            "current_password": "testpass1234",
            "new_password": "newpass5678",
        })
        assert resp.status_code == 200

        # Log out and log back in with new password
        authed_client.post("/api/logout")
        resp = authed_client.post("/api/login", json={
            "username": "testuser",
            "password": "newpass5678",
        })
        assert resp.status_code == 200

    def test_change_password_wrong_current(self, authed_client):
        resp = authed_client.post("/api/account/password", json={
            "current_password": "wrongpassword",
            "new_password": "newpass5678",
        })
        assert resp.status_code == 403

    def test_change_password_missing_fields(self, authed_client):
        resp = authed_client.post("/api/account/password", json={
            "new_password": "newpass5678",
        })
        assert resp.status_code == 400
