from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import engine
from app.dependencies import get_db, get_current_user
from app.middlewares.request_debug import request_debug_middleware
from app.models import Base, User
from app.services.conversation_service import ConversationService
from app.services.dify_service import DifyService
from app.services.pleasanter_service import PleasanterService
from app.services.user_service import UserService, is_admin_role, normalize_role, redirect_admin_message

app = FastAPI(title=" Pleasanterメール要約 (python)")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

logger = logging.getLogger("pleasanter-mail-summarizer")
app.state.logger = logger

app.middleware("http")(request_debug_middleware)

dify_service = DifyService()
conversation_service = ConversationService(dify_service)
pleasanter_service = PleasanterService(dify_service, conversation_service)
user_service = UserService()


def _maybe_user_id(request: Request) -> int | None:
    session = request.scope.get("session")
    if not isinstance(session, dict):
        return None
    user_id = session.get("user_id")
    return user_id if isinstance(user_id, int) else None


@app.on_event("startup")
def startup() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    Base.metadata.create_all(bind=engine)

    # DB 初期化（後方互換）
    user_service.ensure_schema()
    user_service.ensure_admin_exists()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "ts": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if _maybe_user_id(request) is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    user = user_service.authenticate(session, username=username, password=password)
    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    user_id = _maybe_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)
    user = session.get(User, user_id)
    if not user:
        request.session.clear()
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
            "case_summary_label": settings.pleasanter_case_summary_label,
            "case_cause_label": settings.pleasanter_case_cause_label,
            "case_action_label": settings.pleasanter_case_action_label,
            "case_body_label": settings.pleasanter_case_body_label,
        },
    )


@app.get("/api/me")
def api_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    role = getattr(user, "role", "user")
    return {"id": user.id, "username": user.username, "role": role, "is_admin": is_admin_role(role)}


@app.get("/admin", response_class=HTMLResponse)
def admin_console(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    user_id = _maybe_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    ok = request.query_params.get("ok")
    error = request.query_params.get("error")

    me = session.get(User, user_id)
    if not me:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)
    if not is_admin_role(getattr(me, "role", None)):
        return RedirectResponse(url="/", status_code=303)

    users = user_service.list_users(session)
    me_row = {"id": me.id, "username": me.username, "role": getattr(me, "role", "user")}
    return templates.TemplateResponse("admin.html", {"request": request, "me": me_row, "users": users, "ok": ok, "error": error})


@app.post("/admin/users/create")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    user_id = _maybe_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    username = str(username or "").strip()
    password = str(password or "").strip()
    role = normalize_role(role)
    if not username or not password:
        return redirect_admin_message("error", "IDとパスワードは必須です")

    me = session.get(User, user_id)
    if not me or not is_admin_role(getattr(me, "role", None)):
        return RedirectResponse(url="/", status_code=303)

    try:
        user_service.create_user(session, username=username, password=password, role=role)
    except HTTPException:
        return redirect_admin_message("error", "そのIDは既に存在します")

    return redirect_admin_message("ok", "ユーザーを作成しました")


@app.post("/admin/users/{target_user_id}/password")
def admin_change_password(
    request: Request,
    target_user_id: int,
    new_password: str = Form(...),
    session: Session = Depends(get_db),
) -> RedirectResponse:
    user_id = _maybe_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    new_password = str(new_password or "").strip()
    if not new_password:
        return redirect_admin_message("error", "新しいパスワードは必須です")

    me = session.get(User, user_id)
    if not me or not is_admin_role(getattr(me, "role", None)):
        return RedirectResponse(url="/", status_code=303)

    try:
        user_service.change_password(session, target_user_id=target_user_id, new_password=new_password)
    except HTTPException:
        return redirect_admin_message("error", "対象ユーザーが見つかりません")

    return redirect_admin_message("ok", "パスワードを更新しました")


@app.post("/admin/users/{target_user_id}/delete")
def admin_delete_user(
    request: Request,
    target_user_id: int,
    session: Session = Depends(get_db),
) -> RedirectResponse:
    user_id = _maybe_user_id(request)
    if user_id is None:
        return RedirectResponse(url="/login", status_code=303)

    me = session.get(User, user_id)
    if not me or not is_admin_role(getattr(me, "role", None)):
        return RedirectResponse(url="/", status_code=303)

    try:
        user_service.delete_user(session, me_user_id=user_id, target_user_id=target_user_id)
    except HTTPException as e:
        if str(e.detail) == "cannot delete yourself":
            return redirect_admin_message("error", "自分自身は削除できません")
        if str(e.detail) == "cannot delete last admin":
            return redirect_admin_message("error", "最後の管理者は削除できません")
        return redirect_admin_message("error", "対象ユーザーが見つかりません")

    return redirect_admin_message("ok", "ユーザーを削除しました")


@app.get("/api/conversations")
def api_conversations(user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return conversation_service.list_conversations(session, user_id=user.id)


@app.post("/api/conversations")
def api_create_conversation(_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"conversation_id": ""}


@app.get("/api/form")
def api_get_form(conversation_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, Any]:
    return conversation_service.get_form(session, user_id=user.id, conversation_id=conversation_id)


@app.post("/api/form/update")
def api_update_form(payload: dict[str, Any], user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, Any]:
    return conversation_service.update_form(session, user_id=user.id, payload=payload)


@app.post("/api/chat")
def api_chat(payload: dict[str, Any], user: User = Depends(get_current_user)) -> JSONResponse:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=400, detail="query is required (string)")

    conversation_id = payload.get("conversation_id")
    inputs = payload.get("inputs")
    user_override = payload.get("user")
    dify_user = user_override if isinstance(user_override, str) and user_override.strip() else dify_service.build_user(user.username)

    data = dify_service.chat(
        query=query,
        conversation_id=conversation_id if isinstance(conversation_id, str) else "",
        inputs=inputs if isinstance(inputs, dict) else {},
        user=dify_user,
    )
    return JSONResponse(data)


@app.post("/api/summarize_email")
def api_summarize_email(payload: dict[str, Any], user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, Any]:
    return conversation_service.summarize_email(session, user=user, payload=payload)


@app.post("/api/form/ai_edit")
def api_form_ai_edit(payload: dict[str, Any], user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, Any]:
    return conversation_service.form_ai_edit(session, user=user, payload=payload)


@app.get("/api/dify/messages")
def api_dify_messages(
    conversation_id: str,
    limit: int = 50,
    first_id: str | None = None,
    last_id: str | None = None,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    try:
        limit = max(1, min(int(limit), 200))
    except Exception:
        limit = 50
    return dify_service.get_messages(
        conversation_id=conversation_id,
        user=dify_service.build_user(user.username),
        limit=limit,
        first_id=first_id,
        last_id=last_id,
    )


@app.api_route("/api/chat-ui", methods=["GET", "POST"])
async def api_chat_ui(request: Request, session: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
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

    if request.method == "GET":
        return conversation_service.chat_ui_get(session, user=user, conversation_id=conversation_id)
    return conversation_service.chat_ui_post(session, user=user, conversation_id=conversation_id, payload=payload)


@app.get("/api/pleasanter/cases")
def api_pleasanter_cases(
    request: Request,
    query: str | None = None,
    limit: int = 50,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return pleasanter_service.list_summaries(request=request, query=query, limit=limit)


@app.get("/api/pleasanter/case_lookup")
def api_pleasanter_case_lookup(case_result_id: int, _user: User = Depends(get_current_user)) -> dict[str, Any]:
    return pleasanter_service.lookup_summary(case_result_id=case_result_id)


@app.post("/api/pleasanter/summarize_case")
def api_pleasanter_summarize_case(
    request: Request,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    result = pleasanter_service.summarize_case(session, request=request, user=user, payload=payload)
    out: dict[str, Any] = {
        "conversation_id": result.conversation_id,
        "summary_result_id": result.summary_result_id,
        "case_result_id": result.summary_result_id,
        "target_case_result_ids": result.target_case_result_ids,
        "emails_total": result.emails_total,
        "emails_stored": result.emails_stored,
        "latest_mail_result_id": result.latest_mail_result_id,
        "answer": result.answer,
        "parsed": result.parsed,
    }
    if result.debug is not None:
        out["debug"] = result.debug
    return out


@app.post("/api/pleasanter/save_summary")
def api_pleasanter_save_summary(
    request: Request,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    return pleasanter_service.save_summary(session, request=request, user=user, payload=payload)


@app.post("/api/pleasanter/save_case")
def api_pleasanter_save_case(payload: dict[str, Any], user: User = Depends(get_current_user), session: Session = Depends(get_db)) -> dict[str, Any]:
    return pleasanter_service.save_case(session, user=user, payload=payload)


@app.exception_handler(HTTPException)
def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(getattr(_request, "state", None), "request_id", None)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail, "request_id": request_id})
