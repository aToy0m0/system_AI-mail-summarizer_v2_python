from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


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
class PleasanterClient:
    base_url: str
    api_key: str
    api_version: str = "1.1"

    def update_item(
        self,
        *,
        site_id: int,
        result_id: int,
        fields: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        """
        Pleasanter レコードを更新する。

        マニュアル: https://pleasanter.org/manual/api-update
        POST /api/items/{result_id}/update
        """
        url = f"{self.base_url.rstrip('/')}/api/items/{result_id}/update"
        payload: dict[str, Any] = {
            "ApiVersion": _to_number_if_possible(self.api_version),
            "ApiKey": self.api_key,
        }
        payload.update(fields)

        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.post(url, json=payload)
            except httpx.ConnectError as e:
                return PleasanterApiResponse(
                    request_url=url,
                    request_payload=payload,
                    status_code=0,
                    ok=False,
                    error_message=f"ConnectError: {e}",
                    text="",
                    data={"exception": "ConnectError", "message": str(e)},
                )
            except httpx.TimeoutException as e:
                return PleasanterApiResponse(
                    request_url=url,
                    request_payload=payload,
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

            error_message: str | None = None
            ok = True
            if resp.status_code >= 400:
                ok = False
                error_message = f"HTTP status={resp.status_code}"
            if isinstance(data, dict) and "StatusCode" in data and data.get("StatusCode") != 200:
                ok = False
                msg = data.get("Message") or data.get("ErrorMessage") or data.get("raw") or "Unknown error"
                error_message = f"StatusCode={data.get('StatusCode')} message={msg}"
            return PleasanterApiResponse(
                request_url=url,
                request_payload=payload,
                status_code=resp.status_code,
                ok=ok,
                error_message=error_message,
                text=text,
                data=data,
            )

    def get_items(
        self,
        *,
        site_id: int,
        view: dict[str, Any] | None = None,
        offset: int = 0,
        page_size: int | None = None,
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        url = f"{self.base_url.rstrip('/')}/api/items/{site_id}/get"
        payload: dict[str, Any] = {"ApiVersion": _to_number_if_possible(self.api_version), "ApiKey": self.api_key}
        if view:
            payload["View"] = view
        # マニュアルのページング例: Offset をルートに指定
        payload["Offset"] = int(offset)
        # PageSize はApi.jsonの上限があるが、指定できる環境もあるため任意で渡す
        if page_size is not None:
            payload["PageSize"] = int(page_size)

        with httpx.Client(timeout=timeout_s) as client:
            try:
                resp = client.post(url, json=payload)
            except httpx.ConnectError as e:
                return PleasanterApiResponse(
                    request_url=url,
                    request_payload=payload,
                    status_code=0,
                    ok=False,
                    error_message=f"ConnectError: {e}",
                    text="",
                    data={"exception": "ConnectError", "message": str(e)},
                )
            except httpx.TimeoutException as e:
                return PleasanterApiResponse(
                    request_url=url,
                    request_payload=payload,
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

            error_message: str | None = None
            ok = True
            if resp.status_code >= 400:
                ok = False
                error_message = f"HTTP status={resp.status_code}"
            # PleasanterはHTTP200でもStatusCode!=200で失敗するケースがある
            if isinstance(data, dict) and "StatusCode" in data and data.get("StatusCode") != 200:
                ok = False
                msg = data.get("Message") or data.get("ErrorMessage") or data.get("raw") or "Unknown error"
                error_message = f"StatusCode={data.get('StatusCode')} message={msg}"
            return PleasanterApiResponse(
                request_url=url,
                request_payload=payload,
                status_code=resp.status_code,
                ok=ok,
                error_message=error_message,
                text=text,
                data=data,
            )


def _to_number_if_possible(v: str) -> str | int | float:
    """
    マニュアルでは ApiVersion は数値として例示されているため、"1.1" のような文字列は数値化する。
    """
    s = str(v).strip()
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return v


def build_mail_view(*, link_column: str, case_result_id: int, body_column: str) -> dict[str, Any]:
    """
    複数レコード取得API向けの View を組み立てる。

    ポイント（マニュアル準拠）:
    - ApiDataType="KeyValues" の場合、既定では Key が「表示名」になるため、
      サーバ側で列名（Body/ResultId 等）を扱うなら ApiColumnKeyDisplayType="ColumnName" を指定する。
    - 取得したい列が一覧に出ていないと返らない場合があるため、GridColumns に必要列を明示する。
    - 分類（ClassA/ClassD など）は ColumnFilterHash の値を JSON文字列（例: '["7"]'）で指定する。
    """

    grid_columns = []
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


def build_case_view(*, result_id: int | None = None, link_column: str | None = None) -> dict[str, Any]:
    """
    親（案件）テーブル取得API向けの View。
    - ResultId/Title/UpdatedTime を取得
    - ResultId での検証用に ExactMatch を使用
    - link_column が指定された場合はそれも GridColumns に追加
    """

    grid_columns = ["ResultId", "Title", "UpdatedTime"]
    if link_column and link_column not in grid_columns:
        grid_columns.append(link_column)

    view: dict[str, Any] = {
        "ApiDataType": "KeyValues",
        "ApiColumnKeyDisplayType": "ColumnName",
        "GridColumns": grid_columns,
        "ColumnSorterHash": {"UpdatedTime": "desc"},
    }
    if result_id is not None:
        view["ColumnFilterHash"] = {"ResultId": str(result_id)}
        view["ColumnFilterSearchTypes"] = {"ResultId": "ExactMatch"}
    return view
