from __future__ import annotations

import json
import re
from typing import Any


def try_parse_json_answer(answer: str) -> dict[str, Any] | None:
    if not isinstance(answer, str) or not answer.strip():
        return None

    s = answer.strip()
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except Exception:
        return None

