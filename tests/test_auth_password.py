"""Tests for email+password authentication — Task 1 behaviors.

Pure-function tests (no DB required):
- hash_password returns bcrypt $2b$12$ format
- verify_password returns True for correct password
- verify_password returns False for wrong password
- DUMMY_HASH is a valid bcrypt string

Import tests (signatures only, no DB):
- create_password_user is async callable
- find_user_by_email is async callable
- log_login_attempt is async callable
- check_brute_force is async callable
- resolve_identity_for_user_id is async callable
"""
from __future__ import annotations

import inspect


def test_hash_password_returns_bcrypt_format():
    from src.backend.apps.auth import hash_password
    h = hash_password("test123")
    assert h.startswith("$2b$12$"), f"Expected $2b$12$ prefix, got: {h[:10]}"


def test_verify_password_correct():
    from src.backend.apps.auth import hash_password, verify_password
    h = hash_password("test123")
    assert verify_password("test123", h) is True


def test_verify_password_wrong():
    from src.backend.apps.auth import hash_password, verify_password
    h = hash_password("test123")
    assert verify_password("wrong", h) is False


def test_dummy_hash_is_valid_bcrypt():
    from src.backend.apps.auth import DUMMY_HASH
    assert DUMMY_HASH.startswith("$2b$"), f"DUMMY_HASH not valid bcrypt: {DUMMY_HASH[:10]}"


def test_create_password_user_is_async():
    from src.backend.apps.identity_store import create_password_user
    assert callable(create_password_user)
    assert inspect.iscoroutinefunction(create_password_user)


def test_find_user_by_email_is_async():
    from src.backend.apps.identity_store import find_user_by_email
    assert callable(find_user_by_email)
    assert inspect.iscoroutinefunction(find_user_by_email)


def test_log_login_attempt_is_async():
    from src.backend.apps.identity_store import log_login_attempt
    assert callable(log_login_attempt)
    assert inspect.iscoroutinefunction(log_login_attempt)


def test_check_brute_force_is_async():
    from src.backend.apps.identity_store import check_brute_force
    assert callable(check_brute_force)
    assert inspect.iscoroutinefunction(check_brute_force)


def test_resolve_identity_for_user_id_is_async():
    from src.backend.apps.identity_store import resolve_identity_for_user_id
    assert callable(resolve_identity_for_user_id)
    assert inspect.iscoroutinefunction(resolve_identity_for_user_id)


def test_auth_py_has_user_id_fallback():
    """resolve_request_principal must have resolve_identity_for_user_id fallback."""
    with open("src/backend/apps/auth.py") as f:
        source = f.read()
    assert "resolve_identity_for_user_id" in source, "auth.py missing resolve_identity_for_user_id fallback"


def test_schema_has_required_ddl():
    with open("src/backend/dbsync/auth_schema.sql") as f:
        sql = f.read()
    assert "password_hash" in sql, "Missing password_hash column"
    assert "email_verified" in sql, "Missing email_verified column"
    assert "login_method" in sql, "Missing login_method column"
    assert "login_attempt" in sql, "Missing login_attempt table"
    assert "idx_user_email_unique" in sql, "Missing email unique index"
