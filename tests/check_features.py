"""기능 목록(tests/features.toml)이 뒤로 가지 않았는지 확인한다. CI가 PR마다 base 브랜치와 비교한다.

    python tests/check_features.py <base의 features.toml> <PR의 features.toml>

막는 것: "done"이었던 기능을 "todo"로 돌리기, 기능 지우기.
기능을 정말 없애야 하면 팀이 합의하고 broker 담당이 이 검사를 통과하는 별도 PR로 처리한다.
"""
import sys
import tomllib
from pathlib import Path


def load(path: str) -> dict:
    p = Path(path)
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() and p.stat().st_size else {}


def main(base_path: str, head_path: str) -> int:
    base, head = load(base_path), load(head_path)
    problems = []
    for fid, f in base.items():
        if fid not in head:
            problems.append(f"{fid} ({f.get('title')}): 기능이 지워짐")
        elif f.get("status") == "done" and head[fid].get("status") != "done":
            problems.append(f"{fid} ({f.get('title')}): done → {head[fid].get('status')}로 되돌림")
    newly_done = [fid for fid, f in head.items() if f.get("status") == "done" and base.get(fid, {}).get("status") != "done"]
    for line in problems:
        print("✗", line)
    for fid in newly_done:
        print("✓ 새로 완료:", fid, head[fid].get("title"))
    if not problems:
        print(f"기능 목록 확인 통과 (완료 {sum(f.get('status') == 'done' for f in head.values())}/{len(head)})")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
