from __future__ import annotations

import json


def build_summarize_prompt(email_text: str) -> str:
    schema = {"llm_comment": "string", "cause": "string", "solution": "string", "details": "string"}
    return (
        "あなたは業務メール要約のアシスタントです。\n"
        "次のメール本文を読み、必ず JSON のみで返してください（前後に説明文は不要）。\n"
        f"出力スキーマ: {json.dumps(schema, ensure_ascii=False)}\n"
        "制約:\n"
        "- llm_comment は短く（ユーザー向け補足）\n"
        "- cause は200文字以内\n"
        "- solution は200文字以内\n"
        "- details は制限なし（ただし冗長は避ける）\n"
        "\n"
        "メール本文:\n"
        "```\n"
        f"{email_text}\n"
        "```\n"
    )


def build_edit_prompt(
    *,
    instruction: str,
    cause: str,
    solution: str,
    details: str,
    include_cause: bool,
    include_solution: bool,
    include_details: bool,
) -> str:
    # 修正対象フィールドのリストを作成
    target_fields = []
    if include_cause:
        target_fields.append("cause")
    if include_solution:
        target_fields.append("solution")
    if include_details:
        target_fields.append("details")

    # コンテキスト構築
    parts: list[str] = []
    if include_cause:
        parts.append(f"cause:\n{cause}".strip())
    if include_solution:
        parts.append(f"solution:\n{solution}".strip())
    if include_details:
        parts.append(f"details:\n{details}".strip())
    context = "\n\n".join(parts).strip() or "(フォーム内容なし)"

    # チェックされたフィールドだけを含むスキーマを動的に構築
    schema_properties = {"llm_comment": "string"}
    required_fields = ["llm_comment"]

    if include_cause:
        schema_properties["cause"] = "string"
        required_fields.append("cause")
    if include_solution:
        schema_properties["solution"] = "string"
        required_fields.append("solution")
    if include_details:
        schema_properties["details"] = "string"
        required_fields.append("details")

    target_fields_str = "、".join(target_fields) if target_fields else "なし"

    return (
        "あなたは業務文書の推敲アシスタントです。\n"
        "以下の「フォーム内容」を参照し、ユーザーの指示に従って修正してください。\n"
        f"重要: 修正対象フィールドは【{target_fields_str}】のみです。これらのフィールドだけをJSONに含めてください。\n"
        "必ず JSON のみで返してください（前後に説明文は不要）。\n"
        f"出力スキーマ: {json.dumps(schema_properties, ensure_ascii=False)}\n"
        f"必須フィールド: {required_fields}\n"
        "制約:\n"
        "- llm_comment は短く（ユーザー向け補足）\n"
        "- cause は200文字以内（修正対象の場合のみ出力）\n"
        "- solution は200文字以内（修正対象の場合のみ出力）\n"
        "- details は制限なし（修正対象の場合のみ出力）\n"
        "- 修正対象でないフィールドはJSONに含めないでください\n"
        "\n"
        f"ユーザー指示:\n{instruction}\n"
        "\n"
        "修正対象フォーム内容:\n"
        "```\n"
        f"{context}\n"
        "```\n"
    )
