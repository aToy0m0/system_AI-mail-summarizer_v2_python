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

    def get_items(
        self,
        *,
        site_id: int,
        view: dict[str, Any] | None = None,
        offset: int = 0,
        page_size: int | None = None,
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        """
        レコード取得: POST {base_url}/api/items/{site_id}/get
        - View を指定するとフィルタ/取得列を制御できる
        - Offset/PageSize でページング
        """
        url = f"{self.base_url.rstrip('/')}/api/items/{int(site_id)}/get"
        payload: dict[str, Any] = {"ApiVersion": _to_number_if_possible(self.api_version), "ApiKey": self.api_key}
        if view:
            payload["View"] = view
        payload["Offset"] = int(offset)
        if page_size is not None:
            payload["PageSize"] = int(page_size)
        return _post_json(url, payload, timeout_s=timeout_s)

    def update_item(
        self,
        *,
        record_id: int,
        fields: dict[str, Any],
        timeout_s: float = 30.0,
    ) -> PleasanterApiResponse:
        """
        レコード更新: POST {base_url}/api/items/{record_id}/update

        fields のキーで更新先を振り分ける:
        - Body はトップレベル
        - DescriptionX は DescriptionHash
        - ClassX は ClassHash
        """
        url = f"{self.base_url.rstrip('/')}/api/items/{int(record_id)}/update"
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

        return _post_json(url, payload, timeout_s=timeout_s)


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: float) -> PleasanterApiResponse:
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
            data=data if isinstance(data, dict) else {"raw": data},
        )


def _to_number_if_possible(v: str) -> str | int | float:
    """
    Pleasanter の ApiVersion は数値として例示されているため、"1.1" のような値は数値化して送る。
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
    子テーブル(メール)取得 API 向け View。

    - ApiDataType="KeyValues" の場合、既定ではキーが「表示名」になるため、
      サーバ側で列名を扱えるよう ApiColumnKeyDisplayType="ColumnName" を指定する。
    - 取得したい列が一覧に出ていないと返らないことがあるため、GridColumns に明示する。
    - リンク列(ClassA/ClassD等)は ColumnFilterHash の値を JSON配列文字列 (例: '[\"99\"]') で指定する環境がある。
    """
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
    """
    親テーブル(案件)取得 API 向け View。
    - ResultId / Title での存在確認は ExactMatch を使用
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
    if result_id is not None and title is not None:
        raise ValueError("Specify only one of result_id or title")

    if result_id is not None:
        view["ColumnFilterHash"] = {"ResultId": str(result_id)}
        view["ColumnFilterSearchTypes"] = {"ResultId": "ExactMatch"}
    if title is not None:
        view["ColumnFilterHash"] = {"Title": str(title)}
        view["ColumnFilterSearchTypes"] = {"Title": "ExactMatch"}
    return view
