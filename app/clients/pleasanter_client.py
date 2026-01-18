from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.clients.base_client import ApiResponse, BaseHttpClient


@dataclass(frozen=True)
class PleasanterApiResponse:
    request_url: str
    request_payload: dict[str, Any]
    status_code: int
    ok: bool
    error_message: str | None
    text: str
    data: dict[str, Any]


@dataclass(frozen=True)
class PleasanterClient(BaseHttpClient):
    base_url: str
    api_key: str
    api_version: str = "1.1"

    def __post_init__(self) -> None:  # type: ignore[override]
        BaseHttpClient.__init__(self, base_url=self.base_url)

    def get_items(
        self,
        *,
        site_id: int,
        view: dict[str, Any] | None = None,
        offset: int = 0,
        page_size: int | None = None,
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        payload: dict[str, Any] = {"ApiVersion": _to_number_if_possible(self.api_version), "ApiKey": self.api_key}
        if view:
            payload["View"] = view
        payload["Offset"] = int(offset)
        if page_size is not None:
            payload["PageSize"] = int(page_size)

        resp = self._post(endpoint=f"/api/items/{int(site_id)}/get", payload=payload, timeout_s=timeout_s)
        return _to_pleasanter_response(resp)

    def update_item(
        self,
        *,
        record_id: int,
        fields: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        payload: dict[str, Any] = {"ApiVersion": _to_number_if_possible(self.api_version), "ApiKey": self.api_key}

        description_hash: dict[str, Any] = {}
        class_hash: dict[str, Any] = {}
        for k, v in (fields or {}).items():
            key = str(k or "").strip()
            if not key:
                continue
            if key == "Body":
                payload["Body"] = "" if v is None else str(v)
                continue
            if key.startswith("Description"):
                description_hash[key] = "" if v is None else str(v)
                continue
            if key.startswith("Class"):
                class_hash[key] = "" if v is None else str(v)
                continue
            payload[key] = v

        if description_hash:
            payload["DescriptionHash"] = description_hash
        if class_hash:
            payload["ClassHash"] = class_hash

        resp = self._post(endpoint=f"/api/items/{int(record_id)}/update", payload=payload, timeout_s=timeout_s)
        return _to_pleasanter_response(resp)


def _to_pleasanter_response(resp: ApiResponse) -> PleasanterApiResponse:
    data = resp.data if isinstance(resp.data, dict) else {"raw": resp.data}
    ok = bool(resp.ok)
    error_message = resp.error_message
    if isinstance(data, dict) and "StatusCode" in data and data.get("StatusCode") != 200:
        ok = False
        msg = data.get("Message") or data.get("ErrorMessage") or data.get("raw") or "Unknown error"
        error_message = f"StatusCode={data.get('StatusCode')} message={msg}"
    return PleasanterApiResponse(
        request_url=resp.request_url,
        request_payload=resp.request_payload or {},
        status_code=resp.status_code,
        ok=ok,
        error_message=error_message,
        text=resp.text,
        data=data,
    )


def _to_number_if_possible(v: str) -> str | int | float:
    s = str(v).strip()
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return v


def build_mail_view(*, link_column: str, case_result_id: int, body_column: str) -> dict[str, Any]:
    grid_columns: list[str] = []
    for c in ("ResultId", "Title", "UpdatedTime", link_column, body_column):
        c = (c or "").strip()
        if c and c not in grid_columns:
            grid_columns.append(c)

    return {
        "ApiDataType": "KeyValues",
        "ApiColumnKeyDisplayType": "ColumnName",
        "GridColumns": grid_columns,
        "ColumnFilterHash": {link_column: json.dumps([str(case_result_id)], ensure_ascii=False)},
        "ColumnFilterSearchTypes": {link_column: "ExactMatch"},
        "ColumnSorterHash": {"UpdatedTime": "desc"},
    }


def build_case_view(*, result_id: int | None = None, title: str | None = None, link_column: str | None = None) -> dict[str, Any]:
    grid_columns = ["ResultId", "Title", "UpdatedTime"]
    if link_column and link_column not in grid_columns:
        grid_columns.append(link_column)

    view: dict[str, Any] = {
        "ApiDataType": "KeyValues",
        "ApiColumnKeyDisplayType": "ColumnName",
        "GridColumns": grid_columns,
        "ColumnSorterHash": {"UpdatedTime": "desc"},
    }
    if result_id is not None and title is not None:
        raise ValueError("Specify only one of result_id or title")

    if result_id is not None:
        view["ColumnFilterHash"] = {"ResultId": str(result_id)}
        view["ColumnFilterSearchTypes"] = {"ResultId": "ExactMatch"}
    if title is not None:
        view["ColumnFilterHash"] = {"Title": str(title)}
        view["ColumnFilterSearchTypes"] = {"Title": "ExactMatch"}
    return view

