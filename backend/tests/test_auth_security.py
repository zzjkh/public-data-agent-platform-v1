from __future__ import annotations

from app.auth.security import hash_password, verify_password


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("admin123")

    assert password_hash != "admin123"
    assert verify_password("admin123", password_hash)
    assert not verify_password("wrong-password", password_hash)

