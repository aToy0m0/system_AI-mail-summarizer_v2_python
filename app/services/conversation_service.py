from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai_prompt import build_edit_prompt, build_summarize_prompt
from app.config import settings
from app.email_cleaner import clean_email_text
from app.json_extract import try_parse_json_answer
from app.models import Conversation, Email, FormState, User
from app.services.dify_service import DifyService

_SUMMARY_MAX_CHARS = 200
_CAUSE_MAX_CHARS = 200
_ACTION_MAX_CHARS = 200


def _limit_chars(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = s or ""
    return s if len(s) <= max_chars else s[:max_chars]


class ConversationService:
    def __init__(self, dify: DifyService) -> None:
        self._dify = dify

    def get_by_dify_id(self, session: Session, *, user_id: int, dify_id: str) -> Conversation | None:
        return (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == dify_id)
            .one_or_none()
        )

    def get_or_create_for_case(self, session: Session, *, user: User, case_id: int) -> Conversation:
        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user.id, Conversation.pleasanter_case_result_id == case_id)
            .one_or_none()
        )
        if conv:
            return conv

        data = self._dify.chat(
            query=f"案件 {case_id} の会話を開始します。",
            conversation_id="",
            inputs={},
            user=self._dify.build_user(user.username),
        )
        conversation_id = str(data.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=502, detail="Dify did not return conversation_id")

        conv = Conversation(
            user_id=user.id,
            dify_conversation_id=conversation_id,
            title=f"案件 {case_id}",
            pleasanter_case_result_id=case_id,
        )
        session.add(conv)
        session.flush()
        form = FormState(conversation_id=conv.id)
        session.add(form)
        conv.form = form
        return conv

    def ensure_form(self, session: Session, conv: Conversation) -> FormState:
        if conv.form:
            return conv.form
        conv.form = FormState(conversation_id=conv.id)
        session.add(conv.form)
        return conv.form

    def apply_parsed_to_form(self, form: FormState, parsed: dict[str, Any]) -> None:
        """パース結果をフォームに適用する。parsedに含まれるフィールドのみを更新する。"""
        summary_keys = [settings.pleasanter_case_summary_column, "summary", "overview", "DescriptionA"]
        cause_keys = [settings.pleasanter_case_cause_column, "cause", "DescriptionB"]
        action_keys = [settings.pleasanter_case_action_column, "action", "solution", "DescriptionC"]
        body_keys = [settings.pleasanter_case_body_column, "body", "details", "Body"]

        def pick(keys: list[str]) -> tuple[bool, str]:
            for k in keys:
                if k not in parsed:
                    continue
                v = parsed.get(k)
                if v is None:
                    continue
                if isinstance(v, str) and not v.strip():
                    continue
                return True, str(v)
            return False, ""

        has_summary, summary = pick(summary_keys)
        has_cause, cause = pick(cause_keys)
        has_action, action = pick(action_keys)
        has_body, body = pick(body_keys)

        if has_summary:
            form.summary = _limit_chars(summary, _SUMMARY_MAX_CHARS)
        if has_cause:
            form.cause = _limit_chars(cause, _CAUSE_MAX_CHARS)
        if has_action:
            form.action = _limit_chars(action, _ACTION_MAX_CHARS)
        if has_body:
            form.body = body

    def list_conversations(self, session: Session, *, user_id: int) -> list[dict[str, Any]]:
        rows = session.query(Conversation).filter(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).all()
        return [
            {"dify_conversation_id": r.dify_conversation_id, "title": r.title, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows
        ]

    def get_form(self, session: Session, *, user_id: int, conversation_id: str) -> dict[str, Any]:
        conv = self.get_by_dify_id(session, user_id=user_id, dify_id=conversation_id)
        if not conv or not conv.form:
            raise HTTPException(status_code=404, detail="conversation not found")
        f = conv.form
        return {
            "conversation_id": conversation_id,
            "summary_result_id": conv.pleasanter_case_result_id,
            "case_result_id": conv.pleasanter_case_result_id,
            "summary": f.summary,
            "cause": f.cause,
            "action": f.action,
            "body": f.body,
            "include_summary": f.include_summary,
            "include_cause": f.include_cause,
            "include_action": f.include_action,
            "include_body": f.include_body,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None,
        }

    def update_form(self, session: Session, *, user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        conv = self.get_by_dify_id(session, user_id=user_id, dify_id=conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        form = self.ensure_form(session, conv)
        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        form.summary = str(payload.get("summary") or "")
        form.cause = str(payload.get("cause") or "")
        form.action = str(payload.get("action") or "")
        form.body = str(payload.get("body") or "")
        form.include_summary = bool(payload.get("include_summary", True))
        form.include_cause = bool(payload.get("include_cause", True))
        form.include_action = bool(payload.get("include_action", True))
        form.include_body = bool(payload.get("include_body", True))
        return {"ok": True}

    def summarize_email(self, session: Session, *, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        raw_email = payload.get("email_text")
        if not isinstance(raw_email, str) or not raw_email.strip():
            raise HTTPException(status_code=400, detail="email_text is required (string)")

        conversation_id = str(payload.get("conversation_id") or "").strip()
        conv: Conversation | None = None
        if conversation_id:
            conv = self.get_by_dify_id(session, user_id=user.id, dify_id=conversation_id)

        cleaned = clean_email_text(raw_email)
        prompt = build_summarize_prompt(
            email_text=cleaned,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )
        data = self._dify.chat(query=prompt, conversation_id=conversation_id, inputs={}, user=self._dify.build_user(user.username))
        conversation_id = str(data.get("conversation_id") or conversation_id or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=502, detail="Dify did not return conversation_id")

        if not conv:
            conv = Conversation(user_id=user.id, dify_conversation_id=conversation_id, title="メール要約")
            session.add(conv)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                conv = self.get_by_dify_id(session, user_id=user.id, dify_id=conversation_id)
                if not conv:
                    raise

        form = self.ensure_form(session, conv)
        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        session.add(Email(conversation_id=conv.id, raw_text=raw_email, cleaned_text=cleaned))

        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if parsed and isinstance(parsed, dict):
            self.apply_parsed_to_form(form, parsed)

        return {"conversation_id": conversation_id, "answer": answer, "parsed": parsed}

    def form_ai_edit(self, session: Session, *, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        instruction = payload.get("instruction")
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")
        if not isinstance(instruction, str) or not instruction.strip():
            raise HTTPException(status_code=400, detail="instruction is required (string)")

        conv = self.get_by_dify_id(session, user_id=user.id, dify_id=conversation_id)
        if not conv or not conv.form:
            raise HTTPException(status_code=404, detail="conversation not found")
        f = conv.form

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        prompt = build_edit_prompt(
            instruction=instruction.strip(),
            summary=f.summary,
            cause=f.cause,
            action=f.action,
            body=f.body,
            include_summary=f.include_summary,
            include_cause=f.include_cause,
            include_action=f.include_action,
            include_body=f.include_body,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )
        data = self._dify.chat(query=prompt, conversation_id=conversation_id, inputs={}, user=self._dify.build_user(user.username))
        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if isinstance(parsed, dict):
            self.apply_parsed_to_form(f, parsed)

        return {"conversation_id": conversation_id, "answer": answer, "parsed": parsed}

    def chat_ui_get(self, session: Session, *, user: User, conversation_id: str) -> dict[str, Any]:
        data = self._dify.get_messages(conversation_id=conversation_id, user=self._dify.build_user(user.username), limit=50, first_id=None, last_id=None)
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = []
        items = sorted(items, key=lambda x: x.get("created_at") or 0)
        messages: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            user_msg = self._dify.extract_user_message(item.get("query") if isinstance(item.get("query"), str) else None)
            if user_msg:
                messages.append({"role": "user", "content": user_msg, "created_at": item.get("created_at")})
            comment = self._dify.extract_llm_comment(item.get("answer") if isinstance(item.get("answer"), str) else None)
            if comment:
                messages.append({"role": "assistant", "content": comment, "created_at": item.get("created_at")})
        return {"messages": messages, "conversation_id": conversation_id}

    def chat_ui_post(self, session: Session, *, user: User, conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        conv = self.get_by_dify_id(session, user_id=user.id, dify_id=conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        instruction = ""
        if isinstance(payload, dict):
            for key in ("user_comment", "instruction", "message", "text", "content", "query", "input", "prompt"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    instruction = val.strip()
                    break
        if not instruction:
            raise HTTPException(status_code=400, detail="user_comment is required")

        f = self.ensure_form(session, conv)

        has_summary = isinstance(payload.get("summary"), str)
        has_cause = isinstance(payload.get("cause"), str)
        has_action = isinstance(payload.get("action"), str)
        has_body = isinstance(payload.get("body"), str)

        f.include_summary = has_summary
        f.include_cause = has_cause
        f.include_action = has_action
        f.include_body = has_body

        if has_summary:
            f.summary = str(payload.get("summary") or "")
        if has_cause:
            f.cause = str(payload.get("cause") or "")
        if has_action:
            f.action = str(payload.get("action") or "")
        if has_body:
            f.body = str(payload.get("body") or "")

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        prompt = build_edit_prompt(
            instruction=instruction,
            summary=f.summary,
            cause=f.cause,
            action=f.action,
            body=f.body,
            include_summary=f.include_summary,
            include_cause=f.include_cause,
            include_action=f.include_action,
            include_body=f.include_body,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )
        data = self._dify.chat(query=prompt, conversation_id=conversation_id, inputs={}, user=self._dify.build_user(user.username))
        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if isinstance(parsed, dict):
            self.apply_parsed_to_form(f, parsed)

        comment = self._dify.extract_llm_comment(answer if isinstance(answer, str) else None)
        return {"message": comment or (answer if isinstance(answer, str) else ""), "answer": answer, "conversation_id": conversation_id}
