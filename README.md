## 目的
Pleasanter から取得したメール本文をクレンジングし、Dify（LLM）で要約・追記修正し、最終的に Pleasanter（または帳票生成用サイト）へ保存するための Python Web サーバー。

## ローカル起動（Docker）
1) `01_python/.env` を作成（`01_python/.env.example` を参考）
2) `01_python` で起動

```powershell
cd 01_python
docker compose up -d --build
```

- Web: `http://localhost:8000`
- Health: `http://localhost:8000/health`

初期ユーザーは `.env` の `ADMIN_USERNAME` / `ADMIN_PASSWORD` で作成されます（初回起動時のみ）。

※ Difyがホスト側（例：Windows/WSL外）で動いている場合、webコンテナからは `localhost` で到達できません。`.env` の `DIFY_BASE_URL` を `http://host.docker.internal/v1` に変更して再作成してください。

## Pleasanter接続の確認ポイント
- `PLEASANTER_BASE_URL` / `PLEASANTER_API_KEY` / `PLEASANTER_MAIL_SITE_ID` が正しいこと
- 案件→メールのリンク列（例：`ClassD`）が `.env` の `PLEASANTER_MAIL_LINK_COLUMN` と一致していること
- メール本文列（例：`Body`）が `.env` の `PLEASANTER_MAIL_BODY_COLUMN` と一致していること
- 取得APIは `/api/items/{site_id}/get` を使用し、`Offset` はルートに指定、フィルタ/ソート/列指定は `View` に指定します

## ローカル起動（Dockerなし）
`.env` を作成していれば、`python -m uvicorn ...` 実行時に `.env` を自動読み込みします（環境変数が未設定の場合のみ）。

```bash
cd 01_python
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 主要エンドポイント（抜粋）
- `GET /`：フォームUI（ログイン必須）
- `POST /login`：ログイン
- `POST /api/summarize_email`：メール本文を要約してフォームに反映
- `POST /api/pleasanter/summarize_case`：Pleasanterから案件メールを取得→要約→フォーム反映
- `POST /api/form/ai_edit`：フォーム内容＋追加指示をDifyへ再送し、フォームを更新
- `POST /api/chat`：Dify `chat-messages` へのプロキシ（00_test と同等）
