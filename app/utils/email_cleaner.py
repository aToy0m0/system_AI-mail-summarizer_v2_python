from __future__ import annotations

import re

_THREAD_SEPARATORS = [
    r"^-----Original Message-----$",
    r"^---+ 転送メッセージ ---+$",
    r"^From:\s",
    r"^Sent:\s",
    r"^To:\s",
    r"^Subject:\s",
]


def clean_email_text(raw: str) -> str:
    text = (raw or "").replace("\r\n", "\n").strip()
    if not text:
        return ""

    # 2つ目の "From:" 以降を切る（要件）
    from_hits = [m.start() for m in re.finditer(r"(?m)^From:\s", text)]
    if len(from_hits) >= 2:
        text = text[: from_hits[1]].rstrip()

    # 明らかなスレッド区切りが出たらそこで切る（安全側）
    for pattern in _THREAD_SEPARATORS:
        m = re.search(rf"(?m){pattern}", text)
        if m and m.start() > 0:
            text = text[: m.start()].rstrip()
            break

    # 引用行を減らす（全部消すと情報欠損が怖いので、先頭が ">" の行だけ除去）
    lines = [ln for ln in text.split("\n") if not ln.lstrip().startswith(">")]
    text = "\n".join(lines).strip()

    return text

