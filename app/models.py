from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("user_id", "dify_conversation_id", name="uq_user_dify_conversation"),
        UniqueConstraint("user_id", "pleasanter_case_result_id", name="uq_user_case_result_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    dify_conversation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    pleasanter_case_result_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    form: Mapped[Optional["FormState"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", uselist=False)
    emails: Mapped[list["Email"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")


class FormState(Base):
    __tablename__ = "form_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, unique=True, index=True)

    summary: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    cause: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)

    include_summary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_cause: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_action: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_body: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: dt.datetime.now(dt.timezone.utc),
        onupdate=lambda: dt.datetime.now(dt.timezone.utc),
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="form")


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (UniqueConstraint("pleasanter_mail_result_id", name="uq_pleasanter_mail_result_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False, index=True)

    pleasanter_mail_result_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    conversation: Mapped["Conversation"] = relationship(back_populates="emails")
