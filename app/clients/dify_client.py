from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.clients.base_client import BaseHttpClient


@dataclass(frozen=True)
class DifyClient(BaseHttpClient):
    base_url: str
    api_key: str

    def __post_init__(self) -> None:  # type: ignore[override]
        BaseHttpClient.__init__(self, base_url=self.base_url)

    def chat(
        self,
        *,
        query: str,
        conversation_id: str = "",
        inputs: dict[str, Any] | None = None,
        user: str = "local-user",
        response_mode: str = "blocking",
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        payload = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": response_mode,
            "conversation_id": conversation_id or "",
            "user": user or "local-user",
        }
        resp = self._post(
            endpoint="/chat-messages",
            payload=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            timeout_s=timeout_s,
        )
        if not resp.ok:
            raise RuntimeError(f"Dify request failed: {resp.error_message} data={resp.data} base_url={self.base_url}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Dify upstream error: status={resp.status_code} data={resp.data}")
        return resp.data if isinstance(resp.data, dict) else {"raw": resp.text}

    def get_messages(
        self,
        *,
        conversation_id: str,
        user: str,
        limit: int = 50,
        first_id: str | None = None,
        last_id: str | None = None,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"conversation_id": conversation_id, "user": user, "limit": limit}
        if first_id:
            params["first_id"] = first_id
        if last_id:
            params["last_id"] = last_id

        resp = self._get(
            endpoint="/messages",
            params=params,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout_s=timeout_s,
        )
        if not resp.ok:
            raise RuntimeError(f"Dify request failed: {resp.error_message} data={resp.data} base_url={self.base_url}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Dify upstream error: status={resp.status_code} data={resp.data}")
        return resp.data if isinstance(resp.data, dict) else {"raw": resp.text}

