from __future__ import annotations

from datetime import timedelta

import pytest

from src.auth_db import (
    ADMIN_LOGIN,
    ADMIN_PASSWORD,
    AuthDatabase,
    AuthError,
    RULE_FIRST_LOGIN,
    utc_now,
)


def admin(db: AuthDatabase):
    return db.authenticate(ADMIN_LOGIN, ADMIN_PASSWORD)


def test_initial_admin_is_created_once_and_password_is_hashed(tmp_path):
    path = tmp_path / "ff.db"
    db = AuthDatabase(path)
    assert admin(db).role == "admin"
    assert AuthDatabase(path).list_users(admin(AuthDatabase(path)).id)[0].login == ADMIN_LOGIN
    raw = path.read_bytes()
    assert b"adminff100" not in raw


def test_invalid_login_is_generic_and_common_user_is_not_admin(tmp_path):
    db = AuthDatabase(tmp_path / "ff.db")
    with pytest.raises(AuthError, match="Login ou senha inválidos"):
        db.authenticate(ADMIN_LOGIN, "errada")
    a = admin(db)
    db.create_user(a.id, "joao", "senha123", "chave123", 10, "creation")
    user = db.authenticate("joao", "senha123")
    assert user.role == "user"
    with pytest.raises(AuthError, match="Permissão administrativa"):
        db.list_users(user.id)


def test_duplicate_login_and_key_are_rejected(tmp_path):
    db = AuthDatabase(tmp_path / "ff.db")
    a = admin(db)
    db.create_user(a.id, "joao", "senha123", "chave123", 10, "creation")
    with pytest.raises(AuthError):
        db.create_user(a.id, "joao", "outrasenha", "chave456", 10, "creation")
    with pytest.raises(AuthError):
        db.create_user(a.id, "maria", "outrasenha", "chave123", 10, "creation")


def test_first_login_license_and_expiration(tmp_path):
    db = AuthDatabase(tmp_path / "ff.db")
    a = admin(db)
    created = db.create_user(a.id, "maria", "senha123", "chave789", 10, RULE_FIRST_LOGIN)
    assert db.license_info(created).status == "AGUARDANDO ATIVAÇÃO"
    logged = db.authenticate("maria", "senha123")
    assert logged.starts_at is not None
    assert db.license_info(logged).days_remaining in (9, 10)


def test_suspend_revoke_renew_and_persist(tmp_path):
    path = tmp_path / "ff.db"
    db = AuthDatabase(path)
    a = admin(db)
    user = db.create_user(a.id, "maria", "senha123", "chave789", 2, "creation")
    db.set_suspended(a.id, user.id, True)
    with pytest.raises(AuthError):
        db.authenticate("maria", "senha123")
    db.set_suspended(a.id, user.id, False)
    db.revoke_key(a.id, user.id)
    assert db.key_status(user.id) == "REVOGADA"
    renewed = db.update_license(a.id, user.id, days=30, add_days=True)
    assert renewed.expires_at is not None
    assert AuthDatabase(path).list_users(a.id)


def test_password_reset_and_generated_key(tmp_path):
    db = AuthDatabase(tmp_path / "ff.db")
    a = admin(db)
    user = db.create_user(a.id, "maria", "senha123", "chave789", 10, "creation")
    db.reset_password(a.id, user.id, "senha456")
    assert db.authenticate("maria", "senha456").login == "maria"
    key = db.replace_key(a.id, user.id)
    assert key.startswith("FF-")
