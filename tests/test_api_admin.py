"""Tests for admin-only API routes in app.py."""

from __future__ import annotations

import pytest


class TestCreateUser:
    def test_create_user(self, admin_client):
        resp = admin_client.post("/api/users", json={
            "username": "newuser",
            "password": "password1234",
            "role": "user",
        })
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["username"] == "newuser"
        assert data["role"] == "user"

    def test_create_duplicate_user(self, admin_client):
        admin_client.post("/api/users", json={
            "username": "dupuser",
            "password": "password1234",
            "role": "user",
        })
        resp = admin_client.post("/api/users", json={
            "username": "dupuser",
            "password": "password1234",
            "role": "user",
        })
        assert resp.status_code == 409
        assert "exists" in resp.get_json()["error"].lower()


class TestListUsers:
    def test_list_users_no_password_hash(self, admin_client):
        resp = admin_client.get("/api/users")
        assert resp.status_code == 200
        users = resp.get_json()
        assert isinstance(users, list)
        assert len(users) >= 1  # at least admin
        for u in users:
            assert "password_hash" not in u
            assert "username" in u
            assert "role" in u


class TestDeleteUser:
    def test_delete_user(self, admin_client):
        # Create a user to delete
        admin_client.post("/api/users", json={
            "username": "todelete",
            "password": "password1234",
            "role": "user",
        })
        resp = admin_client.delete("/api/users/todelete")
        assert resp.status_code == 200

        # Verify they are gone
        resp = admin_client.get("/api/users")
        usernames = [u["username"] for u in resp.get_json()]
        assert "todelete" not in usernames

    def test_delete_self_returns_400(self, admin_client):
        resp = admin_client.delete("/api/users/admin")
        assert resp.status_code == 400
        assert "yourself" in resp.get_json()["error"].lower()

    def test_delete_nonexistent_user(self, admin_client):
        resp = admin_client.delete("/api/users/nosuchuser")
        assert resp.status_code == 404


class TestNonAdminDenied:
    def test_non_admin_gets_403(self, authed_client):
        """A regular user should get 403 on admin-only endpoints."""
        resp = authed_client.get("/api/users")
        assert resp.status_code == 403

        resp = authed_client.post("/api/users", json={
            "username": "hacker",
            "password": "password1234",
            "role": "user",
        })
        assert resp.status_code == 403

        resp = authed_client.delete("/api/users/admin")
        assert resp.status_code == 403
