from __future__ import annotations

import json

_USER_MESSAGE_BEGIN = "<<<USER_MESSAGE_BEGIN>>>"
_USER_MESSAGE_END = "<<<USER_MESSAGE_END>>>"


def build_summarize_prompt(
    *,
    email_text: str,
    summary_key: str,
    cause_key: str,
    action_key: str,
    body_key: str,
) -> str:
    schema = {
        "llm_comment": "string",
        summary_key: "string",
        cause_key: "string",
        action_key: "string",
        body_key: "string",
    }
    return (
        f"{_USER_MESSAGE_BEGIN}\n案件メールを要約してフォームを埋めてください。\n{_USER_MESSAGE_END}\n\n"
        "あなたは業務メール要約のアシスタントです。\n"
        "次のメール本文を読み、必ず JSON のみで返してください（前後に説明文は不要）。\n"
        f"出力スキーマ: {json.dumps(schema, ensure_ascii=False)}\n"
        "制約:\n"
        "- llm_comment は短く（ユーザー向け補足）\n"
        f"- {summary_key} は200文字以内\n"
        f"- {cause_key} は200文字以内\n"
        f"- {action_key} は200文字以内\n"
        f"- {body_key} は制限なし（ただし冗長は避ける）\n"
        "\n"
        "メール本文:\n"
        "```\n"
        f"{email_text}\n"
        "```\n"
    )


def build_edit_prompt(
    *,
    instruction: str,
    summary: str,
    cause: str,
    action: str,
    body: str,
    include_summary: bool,
    include_cause: bool,
    include_action: bool,
    include_body: bool,
    summary_key: str,
    cause_key: str,
    action_key: str,
    body_key: str,
) -> str:
    target_fields: list[str] = []
    if include_summary:
        target_fields.append(summary_key)
    if include_cause:
        target_fields.append(cause_key)
    if include_action:
        target_fields.append(action_key)
    if include_body:
        target_fields.append(body_key)

    parts: list[str] = []
    if include_summary:
        parts.append(f"{summary_key}:\n{summary}".strip())
    if include_cause:
        parts.append(f"{cause_key}:\n{cause}".strip())
    if include_action:
        parts.append(f"{action_key}:\n{action}".strip())
    if include_body:
        parts.append(f"{body_key}:\n{body}".strip())
    context = "\n\n".join(parts).strip() or "(フォームが空です)"

    schema_properties: dict[str, str] = {"llm_comment": "string"}
    required_fields = ["llm_comment"]

    if include_summary:
        schema_properties[summary_key] = "string"
        required_fields.append(summary_key)
    if include_cause:
        schema_properties[cause_key] = "string"
        required_fields.append(cause_key)
    if include_action:
        schema_properties[action_key] = "string"
        required_fields.append(action_key)
    if include_body:
        schema_properties[body_key] = "string"
        required_fields.append(body_key)

    target_fields_str = "、".join(target_fields) if target_fields else "（なし）"

    return (
        f"{_USER_MESSAGE_BEGIN}\n{instruction}\n{_USER_MESSAGE_END}\n\n"
        "あなたは業務文書の推敲アシスタントです。\n"
        "以下の「フォーム内容」を参照し、ユーザーの指示に従って修正してください。\n"
        f"重要: 修正対象フィールドは【{target_fields_str}】のみです。修正対象以外のフィールドは JSON に含めないでください。\n"
        "必ず JSON のみで返してください（前後に説明文は不要）。\n"
        f"出力スキーマ: {json.dumps(schema_properties, ensure_ascii=False)}\n"
        f"必須フィールド: {required_fields}\n"
        "制約:\n"
        "- llm_comment は短く（ユーザー向け補足）\n"
        f"- {summary_key} は200文字以内（修正対象の場合のみ出力）\n"
        f"- {cause_key} は200文字以内（修正対象の場合のみ出力）\n"
        f"- {action_key} は200文字以内（修正対象の場合のみ出力）\n"
        f"- {body_key} は制限なし（修正対象の場合のみ出力）\n"
        "\n"
        "フォーム内容:\n"
        "```\n"
        f"{context}\n"
        "```\n"
    )
