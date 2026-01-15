## 目的
Pleasanter から取得したメール本文をクレンジングし、Dify（LLM）で要約・追記修正し、最終的に Pleasanter（案件テーブル等）へ反映するための Python Web サーバーです。

## 起動（Docker）
1) `01_python/.env` を作成（`01_python/.env.example` を参考）
2) `01_python` で起動

```powershell
cd 01_python
docker compose up -d --build
```

- Web: `http://localhost:8000`
- Health: `http://localhost:8000/health`

※ ポートを変える場合は `APP_PORT` を設定してください（例：`APP_PORT=8050`）。

初期ユーザーは `.env` の `ADMIN_USERNAME` / `ADMIN_PASSWORD` で作成されます（初回起動時のみ）。

### 注意（DBスキーマ変更）
フォーム項目やDBスキーマを変更した後、既存の Postgres ボリューム（`pgdata`）が残っていると起動/実行時に SQLAlchemy エラーになります。
開発用途でデータを捨ててよい場合は次で作り直してください。

```powershell
docker compose down -v
docker compose up -d --build
```

## 起動（Dockerなし）
`.env` を作成していれば、`python -m uvicorn ...` 実行時に `.env` を自動読み込みします（環境変数が未設定の場合のみ）。

```bash
cd 01_python
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## ネットワーク注意点（WSL / Docker）
Docker コンテナ内の `localhost` は「そのコンテナ自身」です。Dify や Pleasanter がホスト側（別コンテナ/別Compose/別VM）にいる場合、`.env` の `*_BASE_URL` は到達可能なホスト名にしてください。

- Docker Desktop の場合: `http://host.docker.internal:xxxx`
- 同一 Compose 内ならサービス名（例: `http://dify-api:5001`）

このプロジェクトの `docker-compose.yml` には `host.docker.internal` を引けるよう `extra_hosts` を入れています。

## フォーム（4項目）と案件テーブルへの書き込み
フォームは次の4項目で運用します（UIラベル → Pleasanter物理名の既定値）。

- 概要 → `DescriptionA`
- 原因 → `DescriptionB`
- 処置 → `DescriptionC`
- 内容 → `Body`

案件テーブルへ書き込む物理名は `.env` で差し替えできます。

- `PLEASANTER_CASE_SUMMARY_COLUMN`（既定: `DescriptionA`）
- `PLEASANTER_CASE_CAUSE_COLUMN`（既定: `DescriptionB`）
- `PLEASANTER_CASE_ACTION_COLUMN`（既定: `DescriptionC`）
- `PLEASANTER_CASE_BODY_COLUMN`（既定: `Body`）

書き込みAPIは `POST /api/pleasanter/save_case` です（会話に紐づく案件IDへ反映します）。

## 主要エンドポイント（抜粋）
- `GET /`：UI（ログイン必須）
- `POST /login`：ログイン
- `GET /api/me`：ログインユーザー
- `GET /api/conversations`：会話一覧
- `GET /api/form` / `POST /api/form/update`：フォームの取得/保存
- `POST /api/summarize_email`：手動貼り付けメールを要約→フォーム反映
- `POST /api/pleasanter/summarize_case`：Pleasanterから案件メールを取得→要約→フォーム反映
- `GET /api/chat-ui` / `POST /api/chat-ui`：会話履歴表示・追加指示（フォーム更新まで実施）
- `POST /api/pleasanter/save_case`：フォーム→案件テーブルへ反映

## 新規会話について
- 「新規会話」はクライアント側の選択状態をクリアします。
- `POST /api/pleasanter/summarize_case` は `conversation_id` が指定された場合のみその会話を継続し、未指定の場合は同じ案件IDでも新しいDify会話として要約します。
