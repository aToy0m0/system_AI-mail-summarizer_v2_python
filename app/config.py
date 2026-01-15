from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing env: {name}")
    return value


def _maybe_int(s: str | None) -> int | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise RuntimeError(f"Invalid integer env value: {s}")


def _load_dotenv_if_present() -> None:
    """
    ローカル実行（python -m uvicorn ...）で .env が読み込まれていないケースの救済。
    - 既に環境変数がある場合は上書きしない
    - docker compose の env_file と衝突しない
    """

    def load_file(path: Path) -> None:
        if not path.exists() or not path.is_file():
            return
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # remove surrounding quotes
            if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
                value = value[1:-1]
            os.environ.setdefault(key, value)

    # 優先: 現在ディレクトリ（01_python）直下の .env
    load_file(Path.cwd() / ".env")
    # 保険: app/ の1つ上（01_python）直下の .env
    load_file(Path(__file__).resolve().parents[1] / ".env")


class Settings:
    app_env: str
    secret_key: str
    host: str
    port: int

    database_url: str

    admin_username: str
    admin_password: str

    dify_base_url: str
    dify_api_key: str
    dify_user_prefix: str

    pleasanter_base_url: str | None
    pleasanter_api_key: str | None
    pleasanter_api_version: str

    pleasanter_summary_site_id: int | None
    pleasanter_case_site_id: int | None
    pleasanter_mail_site_id: int | None
    pleasanter_case_link_column: str
    pleasanter_mail_link_column: str
    pleasanter_mail_body_column: str
    pleasanter_case_summary_column: str
    pleasanter_case_cause_column: str
    pleasanter_case_action_column: str
    pleasanter_case_body_column: str

    def __init__(self) -> None:
        self.app_env = os.getenv("APP_ENV", "dev")
        self.secret_key = _env("APP_SECRET_KEY", "change-me")
        self.host = os.getenv("APP_HOST", "0.0.0.0")
        self.port = int(os.getenv("APP_PORT", "8000"))

        self.database_url = _env("DATABASE_URL", "postgresql+psycopg2://app:app@db:5432/app")

        self.admin_username = _env("ADMIN_USERNAME", "admin")
        self.admin_password = _env("ADMIN_PASSWORD", "admin")

        self.dify_base_url = _env("DIFY_BASE_URL").rstrip("/")
        self.dify_api_key = _env("DIFY_API_KEY")
        self.dify_user_prefix = os.getenv("DIFY_USER_PREFIX", "local-")

        self.pleasanter_base_url = os.getenv("PLEASANTER_BASE_URL") or None
        self.pleasanter_api_key = os.getenv("PLEASANTER_API_KEY") or None
        self.pleasanter_api_version = os.getenv("PLEASANTER_API_VERSION", "1.1")

        self.pleasanter_summary_site_id = _maybe_int(os.getenv("PLEASANTER_SUMMARY_SITE_ID"))
        self.pleasanter_case_site_id = _maybe_int(os.getenv("PLEASANTER_CASE_SITE_ID"))
        self.pleasanter_mail_site_id = _maybe_int(os.getenv("PLEASANTER_MAIL_SITE_ID"))
        self.pleasanter_case_link_column = os.getenv("PLEASANTER_CASE_LINK_COLUMN", "ClassA")
        self.pleasanter_mail_link_column = os.getenv("PLEASANTER_MAIL_LINK_COLUMN", "ClassD")
        self.pleasanter_mail_body_column = os.getenv("PLEASANTER_MAIL_BODY_COLUMN", "Body")
        self.pleasanter_case_summary_column = os.getenv("PLEASANTER_CASE_SUMMARY_COLUMN", "DescriptionA")
        self.pleasanter_case_cause_column = os.getenv("PLEASANTER_CASE_CAUSE_COLUMN", "DescriptionB")
        self.pleasanter_case_action_column = os.getenv("PLEASANTER_CASE_ACTION_COLUMN", "DescriptionC")
        self.pleasanter_case_body_column = os.getenv("PLEASANTER_CASE_BODY_COLUMN", "Body")


_load_dotenv_if_present()
settings = Settings()
