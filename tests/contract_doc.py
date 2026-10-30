"""docs/contracts/README.md를 읽어 테스트가 쓸 수 있게 만든다. 테스트의 기준은 이 문서다."""
from __future__ import annotations

import json
import re

from helpers import CONTRACTS

README = (CONTRACTS / "README.md").read_text(encoding="utf-8")


def topic_table() -> dict[str, dict]:
    """토픽 표: {종류: {"qos": 0|1, "retain": bool, "from_to": "..."}}"""
    rows = {}
    for m in re.finditer(r"^\|\s*`zt/<기기>/(\w+)`\s*\|([^|]*)\|\s*(\d)\s*\|\s*(예|아니오)\s*\|", README, re.M):
        kind, from_to, qos, retain = m.groups()
        rows[kind] = {"qos": int(qos), "retain": retain == "예", "from_to": from_to.strip()}
    return rows


def examples() -> dict[str, list[dict]]:
    """'## <종류> — ...' 절의 ```json 블록에서 한 줄짜리 JSON 예시를 모은다."""
    out: dict[str, list[dict]] = {}
    sections = re.split(r"^## ", README, flags=re.M)[1:]
    for section in sections:
        kind = section.split(None, 1)[0]
        for block in re.findall(r"```json\n(.*?)```", section, re.S):
            for line in block.strip().splitlines():
                line = line.strip()
                if line.startswith("{"):
                    out.setdefault(kind, []).append(json.loads(line))
    return out
