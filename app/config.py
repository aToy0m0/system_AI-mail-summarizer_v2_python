from __future__ import annotations

import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class DifyConfig:
    base_url: str
    api_key: str
    user_prefix: str = "local-"


@dataclass(frozen=True)
class PleasanterConfig:
    base_url: str | None
    api_key: str | None
    api_version: str = "1.1"

    summary_site_id: int | None = None
    case_site_id: int | None = None
    mail_site_id: int | None = None

    case_link_column: str = "ClassA"
    mail_link_column: str = "ClassD"
    mail_body_column: str = "Body"

    case_summary_column: str = "DescriptionA"
    case_cause_column: str = "DescriptionB"
    case_action_column: str = "DescriptionC"
    case_body_column: str = "Body"

    case_summary_label: str = "概要"
    case_cause_label: str = "原因"
    case_action_label: str = "処置"
    case_body_label: str = "内容"


@dataclass(frozen=True)
class Settings:
    app_env: str
    secret_key: str
    host: str
    port: int

    database_url: str

    admin_username: str
    admin_password: str

    dify: DifyConfig
    pleasanter: PleasanterConfig

    @classmethod
    def from_env(cls) -> "Settings":
        dify = DifyConfig(
            base_url=_env("DIFY_BASE_URL").rstrip("/"),
            api_key=_env("DIFY_API_KEY"),
            user_prefix=os.getenv("DIFY_USER_PREFIX", "local-"),
        )
        pleasanter = PleasanterConfig(
            base_url=os.getenv("PLEASANTER_BASE_URL") or None,
            api_key=os.getenv("PLEASANTER_API_KEY") or None,
            api_version=os.getenv("PLEASANTER_API_VERSION", "1.1"),
            summary_site_id=_maybe_int(os.getenv("PLEASANTER_SUMMARY_SITE_ID")),
            case_site_id=_maybe_int(os.getenv("PLEASANTER_CASE_SITE_ID")),
            mail_site_id=_maybe_int(os.getenv("PLEASANTER_MAIL_SITE_ID")),
            case_link_column=os.getenv("PLEASANTER_CASE_LINK_COLUMN", "ClassA"),
            mail_link_column=os.getenv("PLEASANTER_MAIL_LINK_COLUMN", "ClassD"),
            mail_body_column=os.getenv("PLEASANTER_MAIL_BODY_COLUMN", "Body"),
            case_summary_column=os.getenv("PLEASANTER_CASE_SUMMARY_COLUMN", "DescriptionA"),
            case_cause_column=os.getenv("PLEASANTER_CASE_CAUSE_COLUMN", "DescriptionB"),
            case_action_column=os.getenv("PLEASANTER_CASE_ACTION_COLUMN", "DescriptionC"),
            case_body_column=os.getenv("PLEASANTER_CASE_BODY_COLUMN", "Body"),
            case_summary_label=os.getenv("PLEASANTER_CASE_SUMMARY_LABEL", "概要"),
            case_cause_label=os.getenv("PLEASANTER_CASE_CAUSE_LABEL", "原因"),
            case_action_label=os.getenv("PLEASANTER_CASE_ACTION_LABEL", "処置"),
            case_body_label=os.getenv("PLEASANTER_CASE_BODY_LABEL", "内容"),
        )
        return cls(
            app_env=os.getenv("APP_ENV", "dev"),
            secret_key=_env("APP_SECRET_KEY", "change-me"),
            host=os.getenv("APP_HOST", "0.0.0.0"),
            port=int(os.getenv("APP_PORT", "8000")),
            database_url=_env("DATABASE_URL", "postgresql+psycopg2://app:app@db:5432/app"),
            admin_username=_env("ADMIN_USERNAME", "admin"),
            admin_password=_env("ADMIN_PASSWORD", "admin"),
            dify=dify,
            pleasanter=pleasanter,
        )

    # --- backward compatible aliases (既存コード互換) ---
    @property
    def dify_base_url(self) -> str:
        return self.dify.base_url

    @property
    def dify_api_key(self) -> str:
        return self.dify.api_key

    @property
    def dify_user_prefix(self) -> str:
        return self.dify.user_prefix

    @property
    def pleasanter_base_url(self) -> str | None:
        return self.pleasanter.base_url

    @property
    def pleasanter_api_key(self) -> str | None:
        return self.pleasanter.api_key

    @property
    def pleasanter_api_version(self) -> str:
        return self.pleasanter.api_version

    @property
    def pleasanter_summary_site_id(self) -> int | None:
        return self.pleasanter.summary_site_id

    @property
    def pleasanter_case_site_id(self) -> int | None:
        return self.pleasanter.case_site_id

    @property
    def pleasanter_mail_site_id(self) -> int | None:
        return self.pleasanter.mail_site_id

    @property
    def pleasanter_case_link_column(self) -> str:
        return self.pleasanter.case_link_column

    @property
    def pleasanter_mail_link_column(self) -> str:
        return self.pleasanter.mail_link_column

    @property
    def pleasanter_mail_body_column(self) -> str:
        return self.pleasanter.mail_body_column

    @property
    def pleasanter_case_summary_column(self) -> str:
        return self.pleasanter.case_summary_column

    @property
    def pleasanter_case_cause_column(self) -> str:
        return self.pleasanter.case_cause_column

    @property
    def pleasanter_case_action_column(self) -> str:
        return self.pleasanter.case_action_column

    @property
    def pleasanter_case_body_column(self) -> str:
        return self.pleasanter.case_body_column

    @property
    def pleasanter_case_summary_label(self) -> str:
        return self.pleasanter.case_summary_label

    @property
    def pleasanter_case_cause_label(self) -> str:
        return self.pleasanter.case_cause_label

    @property
    def pleasanter_case_action_label(self) -> str:
        return self.pleasanter.case_action_label

    @property
    def pleasanter_case_body_label(self) -> str:
        return self.pleasanter.case_body_label


_load_dotenv_if_present()
settings = Settings.from_env()
