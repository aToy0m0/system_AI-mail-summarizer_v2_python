from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class DifyClient:
    base_url: str
    api_key: str

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

        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.post(
                    f"{self.base_url}/chat-messages",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
            except httpx.ConnectError as e:
                raise RuntimeError(
                    "Cannot connect to Dify. "
                    "If this app runs in Docker, 'localhost' refers to the container itself; "
                    "use host.docker.internal (Docker Desktop) or a Compose service name instead. "
                    f"base_url={self.base_url}"
                ) from e
            except httpx.TimeoutException as e:
                raise RuntimeError(f"Dify request timed out. base_url={self.base_url}") from e
            text = resp.text
            try:
                data = resp.json()
            except Exception:
                data = {"raw": text}

            if resp.status_code >= 400:
                raise RuntimeError(f"Dify upstream error: status={resp.status_code} data={data}")
            return data

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
        params: dict[str, Any] = {
            "conversation_id": conversation_id,
            "user": user,
            "limit": limit,
        }
        if first_id:
            params["first_id"] = first_id
        if last_id:
            params["last_id"] = last_id

        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.get(
                    f"{self.base_url}/messages",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params=params,
                )
            except httpx.ConnectError as e:
                raise RuntimeError(
                    "Cannot connect to Dify. "
                    "If this app runs in Docker, 'localhost' refers to the container itself; "
                    "use host.docker.internal (Docker Desktop) or a Compose service name instead. "
                    f"base_url={self.base_url}"
                ) from e
            except httpx.TimeoutException as e:
                raise RuntimeError(f"Dify request timed out. base_url={self.base_url}") from e
            text = resp.text
            try:
                data = resp.json()
            except Exception:
                data = {"raw": text}

            if resp.status_code >= 400:
                raise RuntimeError(f"Dify upstream error: status={resp.status_code} data={data}")
            return data
