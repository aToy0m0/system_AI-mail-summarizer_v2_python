from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class ApiResponse:
    request_url: str
    request_payload: dict[str, Any] | None
    request_params: dict[str, Any] | None
    status_code: int
    ok: bool
    error_message: str | None
    text: str
    data: Any


class BaseHttpClient:
    def __init__(self, *, base_url: str) -> None:
        object.__setattr__(self, "_base_url", str(base_url or "").rstrip("/"))

    def _abs_url(self, endpoint: str) -> str:
        endpoint_s = str(endpoint or "").strip()
        if endpoint_s.startswith("http://") or endpoint_s.startswith("https://"):
            return endpoint_s
        if not endpoint_s.startswith("/"):
            endpoint_s = "/" + endpoint_s
        return f"{self._base_url}{endpoint_s}"

    def _post(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 30.0,
    ) -> ApiResponse:
        url = self._abs_url(endpoint)
        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.post(url, headers=headers, json=payload)
            except httpx.ConnectError as e:
                return ApiResponse(
                    request_url=url,
                    request_payload=payload,
                    request_params=None,
                    status_code=0,
                    ok=False,
                    error_message=f"ConnectError: {e}",
                    text="",
                    data={"exception": "ConnectError", "message": str(e)},
                )
            except httpx.TimeoutException as e:
                return ApiResponse(
                    request_url=url,
                    request_payload=payload,
                    request_params=None,
                    status_code=0,
                    ok=False,
                    error_message=f"Timeout: {e}",
                    text="",
                    data={"exception": "Timeout", "message": str(e)},
                )

        text = resp.text
        try:
            data = resp.json()
        except Exception:
            data = {"raw": text}

        ok = resp.status_code < 400
        error_message = None if ok else f"HTTP status={resp.status_code}"
        return ApiResponse(
            request_url=url,
            request_payload=payload,
            request_params=None,
            status_code=resp.status_code,
            ok=ok,
            error_message=error_message,
            text=text,
            data=data,
        )

    def _get(
        self,
        *,
        endpoint: str,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 30.0,
    ) -> ApiResponse:
        url = self._abs_url(endpoint)
        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.get(url, headers=headers, params=params)
            except httpx.ConnectError as e:
                return ApiResponse(
                    request_url=url,
                    request_payload=None,
                    request_params=params,
                    status_code=0,
                    ok=False,
                    error_message=f"ConnectError: {e}",
                    text="",
                    data={"exception": "ConnectError", "message": str(e)},
                )
            except httpx.TimeoutException as e:
                return ApiResponse(
                    request_url=url,
                    request_payload=None,
                    request_params=params,
                    status_code=0,
                    ok=False,
                    error_message=f"Timeout: {e}",
                    text="",
                    data={"exception": "Timeout", "message": str(e)},
                )

        text = resp.text
        try:
            data = resp.json()
        except Exception:
            data = {"raw": text}

        ok = resp.status_code < 400
        error_message = None if ok else f"HTTP status={resp.status_code}"
        return ApiResponse(
            request_url=url,
            request_payload=None,
            request_params=params,
            status_code=resp.status_code,
            ok=ok,
            error_message=error_message,
            text=text,
            data=data,
        )
