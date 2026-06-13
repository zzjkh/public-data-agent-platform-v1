from __future__ import annotations

from app.auth.security import hash_password
from app.core.config import get_settings
from app.db.repositories.user import UserRepository
from app.db.session import create_session


def seed_users() -> None:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("Default development users cannot be seeded in production.")

    users = [
        (settings.dev_seed_admin_username, settings.dev_seed_admin_password, "admin"),
        (settings.dev_seed_demo_username, settings.dev_seed_demo_password, "user"),
    ]

    with create_session(settings) as db:
        repo = UserRepository(db)
        for username, password, role in users:
            existing = repo.get_by_username(username)
            if existing is not None:
                existing.role = role
                existing.is_active = True
                continue

            repo.create(
                username=username,
                password_hash=hash_password(password),
                role=role,
            )
        db.commit()


if __name__ == "__main__":
    seed_users()
