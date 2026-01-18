from __future__ import annotations

from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine
from app.models import User
from app.security import hash_password, verify_password

_ROLE_ADMIN = "admin"
_ROLE_USER = "user"
_ALLOWED_ROLES = {_ROLE_ADMIN, _ROLE_USER}


def normalize_role(role: str | None) -> str:
    role_s = str(role or "").strip().lower()
    return role_s if role_s in _ALLOWED_ROLES else _ROLE_USER


def is_admin_role(role: str | None) -> bool:
    return normalize_role(role) == _ROLE_ADMIN


def redirect_admin_message(kind: str, message: str) -> RedirectResponse:
    kind_s = str(kind or "").strip().lower()
    if kind_s not in {"ok", "error"}:
        kind_s = "ok"
    return RedirectResponse(url=f"/admin?{kind_s}={quote(str(message or '').strip())}", status_code=303)


class UserService:
    def authenticate(self, session: Session, *, username: str, password: str) -> User | None:
        user = session.query(User).filter(User.username == username).one_or_none()
        if not user or not verify_password(password, user.password_hash):
            return None
        return user

    def ensure_schema(self) -> None:
        insp = inspect(engine)
        if "users" not in set(insp.get_table_names()):
            return
        cols = {c["name"] for c in insp.get_columns("users")}
        if "role" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"))

    def ensure_admin_exists(self) -> None:
        with Session(engine) as session:
            user = session.query(User).filter(User.username == settings.admin_username).one_or_none()
            if user:
                if not is_admin_role(getattr(user, "role", None)):
                    user.role = _ROLE_ADMIN
                    session.commit()
                return
            session.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password), role=_ROLE_ADMIN))
            session.commit()

    def create_user(self, session: Session, *, username: str, password: str, role: str) -> None:
        session.add(User(username=username, password_hash=hash_password(password), role=normalize_role(role)))
        try:
            session.flush()
        except IntegrityError as e:
            raise HTTPException(status_code=400, detail="duplicate username") from e

    def change_password(self, session: Session, *, target_user_id: int, new_password: str) -> None:
        target = session.get(User, int(target_user_id))
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        target.password_hash = hash_password(new_password)

    def delete_user(self, session: Session, *, me_user_id: int, target_user_id: int) -> None:
        if int(target_user_id) == int(me_user_id):
            raise HTTPException(status_code=400, detail="cannot delete yourself")

        target = session.get(User, int(target_user_id))
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        if is_admin_role(getattr(target, "role", None)):
            admin_count = session.query(User).filter(User.role == _ROLE_ADMIN).count()
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="cannot delete last admin")
        session.delete(target)

    def list_users(self, session: Session) -> list[dict[str, object]]:
        users = session.query(User).order_by(User.created_at.asc(), User.id.asc()).all()
        return [
            {"id": u.id, "username": u.username, "role": getattr(u, "role", _ROLE_USER), "created_at": u.created_at}
            for u in users
        ]
