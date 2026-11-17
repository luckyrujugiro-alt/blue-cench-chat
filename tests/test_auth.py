import time

import pytest
from pydantic import ValidationError

from bluecenchchat import config
from bluecenchchat.backend.authentication import AuthError, AuthService, RegistrationData
from bluecenchchat.backend.database import Database
from bluecenchchat.backend.user_service import UserRepository
from bluecenchchat.core import crypto

from .conftest import make_account


def test_register_and_login(tmp_path):
    db = Database(tmp_path / "a.db")
    acc, rk, ident = make_account(db, "alice")
    assert acc.user_id == ident.user_id and acc.user_id.startswith("NX-")
    assert "Passw0rd" not in acc.password_hash and acc.password_hash.startswith("$argon2id$")
    acc2, ident2 = AuthService(db).login("alice", "Passw0rd!x")
    assert ident2.public_bytes == ident.public_bytes
    # login by email works too
    AuthService(db).login("ALICE@example.com", "Passw0rd!x")


def test_identity_key_is_encrypted_at_rest(tmp_path):
    db = Database(tmp_path / "a.db")
    acc, _, ident = make_account(db, "alice")
    raw = ident.private_bytes()
    blob = (tmp_path / "a.db").read_bytes()
    assert raw not in blob


def test_validation():
    with pytest.raises(ValidationError):
        RegistrationData(full_name="A", username="ab", email="bad", password="short", confirm_password="x")
    with pytest.raises(ValidationError, match="do not match"):
        RegistrationData(full_name="Alice", username="alice", email="a@b.co", password="Passw0rd1",
                         confirm_password="Passw0rd2")


def test_duplicate_username(tmp_path):
    db = Database(tmp_path / "a.db")
    make_account(db, "alice")
    with pytest.raises(AuthError):
        make_account(db, "alice")


def test_lockout(tmp_path):
    db = Database(tmp_path / "a.db")
    make_account(db, "alice")
    auth = AuthService(db)
    for _ in range(config.MAX_FAILED_LOGINS - 1):
        with pytest.raises(AuthError, match="attempts left"):
            auth.login("alice", "wrong")
    with pytest.raises(AuthError, match="locked"):
        auth.login("alice", "wrong")
    with pytest.raises(AuthError, match="Too many"):
        auth.login("alice", "Passw0rd!x")  # even correct password refused while locked


def test_unknown_user_message_is_generic(tmp_path):
    db = Database(tmp_path / "a.db")
    with pytest.raises(AuthError, match="Incorrect username or password"):
        AuthService(db).login("nobody", "Passw0rd!x")


def test_recovery_keeps_identity_and_rotates_key(tmp_path):
    db = Database(tmp_path / "a.db")
    acc, rk, ident = make_account(db, "alice")
    auth = AuthService(db)
    with pytest.raises(AuthError):
        auth.recover("alice", "AAAA-BBBB-CCCC-DDDD-EEEE", "NewPassw0rd")
    new_rk = auth.recover("alice", rk.lower().replace("-", " "), "NewPassw0rd")
    assert new_rk != rk
    _, ident2 = auth.login("alice", "NewPassw0rd")
    assert ident2.user_id == ident.user_id
    with pytest.raises(AuthError):
        auth.recover("alice", rk, "Another1pass")  # old key no longer valid


def test_change_password(tmp_path):
    db = Database(tmp_path / "a.db")
    acc, _, _ = make_account(db, "alice")
    auth = AuthService(db)
    with pytest.raises(AuthError):
        auth.change_password(acc.id, "nope", "Brand1new")
    auth.change_password(acc.id, "Passw0rd!x", "Brand1new")
    auth.login("alice", "Brand1new")


def test_guest_is_purged(tmp_path):
    db = Database(tmp_path / "a.db")
    auth = AuthService(db)
    acc, ident = auth.create_guest()
    assert acc.is_guest
    assert all(a.id != acc.id for a in auth.list_accounts())
    auth.purge_guests()
    assert UserRepository(db, acc.id).account() is None


def test_accounts_are_isolated(tmp_path):
    db = Database(tmp_path / "a.db")
    a, _, _ = make_account(db, "alice")
    b, _, _ = make_account(db, "bobby")
    ra, rb = UserRepository(db, a.id), UserRepository(db, b.id)
    c = ra.upsert_contact("NX-AAAAA-BBBBB", b"x" * 32, status="accepted", display_name="Zed")
    assert rb.contact(c.id) is None
    assert rb.contacts() == []


def test_backup_roundtrip(tmp_home):
    from bluecenchchat.backend import backup

    db = Database(config.db_path())
    make_account(db, "alice")
    db.dispose()
    out = backup.create_backup(tmp_home / "b.nxbackup")
    Database(config.db_path())  # data changes after backup
    backup.stage_restore(out)
    assert backup.apply_pending_restore()
    db2 = Database(config.db_path())
    assert [a.username for a in AuthService(db2).list_accounts()] == ["alice"]
    bad = tmp_home / "bad.nxbackup"
    bad.write_bytes(b"not a zip")
    with pytest.raises(Exception):
        backup.stage_restore(bad)
