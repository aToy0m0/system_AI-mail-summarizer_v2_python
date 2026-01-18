from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.clients.dify_client import DifyClient
from app.config import settings
from app.json_extract import try_parse_json_answer


def _dev_debug_enabled() -> bool:
    return str(getattr(settings, "app_env", "dev")).lower() in {"dev", "development", "local"}


def _dify_hint(base_url: str) -> str:
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return (
            "Docker内では localhost はコンテナ自身です。"
            "Dify がホスト側にいる場合は http://host.docker.internal/v1 など到達可能なURLを指定してください。"
        )
    return "Dify の URL/ネットワークを確認してください（Docker/Compose 構成も含む）。"


class DifyService:
    def __init__(self) -> None:
        self._base_url = settings.dify_base_url
        self._api_key = settings.dify_api_key
        self._user_prefix = settings.dify_user_prefix

    def build_user(self, username: str) -> str:
        return f"{self._user_prefix}{username}"

    def chat(self, *, query: str, conversation_id: str, inputs: dict[str, Any], user: str) -> dict[str, Any]:
        dify = DifyClient(base_url=self._base_url, api_key=self._api_key)
        try:
            return dify.chat(query=query, conversation_id=conversation_id, inputs=inputs, user=user)
        except Exception as e:
            detail: dict[str, Any] = {
                "message": "Dify connection failed",
                "base_url": self._base_url,
                "hint": _dify_hint(self._base_url),
            }
            if _dev_debug_enabled():
                detail["error"] = str(e)
            raise HTTPException(status_code=502, detail=detail)

    def get_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        limit: int,
        first_id: str | None,
        last_id: str | None,
    ) -> dict[str, Any]:
        dify = DifyClient(base_url=self._base_url, api_key=self._api_key)
        try:
            return dify.get_messages(
                conversation_id=conversation_id,
                user=user,
                limit=limit,
                first_id=first_id,
                last_id=last_id,
            )
        except Exception as e:
            detail: dict[str, Any] = {
                "message": "Dify connection failed",
                "base_url": self._base_url,
                "hint": _dify_hint(self._base_url),
                "error": str(e),
            }
            raise HTTPException(status_code=502, detail=detail)

    def extract_llm_comment(self, answer: str | None) -> str | None:
        if not answer:
            return None
        parsed = try_parse_json_answer(answer) if isinstance(answer, str) else None
        if parsed and isinstance(parsed, dict):
            comment = parsed.get("llm_comment")
            if isinstance(comment, str) and comment.strip():
                return comment.strip()
        return None

    def extract_user_message(self, query: str | None) -> str | None:
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

