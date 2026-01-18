from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai_prompt import build_summarize_prompt
from app.clients.pleasanter_client import PleasanterClient, build_case_view, build_mail_view
from app.config import settings
from app.email_cleaner import clean_email_text
from app.json_extract import try_parse_json_answer
from app.models import Conversation, Email, FormState, User
from app.services.conversation_service import ConversationService
from app.services.dify_service import DifyService

logger = logging.getLogger("pleasanter-mail-summarizer")


def _dev_debug_enabled() -> bool:
    return str(getattr(settings, "app_env", "dev")).lower() in {"dev", "development", "local"}


def _pleasanter_hint(base_url: str) -> str:
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return (
            "Docker内では localhost はコンテナ自身です。"
            "Pleasanter がホスト側にいる場合は http://host.docker.internal など到達可能なURLを指定してください。"
        )
    return "Pleasanter の URL/ネットワークを確認してください（Docker/Compose 構成も含む）。"


def _assert_pleasanter_ready() -> None:
    if not settings.pleasanter_base_url or not settings.pleasanter_api_key:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_BASE_URL / PLEASANTER_API_KEY)")
    if settings.pleasanter_mail_site_id is None:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_MAIL_SITE_ID)")


def _assert_pleasanter_summary_ready() -> None:
    if not settings.pleasanter_base_url or not settings.pleasanter_api_key:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_BASE_URL / PLEASANTER_API_KEY)")
    if settings.pleasanter_summary_site_id is None:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_SUMMARY_SITE_ID)")


def _extract_items_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    resp = data.get("Response")
    if isinstance(resp, dict):
        v = resp.get("Data")
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return v
    for key in ("Data", "Items", "Results"):
        v = data.get(key)
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return v
    for v in data.values():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            return v
    return []


def _extract_nested_value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        if key in obj:
            return obj.get(key)
        for v in obj.values():
            found = _extract_nested_value(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _extract_nested_value(v, key)
            if found is not None:
                return found
    return None


def _extract_mail_body(item: dict[str, Any], preferred_key: str) -> str:
    for k in [preferred_key, "Body", "MailBody", "Text", "Description"]:
        v = item.get(k)
        if v is None:
            v = _extract_nested_value(item, k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _extract_mail_link_value(item: dict[str, Any], link_column: str) -> str:
    v = item.get(link_column)
    if v is None:
        v = _extract_nested_value(item, link_column)
    if isinstance(v, str):
        return v.strip()
    if v is None:
        return ""
    return str(v).strip()


def _safe_preview(s: str, max_chars: int = 400) -> str:
    s = (s or "").replace("\r\n", "\n")
    return s if len(s) <= max_chars else s[:max_chars] + "…"


def _redact_api_key(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload or {})
    if "ApiKey" in redacted:
        redacted["ApiKey"] = "***"
    return redacted


def _build_pleasanter_debug(*, ple_resp, view: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    status_code = ple_resp.data.get("StatusCode") if isinstance(ple_resp.data, dict) else None
    message = ple_resp.data.get("Message") if isinstance(ple_resp.data, dict) else None
    response = ple_resp.data.get("Response") if isinstance(ple_resp.data, dict) else None
    offset = response.get("Offset") if isinstance(response, dict) else None
    page_size = response.get("PageSize") if isinstance(response, dict) else None
    total_count = response.get("TotalCount") if isinstance(response, dict) else None

    return {
        "pleasanter_url": ple_resp.request_url,
        "http_status": ple_resp.status_code,
        "ok": getattr(ple_resp, "ok", None),
        "error_message": getattr(ple_resp, "error_message", None),
        "StatusCode": status_code,
        "Message": message,
        "Response": {"Offset": offset, "PageSize": page_size, "TotalCount": total_count},
        "pleasanter_request": _redact_api_key(ple_resp.request_payload),
        "view": view,
        "pleasanter_keys": sorted(list(ple_resp.data.keys())) if isinstance(ple_resp.data, dict) else None,
        "items_count": len(items),
        "first_item_keys": sorted(list(items[0].keys())) if items else [],
        "sample_first_item": items[0] if items else None,
        "raw_response_preview": _safe_preview(ple_resp.text, max_chars=2000),
    }


@dataclass(frozen=True)
class SummarizeCaseResult:
    conversation_id: str
    summary_result_id: int
    target_case_result_ids: list[int]
    emails_total: int
    emails_stored: int
    latest_mail_result_id: int | None
    answer: str | None
    parsed: dict[str, Any] | None
    debug: dict[str, Any] | None = None


class PleasanterService:
    def __init__(self, dify: DifyService, conversations: ConversationService) -> None:
        self._dify = dify
        self._conversations = conversations

    def _client(self) -> PleasanterClient:
        return PleasanterClient(
            base_url=settings.pleasanter_base_url or "",
            api_key=settings.pleasanter_api_key or "",
            api_version=settings.pleasanter_api_version,
        )

    def list_summaries(self, *, request: Request, query: str | None, limit: int) -> dict[str, Any]:
        _assert_pleasanter_summary_ready()
        try:
            limit = max(1, min(int(limit), 200))
        except Exception:
            limit = 50

        ple = self._client()
        view = build_case_view()
        ple_resp = ple.get_items(site_id=settings.pleasanter_summary_site_id or 0, view=view, offset=0, page_size=limit)
        items = _extract_items_list(ple_resp.data)
        pleasanter_debug = _build_pleasanter_debug(ple_resp=ple_resp, view=view, items=items)
        if not ple_resp.ok:
            detail: dict[str, Any] = {
                "message": "Pleasanter API error",
                "base_url": settings.pleasanter_base_url,
                "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                "checks": ["PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_SUMMARY_SITE_ID を確認"],
                "pleasanter": pleasanter_debug,
            }
            raise HTTPException(status_code=502, detail=detail)

        q = (query or "").strip().lower()
        results: list[dict[str, Any]] = []
        for it in items:
            result_id = it.get("ResultId")
            title = it.get("Title") or ""
            updated_time = it.get("UpdatedTime")
            if q:
                hay = f"{result_id} {title}".lower()
                if q not in hay:
                    continue
            results.append({"result_id": result_id, "title": title, "updated_time": updated_time})

        return {"items": results, "total": len(results), "site_id": settings.pleasanter_summary_site_id, "site_type": "summary"}

    def lookup_summary(self, *, case_result_id: int) -> dict[str, Any]:
        _assert_pleasanter_summary_ready()
        ple = self._client()
        view = build_case_view(result_id=case_result_id)
        ple_resp = ple.get_items(site_id=settings.pleasanter_summary_site_id or 0, view=view, offset=0, page_size=1)
        items = _extract_items_list(ple_resp.data)
        pleasanter_debug = _build_pleasanter_debug(ple_resp=ple_resp, view=view, items=items)
        if not ple_resp.ok:
            detail: dict[str, Any] = {
                "message": "Pleasanter API error",
                "base_url": settings.pleasanter_base_url,
                "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                "checks": ["PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_SUMMARY_SITE_ID を確認"],
                "pleasanter": pleasanter_debug,
            }
            raise HTTPException(status_code=502, detail=detail)

        if not items:
            raise HTTPException(status_code=404, detail={"message": "Summary not found", "summary_result_id": case_result_id})

        it = items[0]
        return {
            "result_id": it.get("ResultId"),
            "summary_result_id": it.get("ResultId"),
            "title": it.get("Title") or "",
            "updated_time": it.get("UpdatedTime"),
            "site_id": settings.pleasanter_summary_site_id,
            "site_type": "summary",
        }

    def summarize_case(self, session: Session, *, request: Request, user: User, payload: dict[str, Any]) -> SummarizeCaseResult:
        _assert_pleasanter_ready()

        summary_result_id = payload.get("summary_result_id")
        if summary_result_id is None:
            summary_result_id = payload.get("case_result_id")
        try:
            summary_result_id_int = int(summary_result_id)
        except Exception:
            raise HTTPException(status_code=400, detail="summary_result_id is required (int)")

        requested_conversation_id = str(payload.get("conversation_id") or "").strip()

        ple = self._client()
        if settings.pleasanter_summary_site_id is None:
            raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_SUMMARY_SITE_ID)")
        if settings.pleasanter_case_site_id is None:
            raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_CASE_SITE_ID)")

        # 1) サマリー(ResultId) -> Title を取得
        summary_view = build_case_view(result_id=summary_result_id_int)
        summary_resp = ple.get_items(site_id=settings.pleasanter_summary_site_id, view=summary_view, offset=0, page_size=1)
        summary_items = _extract_items_list(summary_resp.data)
        summary_debug = _build_pleasanter_debug(ple_resp=summary_resp, view=summary_view, items=summary_items)
        if not summary_resp.ok:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Pleasanter API error",
                    "base_url": settings.pleasanter_base_url,
                    "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                    "checks": ["PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_SUMMARY_SITE_ID を確認"],
                    "pleasanter": {"summary": summary_debug},
                },
            )
        if not summary_items:
            raise HTTPException(status_code=404, detail={"message": "Summary not found", "summary_result_id": summary_result_id_int})

        summary_title = str(summary_items[0].get("Title") or "").strip()
        if not summary_title:
            raise HTTPException(status_code=400, detail={"message": "Summary Title is empty", "summary_result_id": summary_result_id_int})

        # 2) Title から A/B の案件を引く
        target_case_titles = [f"{summary_title}A", f"{summary_title}B"]
        target_case_result_ids: list[int] = []
        target_case_id_to_title: dict[int, str] = {}
        case_debug_list: list[dict[str, Any]] = []
        for t in target_case_titles:
            case_view = build_case_view(title=t)
            case_resp = ple.get_items(site_id=settings.pleasanter_case_site_id, view=case_view, offset=0, page_size=5)
            case_items = _extract_items_list(case_resp.data)
            case_debug_list.append({"title": t, "debug": _build_pleasanter_debug(ple_resp=case_resp, view=case_view, items=case_items)})
            if not case_resp.ok:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "Pleasanter API error",
                        "base_url": settings.pleasanter_base_url,
                        "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                        "checks": ["PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_CASE_SITE_ID を確認"],
                        "pleasanter": {"summary": summary_debug, "cases": case_debug_list},
                    },
                )

            for it in case_items:
                rid = it.get("ResultId")
                try:
                    rid_int = int(rid) if rid is not None else None
                except Exception:
                    rid_int = None
                if rid_int is not None and rid_int not in target_case_result_ids:
                    target_case_result_ids.append(rid_int)
                    target_case_id_to_title[rid_int] = str(it.get("Title") or "").strip() or t

        if not target_case_result_ids:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "No target cases found for this summary title",
                    "summary_result_id": summary_result_id_int,
                    "summary_title": summary_title,
                    "target_case_titles": target_case_titles,
                },
            )

        # 3) 各案件に紐づくメールを取得
        all_mail_items: list[dict[str, Any]] = []
        mail_debug_list: list[dict[str, Any]] = []
        for case_id in target_case_result_ids:
            expected_case_title = target_case_id_to_title.get(case_id) or ""
            mail_view = build_mail_view(
                link_column=settings.pleasanter_mail_link_column,
                case_result_id=case_id,
                body_column=settings.pleasanter_mail_body_column,
            )
            mail_resp = ple.get_items(site_id=settings.pleasanter_mail_site_id or 0, view=mail_view, offset=0, page_size=200)
            mail_items = _extract_items_list(mail_resp.data)

            filtered_mail_items: list[dict[str, Any]] = []
            filtered_out = 0
            if expected_case_title:
                for it in mail_items:
                    link_value = _extract_mail_link_value(it, settings.pleasanter_mail_link_column)
                    if link_value == expected_case_title or link_value == str(case_id):
                        filtered_mail_items.append(it)
                    else:
                        filtered_out += 1
            else:
                filtered_mail_items = mail_items

            # link_value が Title にならない環境向けフォールバック
            if not filtered_mail_items and expected_case_title:
                alt_view = {
                    "ApiDataType": "KeyValues",
                    "ApiColumnKeyDisplayType": "ColumnName",
                    "GridColumns": ["ResultId", "Title", "UpdatedTime", settings.pleasanter_mail_link_column, settings.pleasanter_mail_body_column],
                    "ColumnFilterHash": {settings.pleasanter_mail_link_column: expected_case_title},
                    "ColumnFilterSearchTypes": {settings.pleasanter_mail_link_column: "ExactMatch"},
                    "ColumnSorterHash": {"UpdatedTime": "desc"},
                }
                alt_resp = ple.get_items(site_id=settings.pleasanter_mail_site_id or 0, view=alt_view, offset=0, page_size=200)
                alt_items = _extract_items_list(alt_resp.data)
                if alt_items:
                    filtered_mail_items = alt_items
                    mail_items = alt_items

            mail_debug_list.append(
                {
                    "case_result_id": case_id,
                    "expected_case_title": expected_case_title,
                    "items_raw": len(mail_items),
                    "items_filtered": len(filtered_mail_items),
                    "items_filtered_out": filtered_out,
                    "debug": _build_pleasanter_debug(ple_resp=mail_resp, view=mail_view, items=mail_items),
                }
            )

            if not mail_resp.ok:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "Pleasanter API error",
                        "base_url": settings.pleasanter_base_url,
                        "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                        "checks": [
                            "PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_MAIL_SITE_ID を確認",
                            "PLEASANTER_MAIL_LINK_COLUMN（例: ClassD）を確認",
                            "PLEASANTER_MAIL_BODY_COLUMN（例: Body）を確認",
                        ],
                        "pleasanter": {"summary": summary_debug, "cases": case_debug_list, "mails": mail_debug_list},
                    },
                )
            all_mail_items.extend(filtered_mail_items)

        # ResultId で重複排除
        dedup: dict[str, dict[str, Any]] = {}
        for it in all_mail_items:
            rid = it.get("ResultId")
            key = str(rid) if rid is not None else str(it)
            dedup.setdefault(key, it)
        items = list(dedup.values())

        pleasanter_debug: dict[str, Any] = {
            "summary_result_id": summary_result_id_int,
            "summary_title": summary_title,
            "target_case_titles": target_case_titles,
            "target_case_result_ids": target_case_result_ids,
            "summary": summary_debug,
            "cases": case_debug_list,
            "mails": mail_debug_list,
        }

        logger.info(
            "pleasanter fetched summary=%s cases=%s site=%s items=%s link=%s body=%s",
            summary_result_id_int,
            target_case_result_ids,
            settings.pleasanter_mail_site_id,
            len(items),
            settings.pleasanter_mail_link_column,
            settings.pleasanter_mail_body_column,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )

        # UpdatedTime が空/未指定でも落ちない sort key
        def _sort_key(item: dict[str, Any]) -> tuple[bool, str]:
            v = item.get("UpdatedTime") or ""
            return (v == "", str(v))

        sorted_items = sorted(items, key=_sort_key)

        stored = 0
        latest_raw: str | None = None
        latest_cleaned: str | None = None
        latest_mail_result_id: int | None = None

        # 会話を決定
        conv: Conversation | None = None
        if requested_conversation_id:
            conv = self._conversations.get_by_dify_id(session, user_id=user.id, dify_id=requested_conversation_id)
            if not conv:
                raise HTTPException(status_code=404, detail="conversation not found")
            if conv.pleasanter_case_result_id is not None and conv.pleasanter_case_result_id != summary_result_id_int:
                raise HTTPException(status_code=400, detail="conversation is linked to a different summary_result_id")
            if conv.pleasanter_case_result_id is None:
                conv.pleasanter_case_result_id = summary_result_id_int
        else:
            conv = session.query(Conversation).filter(Conversation.user_id == user.id, Conversation.pleasanter_case_result_id == summary_result_id_int).one_or_none()
            if conv and summary_title:
                conv.title = f"案件サマリ {summary_title}"

        email_blocks: list[str] = []
        try:
            for idx, it in enumerate(sorted_items, start=1):
                mail_result_id = it.get("ResultId")
                try:
                    mail_result_id_int = int(mail_result_id) if mail_result_id is not None else None
                except Exception:
                    mail_result_id_int = None

                raw_text = _extract_mail_body(it, settings.pleasanter_mail_body_column)
                if not raw_text:
                    continue
                cleaned = clean_email_text(raw_text)
                email_blocks.append(f"## メール{idx}\n{cleaned}".strip())

                latest_raw = raw_text
                latest_cleaned = cleaned
                latest_mail_result_id = mail_result_id_int

                if not conv or mail_result_id_int is None:
                    continue

                # pleasanter_mail_result_id はユニークなので、存在チェックは conversation_id に依存しない
                exists = session.query(Email).filter(Email.pleasanter_mail_result_id == mail_result_id_int).one_or_none()
                if exists:
                    continue

                session.add(
                    Email(
                        conversation_id=conv.id,
                        pleasanter_mail_result_id=mail_result_id_int,
                        raw_text=raw_text,
                        cleaned_text=cleaned,
                    )
                )
                stored += 1
        except SQLAlchemyError as e:
            detail: dict[str, Any] = {"message": "DB error while processing Pleasanter response", "pleasanter": pleasanter_debug}
            if _dev_debug_enabled():
                detail["error"] = str(e)
            raise HTTPException(status_code=500, detail=detail)

        if not latest_cleaned:
            debug: dict[str, Any] = {}
            if _dev_debug_enabled():
                debug = {"pleasanter": pleasanter_debug, "body_column": settings.pleasanter_mail_body_column}
            raise HTTPException(status_code=404, detail={"message": "No email body found for this summary", "debug": debug})

        combined_cleaned = "\n\n".join(email_blocks).strip()
        prompt = build_summarize_prompt(
            email_text=combined_cleaned,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )

        data = self._dify.chat(
            query=prompt,
            conversation_id=conv.dify_conversation_id if conv else "",
            inputs={},
            user=self._dify.build_user(user.username),
        )
        dify_conversation_id = str(data.get("conversation_id") or "").strip()
        if not dify_conversation_id:
            raise HTTPException(status_code=502, detail="Dify did not return conversation_id")

        if not conv:
            conv = Conversation(
                user_id=user.id,
                dify_conversation_id=dify_conversation_id,
                title=f"案件サマリ {summary_title}",
                pleasanter_case_result_id=summary_result_id_int,
            )
            session.add(conv)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                conv = session.query(Conversation).filter(Conversation.user_id == user.id, Conversation.pleasanter_case_result_id == summary_result_id_int).one_or_none()
                if not conv:
                    raise

            form = FormState(conversation_id=conv.id)
            session.add(form)
            conv.form = form
        else:
            if conv.dify_conversation_id != dify_conversation_id:
                conv.dify_conversation_id = dify_conversation_id

            # 既存会話でも未保存メールを取り込む（ユニーク制約に合わせて冪等に）
            for it in sorted_items:
                mail_result_id = it.get("ResultId")
                try:
                    mail_result_id_int = int(mail_result_id) if mail_result_id is not None else None
                except Exception:
                    mail_result_id_int = None
                if mail_result_id_int is None:
                    continue
                exists = session.query(Email).filter(Email.pleasanter_mail_result_id == mail_result_id_int).one_or_none()
                if exists:
                    continue
                raw_text = _extract_mail_body(it, settings.pleasanter_mail_body_column)
                if not raw_text:
                    continue
                cleaned = clean_email_text(raw_text)
                session.add(
                    Email(
                        conversation_id=conv.id,
                        pleasanter_mail_result_id=mail_result_id_int,
                        raw_text=raw_text,
                        cleaned_text=cleaned,
                    )
                )
                stored += 1

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if parsed and isinstance(parsed, dict):
            form = self._conversations.ensure_form(session, conv)
            self._conversations.apply_parsed_to_form(form, parsed)

        debug_payload: dict[str, Any] | None = None
        if _dev_debug_enabled():
            debug_payload = {
                "pleasanter": pleasanter_debug,
                "body_column": settings.pleasanter_mail_body_column,
                "latest_raw_preview": _safe_preview(latest_raw or ""),
                "latest_cleaned_preview": _safe_preview(latest_cleaned or ""),
                "first_item_keys": sorted(list(items[0].keys())) if items else [],
                "request_id": getattr(request.state, "request_id", None),
            }

        return SummarizeCaseResult(
            conversation_id=conv.dify_conversation_id,
            summary_result_id=summary_result_id_int,
            target_case_result_ids=target_case_result_ids,
            emails_total=len(items),
            emails_stored=stored,
            latest_mail_result_id=latest_mail_result_id,
            answer=answer if isinstance(answer, str) else None,
            parsed=parsed if isinstance(parsed, dict) else None,
            debug=debug_payload,
        )

    def save_summary(self, session: Session, *, request: Request, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "pleasanter save_summary request received conversation_id=%s",
            payload.get("conversation_id"),
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        _assert_pleasanter_ready()
        if settings.pleasanter_summary_site_id is None:
            raise HTTPException(status_code=400, detail="PLEASANTER_SUMMARY_SITE_ID is not configured")

        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")

        conv = self._conversations.get_by_dify_id(session, user_id=user.id, dify_id=str(conversation_id))
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
        if conv.pleasanter_case_result_id is None:
            raise HTTPException(status_code=400, detail="conversation has no summary_result_id")
        if not conv.form:
            raise HTTPException(status_code=400, detail="conversation has no form data")

        summary_result_id = int(conv.pleasanter_case_result_id)
        summary = conv.form.summary or ""
        cause = conv.form.cause or ""
        action = conv.form.action or ""
        body = conv.form.body or ""

        ple = self._client()
        logger.info(
            "pleasanter save_summary: updating summary summary_id=%s summary_len=%s cause_len=%s action_len=%s body_len=%s",
            summary_result_id,
            len(summary),
            len(cause),
            len(action),
            len(body),
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        update_resp = ple.update_item(
            record_id=summary_result_id,
            fields={"DescriptionA": summary, "DescriptionB": cause, "DescriptionC": action, "Body": body},
        )
        if not update_resp.ok:
            logger.error(
                "pleasanter save_summary: failed to update summary error=%s",
                update_resp.error_message,
                extra={"request_id": getattr(request.state, "request_id", None)},
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to update summary record in Pleasanter",
                    "pleasanter_error": update_resp.error_message,
                    "summary_result_id": summary_result_id,
                },
            )

        logger.info(
            "pleasanter saved summary summary=%s",
            summary_result_id,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return {"ok": True, "summary_result_id": summary_result_id, "case_result_id": summary_result_id, "message": "まとめてサマリに保存しました"}

    def save_case(self, session: Session, *, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=400, detail="conversation_id is required")

        conv = self._conversations.get_by_dify_id(session, user_id=user.id, dify_id=conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
        if conv.title and str(conv.title).startswith("案件サマリ"):
            raise HTTPException(status_code=400, detail="この会話は案件サマリ用です。/api/pleasanter/save_summary を使用してください")
        if conv.pleasanter_case_result_id is None:
            raise HTTPException(status_code=400, detail="conversation has no case_result_id")
        if not conv.form:
            raise HTTPException(status_code=400, detail="conversation has no form data")

        case_result_id = int(conv.pleasanter_case_result_id)
        f = conv.form

        fields = {
            settings.pleasanter_case_summary_column: f.summary or "",
            settings.pleasanter_case_cause_column: f.cause or "",
            settings.pleasanter_case_action_column: f.action or "",
            settings.pleasanter_case_body_column: f.body or "",
        }

        ple = self._client()
        update_resp = ple.update_item(record_id=case_result_id, fields=fields)
        if not update_resp.ok:
            raise HTTPException(
                status_code=502,
                detail={"message": "Failed to update case record in Pleasanter", "pleasanter_error": update_resp.error_message, "case_result_id": case_result_id},
            )

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        return {"ok": True, "case_result_id": case_result_id, "message": "案件に保存しました"}

