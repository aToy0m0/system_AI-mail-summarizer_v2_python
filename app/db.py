from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except:  # noqa: E722
        session.rollback()
        raise
    finally:
        session.close()

