from __future__ import annotations

import traceback
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings


def dev_debug_enabled() -> bool:
    return str(getattr(settings, "app_env", "dev")).lower() in {"dev", "development", "local"}


async def request_debug_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    # SessionMiddleware の有無で取り方が変わるため、堅牢に取得
    user_id: Any = None
    session = request.scope.get("session")
    if isinstance(session, dict):
        user_id = session.get("user_id")

    logger = getattr(request.app.state, "logger", None)
    if logger:
        logger.info("request start %s %s user=%s", request.method, request.url.path, user_id, extra={"request_id": request_id})

    try:
        response = await call_next(request)
    except Exception as e:
        if logger:
            logger.exception("request error: %s", str(e), extra={"request_id": request_id})
        content: dict[str, Any] = {"error": "internal server error", "request_id": request_id}
        if dev_debug_enabled():
            content["traceback"] = traceback.format_exc()
        resp = JSONResponse(status_code=500, content=content)
        resp.headers["X-Request-ID"] = request_id
        return resp

    response.headers["X-Request-ID"] = request_id
    if logger:
        logger.info(
            "request end %s %s status=%s",
            request.method,
            request.url.path,
            getattr(response, "status_code", None),
            extra={"request_id": request_id},
        )
    return response

