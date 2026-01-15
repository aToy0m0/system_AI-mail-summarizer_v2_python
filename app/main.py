from __future__ import annotations

import datetime as dt
import logging
import os
import traceback
import uuid
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from app.ai_prompt import build_edit_prompt, build_summarize_prompt
from app.config import settings
from app.db import engine, session_scope
from app.dify_client import DifyClient
from app.email_cleaner import clean_email_text
from app.json_extract import try_parse_json_answer
from app.models import Base, Conversation, Email, FormState, User
from app.pleasanter_client import PleasanterClient, build_case_view, build_mail_view
from app.security import hash_password, verify_password

app = FastAPI(title=" Pleasanterメール要約 (python)")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_SUMMARY_MAX_CHARS = 200
_CAUSE_MAX_CHARS = 200
_ACTION_MAX_CHARS = 200

logger = logging.getLogger(" Pleasanterメール要約")


def _get_user_id(request: Request) -> int | None:
    # SessionMiddleware より外側のミドルウェアから呼ばれる可能性があるため、
    # request.session を直接参照せず scope から安全に取り出す。
    session = request.scope.get("session")
    if not isinstance(session, dict):
        return None
    user_id = session.get("user_id")
    return user_id if isinstance(user_id, int) else None


def _require_user_id(request: Request) -> int:
    user_id = _get_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="not logged in")
    return user_id


def _dify_user(username: str) -> str:
    return f"{settings.dify_user_prefix}{username}"


def _limit_chars(s: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    s = s or ""
    return s if len(s) <= max_chars else s[:max_chars]


def _extract_llm_comment(answer: str | None) -> str | None:
    if not answer:
        return None
    parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
    if parsed and isinstance(parsed, dict):
        comment = parsed.get("llm_comment")
        if isinstance(comment, str) and comment.strip():
            return comment.strip()
    return None


def _extract_user_message(query: str | None) -> str | None:
    """
    Difyの会話履歴から「ユーザー発言」として表示したい短いテキストを取り出す。
    - プロンプト先頭に埋め込んだマーカー（<<<USER_MESSAGE_BEGIN>>> ... <<<USER_MESSAGE_END>>>）があればそれを優先
    - マーカーが無ければ、短いテキストのみ返す（長いプロンプトはUIに出さない）
    """
    if not isinstance(query, str):
        return None
    q = query.strip()
    if not q:
        return None

    begin = "<<<USER_MESSAGE_BEGIN>>>"
    end = "<<<USER_MESSAGE_END>>>"
    b = q.find(begin)
    if b != -1:
        b2 = b + len(begin)
        e = q.find(end, b2)
        if e != -1:
            msg = q[b2:e].strip()
            return msg if msg else None

    # フォールバック: プロンプト全文が表示されるのを避ける
    return q if len(q) <= 160 else None


def _apply_parsed_to_form(form: FormState, parsed: dict[str, Any]) -> None:
    """パース結果をフォームに適用する。parsedに含まれるフィールドのみを更新する。"""
    # 新スキーマ（Pleasanter物理名）を優先しつつ、旧スキーマ（cause/solution/details）も吸収する
    summary_keys = [settings.pleasanter_case_summary_column, "summary", "overview", "DescriptionA"]
    cause_keys = [settings.pleasanter_case_cause_column, "cause", "DescriptionB"]
    action_keys = [settings.pleasanter_case_action_column, "action", "solution", "DescriptionC"]
    body_keys = [settings.pleasanter_case_body_column, "body", "details", "Body"]

    def pick(keys: list[str]) -> tuple[bool, str]:
        for k in keys:
            if k in parsed:
                return True, str(parsed.get(k) or "")
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


def _dev_debug_enabled() -> bool:
    return settings.app_env.lower() in {"dev", "development", "local"}


def _assert_pleasanter_ready() -> None:
    if not settings.pleasanter_base_url or not settings.pleasanter_api_key:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_BASE_URL / PLEASANTER_API_KEY)")
    if settings.pleasanter_mail_site_id is None:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_MAIL_SITE_ID)")


def _assert_pleasanter_case_ready() -> None:
    if not settings.pleasanter_base_url or not settings.pleasanter_api_key:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_BASE_URL / PLEASANTER_API_KEY)")
    if settings.pleasanter_case_site_id is None:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_CASE_SITE_ID)")


def _extract_items_list(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Pleasanter の標準レスポンス: {"StatusCode":200, "Response":{"Data":[...]}}
    resp = data.get("Response")
    if isinstance(resp, dict):
        v = resp.get("Data")
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return v

    # Pleasanter のレスポンス形式は View/ApiDataType 等で変わり得るため、よくあるキーを順に拾う
    for key in ("Data", "Items", "Results"):
        v = data.get(key)
        if isinstance(v, list) and all(isinstance(x, dict) for x in v):
            return v
    # 最後の保険：dict の値の中に list[dict] があれば拾う
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


def _dify_hint(base_url: str) -> str:
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return "Docker内では localhost はwebコンテナ自身です。Difyがホスト側なら http://host.docker.internal/v1 を検討してください。"
    return "DifyのURL/起動状態/ネットワークを確認してください（Dockerならサービス名 or host.docker.internal）。"


def _pleasanter_hint(base_url: str) -> str:
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return "Docker内では localhost はwebコンテナ自身です。Pleasanterがホスト側なら http://host.docker.internal を検討してください。"
    return "PleasanterのURL/起動状態/ネットワークを確認してください（Dockerならサービス名 or host.docker.internal）。"


def _dify_chat_or_502(*, query: str, conversation_id: str, inputs: dict[str, Any], user: str) -> dict[str, Any]:
    dify = DifyClient(base_url=settings.dify_base_url, api_key=settings.dify_api_key)
    try:
        return dify.chat(query=query, conversation_id=conversation_id, inputs=inputs, user=user)
    except Exception as e:
        detail: dict[str, Any] = {"message": "Dify connection failed", "base_url": settings.dify_base_url, "hint": _dify_hint(settings.dify_base_url)}
        if _dev_debug_enabled():
            detail["error"] = str(e)
        raise HTTPException(status_code=502, detail=detail)


def _get_or_create_conversation_for_case(session, *, user: User, case_result_id: int) -> Conversation:
    conv = (
        session.query(Conversation)
        .filter(Conversation.user_id == user.id, Conversation.pleasanter_case_result_id == case_result_id)
        .one_or_none()
    )
    if conv:
        return conv

    data = _dify_chat_or_502(
        query=f"案件 {case_result_id} の会話を開始します。",
        conversation_id="",
        inputs={},
        user=_dify_user(user.username),
    )
    conversation_id = str(data.get("conversation_id") or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=502, detail="Dify did not return conversation_id")

    conv = Conversation(
        user_id=user.id,
        dify_conversation_id=conversation_id,
        title=f"案件 {case_result_id}",
        pleasanter_case_result_id=case_result_id,
    )
    session.add(conv)
    session.flush()
    form = FormState(conversation_id=conv.id)
    session.add(form)
    conv.form = form
    return conv


def _get_or_create_admin() -> None:
    with session_scope() as session:
        user = session.query(User).filter(User.username == settings.admin_username).one_or_none()
        if user:
            return
        session.add(User(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))


@app.middleware("http")
async def request_debug_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    user_id = _get_user_id(request)
    logger.info("request start %s %s user=%s", request.method, request.url.path, user_id, extra={"request_id": request_id})
    try:
        response = await call_next(request)
    except Exception as e:
        logger.exception("request error: %s", str(e), extra={"request_id": request_id})
        content: dict[str, Any] = {"error": "internal server error", "request_id": request_id}
        if _dev_debug_enabled():
            content["traceback"] = traceback.format_exc()
        resp = JSONResponse(status_code=500, content=content)
        resp.headers["X-Request-ID"] = request_id
        return resp

    response.headers["X-Request-ID"] = request_id
    logger.info("request end %s %s status=%s", request.method, request.url.path, getattr(response, "status_code", None), extra={"request_id": request_id})
    return response


@app.on_event("startup")
def startup() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    Base.metadata.create_all(bind=engine)
    _get_or_create_admin()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if _get_user_id(request) is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    with session_scope() as session:
        user = session.query(User).filter(User.username == username).one_or_none()
        if not user or not verify_password(password, user.password_hash):
            return RedirectResponse(url="/login?error=1", status_code=303)
        request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    if _get_user_id(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "log_level": log_level,
            "case_summary_column": settings.pleasanter_case_summary_column,
            "case_cause_column": settings.pleasanter_case_cause_column,
            "case_action_column": settings.pleasanter_case_action_column,
            "case_body_column": settings.pleasanter_case_body_column,
        },
    )


@app.get("/api/me")
def api_me(request: Request) -> dict[str, Any]:
    user_id = _require_user_id(request)
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")
        return {"id": user.id, "username": user.username}


@app.get("/api/conversations")
def api_conversations(request: Request) -> list[dict[str, Any]]:
    user_id = _require_user_id(request)
    with session_scope() as session:
        rows = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        return [
            {
                "dify_conversation_id": r.dify_conversation_id,
                "title": r.title,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


@app.post("/api/conversations")
def api_create_conversation(request: Request) -> dict[str, Any]:
    # 互換のためにエンドポイント自体は残すが、Difyへは送信しない
    return {"conversation_id": ""}


@app.get("/api/form")
def api_get_form(request: Request, conversation_id: str) -> dict[str, Any]:
    user_id = _require_user_id(request)
    with session_scope() as session:
        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv or not conv.form:
            raise HTTPException(status_code=404, detail="conversation not found")
        f = conv.form
        return {
            "conversation_id": conversation_id,
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


@app.post("/api/form/update")
def api_update_form(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id(request)
    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    with session_scope() as session:
        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
        if not conv.form:
            conv.form = FormState(conversation_id=conv.id)

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        conv.form.summary = str(payload.get("summary") or "")
        conv.form.cause = str(payload.get("cause") or "")
        conv.form.action = str(payload.get("action") or "")
        conv.form.body = str(payload.get("body") or "")
        conv.form.include_summary = bool(payload.get("include_summary", True))
        conv.form.include_cause = bool(payload.get("include_cause", True))
        conv.form.include_action = bool(payload.get("include_action", True))
        conv.form.include_body = bool(payload.get("include_body", True))
        return {"ok": True}


@app.post("/api/chat")
def api_chat(request: Request, payload: dict[str, Any]) -> JSONResponse:
    user_id = _require_user_id(request)
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=400, detail="query is required (string)")

    conversation_id = payload.get("conversation_id")
    inputs = payload.get("inputs")
    user_override = payload.get("user")

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")
        dify_user = user_override if isinstance(user_override, str) and user_override.strip() else _dify_user(user.username)

    data = _dify_chat_or_502(
        query=query,
        conversation_id=conversation_id if isinstance(conversation_id, str) else "",
        inputs=inputs if isinstance(inputs, dict) else {},
        user=dify_user,
    )
    return JSONResponse(data)


@app.post("/api/summarize_email")
def api_summarize_email(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id(request)
    raw_email = payload.get("email_text")
    if not isinstance(raw_email, str) or not raw_email.strip():
        raise HTTPException(status_code=400, detail="email_text is required (string)")

    conversation_id = str(payload.get("conversation_id") or "").strip()

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        conv = None
        if conversation_id:
            conv = (
                session.query(Conversation)
                .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
                .one_or_none()
            )

        cleaned = clean_email_text(raw_email)

        # Difyへは実際のプロンプトで新規会話を開始する
        prompt = build_summarize_prompt(
            email_text=cleaned,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )
        data = _dify_chat_or_502(
            query=prompt,
            conversation_id=conversation_id if isinstance(conversation_id, str) else "",
            inputs={},
            user=_dify_user(user.username),
        )
        conversation_id = str(data.get("conversation_id") or conversation_id or "").strip()
        if not conversation_id:
            raise HTTPException(status_code=502, detail="Dify did not return conversation_id")

        if not conv:
            conv = Conversation(user_id=user_id, dify_conversation_id=conversation_id, title="メール要約")
            session.add(conv)
            session.flush()
            form = FormState(conversation_id=conv.id)
            session.add(form)
            conv.form = form

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        session.add(Email(conversation_id=conv.id, raw_text=raw_email, cleaned_text=cleaned))

        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if parsed and conv.form:
            _apply_parsed_to_form(conv.form, parsed)

        return {"conversation_id": conversation_id, "answer": answer, "parsed": parsed}


@app.post("/api/form/ai_edit")
def api_form_ai_edit(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id(request)
    conversation_id = str(payload.get("conversation_id") or "").strip()
    instruction = payload.get("instruction")
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    if not isinstance(instruction, str) or not instruction.strip():
        raise HTTPException(status_code=400, detail="instruction is required (string)")

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv or not conv.form:
            raise HTTPException(status_code=404, detail="conversation not found")
        f = conv.form

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

        data = _dify_chat_or_502(query=prompt, conversation_id=conversation_id, inputs={}, user=_dify_user(user.username))
        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None

        if parsed:
            _apply_parsed_to_form(f, parsed)

        return {"conversation_id": conversation_id, "answer": answer, "parsed": parsed}


@app.get("/api/dify/messages")
def api_dify_messages(
    request: Request,
    conversation_id: str,
    limit: int = 50,
    first_id: str | None = None,
    last_id: str | None = None,
) -> dict[str, Any]:
    user_id = _require_user_id(request)
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 50

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        dify = DifyClient(base_url=settings.dify_base_url, api_key=settings.dify_api_key)
        try:
            data = dify.get_messages(
                conversation_id=conversation_id,
                user=_dify_user(user.username),
                limit=limit,
                first_id=first_id,
                last_id=last_id,
            )
        except RuntimeError as e:
            detail: dict[str, Any] = {
                "message": "Dify connection failed",
                "base_url": settings.dify_base_url,
                "hint": _dify_hint(settings.dify_base_url),
                "error": str(e),
            }
            raise HTTPException(status_code=502, detail=detail)

        return data


@app.api_route("/api/chat-ui", methods=["GET", "POST"])
async def api_chat_ui(request: Request) -> dict[str, Any]:
    user_id = _require_user_id(request)
    conversation_id = (request.query_params.get("conversation_id") or "").strip()

    payload: dict[str, Any] = {}
    if request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            conversation_id = str(payload.get("conversation_id") or conversation_id or "").strip()

    if not conversation_id:
        if request.method == "GET":
            return {"messages": [], "conversation_id": ""}
        raise HTTPException(status_code=400, detail="conversation_id is required")

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        dify = DifyClient(base_url=settings.dify_base_url, api_key=settings.dify_api_key)

        if request.method == "GET":
            try:
                data = dify.get_messages(
                    conversation_id=conversation_id,
                    user=_dify_user(user.username),
                    limit=50,
                )
            except RuntimeError as e:
                detail: dict[str, Any] = {
                    "message": "Dify connection failed",
                    "base_url": settings.dify_base_url,
                    "hint": _dify_hint(settings.dify_base_url),
                    "error": str(e),
                }
                raise HTTPException(status_code=502, detail=detail)

            items = data.get("data") if isinstance(data, dict) else []
            if not isinstance(items, list):
                items = []
            items = sorted(items, key=lambda x: x.get("created_at") or 0)
            messages: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                user_msg = _extract_user_message(item.get("query") if isinstance(item.get("query"), str) else None)
                if user_msg:
                    messages.append({"role": "user", "content": user_msg, "created_at": item.get("created_at")})
                comment = _extract_llm_comment(item.get("answer") if isinstance(item.get("answer"), str) else None)
                if comment:
                    messages.append(
                        {"role": "assistant", "content": comment, "created_at": item.get("created_at")}
                    )
            return {"messages": messages, "conversation_id": conversation_id}

        # POST: 追加指示でフォームを更新（/api/form/ai_edit と同じ流れをここに統合）
        instruction = ""
        if isinstance(payload, dict):
            for key in ("user_comment", "instruction", "message", "text", "content", "query", "input", "prompt"):
                val = payload.get(key)
                if isinstance(val, str) and val.strip():
                    instruction = val.strip()
                    break
        if not instruction:
            raise HTTPException(status_code=400, detail="user_comment is required")

        if not conv.form:
            conv.form = FormState(conversation_id=conv.id)
        f = conv.form

        # チェックボックスに応じて「どの項目を修正対象にするか」を決める。
        # サンプルUIに合わせて、payloadに含まれる項目のみを修正対象にする。
        has_summary = isinstance(payload.get("summary"), str)
        has_cause = isinstance(payload.get("cause"), str)
        has_action = isinstance(payload.get("action"), str)
        has_body = isinstance(payload.get("body"), str)

        f.include_summary = has_summary
        f.include_cause = has_cause
        f.include_action = has_action
        f.include_body = has_body

        # 修正対象のものだけ、現在フォーム値として上書きしてプロンプトに反映する
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

        try:
            data = dify.chat(
                query=prompt,
                conversation_id=conversation_id,
                inputs={},
                user=_dify_user(user.username),
            )
        except RuntimeError as e:
            detail = {
                "message": "Dify connection failed",
                "base_url": settings.dify_base_url,
                "hint": _dify_hint(settings.dify_base_url),
                "error": str(e),
            }
            raise HTTPException(status_code=502, detail=detail)

        answer = data.get("answer") if isinstance(data, dict) else None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if isinstance(parsed, dict):
            _apply_parsed_to_form(f, parsed)

        comment = _extract_llm_comment(answer if isinstance(answer, str) else None)
        return {"message": comment or (answer if isinstance(answer, str) else ""), "answer": answer, "conversation_id": conversation_id}


@app.get("/api/pleasanter/cases")
def api_pleasanter_cases(request: Request, query: str | None = None, limit: int = 50) -> dict[str, Any]:
    _require_user_id(request)
    _assert_pleasanter_case_ready()

    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 50

    ple = PleasanterClient(
        base_url=settings.pleasanter_base_url or "",
        api_key=settings.pleasanter_api_key or "",
        api_version=settings.pleasanter_api_version,
    )
    view = build_case_view()
    ple_resp = ple.get_items(site_id=settings.pleasanter_case_site_id or 0, view=view, offset=0, page_size=limit)
    items = _extract_items_list(ple_resp.data)
    pleasanter_debug = _build_pleasanter_debug(ple_resp=ple_resp, view=view, items=items)
    if not ple_resp.ok:
        detail: dict[str, Any] = {
            "message": "Pleasanter API error",
            "base_url": settings.pleasanter_base_url,
            "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
            "checks": [
                "PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_CASE_SITE_ID を確認",
            ],
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

    return {"items": results, "total": len(results)}


@app.get("/api/pleasanter/case_lookup")
def api_pleasanter_case_lookup(request: Request, case_result_id: int) -> dict[str, Any]:
    _require_user_id(request)
    _assert_pleasanter_case_ready()

    ple = PleasanterClient(
        base_url=settings.pleasanter_base_url or "",
        api_key=settings.pleasanter_api_key or "",
        api_version=settings.pleasanter_api_version,
    )
    view = build_case_view(result_id=case_result_id)
    ple_resp = ple.get_items(site_id=settings.pleasanter_case_site_id or 0, view=view, offset=0, page_size=1)
    items = _extract_items_list(ple_resp.data)
    pleasanter_debug = _build_pleasanter_debug(ple_resp=ple_resp, view=view, items=items)
    if not ple_resp.ok:
        detail: dict[str, Any] = {
            "message": "Pleasanter API error",
            "base_url": settings.pleasanter_base_url,
            "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
            "checks": [
                "PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_CASE_SITE_ID を確認",
            ],
            "pleasanter": pleasanter_debug,
        }
        raise HTTPException(status_code=502, detail=detail)

    if not items:
        raise HTTPException(status_code=404, detail={"message": "Case not found", "case_result_id": case_result_id})

    it = items[0]
    return {
        "result_id": it.get("ResultId"),
        "title": it.get("Title") or "",
        "updated_time": it.get("UpdatedTime"),
    }


@app.post("/api/pleasanter/summarize_case")
def api_pleasanter_summarize_case(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = _require_user_id(request)
    _assert_pleasanter_ready()

    case_result_id = payload.get("case_result_id")
    try:
        case_result_id_int = int(case_result_id)
    except Exception:
        raise HTTPException(status_code=400, detail="case_result_id is required (int)")

    requested_conversation_id = str(payload.get("conversation_id") or "").strip()

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        ple = PleasanterClient(
            base_url=settings.pleasanter_base_url or "",
            api_key=settings.pleasanter_api_key or "",
            api_version=settings.pleasanter_api_version,
        )
        view = build_mail_view(
            link_column=settings.pleasanter_mail_link_column,
            case_result_id=case_result_id_int,
            body_column=settings.pleasanter_mail_body_column,
        )
        ple_resp = ple.get_items(site_id=settings.pleasanter_mail_site_id or 0, view=view, offset=0, page_size=200)
        items = _extract_items_list(ple_resp.data)
        pleasanter_debug = _build_pleasanter_debug(ple_resp=ple_resp, view=view, items=items)
        if not ple_resp.ok:
            detail: dict[str, Any] = {
                "message": "Pleasanter API error",
                "base_url": settings.pleasanter_base_url,
                "hint": _pleasanter_hint(settings.pleasanter_base_url or ""),
                "checks": [
                    "PLEASANTER_BASE_URL / PLEASANTER_API_KEY / PLEASANTER_MAIL_SITE_ID を確認",
                    "PLEASANTER_MAIL_LINK_COLUMN（例: ClassD）を確認",
                    "PLEASANTER_MAIL_BODY_COLUMN（例: Body）を確認",
                ],
                "pleasanter": pleasanter_debug,
            }
            raise HTTPException(status_code=502, detail=detail)

        stored = 0
        latest_raw: str | None = None
        latest_cleaned: str | None = None
        latest_mail_result_id: int | None = None

        logger.info(
            "pleasanter fetched case=%s site=%s status=%s items=%s link=%s body=%s",
            case_result_id_int,
            settings.pleasanter_mail_site_id,
            ple_resp.status_code,
            len(items),
            settings.pleasanter_mail_link_column,
            settings.pleasanter_mail_body_column,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )

        # 古い順に並べ替え（UpdatedTimeが無い場合は末尾）
        def _sort_key(item: dict[str, Any]) -> tuple[bool, str]:
            v = item.get("UpdatedTime") or ""
            return (v == "", str(v))

        sorted_items = sorted(items, key=_sort_key)

        try:
            # 会話IDが指定されている場合のみ、その会話の続きとして扱う。
            # 指定が無い場合は「新規会話」として Dify が返す conversation_id で会話を作成する。
            conv: Conversation | None = None
            if requested_conversation_id:
                conv = (
                    session.query(Conversation)
                    .filter(Conversation.user_id == user.id, Conversation.dify_conversation_id == requested_conversation_id)
                    .one_or_none()
                )
                if not conv:
                    raise HTTPException(status_code=404, detail="conversation not found")
                if conv.pleasanter_case_result_id is not None and conv.pleasanter_case_result_id != case_result_id_int:
                    raise HTTPException(status_code=400, detail="conversation is linked to a different case_result_id")
                if conv.pleasanter_case_result_id is None:
                    conv.pleasanter_case_result_id = case_result_id_int

            email_blocks: list[str] = []

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

                if conv and mail_result_id_int is not None:
                    exists = (
                        session.query(Email)
                        .filter(Email.conversation_id == conv.id, Email.pleasanter_mail_result_id == mail_result_id_int)
                        .one_or_none()
                    )
                    if exists:
                        continue

                if conv:
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
            # 既存DBに後からカラムを足した場合（create_allでは反映されない）などで起きやすい
            detail: dict[str, Any] = {
                "message": "DB error while processing Pleasanter response",
                "hint": "DBスキーマが古い可能性があります（Dockerのpgdataを作り直すか、マイグレーションが必要）。",
                "pleasanter": pleasanter_debug,
            }
            if _dev_debug_enabled():
                detail["error"] = str(e)
            raise HTTPException(status_code=500, detail=detail)

        if not latest_cleaned:
            debug: dict[str, Any] = {}
            if _dev_debug_enabled():
                debug = {
                    "pleasanter": pleasanter_debug,
                    "body_column": settings.pleasanter_mail_body_column,
                }
            raise HTTPException(status_code=404, detail={"message": "No email body found for this case", "debug": debug})

        combined_cleaned = "\n\n".join(email_blocks).strip()
        prompt = build_summarize_prompt(
            email_text=combined_cleaned,
            summary_key=settings.pleasanter_case_summary_column,
            cause_key=settings.pleasanter_case_cause_column,
            action_key=settings.pleasanter_case_action_column,
            body_key=settings.pleasanter_case_body_column,
        )
        data = _dify_chat_or_502(
            query=prompt, conversation_id=conv.dify_conversation_id if conv else "", inputs={}, user=_dify_user(user.username)
        )
        dify_conversation_id = str(data.get("conversation_id") or "").strip()
        if not dify_conversation_id:
            raise HTTPException(status_code=502, detail="Dify did not return conversation_id")
        if not conv:
            conv = Conversation(
                user_id=user.id,
                dify_conversation_id=dify_conversation_id,
                title=f"案件 {case_result_id_int}",
                pleasanter_case_result_id=case_result_id_int,
            )
            session.add(conv)
            session.flush()
            form = FormState(conversation_id=conv.id)
            session.add(form)
            conv.form = form

            # 初回はここでEmailを保存
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
        if parsed and conv.form:
            _apply_parsed_to_form(conv.form, parsed)

        result: dict[str, Any] = {
            "conversation_id": conv.dify_conversation_id,
            "case_result_id": case_result_id_int,
            "emails_total": len(items),
            "emails_stored": stored,
            "latest_mail_result_id": latest_mail_result_id,
            "answer": answer,
            "parsed": parsed,
        }
        if _dev_debug_enabled():
            result["debug"] = {
                "pleasanter": pleasanter_debug,
                "body_column": settings.pleasanter_mail_body_column,
                "latest_raw_preview": _safe_preview(latest_raw or ""),
                "latest_cleaned_preview": _safe_preview(latest_cleaned or ""),
                "first_item_keys": sorted(list(items[0].keys())) if items else [],
                "request_id": getattr(request.state, "request_id", None),
            }
        return result


@app.post("/api/pleasanter/save_summary")
def api_pleasanter_save_summary(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """
    フォームデータを Pleasanter まとめサイト（爺）の説明A/B/Cに保存する。

    リンクチェーン: mail → case (via PLEASANTER_MAIL_LINK_COLUMN) → summary (via PLEASANTER_CASE_LINK_COLUMN)
    """
    logger.info(
        "pleasanter save_summary request received conversation_id=%s",
        payload.get("conversation_id"),
        extra={"request_id": getattr(request.state, "request_id", None)},
    )
    user_id = _require_user_id(request)
    _assert_pleasanter_ready()

    if settings.pleasanter_summary_site_id is None:
        raise HTTPException(status_code=400, detail="PLEASANTER_SUMMARY_SITE_ID is not configured")
    if settings.pleasanter_case_site_id is None:
        raise HTTPException(status_code=400, detail="PLEASANTER_CASE_SITE_ID is not configured")

    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            raise HTTPException(status_code=401, detail="not logged in")

        # 会話を取得
        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user.id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        if conv.pleasanter_case_result_id is None:
            raise HTTPException(status_code=400, detail="conversation has no case_result_id")

        case_result_id = conv.pleasanter_case_result_id

        # フォームデータを取得
        if not conv.form:
            raise HTTPException(status_code=400, detail="conversation has no form data")

        summary = conv.form.summary or ""
        cause = conv.form.cause or ""
        action = conv.form.action or ""
        body = conv.form.body or ""

        ple = PleasanterClient(
            base_url=settings.pleasanter_base_url or "",
            api_key=settings.pleasanter_api_key or "",
            api_version=settings.pleasanter_api_version,
        )

        # 1. case テーブルから summary_result_id を取得
        logger.info(
            "pleasanter save_summary: fetching case case_id=%s link_column=%s",
            case_result_id,
            settings.pleasanter_case_link_column,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        case_view = build_case_view(result_id=case_result_id, link_column=settings.pleasanter_case_link_column)
        case_resp = ple.get_items(site_id=settings.pleasanter_case_site_id, view=case_view, offset=0, page_size=1)

        if not case_resp.ok:
            logger.error(
                "pleasanter save_summary: failed to fetch case error=%s",
                case_resp.error_message,
                extra={"request_id": getattr(request.state, "request_id", None)},
            )
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to fetch case record from Pleasanter",
                    "pleasanter_error": case_resp.error_message,
                }
            )

        case_items = _extract_items_list(case_resp.data)
        if not case_items:
            raise HTTPException(status_code=404, detail=f"Case record {case_result_id} not found")

        case_item = case_items[0]
        summary_result_id_raw = case_item.get(settings.pleasanter_case_link_column)

        if not summary_result_id_raw:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"Case record does not have link to summary (column: {settings.pleasanter_case_link_column})",
                    "case_result_id": case_result_id,
                }
            )

        try:
            summary_result_id = int(summary_result_id_raw)
        except Exception:
            logger.error(
                "pleasanter save_summary: invalid summary_result_id value=%s",
                summary_result_id_raw,
                extra={"request_id": getattr(request.state, "request_id", None)},
            )
            raise HTTPException(
                status_code=400,
                detail=f"Invalid summary_result_id: {summary_result_id_raw}"
            )

        # 2. summary テーブルを更新
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
            fields={
                "DescriptionA": summary,
                "DescriptionB": cause,
                "DescriptionC": action,
                "Body": body,
            },
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
                }
            )

        logger.info(
            "pleasanter saved summary case=%s summary=%s",
            case_result_id,
            summary_result_id,
            extra={"request_id": getattr(request.state, "request_id", None)},
        )

        return {
            "ok": True,
            "case_result_id": case_result_id,
            "summary_result_id": summary_result_id,
            "message": "まとめサイトに保存しました",
        }


@app.post("/api/pleasanter/save_case")
def api_pleasanter_save_case(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """
    フォーム（概要/原因/処置/内容）を案件テーブルの指定列に書き込む。
    - 概要 -> PLEASANTER_CASE_SUMMARY_COLUMN（既定: DescriptionA）
    - 原因 -> PLEASANTER_CASE_CAUSE_COLUMN（既定: DescriptionB）
    - 処置 -> PLEASANTER_CASE_ACTION_COLUMN（既定: DescriptionC）
    - 内容 -> PLEASANTER_CASE_BODY_COLUMN（既定: Body）
    """

    user_id = _require_user_id(request)
    if not settings.pleasanter_base_url or not settings.pleasanter_api_key:
        raise HTTPException(status_code=400, detail="Pleasanter env is not set (PLEASANTER_BASE_URL / PLEASANTER_API_KEY)")

    conversation_id = str(payload.get("conversation_id") or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    with session_scope() as session:
        conv = (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id, Conversation.dify_conversation_id == conversation_id)
            .one_or_none()
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
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

        ple = PleasanterClient(
            base_url=settings.pleasanter_base_url or "",
            api_key=settings.pleasanter_api_key or "",
            api_version=settings.pleasanter_api_version,
        )
        update_resp = ple.update_item(record_id=case_result_id, fields=fields)
        if not update_resp.ok:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed to update case record in Pleasanter",
                    "pleasanter_error": update_resp.error_message,
                    "case_result_id": case_result_id,
                },
            )

        conv.updated_at = dt.datetime.now(dt.timezone.utc)
        return {"ok": True, "case_result_id": case_result_id, "message": "案件サイトに保存しました"}


@app.exception_handler(HTTPException)
def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(getattr(_request, "state", None), "request_id", None)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "request_id": request_id})
