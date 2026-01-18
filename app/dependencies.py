from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import User


def get_db() -> Generator[Session, None, None]:
    """
    SQLAlchemy セッションを FastAPI の dependency として提供する。
    - 成功時 commit
    - 例外時 rollback
    """
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except:  # noqa: E722
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user_id(request: Request) -> int:
    # SessionMiddleware が request.scope["session"] に dict を格納する
    session = request.scope.get("session")
    if not isinstance(session, dict):
        raise HTTPException(status_code=401, detail="not logged in")
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="not logged in")
    return user_id


def get_current_user(
    user_id: int = Depends(get_current_user_id),
    session: Session = Depends(get_db),
) -> User:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="not logged in")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    role = str(getattr(user, "role", "user") or "").strip().lower()
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin required")
    return user

