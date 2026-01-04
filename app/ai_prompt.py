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
    parts: list[str] = []
    if include_cause:
        parts.append(f"cause:\n{cause}".strip())
    if include_solution:
        parts.append(f"solution:\n{solution}".strip())
    if include_details:
        parts.append(f"details:\n{details}".strip())
    context = "\n\n".join(parts).strip() or "(フォーム内容なし)"

    schema = {"llm_comment": "string", "cause": "string", "solution": "string", "details": "string"}
    return (
        "あなたは業務文書の推敲アシスタントです。\n"
        "以下の「フォーム内容」を参照し、ユーザーの指示に従って修正してください。\n"
        "必ず JSON のみで返してください（前後に説明文は不要）。\n"
        f"出力スキーマ: {json.dumps(schema, ensure_ascii=False)}\n"
        "制約:\n"
        "- llm_comment は短く（ユーザー向け補足）\n"
        "- cause は200文字以内\n"
        "- solution は200文字以内\n"
        "- details は制限なし（ただし冗長は避ける）\n"
        "\n"
        f"ユーザー指示:\n{instruction}\n"
        "\n"
        "フォーム内容:\n"
        "```\n"
        f"{context}\n"
        "```\n"
    )
